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

### 5.3 Integrações Externas

| Integração | API | Complexidade | Caso de Uso |
|-----------|-----|-------------|-------------|
| **WhatsApp Cloud API** | Meta for Developers (gratuita) | Média | Notificar amigos, enviar resumo diário, lembrete de streak, compartilhar progresso |
| **Telegram Bot API** | Telegram (gratuita, sem aprovação) | Baixa | Alternativa ao WhatsApp, flashcards via bot, lembretes |
| **Google Calendar** | Google Calendar API | Média | Sincronizar calendário de estudos com agenda pessoal |
| **Notion API** | Notion (gratuita) | Média | Exportar edital/progresso para Notion |

#### WhatsApp Cloud API — Detalhes
- **Requisitos**: Conta Meta Business, número verificado, templates aprovados
- **Limites**: 1000 conversas/mês grátis (tier Business), mensagens template precisam aprovação
- **Funcionalidades possíveis**:
  - 📊 Resumo diário de estudo (horas, questões, streak) às 22h
  - 🔔 Lembrete de flashcards pendentes
  - 🔥 Alerta de streak em risco
  - 🏆 Notificação de conquista/badge
  - 💬 Mensagem de amigo no app → notifica via WhatsApp
  - 📋 "O que estudar hoje" (agenda do dia)
- **Fluxo**: Backend → WhatsApp Cloud API (POST /messages) → Usuário recebe no WhatsApp
- **Webhook**: Receber respostas do user (ex: "OK" confirma que vai estudar)

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
| Frontend não atualiza | SW servindo cache antigo | Unregister SW + reload |
| Endpoint retorna 401 | Token expirado ou AUTH_ENABLED=true sem token | Verificar `deps.py`, usar refresh token |
| Dados de outro user aparecem | Query sem `AND user_id = ?` | Adicionar filtro user_id em TODA query |

---

## 8. SCHEMA DO BANCO (Tabelas Principais)

### Core de Estudo
| Tabela | Colunas-chave | Propósito |
|--------|--------------|-----------|
| `sessoes_estudo` | materia, horas, data, tipo, user_id | Registro de tempo estudado |
| `streaks` | data, horas_estudadas, questoes_resolvidas, flashcards_revisados, user_id | Streak diário |
| `edital` | edital_nome, cargo, materia, topico, status, horas_estudadas, pdf_link, user_id | Tópicos do edital |
| `ciclo_estudos` | materia, horas_alvo, horas_cumpridas, ordem, ativo, user_id | Ciclo ativo de matérias |
| `metas_config` | meta_horas, meta_questoes, meta_flashcards, streak_freezes_available, desired_retention, user_id | Configurações e metas |

### Questões & Flashcards
| Tabela | Colunas-chave | Propósito |
|--------|--------------|-----------|
| `questoes` | materia, topico, enunciado, alternativa_a..e, resposta_correta, banca, ano | Banco de questões |
| `questoes_respostas` | questao_id, acertou, tempo_segundos, data, user_id, confianca | Respostas registradas |
| `flashcards` | pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, stability, difficulty, user_id | Flashcards com FSRS/SM-2 |
| `erros_revisao` | questao_id, intervalo_atual, proxima_revisao, revisoes_count, user_id | Caderno de erros (FSRS) |
| `simulados` | titulo, tempo_limite_min, status, nota, total_questoes, acertos, user_id | Simulados |

### Gamificação & Social
| Tabela | Colunas-chave | Propósito |
|--------|--------------|-----------|
| `desafios` | titulo, meta_tipo, meta_valor, progresso, dias, finalizado, user_id | Desafios semanais |
| `leagues` | week_start, tier | Ligas semanais |
| `league_members` | league_id, user_id, weekly_xp, rank, promoted, demoted | Membros das ligas |
| `battles` | codigo, criador_id, materias, total_rodadas, status | Batalhas multiplayer |
| `friendships` | user_a, user_b, status | Amizades |
| `study_groups` | nome, edital_nome, criador_id | Grupos de estudo |
| `direct_messages` | sender_id, receiver_id, mensagem, lida | Chat direto |

### Calendário & Planejamento
| Tabela | Colunas-chave | Propósito |
|--------|--------------|-----------|
| `calendario_personalizado` | dia_semana, materia, tipo, tempo_min, ordem, user_id | Grade semanal salva |
| `calendario_atividades` | data, materia, tipo, tempo_min, concluida, user_id | Atividades concluídas |
| `study_preferences` | hora_inicio, hora_fim, bloco_min, pausa_min, user_id | Preferências de horário |

### AI & Metacognição
| Tabela | Colunas-chave | Propósito |
|--------|--------------|-----------|
| `ai_config` | user_id, provider, api_key, model | Config do AI provider |
| `ai_conversations` | tipo, pergunta, resposta, tokens, user_id | Histórico AI tutor |
| `ai_usage` | data, tokens_used, requests_count, user_id | Uso diário de tokens |
| `elaboration_log` | flashcard_id, questao_id, prompt_tipo, resposta_usuario | Log de elaboração |
| `sessao_adaptativa` | session_id, materia, theta, questoes_respondidas, user_id | CAT (IRT) |

### Auth & Sistema
| Tabela | Colunas-chave | Propósito |
|--------|--------------|-----------|
| `users` | email, nome, plano, role, user_id | Usuários |
| `push_subscriptions` | endpoint, p256dh, auth, user_id | Web Push |
| `progress` | path, current_page, total_pages, user_id | Progresso em PDFs |

---

## 9. QUERIES FREQUENTES (Referência Rápida)

```sql
-- Matérias do ciclo ativo
SELECT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?

-- Questões respondidas por matéria (com % acerto)
SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
WHERE qr.user_id = ? GROUP BY q.materia

-- Flashcards pendentes hoje (reviews + novos limitados a 20)
SELECT * FROM flashcards WHERE proxima_revisao <= date('now') AND user_id = ?

-- Horas estudadas hoje
SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data = date('now') AND user_id = ?

-- Streak: dias com atividade (para calculate_streak)
SELECT data FROM streaks WHERE (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0) AND user_id = ? ORDER BY data DESC

-- Tópicos pendentes do edital (ciclo ativo)
SELECT materia, topico FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?
```

---

## 10. LIÇÕES APRENDIDAS (EARS)

> Formato: **Event** (o que aconteceu) → **Action** (o que fizemos) → **Result** (resultado) → **Summary** (regra extraída)

### #1 — Streak falso-positivo de freeze (26/08/2026)
- **Event:** App mostrava "Streak em risco! Usar freeze?" mesmo tendo estudado ontem.
- **Action:** `calculate_streak()` começava verificando se HOJE tinha registro. Se não (dia em andamento), retornava 0.
- **Result:** Alterado para começar de ontem se hoje não tem registro. Streak preservado.
- **Summary:** Lógica temporal deve considerar que o dia atual está em andamento — nunca penalizar antes do dia acabar.

### #2 — Recomendações de concurso antigo (26/08/2026)
- **Event:** Treinador recomendava "Resolver questões de STM 2025" mesmo com ciclo ativo de outro concurso.
- **Action:** Queries de `_get_study_gaps`, `study-intelligence` e `conquistas-diarias` buscavam TODAS as matérias sem filtro.
- **Result:** Adicionado filtro por `ciclo_estudos WHERE ativo = 1` em 3 endpoints.
- **Summary:** Toda query de recomendação DEVE filtrar pelo ciclo ativo. Dados históricos existem mas não devem poluir sugestões atuais.

### #3 — Botões do ciclo não funcionavam (26/08/2026)
- **Event:** Botões Semanal/Mensal/Completo no ciclo de estudos não respondiam ao click.
- **Action:** SW usava cache-first para `.js` mas `/js/pages/index.js` não estava no PRECACHE_URLS. Versão antiga (sem `window.switchCicloView`) era servida do cache.
- **Result:** Adicionado scripts de páginas ao PRECACHE_URLS + incrementado SW version para invalidar cache.
- **Summary:** Todo JS que usa `window.funcao` para onclick DEVE estar no PRECACHE_URLS. Sempre incrementar SW version ao alterar JS cacheado.

### #4 — Feedback C/E mostrava "Resposta: A" (26/08/2026)
- **Event:** Ao errar questão Certo/Errado, feedback mostrava "Resposta: A" e Self-Explanation dizia "a resposta correta é 'A'" em vez de "CERTO".
- **Action:** `q.resposta_correta` era exibido cru (letra) sem traduzir para texto em questões C/E.
- **Result:** Adicionado check `isCE` com tradução `A→CERTO, B→ERRADO` em 3 arquivos (modules/questoes.js, treinador.js, viewer.js).
- **Summary:** Questões C/E armazenam resposta como letra (A/B) no banco. Todo feedback ao usuário deve traduzir para texto legível.

### #5 — Card do Domingo quebrando layout (26/08/2026)
- **Event:** No calendário semanal, o card de Domingo ficava fora do container principal.
- **Action:** Grid de 7 colunas sem `min-width:0` permitia que conteúdo longo expandisse o card além do espaço disponível.
- **Result:** Adicionado `min-width:0` + `overflow:hidden` no `.cal-grid` e `.cal-day`. Textos de matéria com `ellipsis`.
- **Summary:** CSS Grid items precisam de `min-width:0` para respeitar o espaço alocado. Sem isso, conteúdo longo empurra o layout.

### #6 — CSS truncava texto que tinha expansão JS (26/08/2026)
- **Event:** Após fix do layout, detalhe dos tópicos ficou truncado sem possibilidade de expandir ao clicar.
- **Action:** `white-space:nowrap` + `text-overflow:ellipsis` no CSS sobrescrevia a lógica JS de truncar/expandir via onclick.
- **Result:** Removido CSS forçado do `.cal-activity-detail`. Truncamento volta a ser controlado pelo JS (slice + data-full + onclick).
- **Summary:** Nunca aplicar CSS de truncamento em elementos que têm comportamento interativo via JS. O JS é quem controla a UX, CSS só estiliza.

### #7 — Menu de perfil diferente em cada página (26/08/2026)
- **Event:** Clicar no avatar mostrava menu diferente dependendo da tela (index = completo, dashboard = links, questões = redirecionava).
- **Action:** Cada página tinha implementação própria do menu de perfil (3 versões independentes).
- **Result:** Unificado para usar `handleAuthNav()` → `showProfileMenu()` do `auth.js` em todas as páginas.
- **Summary:** Componentes de UI (menus, modais, toasts) devem ter implementação ÚNICA em módulo compartilhado. Duplicar = divergir inevitavelmente.

### #8 — API key truncada ao salvar configuração de IA (sessão anterior)
- **Event:** Ao salvar configuração do AI Tutor, a chave era sobrescrita com valor mascarado (`****...xxxx`).
- **Action:** Modal preenchia o input com o valor mascarado. Ao salvar, backend gravava o valor mascarado como a nova key.
- **Result:** Input de API key agora fica vazio. Backend preserva a key existente se o campo vier vazio.
- **Summary:** Campos de segredo nunca devem ser pré-preenchidos com valor mascarado. Vazio = "não alterar".


---

## 7. SESSÃO 27/08/2026 — Migração FSRS + 18 Técnicas de Estudo

### 7.1 Migrações Executadas
- **SM-2 → FSRS-5**: Frontend agora chama `/review-fsrs`. 14 cards migrados. Good = ~3d no primeiro acerto (antes: 1d).
- **Spaced Repetition em Questões**: `_schedule_question_review()` no `/api/questoes/{id}/responder` agenda revisão FSRS para erros e chutes.
- **Smart Selection**: `_smart_select_questions()` em simulados e desafio diário (exclui dominadas, prioriza erradas + nunca vistas + interleaving).

### 7.2 Técnicas Implementadas (Endpoints)

