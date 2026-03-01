from __future__ import annotations

import os
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Literal

from murmur.config import normalize_runtime_name

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
        """
        Download the specified model for this runtime and return the installed filesystem path.

        Parameters:
            model_name (str): Name or identifier of the model to download.
            progress_callback (Callable[[int], None] | None): Optional callback invoked with an integer progress percentage (0–100) during the download.
            cancel_check (Callable[[], bool] | None): Optional callable that should be called periodically; if it returns True the download should be aborted.

        Returns:
            Path: Path to the installed model file or directory.
        """
        raise NotImplementedError

    @abstractmethod
    def remove(self, model_name: str) -> None:
        """
        Remove an installed model from the runtime's storage.

        Parameters:
            model_name (str): Name of the model to remove.
        """
        raise NotImplementedError

    @abstractmethod
    def installed_path(self, model_name: str) -> Path | None:
        """
        Get the installed filesystem path for a model or None if the model is not installed.

        Parameters:
            model_name (str): Canonical name of the model to query.

        Returns:
            Path | None: The filesystem path to the installed model, or `None` when the model is not installed.
        """
        raise NotImplementedError

    @abstractmethod
    def cache_size_bytes(self, model_name: str) -> int:
        """
        Return the total size, in bytes, of the cached files for the specified model.

        Parameters:
            model_name (str): The model identifier to query.

        Returns:
            int: Total size in bytes of the model's cache (0 if the model is not installed or has no cached files).
        """
        raise NotImplementedError

    @abstractmethod
    def estimated_size_bytes(self, model_name: str) -> int | None:
        """
        Provide the estimated size in bytes for the specified model.

        Returns:
            int | None: Estimated size in bytes for the model, or `None` if an estimate is not available.
        """
        raise NotImplementedError


