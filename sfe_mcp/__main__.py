"""Console entry point for the local SFE MCP server."""

from __future__ import annotations

from sfe.env import load_repo_env

from .server import run_stdio


def main() -> int:
    load_repo_env()
    run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