| # | Técnica | Endpoint | Commit |
|---|---------|----------|--------|
| 1 | FSRS-5 Flashcards | `/api/flashcards/{id}/review-fsrs` | 811e1ab |
| 2 | FSRS Questões | Automático em `/responder` | f3d3c39 |
| 3 | Smart Selection | `/api/simulado-inteligente` + cronometrado + desafio | 29ed216 + f3d3c39 |
| 4 | Confidence-based | Automático em `/responder` (tempo + confiança) | f3d3c39 |
| 5 | Blocked Practice Detection | `/api/study-intelligence/blocked-practice` + inline | 3361afd |
| 6 | Sleep Consolidation | `/api/study-intelligence/sleep-consolidation` | 3361afd |
| 7 | Overlearning Detection | `/api/study-intelligence/overlearning` | 3361afd |
| 8 | Transfer Testing | `/api/study-intelligence/transfer-test` | b3289a9 |
| 9 | Adaptive Break | `/api/study-intelligence/adaptive-break` | b3289a9 |
| 10 | Progress Milestones | `/api/study-intelligence/milestones` | b3289a9 |
| 11 | Error Analysis Patterns | `/api/study-intelligence/error-patterns` | b3289a9 |
| 12 | Retrieval Warmup | `/api/study-intelligence/retrieval-warmup` | 957a8ad |
| 13 | Minimum Effective Dose | `/api/study-intelligence/minimum-dose` | 957a8ad |
| 14 | Implementation Intentions | `/api/study-intelligence/intention` + `/concluir` + `/hoje` | 957a8ad |
| 15 | Banca-Specific Profile | `/api/study-intelligence/banca-profile` | 3ed975a |
| 16 | Banca Training Session | `/api/study-intelligence/banca-training` | 3ed975a |

### 7.3 Bugs Corrigidos
- **Study Room 61.48h**: Sessão inflada → cap 4h/sessão + fix sairSala() não registrava tempo
- **Ciclo visões não carregavam**: closeSidebar null crashava index.js → switchCicloView movida para ciclo.js
- **Resumo semanal errado**: Dados corrigidos (total real: 5.74h, não 65.2h)

### 7.4 Roadmap — Técnicas Futuras (implementar progressivamente)

| # | Técnica | Complexidade | Dependências | Descrição |
|---|---------|-------------|--------------|-----------|
| 1 | **Exam Anxiety Exposure** | Média | Simulados | Simulados progressivamente mais estressantes (tempo apertado → nota de corte visível → ambiente barulhento simulado). Exposição gradual reduz ansiedade. |
| 2 | **Peer Teaching via Chat** | Alta | Social/Chat | Explicar conteúdo para amigos no chat = processamento profundo (Webb 1991). Detectar quando user ensina e dar XP bônus. |
| 3 | **Gamified Spaced Rep** | Baixa | Flashcards + Batalha | Flashcard review como "batalha contra chefe". Boss HP = difficulty do card. Critical hit = Easy. Miss = Again. Motivação via narrativa. |
| 4 | **Knowledge Graph Navigation** | Alta | Edital + Mastery | Visualizar mapa de dependências entre tópicos. "Não estude X antes de dominar Y". Sugere ordem ótima baseada em pré-requisitos. |

### 7.5 Perfis de Banca (dados compilados)

**CESPE/CEBRASPE**: C/E, penalização -1, doutrina+jurisprudência, NÃO CHUTE se <70% certeza.
**FCC**: 5 alternativas, sem penalização, provas extensas, interpretação, gestão de tempo.
**FGV**: 5 alternativas, sem penalização, imprevisível, math pura em RLM, varia por órgão.
**VUNESP**: 5 alternativas, sem penalização, SP, direta, legislação específica.


---

## 8. ROADMAP — Features Gap vs Mercado (implementação progressiva)

### 8.1 Comparativo Competitivo (27/08/2026)

**Nosso diferencial exclusivo (ninguém no mercado tem):**
- 22 técnicas de estudo com base científica integradas no fluxo
- FSRS-5 em flashcards E questões (spaced repetition de verdade)
- Seleção inteligente (exclui dominadas, prioriza erradas + nunca vistas)
- Detecção automática: fadiga, blocked practice, overlearning, platô
- Sleep consolidation, retrieval warmup, minimum effective dose
- Boss Battle, banca-specific training, anxiety exposure
- PWA offline-first gratuita e open-source

**Gaps identificados vs QConcursos, Gran Cursos, RemNote, EmÁudio:**

### 8.2 Features para Implementar (prioridade decrescente)

| # | Feature | Referência | Impacto | Complexidade | Status |
|---|---------|-----------|---------|--------------|--------|
| 1 | **Comentários em questões** | QConcursos, Gran | ⭐⭐⭐ | Média | 🔲 Pendente |
|   | Permitir user e IA adicionarem explicações/comentários em cada questão. Comunidade vota nos melhores. | | | | |
| 2 | **Estudo por áudio (TTS)** | EmÁudio, Gran | ⭐⭐⭐ | Baixa-Média | 🔲 Pendente |
|   | Text-to-Speech para flashcards, súmulas e leis. Modo "commuting" (ouvir enquanto caminha/dirige). Web Speech API no frontend ou API externa (ElevenLabs/Google TTS). | | | | |
| 3 | **Mapas mentais visuais** | Gran, RemNote | ⭐⭐ | Média | 🔲 Pendente |
|   | Geração automática via IA a partir de tópicos do edital. Templates visuais (canvas SVG ou lib como Mermaid/D3). | | | | |
| 4 | **Notificações push inteligentes** | Quizlet, Anki | ⭐⭐ | Baixa | 🔲 Pendente |
|   | Backend já tem push_subscriptions + notification_log. Falta: triggers automáticos (streak em risco, flashcard pendente, sleep consolidation, meta não batida). Cron job ou check no login. | | | | |
| 5 | **Importação direta de provas (scraping)** | QConcursos, TEC | ⭐⭐⭐ | Alta | 🔲 Pendente |
|   | Scraper para importar questões de sites públicos (QConcursos, PCI). Parser de PDF de prova com OCR (já tem endpoint parcial). | | | | |
| 6 | **Vade mecum digital** | Gran | ⭐⭐ | Média | 🔲 Pendente |
|   | Leis indexadas com busca full-text. Links entre artigos e questões. Anotações inline. Highlight de trechos cobrados. | | | | |
| 7 | **Compartilhamento de progresso** | Aprovado | ⭐ | Baixa | 🔲 Pendente |
|   | Card bonito para compartilhar em redes sociais (imagem gerada server-side com stats do user). "Estudei 50h essa semana!" | | | | |
| 8 | **Modo commuting (áudio flashcards)** | EmÁudio | ⭐⭐ | Média | 🔲 Pendente |
|   | Player de áudio que lê pergunta → pausa → lê resposta. Controle por gesture/fone. Ideal para transporte. | | | | |

### 8.3 Features Futuras (longo prazo)

