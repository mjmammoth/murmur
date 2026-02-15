from __future__ import annotations

import importlib.util
from pathlib import Path


def test_project_versions_are_synchronized() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "check_version_sync.py"
    spec = importlib.util.spec_from_file_location("check_version_sync", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pyproject_version = module.read_pyproject_version(repo_root / "pyproject.toml")
    init_version = module.read_init_version(repo_root / "src" / "whisper_local" / "__init__.py")
    assert pyproject_version == init_version
