# ConcurseiroOS — Makefile multiplataforma
# Funciona em Linux, macOS e Windows (via WSL/Git Bash/Make for Windows)

SHELL := /bin/bash
VENV := backend/venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff

ifeq ($(OS),Windows_NT)
	PYTHON := $(VENV)/Scripts/python
	PIP := $(VENV)/Scripts/pip
	UVICORN := $(VENV)/Scripts/uvicorn
	PYTEST := $(VENV)/Scripts/pytest
	RUFF := $(VENV)/Scripts/ruff
endif

.PHONY: dev test lint clean docker-up docker-down backup setup help

help: ## Mostra esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

dev: ## Cria venv, instala deps e inicia uvicorn (dev)
	@if [ ! -d "$(VENV)" ]; then \
		echo "🔧 Criando virtualenv..."; \
		python3 -m venv $(VENV); \
	fi
	@echo "📦 Instalando dependências..."
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r backend/requirements.txt
	@echo "🚀 Iniciando servidor em http://localhost:8000"
	@$(UVICORN) backend.main:app --host 0.0.0.0 --port 8000 --reload

test: ## Roda pytest
	@$(PYTEST) backend/tests/ -v --tb=short

lint: ## Roda ruff check + ruff format --check
	@$(RUFF) check backend/
	@$(RUFF) format --check backend/

clean: ## Remove __pycache__, .pyc e arquivos temporários
	@echo "🧹 Limpando..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Limpo!"

docker-up: ## Docker compose up -d
	@docker compose up -d --build

docker-down: ## Docker compose down
	@docker compose down

backup: ## Cria backup via API (servidor deve estar rodando)
	@curl -s -X POST http://localhost:8000/api/backups | python3 -m json.tool

setup: ## Instala pre-commit hooks
	@if [ ! -d "$(VENV)" ]; then \
		python3 -m venv $(VENV); \
	fi
	@$(PIP) install --quiet pre-commit
	@$(VENV)/bin/pre-commit install
	@echo "✅ Pre-commit hooks instalados!"