class FasterWhisperModelRuntimeOperations(ModelRuntimeOperations):
    runtime: RuntimeName = "faster-whisper"

    def download(
        self,
        model_name: str,
        progress_callback: Callable[[int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """
        Download and install the specified model for the faster-whisper runtime.

        Parameters:
            model_name (str): The identifier of the model to download.
            progress_callback (Callable[[int], None] | None): Optional callback invoked with download progress as an integer percentage (0–100).
            cancel_check (Callable[[], bool] | None): Optional callable that should return True to signal cancellation of the download.

        Returns:
            Path: Filesystem path to the installed model.
        """
        from murmur import model_manager as mm

        return mm._download_faster_model(
            model_name,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    def remove(self, model_name: str) -> None:
        """
        Remove a model installed for the faster-whisper runtime.

        Parameters:
            model_name (str): The model identifier used by the faster-whisper runtime to locate and remove the installed model.
        """
        from murmur import model_manager as mm

        mm._remove_faster_model(model_name)

    def installed_path(self, model_name: str) -> Path | None:
        """
        Get the installed path for a faster-whisper model.

        Returns:
        	Path or `None`: Path to the installed model file if the model is installed, `None` otherwise.
        """
        from murmur import model_manager as mm

        return mm._get_installed_faster_model_path(model_name)

    def cache_size_bytes(self, model_name: str) -> int:
        """
        Return the total size in bytes of the cached files for the specified faster-whisper model.

        Parameters:
            model_name (str): Identifier of the model whose cache size should be calculated.

        Returns:
            int: Total cache size for the specified model in bytes.
        """
        from murmur import model_manager as mm

        return mm._faster_model_cache_size_bytes(model_name)

    def estimated_size_bytes(self, model_name: str) -> int | None:
        """
        Provide the estimated download size in bytes for the specified model, if available.

        Returns:
            int | None: The estimated size in bytes for `model_name` if known, `None` otherwise.
        """
        from murmur import model_manager as mm

        return mm.MODEL_ESTIMATED_SIZE_BYTES.get(model_name)


class WhisperCppModelRuntimeOperations(ModelRuntimeOperations):
    runtime: RuntimeName = "whisper.cpp"

    def download(
        self,
        model_name: str,
        progress_callback: Callable[[int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """
        Download and install the specified whisper.cpp model and return the installed file path.

        Parameters:
            model_name (str): Name of the model to download; must be one of the known whisper.cpp model names.
            progress_callback (Callable[[int], None] | None): Optional callback that receives integer progress percentages (0–100).
            cancel_check (Callable[[], bool] | None): Optional callable that returns True to request cancellation.

        Returns:
            Path: Filesystem path to the installed model file.

        Raises:
            ValueError: If `model_name` is not a recognized whisper.cpp model.
            DownloadCancelledError: If cancellation is requested before start or during the download.
        """
        from murmur import model_manager as mm

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
        """
        Download a file from a Hugging Face repository in a subprocess while reporting progress and supporting cancellation.

        Parameters:
        	repo_id (str): Hugging Face repository identifier to download from (e.g., "owner/repo").
        	filename (str): Name of the file within the repository to download.
        	progress_callback (Callable[[int], None] | None): Optional callback receiving download progress as an integer percent (0–100).
        	expected_total_bytes (int | None): Optional expected total size in bytes used to estimate progress; if None, progress may be indeterminate.
        	cancel_check (Callable[[], bool] | None): Optional callable that returns True to request cancellation; if it returns True, the download is aborted.

        Returns:
        	Path: Path to the downloaded file as printed by the subprocess.

        Raises:
        	murmur.model_manager.DownloadCancelledError: If cancellation is requested via cancel_check during download.
        	RuntimeError: If the subprocess fails or does not return a download path.
        """
        from murmur import model_manager as mm

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
            """
            Compute current download progress from the local cache size and invoke the provided progress callback.

            If no progress callback is set, this function does nothing. It samples the cache directory size at most once per size_scan_interval, computes downloaded bytes as max(last_size - baseline_size, 0), and maps that to a percentage of expected_total_bytes. When expected_total_bytes is unknown or zero the percentage is treated as 0. The reported percentage is clamped between 0 and 99 and is only sent to progress_callback when it differs from the last reported value; last_percent is updated accordingly.
            """
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
        """
        Terminate a subprocess, escalating to kill if it does not exit within a short timeout.

        Attempts to terminate the given subprocess gracefully and waits up to 2 seconds for it to exit.
        If the process does not exit in that time, it is killed and another wait of up to 2 seconds is performed.

        Parameters:
            process (subprocess.Popen[str]): The subprocess to terminate.
        """
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
        """
        Remove the installed whisper.cpp model files for the given model name.

        Parameters:
            model_name (str): The whisper.cpp model identifier to remove (e.g., a known model name).
        """
        from murmur import model_manager as mm

        mm._remove_whisper_cpp_model(model_name)

    def installed_path(self, model_name: str) -> Path | None:
        """
        Get the installed file path for a whisper.cpp model.

        Parameters:
            model_name (str): The whisper.cpp model identifier.

        Returns:
            Path | None: Path to the installed model file if installed, `None` otherwise.
        """
        from murmur import model_manager as mm

        return mm.get_installed_whisper_cpp_model_path(model_name)

    def cache_size_bytes(self, model_name: str) -> int:
        """
        Return the total size in bytes of the whisper.cpp model cache for the given model.

        Parameters:
            model_name (str): Name of the whisper.cpp model.

        Returns:
            int: Total cache size in bytes for the specified model.
        """
        from murmur import model_manager as mm

        return mm._whisper_cpp_model_cache_size_bytes(model_name)

    def estimated_size_bytes(self, model_name: str) -> int | None:
        """
        Get the estimated download size for a whisper.cpp model.

        Returns:
            int | None: Estimated size in bytes for the specified model, or None if no estimate is available.
        """
        from murmur import model_manager as mm

        return mm.WHISPER_CPP_ESTIMATED_SIZE_BYTES.get(model_name)


class ModelRuntimeOperationsFactory(ABC):
    @abstractmethod
    def for_runtime(self, runtime: str | None) -> ModelRuntimeOperations:
        """
        Return the ModelRuntimeOperations instance appropriate for the given runtime name.

        Parameters:
            runtime (str | None): Runtime identifier (e.g., "faster-whisper" or "whisper.cpp"); pass `None` to request the default runtime.

        Returns:
            ModelRuntimeOperations: The operations handler for the specified runtime.
        """
        raise NotImplementedError


class DefaultModelRuntimeOperationsFactory(ModelRuntimeOperationsFactory):
    def __init__(self) -> None:
        """
        Initialize the factory's mapping of runtime names to their operation handlers.

        Creates and stores concrete ModelRuntimeOperations instances for the supported runtimes:
        "faster-whisper" and "whisper.cpp", accessible via self._operations.
        """
        self._operations: dict[RuntimeName, ModelRuntimeOperations] = {
            "faster-whisper": FasterWhisperModelRuntimeOperations(),
            "whisper.cpp": WhisperCppModelRuntimeOperations(),
        }

    def for_runtime(self, runtime: str | None) -> ModelRuntimeOperations:
        """
        Selects the appropriate ModelRuntimeOperations implementation for the provided runtime name.

        Parameters:
            runtime (str | None): Runtime identifier to select; if None, defaults to "faster-whisper". The input is normalized with normalize_runtime_name before selection.

        Returns:
            ModelRuntimeOperations: The operation handler for the normalized runtime ("whisper.cpp" or "faster-whisper").
        """
        normalized = normalize_runtime_name(str(runtime or "faster-whisper"))
        key: RuntimeName = "whisper.cpp" if normalized == "whisper.cpp" else "faster-whisper"
        return self._operations[key]


_DEFAULT_MODEL_RUNTIME_OPERATIONS_FACTORY = DefaultModelRuntimeOperationsFactory()


def get_model_runtime_operations_factory() -> ModelRuntimeOperationsFactory:
    """
    Provide the singleton factory used to obtain runtime-specific model operation handlers.

    Returns:
        ModelRuntimeOperationsFactory: The singleton ModelRuntimeOperationsFactory instance.
    """
    return _DEFAULT_MODEL_RUNTIME_OPERATIONS_FACTORY
