"""Import-boundary checks for core SFE modules."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe_tui import backends as tui_backends
from sfe_tui import patch_json_repair as tui_patch_json_repair


def test_core_modules_do_not_import_tui_modules() -> None:
    offenders: list[str] = []

    for path in _python_files_under("sfe"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = _imported_modules(tree)
        tui_imports = sorted(
            module
            for module in imports
            if module == "sfe_tui" or module.startswith("sfe_tui.")
        )
        if tui_imports:
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            offenders.append(f"{relative_path}: {', '.join(tui_imports)}")

    assert offenders == []


def test_core_run_and_discovery_do_not_import_tui_contracts() -> None:
    for relative_path in ("sfe/run_pipeline.py", "sfe/discovery.py"):
        tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
        imports = _imported_modules(tree)

        assert "sfe_tui.contracts" not in imports


def test_run_pipeline_does_not_import_tui_backend_types() -> None:
    tree = ast.parse((PROJECT_ROOT / "sfe/run_pipeline.py").read_text(encoding="utf-8"))
    imports = _imported_modules(tree)

    assert "sfe_tui.backends" not in imports


def test_run_pipeline_does_not_import_tui_modules() -> None:
    tree = ast.parse((PROJECT_ROOT / "sfe/run_pipeline.py").read_text(encoding="utf-8"))
    imports = _imported_modules(tree)

    assert not any(
        module == "sfe_tui" or module.startswith("sfe_tui.")
        for module in imports
    )


def test_unused_tui_compatibility_reexports_are_removed() -> None:
    assert not (PROJECT_ROOT / "sfe_tui/contracts.py").exists()
    assert not hasattr(tui_backends, "BackendResult")
    assert not hasattr(tui_patch_json_repair, "PATCH_JSON_REPAIR_MAX_INPUT_CHARS")
    assert not hasattr(tui_patch_json_repair, "PatchJsonRepairer")
    assert not hasattr(tui_patch_json_repair, "PatchJsonRepairResult")


def _python_files_under(relative_root: str) -> list[Path]:
    return sorted((PROJECT_ROOT / relative_root).rglob("*.py"))


def _imported_modules(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports
