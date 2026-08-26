# ConcurseiroOS — Knowledge Base Completa

> PWA de estudo para concursos públicos com 42 features, 31 técnicas de aprendizagem baseadas em evidência científica, e IA integrada.
> Repositório: https://github.com/Bartolomeu-Cesar/ConcurseiroOS

---

## 1. ARQUITETURA

### Stack
| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn (2 workers) |
| Banco | SQLite (WAL mode, queries diretas sem ORM) + PostgreSQL opcional |
| Frontend | Vanilla JS (ES Modules), CSS puro, PDF.js |
| PWA | Service Worker (offline-first, precache + stale-while-revalidate) |
| Auth | JWT (access + refresh), passwordless via código email |
| AI | Multi-provider: Gemini, OpenAI, Claude, Grok, DeepSeek, Mistral, Ollama (local) |
| Deploy | Docker multi-stage + Nginx reverse proxy + GitHub Actions CI |
| Testes | pytest + httpx (476+ testes) |

### Estrutura de Pastas
```
backend/
├── main.py              # App FastAPI, middlewares, startup
├── database.py          # Conexão SQLite (WAL, PRAGMAs otimizados)
├── deps.py              # get_user_id (JWT ou single-user)
├── constants.py         # XP, pesos, thresholds, FSRS defaults
├── schemas.py           # Pydantic models
├── services.py          # Queries compartilhadas
├── utils.py             # calculate_streak, paginate, pdf helpers
├── fsrs.py              # Implementação FSRS-5 pura Python
├── study_ordering.py    # Ordenação inteligente (6 técnicas)
├── db/                  # tables, migrations, indexes, search, seeds
├── routers/             # 30+ routers (ver seção Features)
│   ├── questoes/        # core, stats, caderno_erros, estudo, importacao
│   ├── study_intelligence/ # core, metas, retention, techniques
│   ├── treinador/       # main, analise, calendario, sugestoes, trilha
│   ├── social/          # friends, chat, groups, feed, helpers
│   ├── analytics/       # core, advanced, export
│   ├── calendario/      # core, personalizado, inteligencia
│   ├── edital/          # core, mastery, revisao
│   ├── batalha/         # crud, gameplay, helpers, pool, results
│   ├── studyroom/       # core, pomodoro, gamification, metacognition
│   └── leagues/         # endpoints, helpers
└── tests/               # 476+ testes

frontend/
├── index.html           # SPA principal (tabs: PDFs, Ciclo, Edital, Flashcards)
├── dashboard.html       # Dashboard com 5 tabs (Visão Geral, Calendário, Analytics, Treinador, Gamificação)
├── sw.js                # Service Worker v37
├── js/pages/            # Lógica por página (index, questoes, viewer, social, etc.)
├── js/modules/          # Módulos reutilizáveis (api, auth, toast, theme, etc.)
└── css/main.css         # 65KB de estilos (tema escuro Catppuccin + claro)
```

### Padrões de Código
- Routers: `APIRouter(prefix="/api/...", tags=[...])` com Depends para auth e DB
- Packages grandes: sub-módulos com `__init__.py` exportando `router` unificado
- DB: queries SQL inline, `conn.execute()`, sem repository pattern
- Frontend: ES modules com `window.funcao = funcao` para onclick inline
- Testes: cada módulo usa `dependency_overrides[get_db_session]` com DB temporário
- Commits: conventional commits (feat:, fix:, refactor:)

---

## 2. TÉCNICAS DE ESTUDO IMPLEMENTADAS

### 2.1 Repetição Espaçada

#### FSRS-5 (Free Spaced Repetition Scheduler)
- **Arquivo:** `fsrs.py`
- **Base:** Paper FSRS-5 (700M+ reviews), R(t,S) = (1 + t/(9·S))^(-1)
- **Uso:** Flashcards e tópicos do edital
- **Config:** `desired_retention` por user (padrão 0.9), 19 pesos W[0..18]
- **Estados:** New → Learning → Review → Relearning

