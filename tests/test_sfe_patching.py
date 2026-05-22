"""Tests for conservative local unified-diff parsing and application."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.patching import (
    INVALID_PATCH_PROPOSAL,
    PATCH_PREIMAGE_MISMATCH,
    UNSAFE_PATCH,
    apply_patch_to_workspace,
    parse_unified_diff,
    validate_patch_targets,
)


def _diff(path: str, old: str = "old", new: str = "new") -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -1,1 +1,1 @@",
            f"-{old}",
            f"+{new}",
        ]
    )


def _parse_ok(text: str):
    parsed = parse_unified_diff(text)
    assert parsed.issue is None
    assert parsed.patch is not None
    return parsed.patch


def test_parse_valid_single_file_modification_diff() -> None:
    parsed = parse_unified_diff(_diff("notes.txt"))

    assert parsed.issue is None
    assert parsed.patch is not None
    assert parsed.summary is not None
    assert parsed.summary.paths == ("notes.txt",)
    assert parsed.summary.file_count == 1
    assert parsed.summary.hunk_count == 1
    assert parsed.summary.lines_added == 1
    assert parsed.summary.lines_removed == 1


def test_parse_valid_multi_file_modification_diff() -> None:
    parsed = parse_unified_diff(_diff("a.txt") + "\n" + _diff("b.txt", "one", "two"))

    assert parsed.issue is None
    assert parsed.patch is not None
    assert parsed.summary is not None
    assert parsed.summary.paths == ("a.txt", "b.txt")
    assert parsed.summary.file_count == 2
    assert parsed.summary.hunk_count == 2


def test_reject_new_file() -> None:
    text = "\n".join(
        [
            "diff --git a/new.txt b/new.txt",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/new.txt",
            "@@ -0,0 +1,1 @@",
            "+new",
        ]
    )

    parsed = parse_unified_diff(text)

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_delete() -> None:
    text = "\n".join(
        [
            "diff --git a/old.txt b/old.txt",
            "deleted file mode 100644",
            "--- a/old.txt",
            "+++ /dev/null",
            "@@ -1,1 +0,0 @@",
            "-old",
        ]
    )

    parsed = parse_unified_diff(text)

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_rename() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/old.txt b/new.txt",
                "rename from old.txt",
                "rename to new.txt",
                "--- a/old.txt",
                "+++ b/new.txt",
                "@@ -1,1 +1,1 @@",
                "-old",
                "+new",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_chmod_mode_change() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/script.sh b/script.sh",
                "old mode 100644",
                "new mode 100755",
                "--- a/script.sh",
                "+++ b/script.sh",
                "@@ -1,1 +1,1 @@",
                "-old",
                "+new",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_index_metadata() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/notes.txt b/notes.txt",
                "index 1111111..2222222 100644",
                "--- a/notes.txt",
                "+++ b/notes.txt",
                "@@ -1,1 +1,1 @@",
                "-old",
                "+new",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_binary_patch() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/image.png b/image.png",
                "Binary files a/image.png and b/image.png differ",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_dev_null() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/file.txt b/file.txt",
                "--- /dev/null",
                "+++ b/file.txt",
                "@@ -0,0 +1,1 @@",
                "+new",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_absolute_path() -> None:
    parsed = parse_unified_diff(_diff("/tmp/file.txt"))

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_windows_absolute_path() -> None:
    parsed = parse_unified_diff(_diff("C:/Users/patrice/file.txt"))

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_traversal_path() -> None:
    parsed = parse_unified_diff(_diff("../outside.txt"))

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_backslash_path() -> None:
    parsed = parse_unified_diff(_diff("safe\\..\\outside.txt"))

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_hidden_path() -> None:
    parsed = parse_unified_diff(_diff(".hidden/file.txt"))

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_env_paths() -> None:
    assert parse_unified_diff(_diff(".env")).issue.category == UNSAFE_PATCH  # type: ignore[union-attr]
    assert parse_unified_diff(_diff(".env.local")).issue.category == UNSAFE_PATCH  # type: ignore[union-attr]


def test_reject_ssh_path() -> None:
    parsed = parse_unified_diff(_diff(".ssh/config"))

    assert parsed.issue is not None
    assert parsed.issue.category == UNSAFE_PATCH


def test_reject_logs_caches_db_jsonl_generated_files() -> None:
    paths = [
        "logs/app.txt",
        ".cache/state.txt",
        "data/app.db",
        "events.jsonl",
        "coverage.xml",
        "module.pyc",
        "archive.zip",
        "build/output.txt",
        "dist/output.txt",
        "node_modules/package/index.js",
        "venv/lib/site.py",
    ]

    for path in paths:
        parsed = parse_unified_diff(_diff(path))
        assert parsed.issue is not None, path
        assert parsed.issue.category == UNSAFE_PATCH, path


def test_reject_symlink_target(tmp_path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    patch = _parse_ok(_diff("link.txt"))

    result = validate_patch_targets(tmp_path, patch)

    assert result.ok is False
    assert result.issue is not None
    assert result.issue.category == UNSAFE_PATCH
    assert result.issue.reason == "symlink_target"


def test_reject_non_utf8_target(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_bytes(b"\xff\xfe\x00")
    patch = _parse_ok(_diff("notes.txt"))

    result = validate_patch_targets(tmp_path, patch)

    assert result.ok is False
    assert result.issue is not None
    assert result.issue.category == UNSAFE_PATCH


def test_reject_oversized_target(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("old\n", encoding="utf-8")
    patch = _parse_ok(_diff("notes.txt"))

    result = validate_patch_targets(tmp_path, patch, max_bytes=1)

    assert result.ok is False
    assert result.issue is not None
    assert result.issue.reason == "file_too_large"


def test_reject_malformed_hunk() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/notes.txt b/notes.txt",
                "--- a/notes.txt",
                "+++ b/notes.txt",
                "@@ nope @@",
                "-old",
                "+new",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == INVALID_PATCH_PROPOSAL


def test_reject_impossible_hunk_accounting() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/notes.txt b/notes.txt",
                "--- a/notes.txt",
                "+++ b/notes.txt",
                "@@ -1,2 +1,1 @@",
                "-old",
                "+new",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == INVALID_PATCH_PROPOSAL


def test_successful_apply_to_one_existing_text_file(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("old\n", encoding="utf-8")
    patch = _parse_ok(_diff("notes.txt"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is True
    assert result.summary is not None
    assert source.read_text(encoding="utf-8") == "new\n"


def test_successful_all_or_nothing_multi_file_apply(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old\n", encoding="utf-8")
    second.write_text("one\n", encoding="utf-8")
    patch = _parse_ok(_diff("first.txt") + "\n" + _diff("second.txt", "one", "two"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is True
    assert first.read_text(encoding="utf-8") == "new\n"
    assert second.read_text(encoding="utf-8") == "two\n"


def test_apply_uses_byte_decoding_without_newline_normalization(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_bytes(b"old\r\n")
    patch = _parse_ok(_diff("notes.txt"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is False
    assert result.issue is not None
    assert result.issue.category == PATCH_PREIMAGE_MISMATCH
    assert source.read_bytes() == b"old\r\n"


def test_preimage_mismatch_writes_nothing(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("changed\n", encoding="utf-8")
    patch = _parse_ok(_diff("notes.txt"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is False
    assert result.issue is not None
    assert result.issue.category == PATCH_PREIMAGE_MISMATCH
    assert result.pending_patch_cleared is False
    assert source.read_text(encoding="utf-8") == "changed\n"


def test_unsafe_second_file_causes_no_partial_write_to_first_file(tmp_path) -> None:
    first = tmp_path / "first.txt"
    first.write_text("old\n", encoding="utf-8")
    patch = _parse_ok(_diff("first.txt") + "\n" + _diff("second.txt", "one", "two"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is False
    assert result.issue is not None
    assert result.issue.category == UNSAFE_PATCH
    assert first.read_text(encoding="utf-8") == "old\n"


def test_duplicate_target_file_is_rejected_before_writes(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("old\n", encoding="utf-8")
    patch = _parse_ok(_diff("notes.txt") + "\n" + _diff("notes.txt"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is False
    assert result.issue is not None
    assert result.issue.category == UNSAFE_PATCH
    assert result.issue.reason == "duplicate_target_path"
    assert source.read_text(encoding="utf-8") == "old\n"