| # | Feature | Descrição | Complexidade |
|---|---------|-----------|--------------|
| 9 | **Videoaulas integradas** | Player com anotações timestamped, vincular ao tópico do edital | Alta |
| 10 | **OCR em tempo real** | Fotografar caderno/livro → gerar flashcards automaticamente | Alta |
| 11 | **Estudo colaborativo síncrono** | Estudar junto com resolução simultânea (like Google Docs) | Alta |
| 12 | **IA geradora de questões** | Gerar questões inéditas no estilo da banca a partir do tópico | Média |
| 13 | **Simulado adaptativo real-time** | CAT verdadeiro que ajusta dificuldade A CADA questão | Média |
| 14 | **Resumos automáticos** | IA resume PDFs/aulas em bullets para revisão rápida | Média |
| 15 | **Planner de longo prazo** | Countdown até prova com distribuição ótima de matérias ao longo dos meses | Média |
| 16 | **Integração WhatsApp/Telegram** | Bot que manda lembrete de revisão, quiz rápido, resumo do dia | Média |

### 8.4 Ordem de Implementação Recomendada

**Sprint 1 (próxima sessão):**
1. Notificações push inteligentes (backend quase pronto)
2. Estudo por áudio / TTS (Web Speech API = sem custo)
3. Comentários em questões (CRUD + IA auto-comment)

**Sprint 2:**
4. Importação de provas melhorada (PDF parser + scraping)
5. Compartilhamento de progresso (card social)
6. Mapas mentais (Mermaid.js)

**Sprint 3:**
7. Vade mecum digital (leis indexadas)
8. Modo commuting (player áudio)
9. IA geradora de questões

**Sprint 4 (longo prazo):**
10-16. Features de alta complexidade conforme demanda


---

## 9. SESSÃO 28/08/2026 — 20 Técnicas Científicas + Parser Estratégia + Embaralhamento

### 9.1 Técnicas Científicas de Estudo (20 novas implementadas)

O app agora tem **29 técnicas** integradas ao fluxo de revisão. Todas baseadas em papers peer-reviewed.

| # | Técnica | Local | Evidência | Descrição |
|---|---------|-------|-----------|-----------|
| 1 | Elaborative Interrogation | `flashcards.js` | Dunlosky 2013 | Prompt "Por quê?" a cada 3 acertos. Salva em `elaboration_log` |
| 2 | Serial Position Effect | `study_ordering.py` | Murdock 1962 | Itens de reforço nas posições 1-2 (primacy), relearning nas últimas 2 (recency) |
| 3 | Lag Effect (Exam-Aware) | `flashcards.py` review-fsrs | Cepeda 2006 | Comprime intervalos FSRS baseado em `get_dias_ate_prova()`. Prova <60d = fator 0.5-1.0 |
| 4 | Free Recall (Brain Dump) | `techniques.py` + `flashcards.js` | Karpicke & Blunt 2011 | Textarea para escrever tudo + gap analysis vs edital. Tabela `brain_dump_log` |
| 5 | Chunking | `flashcards.js` | Miller 1956 | Pausa reflexiva a cada 6 cards + mini-resumo. Sessões 8+ cards |
| 6 | Keyword Mnemonic | `flashcards.js` | Pressley 1982 | Sugestão de mnemônicos após errar card difícil (quality<=1, repetitions>0) |
| 7 | Variação de Contexto | `flashcards.js` | Smith 1978 | Cards `_expanding_retrieval` mostrados invertidos (resposta→pergunta) |
| 8 | Errorful Learning | `questoes.js` + `core.py` | Kornell 2009 | Após erro, busca questão similar via `/api/questoes/similar` para teste imediato |
| 9 | Distributed Summary | `flashcards.js` | Rawson & Dunlosky 2022 | Prompt "Resuma em 1 frase" ao final da sessão (3+ cards) |
| 10 | Encoding Specificity (Modo Prova) | `flashcards.js` | Tulving & Thomson 1973 | `startExamMode()` desabilita todas as ajudas — simula pressão real |
| 11 | Hypercorrection Effect | `flashcards.js` | Butterfield & Metcalfe 2001 | Tela impactante quando confiança>=4 E quality<=1. Surprise signal |
| 12 | Forward Testing Effect | `flashcards.js` (chunking) | Chan 2018, Pastötter 2011 | Quiz de 2 cards do bloco anterior na pausa reflexiva |
| 13 | Micro-Breaks Cognitivos | `flashcards.js` | Frontiers 2025 | Pausa de 5s com countdown após cards difíceis (quality<=2). Auto-advance |
| 14 | Testing Boundaries | `techniques.py` | Bjork 2011 | Endpoint identifica zona ótima (difficulty 0.3-0.7). Recomendações |
| 15 | Temporal Landmarks | `techniques.py` | Dai 2014 | Fresh Start em segundas, 1° do mês, streak milestones. Boost multiplier |
| 16 | Production Effect | `flashcards.js` | MacLeod 2010 | Hint "🔊 Leia em voz alta" a cada 4 cards. +15% encoding |
| 17 | Spacing Gap Optimization | `techniques.py` | Cepeda 2008 | Calcula gap ótimo (10-20% do tempo até prova). Sugere horário ideal |
| 18 | Expressive Writing | `techniques.py` | Ramirez & Beilock 2011 | 48h antes da prova: prompt para escrever medos. Reduz ansiedade 15% |
| 19 | Cognitive Load Segmenting | `flashcards.js` | Mayer 2009 | Respostas >120 chars reveladas em partes de ~80 chars |
| 20 | Production Effect (Audio) | `flashcards.js` | Já existia modo TTS/Commuting | Reforçado com hint visual |

### 9.2 Fluxo de Revisão com Técnicas (ordem de intervenções)

```
showCurrentFlashcard()
  ├── [Modo Prova?] → Pula tudo, direto ao card
  ├── [Chunking] → A cada 6 cards, pausa reflexiva + Forward Testing + Mini-resumo
  ├── [Variação de Contexto] → Cards _expanding_retrieval mostrados invertidos
  ├── [Cognitive Load Segmenting] → Respostas longas em partes
  └── [Production Effect] → Hint "leia em voz alta" a cada 4 cards

revealAnswer()
  └── Botões de review (0-5)

reviewFlashcard(quality)
  ├── [Hypercorrection] → Se confiança>=4 E quality<=1, tela impactante
  ├── [Keyword Mnemonic] → Se quality<=1 E repetitions>0, sugestão de mnemônico
  ├── [Elaborative Interrogation] → Se quality>=3 a cada 3 acertos, prompt "Por quê?"
  ├── [Micro-Break] → Se quality<=2, pausa 5s com countdown
  └── _advanceAfterReview()

Final da sessão:
  └── [Distributed Summary] → Prompt "Resuma em 1 frase"
```

