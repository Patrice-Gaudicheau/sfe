"""Import-boundary checks for core SFE modules."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_run_and_discovery_do_not_import_tui_contracts() -> None:
    for relative_path in ("sfe/run_pipeline.py", "sfe/discovery.py"):
        tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
        imports = _imported_modules(tree)

        assert "sfe_tui.contracts" not in imports


def test_run_pipeline_does_not_import_tui_backend_types() -> None:
    tree = ast.parse((PROJECT_ROOT / "sfe/run_pipeline.py").read_text(encoding="utf-8"))
    imports = _imported_modules(tree)

    assert "sfe_tui.backends" not in imports


def _imported_modules(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports
