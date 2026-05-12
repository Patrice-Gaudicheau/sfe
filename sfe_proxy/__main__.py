"""Command-line entry point for SFE proxy mode."""

from __future__ import annotations

from sfe.env import load_repo_env

from .config import ProxyConfig
from .server import run_server


def main() -> None:
    load_repo_env()
    run_server(ProxyConfig.from_env())


if __name__ == "__main__":
    main()