### 9.3 `study_ordering.py` — 7 Etapas de Ordenação

```python
# Etapa 1: Classificar em faixas cognitivas (pretesting, reforço, relearning, difíceis, regulares)
# Etapa 2: Randomizar dentro de cada faixa
# Etapa 3: Importância/ROI (se fornecida)
# Etapa 4: Desirable Difficulty (2 difíceis + 1 regular)
# Etapa 5: Interleaving (round-robin por matéria)
# Etapa 6: Expanding Retrieval (re-inserir reforço 5-8 posições depois)
# Etapa 7: Serial Position Effect (reforço no início, relearning no fim)
```

### 9.4 Parser PDF Estratégia Concursos — Melhorias

**Problema original:** Cabeçalhos como "Questão 2 2024 Nível Superior FCC Tribunal Regional..." misturados no enunciado.

**Solução:** Heurística multi-camada que identifica e remove metadata antes do enunciado:

1. **Ano**: `^\d{4}$` (4 dígitos sozinhos)
2. **Bancas**: FCC, VUNESP, FGV, CESPE, FUNDATEC, etc.
3. **"Questões oficiais"**: regex
4. **"Nível Superior/Médio"**: regex
5. **Tribunais/Órgãos**: linhas com Tribunal, Analista, Auditor, etc. que NÃO começam com artigo/preposição
6. **Tópicos**: linhas curtas sem pontuação e sem verbos de enunciado
7. **Numerais soltos**: `^[IVXivx\d]{1,5}$`
8. **Letras soltas**: `^[A-Ea-e]$`

**Extração de metadados** (antes de limpar):
- `detected_banca` via regex de nomes de bancas
- `detected_ano` via `^\d{4}$`
- `detected_topico` via linhas que começam com "Da/Do/Dos" ou são capitalizadas curtas
- `detected_dificuldade` via número 1-5 no cabeçalho (1-2=Fácil, 3=Médio, 4-5=Difícil)

**Pattern de alternativas** (4 fallbacks):
1. `\n\s*\(?([A-E])\)?\s*[-–.]?\s*(.+?)` — letra com parêntese
2. `(?:^|\n)\s*([A-E])\s*[).\-–]\s*(.+?)` — letra com separador
3. `\n([A-E]) (.+?)` — letra com espaço
4. `\n([A-E])\n(.+?)` — **Estratégia**: letra sozinha na linha

**Resultado:** 94.7% accuracy em Dir Constitucional (143/151 questões limpas)

### 9.5 Texto Base em Questões

**Coluna:** `texto_base TEXT DEFAULT ''` (migration 49)

**Detecção:** Marcadores como:
- "baseie-se no texto abaixo"
- "Leia o texto a seguir"
- "Considere o texto/trecho/fragmento"
- "TEXTO I/II/III"

**Separação:** Busca o último marcador de enunciado (assinale, é correto, considere as, de acordo com o texto, etc.) e separa em texto_base + enunciado. Fallback: última frase curta (<250 chars) após último ponto.

**Resultado:** 32.3% das questões de português com texto base separado (131/406)

### 9.6 Embaralhamento de Alternativas

**Endpoint:** `GET /api/questoes/{id}?embaralhar=true`

**Lógica:** `_embaralhar_alternativas(questao, user_id)`
- Seed determinístico: `hash(md5(f"{user_id}-{q_id}"))` → mesmo user sempre vê mesma ordem
- Fisher-Yates shuffle com Random(seed)
- Não embaralha Certo/Errado (≤2 alternativas)
- Retorna `mapeamento: {nova_letra: letra_original}` + `resposta_correta` atualizada
- `embaralhada: true/false` no response

### 9.7 Fix Push Notifications (VAPID)

**Problema:** `InvalidAccessError: The provided applicationServerKey is not valid`
**Causa:** Keys geradas com `secrets.token_urlsafe(65)` (bytes aleatórios) em vez de chave EC P-256
**Fix:** Regenerar com `py_vapid` + `cryptography` usando `Encoding.X962 + UncompressedPoint` (65 bytes, começa com 0x04)

### 9.8 Flashcards por Matéria (Dashboard)

**Feature:** Clicar na matéria na seção "Pendentes por matéria" do dashboard inicia revisão filtrada.
**Função:** `startFlashByMateria(materia)` → `GET /api/flashcards/today?materia=X` → `showCurrentFlashcard()`
**Backend:** Endpoint já suportava parâmetro `materia` — apenas conectado ao frontend.

### 9.9 Regras Atualizadas no SKILL.md

- **Regra 7 reforçada:** "Commit + Push IMEDIATO" — sem exceções
- **Regra 11 (nova):** "Técnicas Científicas de Estudo" — obrigatório considerar qual técnica se aplica ao implementar qualquer feature de estudo. Lista completa de 29 técnicas.

---

## 10. SESSÃO 29/08/2026 — Feature Trilha de Estudo + Bolinha de Status

### 10.1 Bolinha de Status de Presença no Avatar

**Feature:** O avatar no menu de perfil (`showProfileMenu` em `auth.js`) ganhou uma bolinha
de status colorida no canto (mesmo padrão visual do widget de amigos em `presence.js`).
- `presence.js`: `STATUS_META` (label/emoji/cor por status, espelha `STATUS_VALIDOS` do backend
  em `routers/social/status.py`) + `getCurrentPresenceStatus()` exposto em `window` (usa override
  manual ou inferência da página).
- `auth.js`: wrapper `position:relative` no avatar + `<span>` com a cor do status; fallback seguro
  se `window.getCurrentPresenceStatus` não existir (auth.js é importado em páginas sem presence.js).

### 10.2 Feature Trilha de Estudo (roadmap longitudinal)