#### SM-2 (SuperMemo 2)
- **Endpoint:** `POST /api/flashcards/{id}/review-sm2`
- **Base:** Wozniak (1987), EF ajustado por quality 0-5
- **Config:** `SM2_INITIAL_EF=2.5`, `SM2_MIN_EF=1.3`, intervalos 1d → 6d → EF×

### 2.2 Dificuldade e Ordenação

#### Difficulty Score (0-100)
- **Endpoint:** `GET /api/study-intelligence`
- **Pesos:** Erro 40% + Tempo 20% + Recência 15% + Repetição 15% + Flashcard 10%

#### Desirable Difficulty
- **Base:** Bjork & Bjork (2011)
- **Impl:** Padrão 2 difíceis + 1 fácil, labels: reduzir/manter/aumentar/reforçar

#### Ordenação Inteligente (6 etapas)
- **Arquivo:** `study_ordering.py` → `order_items_intelligently()`
- 1. Classificação em faixas cognitivas (pretesting, reforço, relearning, difíceis, regulares)
- 2. Randomização intra-faixa
- 3. Importância/ROI
- 4. Desirable Difficulty (sequência 2:1)
- 5. Interleaving (round-robin por matéria)
- 6. Expanding Retrieval (re-inserção 5-8 posições depois)

### 2.3 Retrieval Practice

#### Active Recall
- Todo o sistema de flashcards/questões É retrieval practice
- Caderno de erros com FSRS para re-testar erros

#### Successive Relearning
- **Base:** Rawson & Dunlosky (2022)
- **Critério:** 3 acertos consecutivos = domínio
- **Endpoint:** `GET /api/study-intelligence/successive-relearning`

#### Pre-Testing Effect
- **Base:** Pan & Carpenter (2023)
- **Impl:** Itens novos (reps=0) vão primeiro (máx 20% da sessão)
- **Endpoint:** `GET /api/study-intelligence/pre-test`

#### Expanding Retrieval (intra-sessão)
- **Base:** Karpicke & Roediger (2007)
- **Impl:** Re-insere até 3 itens errados 5-8 posições depois

### 2.4 Elaboração e Metacognição

#### Elaborative Interrogation
- **Base:** Dunlosky et al. (2013)
- **Impl:** 20 prompts contextuais (por_que, diferenciação, exemplo, consequência, etc.)
- Sugerido após erros em flashcards/questões

#### Self-Explanation
- **Base:** Chi et al. (1989)
- **Endpoint:** `POST /api/study-intelligence/self-explanation`

#### Calibração Metacognitiva
- **Impl:** Overconfidence index = (confiança reportada) - (% acerto real)
- Status: "ilusão de saber" (>20), "calibrado" (±10), "subconfiante" (<-10)

#### Técnica Feynman
- **Endpoint:** `POST /api/feynman`
- "Explique como se fosse para uma criança" + avaliação via IA

#### Metacognição (Intention + Reflection)
- **Base:** Gollwitzer (1999) — Implementation Intentions
- **Impl:** Antes da sessão = intenção, depois = reflexão (5 campos)

### 2.5 Interleaving e Variação

#### Interleaving
- **Base:** Rohrer (2012), +20-40% retenção vs blocked practice
- **Impl:** Round-robin por matéria em flashcards, ciclo semanal, estudo diário

#### Contextual Variation
- 5 formatos: flashcard, questão, dissertativa, ensinar, conexões

#### Dual Coding
- **Base:** Paivio (1971)
- 6 templates visuais (fluxograma, tabela, mapa mental, timeline, causa-efeito, mnemônico)

### 2.6 Memória e Consolidação

#### Retrieval Strength (Força de Memória)
- **Fórmula:** R = (1 + dias/(9·stability))^(-1) × 100
- "at_risk" quando R < 50% e dias > 3

