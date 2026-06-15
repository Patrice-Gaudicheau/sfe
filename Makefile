SHELL := /bin/sh

-include .env

.PHONY: install sfe-tui

install:
	@./scripts/install.sh

sfe-tui:
	@set -a; [ ! -f .env ] || . ./.env; set +a; python -m sfe_tui