Nova feature completa (Fases 1–4). **Diferente** da "trilha diária" (agenda do dia em
`treinador/trilha.py`). A Trilha é um **percurso ordenado de etapas por tópico do edital**, com
pré-requisitos e progresso persistente (bloqueada → atual → concluída).

**Arquivos:**
- Backend: `routers/trilha/` (package: `__init__.py`, `core.py`, `tables.py`), migration `_m58_trilha`
  (tabelas `trilha` + `trilha_etapas`), espelhada em `db/tables.py` para DBs novos.
- Frontend: `js/modules/trilha.js`, aba `#tab-trilha` em `index.html`, wiring em `app.js` +
  `js/pages/index.js` + `sidebar.js`, estilos `.trilha-*` em `css/main.css`.

**Endpoints:**
| Método | Rota | Função |
|--------|------|--------|
| POST | `/api/trilha/gerar` | Gera/regenera a trilha a partir do ciclo ativo |
| GET | `/api/trilha` | Trilha ativa + etapas + progresso |
| POST | `/api/trilha/etapas/{id}/concluir` | Conclui etapa, desbloqueia próxima, +25 XP |
| POST | `/api/trilha/sincronizar-calendario` | Agenda próximas etapas no calendário |

**Regras de negócio (IMPORTANTE):**
- **A Trilha considera APENAS as matérias do ciclo de estudos ativo** (`ciclo_estudos WHERE ativo=1`),
  NUNCA o edital inteiro. Sem ciclo → `gerar` retorna 400 orientando montar o ciclo.
  `_topicos_ordenados` retorna `[]` se `materias` vazio (blindagem contra varrer o edital todo).
- **Ordem das etapas:** topological sort (Kahn) sobre `topic_dependencies` (Knowledge Graph);
  sem dependências → interleaving (round-robin) por matéria preservando ordem do edital.
- **Conclusão = single source of truth:** concluir etapa marca o tópico do edital como `'Concluído'`
  + `mastery_updated_at`. Isso alimenta o XP semanal das Ligas (+25/tópico via `XP_PER_TOPIC`),
  sem contador de XP próprio. Evita XP duplicado ao reconcluir (`_aplicar_conclusao_etapa` retorna 0).
- **Integração Ciclo → Knowledge Graph → Trilha → Calendário** fecha o fluxo de planejamento.

**Sincronização com calendário (Fase 4):**
- `sincronizar-calendario` distribui as próximas N etapas pendentes (round-robin pelos dias úteis)
  no `calendario_personalizado` como `tipo='trilha'`. **Idempotente:** remove só os itens `tipo='trilha'`
  antigos, preserva as demais atividades. Params: `dias_semana` (1-7, def 6), `tempo_min` (def 60),
  `max_etapas` (def 12).
- **Conclusão automática:** marcar atividade `tipo='trilha'` no calendário conclui a etapa
  correspondente (via `marcar_etapa_por_topico(conn, user_id, materia, topico)`, importado
  lazy em `calendario/personalizado.py` para evitar import circular). `AtividadeConcluidaRequest`
  ganhou campo opcional `topico` para casar a etapa; frontend envia `data-topico` no toggle.
- Grid do calendário: atividades `tipo='trilha'` têm ícone 🧭 e classe `.cal-activity--trilha`
  (borda de acento Catppuccin), definida inline em `dashboard.html`.

**Técnicas científicas aplicadas:** Desirable Difficulty (ordem por pré-requisito),
Progress Milestones (barra/marcos de etapa), Interleaving (round-robin entre matérias).

**Testes:** `tests/test_trilha.py` (19 testes). Fixture limpa `trilha_etapas, trilha,
topic_dependencies, ciclo_estudos, edital, calendario_personalizado, calendario_atividades,
calendario_streaks`. Helper `_add_topico(..., no_ciclo=True)` já adiciona a matéria ao ciclo
por padrão (reflete o uso real: trilha só considera o ciclo).

### 10.3 Incidentes de Ambiente e Lições (CRÍTICO para o agente)

Três erros de ambiente causaram retrabalho nesta sessão. Registrados para nunca repetir:

1. **NUNCA usar `git stash` / `git stash pop` com trabalho não commitado.** O `stash pop`
   reverteu silenciosamente várias mudanças não commitadas (source + testes), que tiveram de
   ser reaplicadas. Para lint, rodar o linter direto nos arquivos — sem stash.

2. **NUNCA construir comandos `rm` com variáveis potencialmente vazias.** Um
   `rm -f "$TMPDB"*` com `$TMPDB` vazio (mktemp do BusyBox/WSL não aceita `--suffix`) virou
   `rm -f *` e deletou arquivos Python de topo em `backend/`. Recuperados via `git checkout`
   (eram rastreados). Sempre validar que a variável não é vazia antes; usar caminhos explícitos.

3. **SQLite no WSL (`/mnt/c`) trava com processos uvicorn remanescentes.** Smoke tests que
   sobem uvicorn em background e não são encerrados deixam handles nos arquivos `.db`, causando
   `sqlite3.OperationalError: unable to open database file` em execuções seguintes. Sempre
   `pkill -f uvicorn` após smoke tests. `rate_limit.db` é efêmero/não-rastreado (`.gitignore`) —
   se corromper, basta apagar que o app recria.

4. **`backend/progress.db` é o banco REAL e é rastreado pelo git — dados reais novos DEVEM
   ser commitados para sincronizar entre estações.** O projeto tem múltiplos contribuidores
   que trabalham em estações diferentes e usam o `progress.db` versionado para levar os dados
   (flashcards, questões, edital, sessões, config) de uma máquina para outra.
   - **Dados reais inseridos pelo uso do app** (fora de testes) → **REGRA IMUTÁVEL:** fazer
     IMEDIATAMENTE, no momento da inserção, um commit dedicado
     `chore: atualizar progress.db (<descrição do que foi adicionado>)` e push. Assim o dado
     fica salvo nos objetos do git e um `git checkout`/reset acidental NÃO o apaga. Nunca
     misturar o `.db` no mesmo commit de alterações de código-fonte.
   - **Diffs espúrios gerados por testes/smoke** (a suite e o import do app tocam no banco) →
     descartar com `git checkout -- backend/progress.db` ANTES de commitar código, para não
     poluir o commit de código com alterações incidentais do banco. **PORÉM (obrigatório):**
     antes de qualquer `git checkout`/`git restore`/`reset --hard` que afete o `progress.db`,
     (a) inspecionar as contagens das tabelas de dados reais (simulados, vademecum_leis,
     questoes, flashcards, edital...) versus o HEAD e (b) CONFIRMAR com o usuário que o diff é
     espúrio. Na dúvida, commitar o `.db` primeiro — jamais descartar. (Incidente 29/ago:
     dados reais de leis+simulados foram perdidos por checkout indevido — não repetir.)
   - Regra de ouro do fluxo: primeiro faça o commit/push do CÓDIGO (restaurando o `.db` só se
     confirmado que os testes o alteraram); depois, se houver dados reais a sincronizar, faça
     um commit/push SEPARADO do `progress.db`.
   - Há um `progress.db` solto na RAIZ (não rastreado, `.dockerignore`) que NÃO deve ir ao repo.
   - `make backup` / `POST /api/backups` continuam disponíveis para snapshots com timestamp.