#### Forgetting Curve + Alertas
- Projeção de 30 dias por matéria
- Alertas proativos: itens que cairão abaixo de 90% amanhã

#### Sleep Consolidation
- Revisão antes de dormir (21h-1h) + ao acordar (5-9h) = +20%
- Retorna flashcards difíceis + erros dos últimos 3 dias

#### Memory Palace / Loci
- Template com 8 posições
- Ideal para: listas, artigos, princípios, prazos

### 2.7 Adaptação e Detecção

#### CAT (Computerized Adaptive Testing)
- **Base:** IRT 1-PL, zona flow 65-80% acerto
- Theta atualizado a cada resposta: `±0.4 × (surpresa)`

#### Fatigue Detection (intra-sessão)
- Monitora tempo+acerto por questão em tempo real
- Status: flow → fadiga_leve → fadiga_moderada → fadiga_alta

#### Burnout Detection
- Horas > meta × 1.5 por 5+ dias = moderado
- Horas > meta × 2.0 por 3+ dias = alto

#### Meta Adaptativa (+15%/semana)
- Progressão automática baseada no ritmo da semana anterior
- Mínimos: 5h/sem, 20 questões/sem, 10 flashcards/sem

#### Detecção de Platô
- Matérias sem melhora (±3%) em 2+ semanas e abaixo de 80%
- Sugestões: aumentar dificuldade, interleaving, generation mode

### 2.8 Pomodoro e Study Room

#### Pomodoro com Focus Score
- 5 fatores: tempo foco 40%, ciclos 20%, break-cards 20%, meta 10%, commitment 10%
- Ciclos configuráveis (padrão 25min foco + 5min pausa)

#### Break Cards (Micro-Retrieval durante pausas)
- Máx 5 flashcards/súmulas priorizados por urgência

#### Guided Mindfulness
- Respiração 4-4-6 em 8 ciclos (2min) para recuperação cognitiva

---

## 3. FEATURES POR CATEGORIA

### 🎮 Gamificação (4)
| Feature | Descrição |
|---------|-----------|
| Streaks & XP | Streak diário, XP por atividade, 15 badges, níveis (500 XP/nível) |
| Ligas Semanais | 4 tiers (Bronze→Diamante), promoção/rebaixamento, bots |
| Desafios | Semanais personalizados + Desafio Diário (5q por IA) |
| Batalha | Quiz multiplayer até 5 jogadores, rodadas configuráveis |

### 👥 Social (5)
| Feature | Descrição |
|---------|-----------|
| Amizades | Solicitações, aceitar/rejeitar |
| Chat | Mensagens diretas entre amigos |
| Grupos | Grupos com roles, ranking interno, desafios |
| Feed | Atividades dos amigos |
| Study Room | Sala virtual com Pomodoro, gamificação, metacognição, discussão |

### 📊 Analytics (4)
| Feature | Descrição |
|---------|-----------|
| Relatórios | Semanal, diário, radar, heatmap, projeção |
| Avançado | Curva esquecimento, raio-x banca, ROI, weekly-wrap |
| Export | CSV/JSON, importação, compartilhamento |
| Dashboard | Consolidado: horas, questões (total+hoje), edital, flashcards |

### 📅 Calendário (4)
| Feature | Descrição |
|---------|-----------|
| Agenda | Blocos de tempo com Play button |
| Personalizado | CRUD semanal, marcar concluído |
| Inteligência | Matérias negligenciadas, micro-revisão, spacing |
| Planejador | Grade semanal auto-gerada por scoring |

### ❓ Questões (7)
| Feature | Descrição |
|---------|-----------|
| CRUD | Criar, editar, responder com tempo/confiança |
| Stats | Por matéria/banca/prova, filtros |
| Caderno Erros | FSRS nos erros, revisão espaçada |
| Estudo | Daily challenge, active recall, intercalação |
| Importação | CSV, PDF (OCR), URL (scraping) |
| Simulados | Manual, prova-real, cronometrado |
| Súmulas | CRUD com SM-2 integrado |

