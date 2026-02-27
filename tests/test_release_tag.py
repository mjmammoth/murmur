from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_release_tag_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "release_tag.py"
    spec = importlib.util.spec_from_file_location("release_tag", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module():
    return _load_release_tag_module()


def test_classify_release_tag_stable(module) -> None:
    info = module.classify_release_tag("v1.2.3")
    assert info.version_no_v == "1.2.3"
    assert info.release_kind == "stable"
    assert info.is_prerelease is False


def test_classify_release_tag_post(module) -> None:
    info = module.classify_release_tag("v1.2.3.post1")
    assert info.version_no_v == "1.2.3.post1"
    assert info.release_kind == "post"
    assert info.is_prerelease is False


def test_classify_release_tag_prerelease(module) -> None:
    rc = module.classify_release_tag("v1.2.4rc1")
    assert rc.release_kind == "prerelease"
    assert rc.is_prerelease is True

    dev = module.classify_release_tag("v1.2.4.dev1")
    assert dev.release_kind == "prerelease"
    assert dev.is_prerelease is True


@pytest.mark.parametrize(
    "tag",
    (
        "1.2.3",
        "v1.2",
        "v1.2.3-rc1",
        "v1.2.3+local1",
    ),
)
def test_classify_release_tag_rejects_invalid_input(module, tag: str) -> None:
    with pytest.raises(ValueError):
        module.classify_release_tag(tag)
