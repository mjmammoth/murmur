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


def test_classify_release_tag_alpha_prerelease(module) -> None:
    """Test that alpha versions are classified as prerelease."""
    info = module.classify_release_tag("v1.2.3a1")
    assert info.version_no_v == "1.2.3a1"
    assert info.release_kind == "prerelease"
    assert info.is_prerelease is True


def test_classify_release_tag_beta_prerelease(module) -> None:
    """Test that beta versions are classified as prerelease."""
    info = module.classify_release_tag("v1.2.3b2")
    assert info.version_no_v == "1.2.3b2"
    assert info.release_kind == "prerelease"
    assert info.is_prerelease is True


def test_classify_release_tag_preserves_tag_with_v(module) -> None:
    """Test that the original tag with 'v' prefix is preserved."""
    info = module.classify_release_tag("v1.2.3")
    assert info.tag == "v1.2.3"


def test_classify_release_tag_strips_whitespace(module) -> None:
    """Test that whitespace is stripped from tag input."""
    info = module.classify_release_tag("  v1.2.3  ")
    assert info.tag == "v1.2.3"
    assert info.version_no_v == "1.2.3"


def test_classify_release_tag_handles_multi_digit_versions(module) -> None:
    """Test that multi-digit version numbers are handled correctly."""
    info = module.classify_release_tag("v10.20.30")
    assert info.version_no_v == "10.20.30"
    assert info.release_kind == "stable"


def test_classify_release_tag_handles_multi_digit_prerelease(module) -> None:
    """Test that multi-digit prerelease numbers are handled."""
    info = module.classify_release_tag("v1.2.3rc12")
    assert info.version_no_v == "1.2.3rc12"
    assert info.release_kind == "prerelease"


def test_classify_release_tag_handles_multi_digit_post(module) -> None:
    """Test that multi-digit post release numbers are handled."""
    info = module.classify_release_tag("v1.2.3.post10")
    assert info.version_no_v == "1.2.3.post10"
    assert info.release_kind == "post"


def test_classify_release_tag_rejects_missing_v_prefix(module) -> None:
    """Test that tags without 'v' prefix are rejected."""
    with pytest.raises(ValueError, match="Invalid release tag"):
        module.classify_release_tag("1.2.3")


def test_classify_release_tag_rejects_dash_separator(module) -> None:
    """Test that tags with dash separators (non-PEP440) are rejected."""
    with pytest.raises(ValueError, match="Invalid release tag"):
        module.classify_release_tag("v1.2.3-alpha1")


def test_classify_release_tag_rejects_plus_local_version(module) -> None:
    """Test that local version identifiers with '+' are rejected."""
    with pytest.raises(ValueError, match="Invalid release tag"):
        module.classify_release_tag("v1.2.3+local")


def test_write_github_outputs_appends_to_file(module, tmp_path) -> None:
    """Test that write_github_outputs correctly appends to a file."""
    output_file = tmp_path / "github_output.txt"
    output_file.write_text("existing=content\n", encoding="utf-8")

    from scripts.release_tag import ReleaseTagInfo

    info = ReleaseTagInfo(
        tag="v1.2.3",
        version_no_v="1.2.3",
        release_kind="stable",
        is_prerelease=False,
    )

    module.write_github_outputs(output_file, info)

    content = output_file.read_text(encoding="utf-8")
    assert "existing=content" in content
    assert "normalized_tag=v1.2.3" in content
    assert "version_no_v=1.2.3" in content
    assert "release_kind=stable" in content
    assert "is_prerelease=false" in content


def test_write_github_outputs_prerelease_flag(module, tmp_path) -> None:
    """Test that prerelease flag is correctly written as 'true'."""
    output_file = tmp_path / "github_output.txt"

    from scripts.release_tag import ReleaseTagInfo

    info = ReleaseTagInfo(
        tag="v1.2.3rc1",
        version_no_v="1.2.3rc1",
        release_kind="prerelease",
        is_prerelease=True,
    )

    module.write_github_outputs(output_file, info)

    content = output_file.read_text(encoding="utf-8")
    assert "is_prerelease=true" in content