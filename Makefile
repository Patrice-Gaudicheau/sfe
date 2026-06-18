SHELL := /bin/sh

-include .env

.PHONY: install doctor sfe-tui

install:
	@./scripts/install.sh

doctor:
	@./scripts/doctor.sh

sfe-tui:
	@set -a; [ ! -f .env ] || . ./.env; set +a; python -m sfe_tui