### 🤖 IA (3)
| Feature | Descrição |
|---------|-----------|
| AI Tutor | 6 especialidades: explicar erro, gerar flashcards, simplificar lei, Feynman, gerar questões, dicas |
| Generation | "Gere a resposta de memória" (sem alternativas) — 40% mais efetivo |
| Treinador | 8 camadas de inteligência, recomendações personalizadas |

### 📚 Estudo (10)
| Feature | Descrição |
|---------|-----------|
| Flashcards | SM-2 + FSRS, speed review, limite Anki novos/dia |
| Edital | Tópicos por concurso/cargo, mastery, revisão espaçada |
| Ciclo | Scoring inteligente, 4 visões (diário/semanal/mensal/completo) |
| Study Intelligence | Difficulty, retrieval, interleaving, pre-test, calibration |
| CAT | Sessão adaptativa IRT, zona flow |
| Fatigue | Detecção em tempo real |
| Feynman | Explicação + avaliação IA |
| PDFs | Árvore, progresso, bookmarks, notas |
| Cadernos | Coleções temáticas |
| Notas/Bookmarks | Por página em PDFs |

---

## 4. CONSTANTES IMPORTANTES

```python
# XP
XP_PER_HOUR = 100
XP_PER_QUESTION = 10
XP_PER_CORRECT = 5
XP_PER_FLASHCARD = 5
XP_PER_TOPIC = 25
XP_PER_SIMULADO = 50
XP_STREAK_WEEKLY_BONUS = 200
LEVEL_XP = 500

# FSRS
FSRS_DEFAULT_RETENTION = 0.9
FSRS_MIN_STABILITY = 0.01
FSRS_MAX_DIFFICULTY = 10.0
FSRS_MIN_DIFFICULTY = 1.0

# SM-2
SM2_INITIAL_EF = 2.5
SM2_MIN_EF = 1.3
SM2_FIRST_INTERVAL = 1
SM2_SECOND_INTERVAL = 6

# Treinador
WEIGHT_ACCURACY = 0.4
WEIGHT_PROGRESS = 0.3
WEIGHT_CONSISTENCY = 0.3

# Difficulty Score
W_ERROR_RATE = 0.40
W_RESPONSE_TIME = 0.20
W_RECENCY = 0.15
W_REPETITION = 0.15
W_FLASHCARD_FAIL = 0.10

# Ligas
PROMOTION_ZONE = 3
DEMOTION_ZONE = 3
MIN_LEAGUE_SIZE = 15
MAX_LEAGUE_SIZE = 20
```

---

## 5. ROADMAP — TÉCNICAS PARA IMPLEMENTAR

### 5.1 Técnicas Parcialmente Implementadas (completar)

| Técnica | Status Atual | O que falta |
|---------|-------------|-------------|
| Generation Effect | Mencionado em platô detection | Endpoint dedicado com tracking de respostas geradas vs múltipla escolha |
| Blocked Practice Detection | Interleaving aplicado mas silencioso | Alertar quando user faz 10+ questões da mesma matéria seguidas |
| Confidence Slider em Flashcards | Só existe em questões_respostas | Adicionar campo `confianca` em flashcard reviews |
| Mindfulness Auto | Endpoint existe | Disparar automaticamente após Pomodoro (frontend) |
| Transfer Testing | Variação contextual sugere | Teste formal: mesma matéria em formato nunca visto |
| Overlearning Detection | Burnout por horas | Alertar itens com stability > 60 dias sendo revisados |
| Distributed Practice Planning | Ciclo distribui por score | Calcular spacing ideal individual (stability-based) |

### 5.2 Técnicas Novas para Implementar

