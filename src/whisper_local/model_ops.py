from __future__ import annotations

import os
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Literal

from whisper_local.config import normalize_runtime_name

RuntimeName = Literal["faster-whisper", "whisper.cpp"]


class ModelRuntimeOperations(ABC):
    """Runtime-specific model lifecycle operations."""

    runtime: RuntimeName

    @abstractmethod
    def download(
        self,
        model_name: str,
        progress_callback: Callable[[int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        raise NotImplementedError

    @abstractmethod
    def remove(self, model_name: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def installed_path(self, model_name: str) -> Path | None:
        raise NotImplementedError

    @abstractmethod
    def cache_size_bytes(self, model_name: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def estimated_size_bytes(self, model_name: str) -> int | None:
        raise NotImplementedError


class FasterWhisperModelRuntimeOperations(ModelRuntimeOperations):
    runtime: RuntimeName = "faster-whisper"

    def download(
        self,
        model_name: str,
        progress_callback: Callable[[int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        from whisper_local import model_manager as mm

        return mm._download_faster_model(
            model_name,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    def remove(self, model_name: str) -> None:
        from whisper_local import model_manager as mm

        mm._remove_faster_model(model_name)

    def installed_path(self, model_name: str) -> Path | None:
        from whisper_local import model_manager as mm

        return mm._get_installed_faster_model_path(model_name)

    def cache_size_bytes(self, model_name: str) -> int:
        from whisper_local import model_manager as mm

        return mm._faster_model_cache_size_bytes(model_name)

    def estimated_size_bytes(self, model_name: str) -> int | None:
        from whisper_local import model_manager as mm

        return mm.MODEL_ESTIMATED_SIZE_BYTES.get(model_name)


class WhisperCppModelRuntimeOperations(ModelRuntimeOperations):
    runtime: RuntimeName = "whisper.cpp"

    def download(
        self,
        model_name: str,
        progress_callback: Callable[[int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        from whisper_local import model_manager as mm

        if model_name not in mm.MODEL_NAMES:
            raise ValueError(f"Unknown model: {model_name}")

        filename = mm.whisper_cpp_model_filename(model_name)
        existing = mm.get_installed_whisper_cpp_model_path(model_name)
        if existing is not None:
            if progress_callback is not None:
                progress_callback(100)
            return existing

        if cancel_check is not None and cancel_check():
            raise mm.DownloadCancelledError("Download cancelled before start")

        expected_total = mm._resolve_repo_file_size_bytes(mm.WHISPER_CPP_REPO_ID, filename)
        if expected_total is None:
            expected_total = mm.WHISPER_CPP_ESTIMATED_SIZE_BYTES.get(model_name)
        if expected_total is not None:
            with mm._MODEL_SIZE_CACHE_LOCK:
                mm._MODEL_SIZE_CACHE[mm._size_cache_key(model_name, self.runtime)] = expected_total

        if progress_callback is not None:
            progress_callback(0)

        downloaded = self._download_file_in_subprocess(
            repo_id=mm.WHISPER_CPP_REPO_ID,
            filename=filename,
            progress_callback=progress_callback,
            expected_total_bytes=expected_total,
            cancel_check=cancel_check,
        )

        with mm._MODEL_SIZE_CACHE_LOCK:
            try:
                mm._MODEL_SIZE_CACHE[mm._size_cache_key(model_name, self.runtime)] = (
                    downloaded.stat().st_size
                )
            except OSError:
                pass

        if progress_callback is not None:
            progress_callback(100)
        return downloaded

    def _download_file_in_subprocess(
        self,
        repo_id: str,
        filename: str,
        progress_callback: Callable[[int], None] | None = None,
        expected_total_bytes: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        from whisper_local import model_manager as mm

        env = os.environ.copy()
        env["HF_HUB_DISABLE_XET"] = "1"
        env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
        env["HF_HUB_DISABLE_TQDM"] = "1"
        script = (
            "from huggingface_hub import hf_hub_download; "
            f"print(hf_hub_download(repo_id={repo_id!r}, filename={filename!r}))"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )

        cache_path = mm._cache_path_for_repo_id(repo_id)
        baseline_size = mm._cache_path_size_bytes(cache_path)
        last_percent = -1
        last_size = 0
        last_scan_time = 0.0
        size_scan_interval = 3.0

        def emit_progress() -> None:
            nonlocal last_percent, last_size, last_scan_time
            if progress_callback is None:
                return

            current_time = time.monotonic()
            total = int(expected_total_bytes or 0)
            if total <= 0:
                percent = 0
            else:
                if current_time - last_scan_time >= size_scan_interval:
                    last_size = mm._cache_path_size_bytes(cache_path)
                    last_scan_time = current_time
                downloaded_bytes = max(last_size - baseline_size, 0)
                percent = int(max(0.0, min((downloaded_bytes / float(total)) * 100.0, 99.0)))

            if percent == last_percent:
                return
            last_percent = percent
            progress_callback(percent)

        while process.poll() is None:
            if cancel_check is not None and cancel_check():
                self._terminate_process(process)
                mm._prune_whisper_cpp_cache()
                raise mm.DownloadCancelledError("Download cancelled during shutdown")
            emit_progress()
            time.sleep(0.2)

        stdout, _ = process.communicate()
        if process.returncode:
            mm._prune_whisper_cpp_cache()
            details = (stdout or "").strip()
            raise RuntimeError(
                f"whisper.cpp model download subprocess failed for {repo_id}/{filename}"
                + (f": {details}" if details else "")
            )

        emit_progress()
        output = stdout.strip().splitlines()
        if not output:
            mm._prune_whisper_cpp_cache()
            raise RuntimeError("No model path returned by whisper.cpp download subprocess")
        if progress_callback is not None and last_percent < 100:
            progress_callback(100)
        return Path(output[-1])

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass

    def remove(self, model_name: str) -> None:
        from whisper_local import model_manager as mm

        mm._remove_whisper_cpp_model(model_name)

    def installed_path(self, model_name: str) -> Path | None:
        from whisper_local import model_manager as mm

        return mm.get_installed_whisper_cpp_model_path(model_name)

    def cache_size_bytes(self, model_name: str) -> int:
        from whisper_local import model_manager as mm

        return mm._whisper_cpp_model_cache_size_bytes(model_name)

    def estimated_size_bytes(self, model_name: str) -> int | None:
        from whisper_local import model_manager as mm

        return mm.WHISPER_CPP_ESTIMATED_SIZE_BYTES.get(model_name)


class ModelRuntimeOperationsFactory(ABC):
    @abstractmethod
    def for_runtime(self, runtime: str | None) -> ModelRuntimeOperations:
        raise NotImplementedError


class DefaultModelRuntimeOperationsFactory(ModelRuntimeOperationsFactory):
    def __init__(self) -> None:
        self._operations: dict[RuntimeName, ModelRuntimeOperations] = {
            "faster-whisper": FasterWhisperModelRuntimeOperations(),
            "whisper.cpp": WhisperCppModelRuntimeOperations(),
        }

    def for_runtime(self, runtime: str | None) -> ModelRuntimeOperations:
        normalized = normalize_runtime_name(str(runtime or "faster-whisper"))
        key: RuntimeName = "whisper.cpp" if normalized == "whisper.cpp" else "faster-whisper"
        return self._operations[key]


_DEFAULT_MODEL_RUNTIME_OPERATIONS_FACTORY = DefaultModelRuntimeOperationsFactory()


def get_model_runtime_operations_factory() -> ModelRuntimeOperationsFactory:
    return _DEFAULT_MODEL_RUNTIME_OPERATIONS_FACTORY
