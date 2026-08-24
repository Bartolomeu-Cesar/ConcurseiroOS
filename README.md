# 📚 ConcurseiroOS

[![CI](https://github.com/Bartholomew/ConcurseiroOS/actions/workflows/ci.yml/badge.svg)](https://github.com/Bartholomew/ConcurseiroOS/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**Plataforma PWA para estudo de concursos públicos** — Vanilla JS + FastAPI + SQLite.

Leitor de PDFs com tracking, plano de estudos inteligente com ciclo pomodoro, flashcards FSRS, banco de questões, simulados cronometrados, batalhas PvP, analytics avançado e tutor IA multi-provider.

---

## 📸 Screenshots

<!-- TODO: adicionar screenshots -->
| Dashboard | Leitor PDF | Questões | Batalha |
|-----------|-----------|----------|---------|
| *em breve* | *em breve* | *em breve* | *em breve* |

---

## 🚀 Instalação

### Windows (mais fácil)

Duplo-clique em **`Setup-e-Iniciar.cmd`** — configura tudo e abre o navegador.

### Linux / macOS

```bash
git clone https://github.com/Bartholomew/ConcurseiroOS.git
cd ConcurseiroOS
make dev
```

### Docker

```bash
docker compose up --build
```

Acesse: [http://localhost:8000](http://localhost:8000)

---

## 🏗️ Arquitetura

```
ConcurseiroOS/
├── backend/
│   ├── routers/          # Endpoints FastAPI (questoes, edital, ciclo, batalha, etc.)
│   ├── db/               # Migrations, tables, indexes, seeds
│   ├── tests/            # Pytest suite
│   ├── main.py           # App entrypoint
│   └── requirements.txt
├── frontend/
│   ├── css/main.css      # Design system consolidado (Catppuccin)
│   ├── js/
│   │   ├── pages/        # Lógica por página
│   │   ├── modules/      # Módulos compartilhados (auth, api, toast, etc.)
│   │   └── components/   # Web components
│   ├── *.html            # Páginas (SPA-like com sidebar)
│   └── sw.js             # Service Worker (offline-first)
├── .github/workflows/    # CI (lint + test + Docker build + Trivy)
├── Makefile              # Comandos dev/test/lint/clean/docker
├── docker-compose.yml    # Dev environment
├── docker-compose.prod.yml
└── deploy.sh             # Deploy script (prod)
```

---

## 🛠️ Comandos úteis

| Comando | Descrição |
|---------|-----------|
| `make dev` | Cria venv, instala deps, inicia uvicorn com reload |
| `make test` | Roda pytest |
| `make lint` | Ruff check + format --check |
| `make clean` | Remove `__pycache__`, `.pyc`, temp files |
| `make docker-up` | `docker compose up -d --build` |
| `make docker-down` | `docker compose down` |
| `make backup` | POST /api/backups (servidor precisa estar rodando) |
| `make setup` | Instala pre-commit hooks |
| `./deploy.sh` | Deploy produção (Docker + Nginx) |
| `./deploy.sh status` | Status dos containers |
| `./deploy.sh logs` | Logs em tempo real |
| `./deploy.sh rollback` | Reverte para versão anterior |

---

## 💻 Tecnologias

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn, SQLite (aiosqlite) |
| Frontend | HTML5, CSS3, JavaScript (Vanilla), PDF.js |
| Design | Catppuccin Mocha/Latte, CSS custom properties |
| PWA | Service Worker, Web Push, Offline-first |
| AI Tutor | Multi-provider (OpenAI, Claude, Gemini, Grok, DeepSeek) |
| Auth | JWT + código por email (SMTP) |
| Revisão | FSRS (Free Spaced Repetition Scheduler) |
| Infra | Docker, Nginx, Docker Compose |
| CI/CD | GitHub Actions (ruff, pytest, pip-audit, Trivy) |
| Linting | Ruff (lint + format), pre-commit hooks |

---

## 🧪 Testes

```bash
make test
# ou manualmente:
cd backend && python -m pytest tests/ -v
```

---

## 🔧 Desenvolvimento

### Pre-commit hooks

```bash
make setup
# ou manualmente:
pip install pre-commit
pre-commit install
```

Hooks configurados: trailing-whitespace, end-of-file-fixer, check-yaml, check-json, ruff (lint + format).

### API docs

Com o servidor rodando:
- **Swagger**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 🤝 Contribuição

1. Fork o repositório
2. Crie uma branch (`git checkout -b feature/minha-feature`)
3. Commit (`git commit -m 'feat: adiciona X'`)
4. Push (`git push origin feature/minha-feature`)
5. Abra um Pull Request

### Convenções

- Commits: [Conventional Commits](https://www.conventionalcommits.org/)
- Code style: `ruff` (Python)
- Testes obrigatórios para novas features
- PRs precisam passar no CI

---

## 📄 License

MIT — veja [LICENSE](LICENSE) para detalhes.