### 10.4 Service Worker

`CACHE_VERSION` avançou v95 → v99 nesta sessão (auth.js, trilha.js, dashboard/main.js são
precacheados). Regra reforçada: incrementar a cada mudança em JS/CSS listado em `PRECACHE_URLS`.


---

## 11. SESSÃO 04/09/2026 — Roadmap "Anki-like" (melhorias graduais)

Análise profunda Anki vs ConcurseiroOS. Veredito: o app já SUPERA o Anki em pedagogia
(FSRS-5 em flashcards E questões, 29+ técnicas científicas, boss battle, TTS/commuting,
importação .apkg, viz Leitner). As lacunas do Anki estão na PROFUNDIDADE do modelo de card
e no RIGOR do agendador. Roadmap priorizado por ROI (implementar gradualmente, sem esquecer
nenhum ponto):

| # | Melhoria | Impacto | Esforço | Depende de | Status |
|---|----------|---------|---------|------------|--------|
| 1 | **Review log (`revlog`) + retenção real** | ⭐⭐⭐ | Médio | — | ✅ SPRINT 1 (6c64c94) |
| 2 | **Leech detection** (lapses ≥ 8 → suspende/sinaliza) | ⭐⭐⭐ | Baixo | — | ✅ SPRINT 1 (6c64c94) |
| 3 | **Cloze deletion nativo** (`{{c1::...}}` → múltiplos cards) | ⭐⭐⭐ | Médio | note types | ✅ SPRINT 2 |
| 4 | **Cards reversos / note type básico** (frente↔verso) | ⭐⭐ | Médio | — | ✅ SPRINT 3 |
| 5 | **Filtered / Custom Study** (cram, "só erros de hoje") | ⭐⭐ | Baixo-Médio | — | ✅ SPRINT 4 |
| 6 | **Otimização dos pesos FSRS por usuário** (treina W[0..18]) | ⭐⭐⭐ | Alto | revlog (#1) | ✅ SPRINT 5 (S0/W[0..3]) |
| 7 | **Image Occlusion** (ocultar regiões de imagem) | ⭐⭐ | Alto | upload mídia | 🔲 |
| 8 | **Estatísticas visuais** (heatmap reviews, forecast carga) | ⭐⭐ | Médio | revlog (#1) | 🔲 |
| 9 | **Undo de review** (desfazer última avaliação) | ⭐ | Baixo | revlog (#1) | 🔲 |

**Por que começar por #1 + #2:** aditivos ao FSRS atual (não quebram nada), baixo/médio esforço,
e o revlog DESTRAVA #6, #8 e alimenta #2. Leech = vitória rápida percebida pelo aluno.

**Estado atual confirmado (código):** tabela `flashcards` é simples (pergunta/resposta/materia +
campos FSRS). NÃO há: tags de card, mídia/anexo, cloze nativo, card reverso agendável, decks
hierárquicos, leech, revlog, otimização de pesos FSRS, retenção medida. `_converter_cloze` existe
só na importação de .apkg (não é card cloze nativo). "Variação de Contexto" mostra invertido como
técnica, mas não é card reverso agendado.

### 11.1 SPRINT 1 — Fundação (revlog + retenção real + leech)

**Schema (migration aditiva):**
- Nova tabela `flashcard_revlog`: (id, flashcard_id, user_id, rating 1-4, quality 0-5, estado FSRS
  antes/depois, stability, difficulty, intervalo_dias, elapsed_days, tempo_ms, revisado_em).
- Novas colunas em `flashcards`: `lapses INTEGER DEFAULT 0`, `is_leech INTEGER DEFAULT 0`,
  `suspenso INTEGER DEFAULT 0`.
- Espelhar em `db/tables.py` (DBs novos) + migration numerada.

**Gravação:** `/api/flashcards/{id}/review-fsrs` insere 1 linha no revlog por review (antes de
atualizar o card, capturando estado anterior).

**Leech:** rating Again (quality ≤ 1 / rating 1) incrementa `lapses`. Ao atingir `LEECH_THRESHOLD`
(8, configurável) marca `is_leech=1`; múltiplo do threshold → `suspenso=1` (sai da fila `/today`).
Técnica: "desirable difficulty tem limite" (Bjork). UI: badge 🩸 no card.

**Retenção real:** endpoint `/api/flashcards/retencao-real` = % de acerto (rating≥3) em reviews de
cards MADUROS (intervalo prévio ≥ 21d) a partir do revlog, + forecast de carga (quantos cards
vencem por dia nos próximos N dias) a partir de `proxima_revisao`.


### 11.2 SPRINT 2 — Cloze deletion nativo (#3)

**Objetivo:** cards de lacuna estilo Anki (`{{c1::resposta}}`), ideal para lei seca.

**Backend:**
- `parse_cloze_nativo(texto)` em `routers/flashcards.py`: gera 1 card por NÚMERO de
  lacuna distinto (c1, c2...). No card do grupo N, as lacunas cN viram `[...]` (ou
  `[dica]` se `{{cN::resp::dica}}`); as demais lacunas ficam REVELADAS. Reusa a
  ideia do `_converter_cloze` (importação .apkg) mas com a semântica multi-card do Anki.
  Helper `_gerar_card_cloze` extraído para evitar closure em loop (B023).
- Migration 77 (`_m77_flashcards_cloze`): coluna `cloze_text` guarda o texto-fonte
  com marcações (para reedição). pergunta/resposta seguem sendo frente/verso derivadas.
- Endpoint `POST /api/flashcards/cloze` {texto, materia?}: cria N cards (1/lacuna),
  valida texto sem lacuna (400), respeita limite do plano (conta N cards), salva cloze_text.

**Frontend (`index.html` + `flashcards.js`):** painel "🧩 Criar Cloze" com textarea,
botões "Inserir lacuna c1/c2" (envolvem a seleção com `{{cN::}}`), preview local
(`_parseClozeLocal`) e `criarCloze()`. Cards cloze entram na fila normal e herdam
todo o fluxo FSRS/revlog/leech da Sprint 1.

**Testes:** `test_flashcard_cloze.py` (10) — parsing (1 lacuna, multi-grupo, repetida,
dica, sem cloze) + endpoint (cria N, salva cloze_text, valida, aparece no /today).
**Constantes:** `LEECH_THRESHOLD = 8`, `LEECH_SUSPEND_MULTIPLE = 2` (suspende no 16º), em `constants.py`.

### 11.3 SPRINT 3 — Cards reversos / note type básico (#4)

**Objetivo:** de uma nota (pergunta/resposta) gerar 2 cards independentes: frente
(P→R) e verso (R→P). Dobra o valor de cada flashcard criado.

**Backend:**
- Migration 78 (`_m78_flashcards_reverso`): colunas `card_tipo`
  ('normal'|'frente'|'verso', default 'normal') e `note_id` (agrupa os cards da
  mesma nota; = id do primeiro card). Índice idx_flashcards_note.
- `FlashcardCreate.reverso: bool = False` (schemas.py).
- `create_flashcard`: se reverso, cria card 'frente' (P→R) + card 'verso' (R→P
  invertido) com o mesmo note_id; senão 1 card 'normal'. Conta 2 no limite do
  plano quando reverso. Retorna {id, ids, criados, reverso}.
- Cards são INDEPENDENTES: cada um tem seu próprio FSRS/revlog; excluir/editar um
  não afeta o irmão (DELETE/PUT por id). Sibling burying (não mostrar irmãos no
  mesmo dia) ficou para uma sprint futura.

**Frontend:** checkbox "🔄 Criar também o card reverso" no formulário (index.html);
`addFlashcard` envia `reverso` e mostra toast "2 cards criados" quando aplicável.

**Testes:** `test_flashcard_reverso.py` (8) — cria 2 cards, inverte P/R, note_id
compartilhado, normal/retrocompat (sem campo reverso), ambos no /today, revisão
independente, excluir um preserva o irmão.

### 11.4 SPRINT 4 — Filtered / Custom Study (#5)

**Objetivo:** sessões de estudo sob demanda por critério, fora do agendamento SRS
(úteis na reta final). Não altera o agendamento; respostas seguem indo ao revlog.

**Backend:** `GET /api/flashcards/custom-study?modo=&materia=&limite=&dias=`. Modos:
- `errados_hoje`: cards com rating Again hoje (via revlog) — reforço imediato.
- `adiantar`: cards que vencem nos próximos `dias` (default 3) — antecipar carga.
- `materia`: cram (todos os cards de uma matéria, aleatório).
- `leech`: cards is_leech=1 (INCLUI suspensos, para reformular), ordenado por lapses.
- `dificeis`: maior difficulty FSRS.
Todos (exceto leech) excluem suspensos; retornam tempo_segundos + is_leech.
Validações: modo inválido → 400; materia sem materia → 400.

**Frontend:** painel "🧪 Estudo personalizado" (index.html) com botões por modo;
`customStudy(modo, materia)` carrega a fila em `flashSessao` e usa o fluxo de
sessão existente (`showSessaoFlashcard`); `customStudyMateria()` pede a disciplina.

**Testes:** `test_flashcard_custom_study.py` (10) — cada modo, limite, exclusão de
suspensos, leech inclui suspenso, tempo_segundos/is_leech, vazio, validações.

### 11.5 SPRINT 5 — Otimização dos pesos FSRS por usuário (#6, parcial)

**Escopo (baixo risco/alto valor):** otimizar os pesos de estabilidade inicial
S0 = W[0..3] (por rating Again/Hard/Good/Easy) a partir do revlog (Sprint 1).
NÃO reescreve o FSRS inteiro nem treina os 19 pesos (otimização completa fica
para uma sprint futura); foca no subconjunto mais impactante e estimável.

**fsrs.py:**
- `_initial_stability(rating, w_inicial=None)`: usa S0 custom (dict {1..4} ou lista
  de 4) quando fornecido; senão o default global W[rating-1]. Retrocompat total.
- `review_card(..., w_inicial=None)`: propaga w_inicial às chamadas de S0.
- `otimizar_pesos_iniciais(primeiras_revisoes)`: por rating, S0 = MEDIANA da
  stability observada; exige ≥20 amostras/rating; clampa à faixa sã
  (_S0_MIN/_S0_MAX) e impõe monotonicidade Again≤Hard≤Good≤Easy. Ratings sem
  dados usam default.

**Backend:**
- Migration 79: coluna `fsrs_weights` (JSON) em metas_config.
- `POST /api/flashcards/fsrs/otimizar`: estima S0 das PRIMEIRAS revisões ESPAÇADAS
  (elapsed_days>=1 — evita circularidade com o S0 default) de cada card, salva em
  metas_config. Falha graciosa se histórico insuficiente.
- `GET /api/flashcards/fsrs/pesos`: retorna pesos atuais (custom ou default) + amostras.
- `review-fsrs` carrega `_get_fsrs_weights(user)` e passa a review_card.

**Frontend:** botão "🧠 Otimizar meu FSRS" na seção de retenção (loadRetencaoReal),
`otimizarFSRS()` + `loadFsrsPesos()` exibindo o S0 por rating.

**Testes:** `test_fsrs_otimizacao.py` (11) — função pura (amostras, monotonicidade,
clamp, sem dados), review_card com/sem w_inicial (dict e lista), endpoints
(default, sem histórico, com histórico espaçado).

**Nota:** a estimativa usa reviews com espaçamento real (não a 1ª revisão, que já
usa o S0 default → seria circular). Otimização completa dos 19 pesos (gradient
descent sobre o revlog) permanece no roadmap como evolução futura.
