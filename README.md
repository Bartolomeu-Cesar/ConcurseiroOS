# 📚 ConcurseiroOS

**Plataforma completa de estudos para concursos públicos** — leitor de PDFs com tracking de progresso, plano de estudos inteligente, flashcards com repetição espaçada (FSRS), questões, simulados, batalhas, analytics e tutor IA.

![Status](https://img.shields.io/badge/status-active-brightgreen)
![Python](https://img.shields.io/badge/python-3.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 📸 Screenshots

<!-- TODO: Add screenshots -->
| Dashboard | Leitor PDF | Questões |
|-----------|-----------|----------|
| *em breve* | *em breve* | *em breve* |

---

## 🚀 Quick Start (Desenvolvimento Local)

### Windows (Mais fácil)

Duplo-clique em `Setup-e-Iniciar.cmd` — faz tudo automaticamente.

### Manual

```bash
# 1. Clone
git clone https://github.com/Bartholomew/LeitorPDF.git
cd LeitorPDF

# 2. Instale dependências
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure
cp ../.env.example ../.env
# Edite .env com suas configurações (AUTH_ENABLED=false para dev)

# 4. Inicie
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Acesse: [http://localhost:8000](http://localhost:8000)

### Docker (Desenvolvimento)

```bash
docker compose up --build
```

---

## 🏭 Production Deployment

### Pré-requisitos

- Docker 24+ com Docker Compose v2
- Domínio configurado (opcional, para SSL)

### Deploy

```bash
# 1. Configure o ambiente
cp .env.example .env
# Edite .env — defina JWT_SECRET, SMTP, e API keys

# 2. (Opcional) Coloque certificados SSL em nginx/certs/
#    fullchain.pem + privkey.pem
#    Descomente as linhas SSL em nginx/nginx.conf

# 3. Deploy!
chmod +x deploy.sh
./deploy.sh
```

### Comandos úteis

```bash
./deploy.sh status    # Ver status dos serviços
./deploy.sh logs      # Acompanhar logs em tempo real
./deploy.sh rollback  # Reverter para versão anterior
./deploy.sh stop      # Parar tudo
```

### Arquitetura em Produção

```
Internet → Nginx (80/443) → App (8000, uvicorn 2 workers)
                ↓
         Static files (frontend/)
                ↓
         Volumes: /data/progress.db, /data/pdfs, /data/backups
```

---

## 🛠️ Tech Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn, SQLite (aiosqlite) |
| Frontend | HTML5, CSS3, JavaScript (vanilla), PDF.js |
| AI Tutor | Multi-provider (OpenAI, Claude, Gemini, Grok, DeepSeek, etc.) |
| Auth | JWT + código por email (SMTP) |
| Revisão | FSRS (Free Spaced Repetition Scheduler) |
| Deploy | Docker, Nginx, Docker Compose |
| CI | GitHub Actions (lint + tests) |
| PWA | Service Worker, Web Push Notifications |

---

## 📖 API Documentation

Com o servidor rodando, acesse:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

Principais endpoints:

| Rota | Descrição |
|------|-----------|
| `GET /api/health` | Health check |
| `POST /api/auth/*` | Autenticação |
| `GET /api/pdfs` | Listar PDFs |
| `GET /api/progress` | Progresso de leitura |
| `POST /api/questoes` | Banco de questões |
| `GET /api/analytics/*` | Métricas e analytics |
| `POST /api/ai-tutor/*` | Tutor IA |

---

## 🧪 Testes

```bash
cd backend
pip install pytest httpx
pytest tests/ -v
```

---

## 🤝 Contributing

1. Fork o repositório
2. Crie uma branch para sua feature (`git checkout -b feature/minha-feature`)
3. Commit suas mudanças (`git commit -m 'feat: adiciona X'`)
4. Push para a branch (`git push origin feature/minha-feature`)
5. Abra um Pull Request

### Convenções

- Commits seguem [Conventional Commits](https://www.conventionalcommits.org/)
- Code style: `ruff` (Python), formatação padrão
- Testes são obrigatórios para novas features
- PRs precisam passar no CI (lint + testes)

---

## 📄 License

MIT License — veja [LICENSE](LICENSE) para detalhes.

---

## 🙏 Agradecimentos

- [PDF.js](https://mozilla.github.io/pdf.js/) — renderização de PDF
- [FastAPI](https://fastapi.tiangolo.com/) — framework web
- [FSRS](https://github.com/open-spaced-repetition/fsrs4anki) — algoritmo de repetição espaçada
