"""Tests for mechanical patch parsing and physical application."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.patching import (
    INVALID_PATCH_PROPOSAL,
    MECHANICAL_GUARD_REJECTED,
    PHYSICAL_APPLICATION_FAILURE,
    apply_patch_to_workspace,
    parse_unified_diff,
    summarize_patch_text,
    validate_patch_paths,
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


def _create_diff(path: str, *lines: str) -> str:
    added = list(lines) or ["created"]
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            f"+++ b/{path}",
            f"@@ -0,0 +1,{len(added)} @@",
            *(f"+{line}" for line in added),
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
    assert parsed.summary.modified_paths == ("a.txt", "b.txt")
    assert parsed.summary.created_paths == ()


def test_parse_valid_single_file_creation_diff() -> None:
    parsed = parse_unified_diff(_create_diff("new.txt", "hello"))

    assert parsed.issue is None
    assert parsed.patch is not None
    assert parsed.summary is not None
    assert parsed.summary.paths == ("new.txt",)
    assert parsed.summary.modified_paths == ()
    assert parsed.summary.created_paths == ("new.txt",)
    assert parsed.summary.lines_added == 1
    assert parsed.summary.lines_removed == 0


def test_parser_accepts_metadata_without_policy_rejection() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/script.sh b/script.sh",
                "index 1111111..2222222 100644",
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

    assert parsed.issue is None
    assert parsed.patch is not None


def test_summarize_patch_text_extracts_patch_like_paths_when_parse_fails() -> None:
    text = "\n".join(
        [
            "```diff",
            "diff --git a/context.txt b/context.txt",
            "--- a/context.txt",
            "+++ b/context.txt",
            "@@ -1,1 +1,1 @@",
            "-old",
            "+new",
            "```",
        ]
    )

    parsed = summarize_patch_text(text)

    assert parsed.issue is None
    assert parsed.patch is None
    assert parsed.summary is not None
    assert parsed.summary.paths == ("context.txt",)
    assert parsed.summary.hunk_count == 1


def test_summarize_binary_patch_like_diff_without_policy_rejection() -> None:
    parsed = summarize_patch_text(
        "\n".join(
            [
                "diff --git a/image.png b/image.png",
                "Binary files a/image.png and b/image.png differ",
            ]
        )
    )

    assert parsed.issue is None
    assert parsed.summary is not None
    assert parsed.summary.paths == ("image.png",)


def test_parse_rejects_non_patch_text() -> None:
    parsed = parse_unified_diff("No safe patch can be proposed.")

    assert parsed.issue is not None
    assert parsed.issue.category == INVALID_PATCH_PROPOSAL


def test_mechanical_guard_rejects_absolute_path(tmp_path) -> None:
    issue = validate_patch_paths(tmp_path, ("/tmp/file.txt",))

    assert issue is not None
    assert issue.category == MECHANICAL_GUARD_REJECTED
    assert issue.reason == "absolute_path"


def test_mechanical_guard_rejects_windows_absolute_path(tmp_path) -> None:
    issue = validate_patch_paths(tmp_path, ("C:/Users/patrice/file.txt",))

    assert issue is not None
    assert issue.category == MECHANICAL_GUARD_REJECTED
    assert issue.reason == "absolute_path"


def test_mechanical_guard_rejects_workspace_escape(tmp_path) -> None:
    issue = validate_patch_paths(tmp_path, ("../outside.txt",))

    assert issue is not None
    assert issue.category == MECHANICAL_GUARD_REJECTED
    assert issue.reason == "path_outside_workspace"


def test_mechanical_guard_rejects_traversal_component(tmp_path) -> None:
    issue = validate_patch_paths(tmp_path, ("safe/../outside.txt",))

    assert issue is not None
    assert issue.category == MECHANICAL_GUARD_REJECTED
    assert issue.reason == "path_outside_workspace"


def test_mechanical_guard_rejects_excluded_write_directories(tmp_path) -> None:
    for path in (
        ".git/config",
        "vendor/package/file.php",
        "var/cache.txt",
        "cache/item.txt",
        "node_modules/package/index.js",
    ):
        issue = validate_patch_paths(tmp_path, (path,))
        assert issue is not None
        assert issue.category == MECHANICAL_GUARD_REJECTED
        assert issue.reason == "excluded_directory"
        assert issue.path == path


def test_no_policy_rejection_for_hidden_secret_suffix_or_binary_like_paths(tmp_path) -> None:
    paths = (
        ".env",
        ".hidden/file.txt",
        ".ssh/config",
        "data/app.db",
        "image.bin",
        "archive.zip",
    )

    assert validate_patch_paths(tmp_path, paths) is None


def test_validate_patch_targets_is_mechanical_only_for_missing_or_binary_targets(tmp_path) -> None:
    patch = _parse_ok(_diff("missing.bin"))

    result = validate_patch_targets(tmp_path, patch)

    assert result.ok is True
    assert result.summary is not None
    assert result.summary.paths == ("missing.bin",)


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


def test_successful_apply_creates_one_text_file(tmp_path) -> None:
    patch = _parse_ok(_create_diff("new.txt", "hello"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is True
    assert result.summary is not None
    assert result.summary.created_paths == ("new.txt",)
    assert result.summary.modified_paths == ()
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello\n"


def test_successful_apply_creates_multiple_text_files(tmp_path) -> None:
    patch = _parse_ok(_create_diff("first.txt", "one") + "\n" + _create_diff("second.txt", "two"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is True
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "one\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "two\n"


def test_successful_apply_creates_file_in_new_subdirectory(tmp_path) -> None:
    patch = _parse_ok(_create_diff("src/App.php", "<?php"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is True
    assert (tmp_path / "src" / "App.php").read_text(encoding="utf-8") == "<?php\n"


def test_creation_outside_workspace_via_symlink_parent_is_refused(tmp_path) -> None:
    outside = tmp_path.parent / "outside-sfe-patch"
    outside.mkdir(exist_ok=True)
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    patch = _parse_ok(_create_diff("linked/escape.txt", "nope"))

    result = validate_patch_targets(tmp_path, patch)

    assert result.ok is False
    assert result.issue is not None
    assert result.issue.category == MECHANICAL_GUARD_REJECTED
    assert result.issue.reason == "path_outside_workspace"
    assert result.summary is not None
    assert result.summary.refused_paths == ("linked/escape.txt",)


def test_creation_absolute_path_is_refused_by_parser() -> None:
    parsed = parse_unified_diff(_create_diff("/tmp/outside.txt", "nope"))

    assert parsed.issue is not None
    assert parsed.issue.category == MECHANICAL_GUARD_REJECTED
    assert parsed.issue.reason == "absolute_path"


def test_creation_with_parent_traversal_is_refused_by_parser() -> None:
    parsed = parse_unified_diff(_create_diff("../outside.txt", "nope"))

    assert parsed.issue is not None
    assert parsed.issue.category == MECHANICAL_GUARD_REJECTED
    assert parsed.issue.reason == "path_outside_workspace"


def test_creation_in_git_directory_is_refused() -> None:
    parsed = parse_unified_diff(_create_diff(".git/hooks/post-checkout", "echo nope"))

    assert parsed.issue is not None
    assert parsed.issue.category == MECHANICAL_GUARD_REJECTED
    assert parsed.issue.reason == "excluded_directory"


def test_creation_in_generated_directories_is_refused() -> None:
    for path in (
        "vendor/autoload.php",
        "var/cache.php",
        "cache/item.txt",
        "node_modules/pkg/index.js",
    ):
        parsed = parse_unified_diff(_create_diff(path, "nope"))
        assert parsed.issue is not None
        assert parsed.issue.category == MECHANICAL_GUARD_REJECTED
        assert parsed.issue.reason == "excluded_directory"


def test_physical_preimage_failure_writes_nothing_and_keeps_pending_patch(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("changed\n", encoding="utf-8")
    patch = _parse_ok(_diff("notes.txt"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is False
    assert result.issue is not None
    assert result.issue.category == PHYSICAL_APPLICATION_FAILURE
    assert result.issue.reason == "hunk_preimage_mismatch"
    assert result.pending_patch_cleared is False
    assert source.read_text(encoding="utf-8") == "changed\n"


def test_physical_decode_failure_writes_nothing_and_keeps_pending_patch(tmp_path) -> None:
    source = tmp_path / "notes.txt"
    source.write_bytes(b"\xff\xfe\x00")
    patch = _parse_ok(_diff("notes.txt"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is False
    assert result.issue is not None
    assert result.issue.category == PHYSICAL_APPLICATION_FAILURE
    assert result.issue.reason == "decode_error"
    assert result.pending_patch_cleared is False
    assert source.read_bytes() == b"\xff\xfe\x00"


def test_physical_second_file_failure_causes_no_partial_write_to_first_file(tmp_path) -> None:
    first = tmp_path / "first.txt"
    first.write_text("old\n", encoding="utf-8")
    patch = _parse_ok(_diff("first.txt") + "\n" + _diff("second.txt", "one", "two"))

    result = apply_patch_to_workspace(tmp_path, patch)

    assert result.applied is False
    assert result.issue is not None
    assert result.issue.category == PHYSICAL_APPLICATION_FAILURE
    assert result.issue.reason == "read_error"
    assert result.pending_patch_cleared is False
    assert first.read_text(encoding="utf-8") == "old\n"


def test_deletion_diff_is_refused_as_unsupported() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/old.txt b/old.txt",
                "deleted file mode 100644",
                "--- a/old.txt",
                "+++ /dev/null",
                "@@ -1,1 +0,0 @@",
                "-old",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == INVALID_PATCH_PROPOSAL
    assert parsed.issue.reason == "delete_not_supported"
    assert parsed.summary is not None
    assert parsed.summary.refused_paths == ("old.txt",)


def test_rename_diff_is_refused_as_unsupported() -> None:
    parsed = parse_unified_diff(
        "\n".join(
            [
                "diff --git a/old.txt b/new.txt",
                "similarity index 100%",
                "rename from old.txt",
                "rename to new.txt",
                "--- a/old.txt",
                "+++ b/new.txt",
            ]
        )
    )

    assert parsed.issue is not None
    assert parsed.issue.category == INVALID_PATCH_PROPOSAL
    assert parsed.issue.reason == "rename_or_copy_not_supported"
