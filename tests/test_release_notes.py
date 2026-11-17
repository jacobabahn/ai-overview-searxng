import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_notes", ROOT / "scripts/release_notes.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_script()

VERSION = '"""Package."""\n\n__version__ = "1.2.0"\n'
CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.0] - 2026-11-20

### Added

- Something new.

## [1.1.0] - 2026-10-01

- Older.

[Unreleased]: https://example.invalid/compare/v1.2.0...HEAD
[1.2.0]: https://example.invalid/releases/tag/v1.2.0
"""


def test_notes_are_the_versions_section_only() -> None:
    notes = release.release_notes("v1.2.0", VERSION, CHANGELOG)
    assert notes == "### Added\n\n- Something new.\n"


def test_last_section_drops_link_definitions() -> None:
    notes = release.release_notes("v1.1.0", VERSION.replace("1.2.0", "1.1.0"), CHANGELOG)
    assert notes == "- Older.\n"


@pytest.mark.parametrize("tag", ["v1.2.1", "1.2.0", "v1.2", "release-1.2.0"])
def test_tag_must_match_the_package_version(tag: str) -> None:
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.release_notes(tag, VERSION, CHANGELOG)


def test_version_needs_a_changelog_section() -> None:
    with pytest.raises(release.ReleaseError, match="no section for 1.3.0"):
        release.release_notes("v1.3.0", VERSION.replace("1.2.0", "1.3.0"), CHANGELOG)


def test_placeholder_date_is_rejected() -> None:
    changelog = CHANGELOG.replace("2026-11-20", "YYYY-MM-DD")
    with pytest.raises(release.ReleaseError, match="needs the release date"):
        release.release_notes("v1.2.0", VERSION, changelog)


def test_empty_section_is_rejected() -> None:
    changelog = CHANGELOG.replace("### Added\n\n- Something new.\n", "")
    with pytest.raises(release.ReleaseError, match="is empty"):
        release.release_notes("v1.2.0", VERSION, changelog)


def test_repository_changelog_covers_the_current_version() -> None:
    version = release.package_version(release.VERSION_FILE.read_text(encoding="utf-8"))
    changelog = release.CHANGELOG.read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(version)}\]", changelog, re.MULTILINE)
    assert re.search(r"^## \[Unreleased\]", changelog, re.MULTILINE)
