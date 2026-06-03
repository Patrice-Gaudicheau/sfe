COMPOSE_FILE ?= docker-compose.proxy.yml
SERVICE ?= sfe-proxy

-include .env

SFE_PROXY_HOST ?= 127.0.0.1
SFE_PROXY_PORT ?= 17891
SFE_PROXY_UPSTREAM_BASE_URL ?=

.PHONY: build install sfe-tui start stop restart logs status update remove check-port check-runtime-config

build:
	docker compose -f $(COMPOSE_FILE) build $(SERVICE)

install: build start

sfe-tui:
	@set -a; [ ! -f .env ] || . ./.env; set +a; python -m sfe_tui

check-port:
	@python -c "import socket; s=socket.socket(); s.settimeout(0.5); code=s.connect_ex(('$(SFE_PROXY_HOST)', int('$(SFE_PROXY_PORT)'))); s.close(); raise SystemExit('Port $(SFE_PROXY_HOST):$(SFE_PROXY_PORT) is already in use' if code == 0 else 0)"

check-runtime-config:
	@SFE_PROVIDER="$(SFE_PROVIDER)" SFE_PROXY_PROVIDER="$(SFE_PROXY_PROVIDER)" SFE_PROXY_UPSTREAM_BASE_URL="$(SFE_PROXY_UPSTREAM_BASE_URL)" SFE_PROXY_UPSTREAM_API_KEY="$(SFE_PROXY_UPSTREAM_API_KEY)" OPENAI_API_KEY="$(OPENAI_API_KEY)" ALIBABA_API_KEY="$(ALIBABA_API_KEY)" DASHSCOPE_API_KEY="$(DASHSCOPE_API_KEY)" GOOGLE_API_KEY="$(GOOGLE_API_KEY)" SFE_ALIBABA_BASE_URL="$(SFE_ALIBABA_BASE_URL)" SFE_GOOGLE_BASE_URL="$(SFE_GOOGLE_BASE_URL)" SFE_ANTHROPIC_API_KEY="$(SFE_ANTHROPIC_API_KEY)" ANTHROPIC_API_KEY="$(ANTHROPIC_API_KEY)" python -c "from urllib.parse import urlparse; import os, sys; aliases={'openai-api':'openai','alibaba-api':'alibaba','gemini':'google'}; provider=(os.environ.get('SFE_PROVIDER','').strip() or os.environ.get('SFE_PROXY_PROVIDER','').strip() or 'openai-compatible').lower(); provider=aliases.get(provider, provider); explicit=os.environ.get('SFE_PROXY_UPSTREAM_API_KEY',''); anth=os.environ.get('SFE_ANTHROPIC_API_KEY','') or os.environ.get('ANTHROPIC_API_KEY',''); alibaba=os.environ.get('ALIBABA_API_KEY','') or os.environ.get('DASHSCOPE_API_KEY',''); google=os.environ.get('GOOGLE_API_KEY',''); base=os.environ.get('SFE_PROXY_UPSTREAM_BASE_URL','') or (os.environ.get('SFE_ALIBABA_BASE_URL','') if provider == 'alibaba' else os.environ.get('SFE_GOOGLE_BASE_URL','') if provider == 'google' else '') or ('http://127.0.0.1:13305' if provider == 'lemonade' else 'https://api.openai.com'); host=(urlparse(base).hostname or '').lower(); openai=os.environ.get('OPENAI_API_KEY',''); ok_openai=provider in {'openai-compatible','openai'} and (explicit or (host == 'api.openai.com' and openai)); ok_lemonade=provider == 'lemonade' and explicit; ok_alibaba=provider == 'alibaba' and (explicit or alibaba); ok_google=provider == 'google' and (explicit or google); sys.exit(0 if (provider == 'anthropic' and anth) or ok_openai or ok_lemonade or ok_alibaba or ok_google else 'SFE_PROXY_UPSTREAM_API_KEY is required for openai-compatible/openai/lemonade proxy modes; ALIBABA_API_KEY or DASHSCOPE_API_KEY is required for alibaba proxy mode; GOOGLE_API_KEY is required for google proxy mode; ANTHROPIC_API_KEY or SFE_ANTHROPIC_API_KEY is required for anthropic proxy mode')"

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
