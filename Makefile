COMPOSE_FILE ?= docker-compose.proxy.yml
SERVICE ?= sfe-proxy

-include .env

SFE_PROXY_HOST ?= 127.0.0.1
SFE_PROXY_PORT ?= 17891
SFE_PROXY_PROVIDER ?= openai-compatible
SFE_PROXY_UPSTREAM_BASE_URL ?= https://api.openai.com

.PHONY: build install start stop restart logs status update remove check-port check-runtime-config

build:
	docker compose -f $(COMPOSE_FILE) build $(SERVICE)

install: build start

check-port:
	@python -c "import socket; s=socket.socket(); s.settimeout(0.5); code=s.connect_ex(('$(SFE_PROXY_HOST)', int('$(SFE_PROXY_PORT)'))); s.close(); raise SystemExit('Port $(SFE_PROXY_HOST):$(SFE_PROXY_PORT) is already in use' if code == 0 else 0)"

check-runtime-config:
	@SFE_PROXY_PROVIDER="$(SFE_PROXY_PROVIDER)" SFE_PROXY_UPSTREAM_BASE_URL="$(SFE_PROXY_UPSTREAM_BASE_URL)" SFE_PROXY_UPSTREAM_API_KEY="$(SFE_PROXY_UPSTREAM_API_KEY)" OPENAI_API_KEY="$(OPENAI_API_KEY)" SFE_ANTHROPIC_API_KEY="$(SFE_ANTHROPIC_API_KEY)" ANTHROPIC_API_KEY="$(ANTHROPIC_API_KEY)" python -c "from urllib.parse import urlparse; import os, sys; provider=os.environ.get('SFE_PROXY_PROVIDER','openai-compatible'); anth=os.environ.get('SFE_ANTHROPIC_API_KEY','') or os.environ.get('ANTHROPIC_API_KEY',''); base=os.environ.get('SFE_PROXY_UPSTREAM_BASE_URL','https://api.openai.com'); host=(urlparse(base).hostname or '').lower(); explicit=os.environ.get('SFE_PROXY_UPSTREAM_API_KEY',''); openai=os.environ.get('OPENAI_API_KEY',''); sys.exit(0 if (provider == 'anthropic' and anth) or (provider == 'openai-compatible' and (explicit or (host == 'api.openai.com' and openai))) else 'SFE_PROXY_UPSTREAM_API_KEY is required for openai-compatible proxy mode; ANTHROPIC_API_KEY or SFE_ANTHROPIC_API_KEY is required for anthropic proxy mode')"

start: check-runtime-config check-port
	docker compose -f $(COMPOSE_FILE) up -d $(SERVICE)

stop:
	docker compose -f $(COMPOSE_FILE) down

restart: stop start

logs:
	docker compose -f $(COMPOSE_FILE) logs -f $(SERVICE)

status:
	docker compose -f $(COMPOSE_FILE) ps

update:
	docker compose -f $(COMPOSE_FILE) pull || true
	docker compose -f $(COMPOSE_FILE) build --pull $(SERVICE)

remove:
	docker compose -f $(COMPOSE_FILE) down --remove-orphans