| Técnica | Base Científica | Complexidade | Impacto |
|---------|----------------|-------------|---------|
| **Leitner System** | Caixas 1-5 com intervalos fixos | Baixa | Alternativa visual ao FSRS |
| **Keyword Mnemonic** | Atkinson & Raugh (1975) | Média | Para vocabulário/termos técnicos |
| **Spacing Calculator** | Optimal spacing (Cepeda 2008) | Média | Gap ideal = 10-20% do período de retenção |
| **Knowledge Graphs** | Relações entre tópicos | Alta | Visualizar dependências e pré-requisitos |
| **Peer Teaching** | Webb (1991) | Média | Explicar para amigos no chat/grupo |
| **Gamified Spaced Repetition** | Boss battles nos flashcards | Baixa | Flashcard review como "batalha" contra chefe |
| **Adaptive Break Scheduling** | Ultradian rhythms (90min) | Média | Pausas calculadas por ritmo biológico |
| **Error Analysis Patterns** | Padrões de erro (distrator analysis) | Alta | Por que erra: leitura, conceito, exceção, pegadinha |
| **Anxiety Management** | Test anxiety literature | Média | Exposição gradual a condições de prova |
| **Progress Milestones** | Goal-setting theory (Locke) | Baixa | Celebrações em marcos (50%, 75%, edital completo) |

### 5.3 Evoluções de Arquitetura

| Evolução | Motivo | Prioridade |
|----------|--------|-----------|
| Modularizar ai_tutor.py | 1138 linhas, testes acoplados | Média |
| Modularizar simulados.py (797L) | Candidato a package | Baixa |
| Repository Pattern para queries | Reutilização, testabilidade | Média |
| WebSocket para Study Room | Real-time em vez de polling | Alta |
| Multi-user ai_config | Hoje hardcoded user_id=1 | Média |
| Background jobs (Celery/ARQ) | AI generation, OCR, backup | Média |

---

## 6. CONVENÇÕES E PADRÕES

### Backend
- Arquivo novo: criar em `routers/{modulo}/` se > 300 linhas
- Endpoint: sempre com `summary=`, `description=`, `tags=[]`
- Auth: `user_id: int = Depends(get_user_id)` em todo endpoint
- DB: `conn = Depends(get_db_session)`, queries inline
- Erro: `raise HTTPException(status_code=X, detail="msg")`
- Paginação: `sql_paginate()` para novos endpoints

### Frontend
- Scripts em `/js/pages/{pagina}.js` (ES module)
- Funções para onclick: expor via `window.funcao = funcao`
- Toast: `showToast('msg', 'success'|'error'|'info')`
- Fetch: usar `/api/...` (relativo), tratar `.catch()`
- SW: incrementar `CACHE_VERSION` a cada mudança em JS precacheado

### Testes
- Cada módulo de teste: `_override_db_session()` com DB temporário
- Mínimo: testar happy path + edge case por endpoint
- Fixture padrão: `setup_function` cria registros + `teardown_function` limpa

### Git
- Branch: `main` (direto para produção)
- Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`
- SW: sempre incrementar versão ao alterar JS cacheado
- Sempre rodar `pytest tests/ -q` antes de push

---

## 7. TROUBLESHOOTING COMUM

| Problema | Causa | Fix |
|----------|-------|-----|
| Botões não funcionam após deploy | SW cache-first servindo JS antigo | Incrementar `CACHE_VERSION` no sw.js |
| Streak zerado sem motivo | `calculate_streak` começa de hoje (sem atividade) | Fix: se hoje não tem registro, começar de ontem |
| Recomendações de concurso antigo | Queries sem filtro por ciclo ativo | Filtrar por `ciclo_estudos WHERE ativo=1` |
| AI Tutor 404 | Modelo descontinuado | Atualizar modelo em `ai_config` table |
| API key truncada | Modal preenche com valor mascarado | Input vazio + backend preserva se vazio |
| Rota não encontrada (405) | Package `__init__.py` não importa sub-router | Verificar includes no `__init__.py` |
| Calendário vazio | `ciclo_estudos` sem matérias ativas | Importar do edital ou criar ciclo |
