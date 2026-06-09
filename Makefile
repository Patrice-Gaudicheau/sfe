-include .env

.PHONY: sfe-tui

sfe-tui:
	@set -a; [ ! -f .env ] || . ./.env; set +a; python -m sfe_tui
