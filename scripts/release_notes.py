"""Check a release tag against the package version and print its changelog section."""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "ai_overview" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"


class ReleaseError(Exception):
    pass


def package_version(source: str) -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    if match is None:
        raise ReleaseError(f"no __version__ in {VERSION_FILE.relative_to(ROOT)}")
    return match.group(1)


def changelog_section(changelog: str, version: str) -> str:
    """Return the body of the version's section, without its heading or link definitions."""
    heading = re.compile(rf"^## \[{re.escape(version)}\](.*)$", re.MULTILINE)
    match = heading.search(changelog)
    if match is None:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}")
    if not re.fullmatch(r" - \d{4}-\d{2}-\d{2}", match.group(1)):
        raise ReleaseError(
            f"the CHANGELOG.md heading {match.group(0)!r} needs the release date, "
            f"written as ## [{version}] - <year>-<month>-<day>"
        )
    rest = changelog[match.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    body = rest[: following.start()] if following else rest
    lines = [line for line in body.splitlines() if not re.match(r"^\[[^\]]+\]: ", line)]
    notes = "\n".join(lines).strip()
    if not notes:
        raise ReleaseError(f"the CHANGELOG.md section for {version} is empty")
    return notes + "\n"


def release_notes(tag: str, version_source: str, changelog: str) -> str:
    version = package_version(version_source)
    if tag != f"v{version}":
        raise ReleaseError(f"tag {tag} does not match ai_overview.__version__ {version}")
    return changelog_section(changelog, version)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="the release tag, such as v0.1.0")
    args = parser.parse_args()
    try:
        notes = release_notes(
            args.tag,
            VERSION_FILE.read_text(encoding="utf-8"),
            CHANGELOG.read_text(encoding="utf-8"),
        )
    except ReleaseError as error:
        sys.exit(f"release check failed: {error}")
    sys.stdout.write(notes)


if __name__ == "__main__":
    main()
