from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"

PUBLIC_DOCS = {
    "10_INDEX.md",
    "20_INSTALL.md",
    "30_USAGE.md",
    "40_CONFIGURATION.md",
    "50_ARCHITECTURE.md",
    "60_BENCHMARKS.md",
    "70_FAQ.md",
}

PUBLIC_TEXT_FILES = (
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "CONTRIBUTING.md",
    PROJECT_ROOT / "pyproject.toml",
    PROJECT_ROOT / ".env.example",
    PROJECT_ROOT / ".gitignore",
    *sorted(DOCS_ROOT.glob("*.md")),
)

def _phrase(*parts: str) -> str:
    return "".join(parts)


DISALLOWED_PUBLIC_PHRASES = (
    _phrase("Spatial Field Engine", " for Cognition"),
    _phrase("SpatialFieldEngine", "ForCognition"),
    _phrase("AI-Coded", ": 95%+"),
    _phrase("experimental", " research"),
    _phrase("diagnostic", " bucketing"),
    _phrase("high-overlap", " authority-gap"),
)


def test_public_docs_are_the_lean_documentation_set() -> None:
    assert {path.name for path in DOCS_ROOT.glob("*.md")} == PUBLIC_DOCS


def test_public_docs_do_not_use_old_public_positioning() -> None:
    for path in PUBLIC_TEXT_FILES:
        text = path.read_text(encoding="utf-8")
        for phrase in DISALLOWED_PUBLIC_PHRASES:
            assert phrase not in text, f"{phrase!r} found in {path.relative_to(PROJECT_ROOT)}"


def test_public_markdown_links_point_to_existing_local_files() -> None:
    markdown_files = [PROJECT_ROOT / "README.md", *sorted(DOCS_ROOT.glob("*.md"))]
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        for match in link_pattern.finditer(text):
            target = match.group(1)
            if "://" in target or target.startswith("#") or target.startswith("mailto:"):
                continue
            target_without_anchor = target.split("#", 1)[0]
            if not target_without_anchor:
                continue
            linked_path = (path.parent / target_without_anchor).resolve()
            assert linked_path.exists(), (
                f"{path.relative_to(PROJECT_ROOT)} links to missing "
                f"{target_without_anchor}"
            )
