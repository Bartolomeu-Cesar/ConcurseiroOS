# ConcurseiroOS — Regras do Projeto (Skill)

## Regras Invioláveis

1. **Pull ao iniciar sessão**: Sempre fazer `git pull` no repositório antes de iniciar qualquer trabalho. Garantir que o código local está sincronizado com o remoto.
2. **SW Version**: Sempre incrementar `CACHE_VERSION` no `frontend/sw.js` ao alterar qualquer JS listado em `PRECACHE_URLS`.
2. **Filtro Ciclo Ativo**: Queries de recomendação/treinador/study-intelligence devem filtrar por `ciclo_estudos WHERE ativo = 1` — nunca mostrar matérias de concursos inativos.
3. **Testes antes de push**: Sempre rodar `python3 -m pytest tests/ -q` e confirmar que TODOS os testes passam antes de commit. Nunca fazer push com testes falhando.
4. **window.funcao**: Em ES modules, toda função usada em `onclick` inline deve ser exposta com `window.funcao = funcao`.
5. **Streak tolerante**: `calculate_streak()` em `utils.py` deve começar de ontem se hoje não tem atividade (dia em andamento).
6. **Auth Depends**: Todo endpoint novo precisa de `user_id: int = Depends(get_user_id)` e `conn = Depends(get_db_session)`.
7. **Commit + Push IMEDIATO**: Toda alteração validada (testes passando) DEVE ser commitada e pushada imediatamente. Nunca acumular alterações sem commit. Usar conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`). O fluxo é: implementar → testar → commit → push. Sem exceções.
8. **Criar testes para toda alteração**: Toda feature nova ou bug fix DEVE ter teste correspondente. Se não existe teste para o código alterado, criar um. Objetivo: nunca diminuir a cobertura.
9. **Não quebrar funcionalidades existentes**: Antes de refatorar ou alterar um módulo, verificar TODOS os imports e chamadores. Manter backward compatibility (re-exportar funções movidas, preservar assinaturas). Se um endpoint muda formato de retorno, garantir que o frontend consome corretamente.
10. **Testar regressão**: Após qualquer fix, rodar os testes do módulo afetado E os testes que dependem dele. Se um teste falha que antes passava = regressão — corrigir antes de continuar.
11. **Técnicas Científicas de Estudo**: Sempre que analisar, alterar ou implantar recursos novos, aplicar as técnicas científicas de estudo baseadas em evidência para melhorar a experiência do candidato. Técnicas implementadas: Spaced Practice (FSRS), Retrieval Practice, Interleaving, Pre-testing, Desirable Difficulty, Successive Relearning, Expanding Retrieval, Elaborative Interrogation, Serial Position Effect, Lag Effect (Exam-Aware), Chunking, Keyword Mnemonic, Free Recall (Brain Dump), Dual Coding, Contextual Variation, Self-Explanation, Concrete Examples, Errorful Learning, Distributed Summary, Encoding Specificity (Modo Prova), Hypercorrection Effect, Forward Testing Effect, Micro-Breaks Cognitivos, Testing Boundaries, Temporal Landmarks (Fresh Start), Production Effect, Spacing Gap Optimization, Expressive Writing, Cognitive Load Segmenting. Toda feature de estudo deve considerar qual técnica se aplica e integrá-la ao fluxo.
12. **Commit IMEDIATO de dados reais no `progress.db` (IMUTÁVEL)**: Sempre que dados reais forem inseridos na base (leis/vademecum, simulados, questões, flashcards, edital, sessões, config etc. — qualquer coisa fora de testes), fazer IMEDIATAMENTE um commit dedicado `chore: atualizar progress.db (<descrição>)` e push, para que o dado fique salvo nos objetos do git e um `git checkout`/reset acidental NÃO o apague. Corolário obrigatório: NUNCA executar `git checkout -- backend/progress.db` (ou `git restore`/`reset --hard` que o afete) sem ANTES (a) inspecionar as contagens das tabelas de dados reais versus o HEAD e (b) CONFIRMAR com o usuário que o diff é espúrio de teste. Na dúvida, commitar o `.db` primeiro — jamais descartar. Esta regra é imutável.
13. **Idioma das respostas: Português do Brasil (SEMPRE)**: Toda comunicação com o usuário — respostas no chat, explicações, resumos, mensagens de commit, comentários voltados ao usuário e qualquer texto exibido a ele — DEVE ser em Português do Brasil (pt-BR). O usuário não fala outro idioma. Termos técnicos consagrados (nomes de funções, comandos, bibliotecas, siglas) podem permanecer no original, mas a explicação ao redor é sempre em pt-BR. Nunca responder em inglês ou outro idioma.

## Padrões de Código

- Backend: SQL inline nos routers, sem ORM. Paginação via `sql_paginate()`.
- Frontend: Vanilla JS puro, sem frameworks. Toast via `showToast('msg', 'tipo')`.
- Packages: Se router > 300 linhas, dividir em package com `__init__.py` que exporta `router`.
- Ordem de rotas em packages: rotas específicas ANTES de rotas com `/{id}` (evita conflito de path).
- `edital/__init__.py`: re-exporta `_update_single_mastery` para manter imports existentes.

## Gotchas

- `ai_tutor.py`: NÃO modularizar — testes usam patch direto em `routers.ai_tutor.call_llm_sync`.
- `_get_ai_config()`: user_id=1 hardcoded. Multi-user precisará refatorar.
- SW: Após deploy, orientar unregister: `navigator.serviceWorker.getRegistrations().then(r => r.forEach(sw => sw.unregister())).then(() => location.reload())`
- `progress.db` no git: é o banco REAL e versionado para sincronizar dados entre estações (projeto multi-contribuidor). Dados reais novos (inseridos pelo uso do app, fora de testes) DEVEM ser commitados/pushados em commit dedicado `chore: atualizar progress.db (...)`, SEPARADO do commit de código. Diffs gerados por testes/smoke são espúrios → descartar com `git checkout -- backend/progress.db` antes de commitar código. Fluxo: commit/push do código primeiro (restaurando o .db se testes o tocaram), depois commit/push separado do progress.db se houver dados reais. `progress.db` na RAIZ não é rastreado e não vai ao repo. Cuidado com conflitos no pull.
- **Ferramenta `db_guard` (decisão automática espúrio vs. dado real)**: em vez de comparar contagens manualmente, use `make db-check` (ou `python3 backend/db_guard.py`). Ela compara o CONTEÚDO (hash por tabela) do `progress.db` do working tree com o HEAD, ignorando tabelas efêmeras/derivadas (`search_index*`, `vademecum_fts*`, `schema_version`, `auth_attempts`, `auth_codes`, `sessao_adaptativa*`, `generation_responses`, `user_status`, `notification_log`). Exit 0 = diff ESPÚRIO (seguro restaurar o .db); exit 1 = DADO REAL (fazer commit dedicado). Em caso de erro/dúvida, falha para o lado seguro (dado real). Atalho: `make db-sync` roda o check e, se for dado real, commita o `progress.db` em commit dedicado e faz push. A ferramenta pega inclusive o caso traiçoeiro de mesma contagem com conteúdo diferente (o hash detecta), que a comparação por COUNT(*) não pega. Também ignora linhas de BOTS (user_id < 0, ex.: oponentes simulados de liga em `league_members`) — seu XP é gerado pela simulação, não é dado real do estudante. E ignora COLUNAS efêmeras no hash (`last_login`, `last_seen`, `updated_at`, `atualizado_em`) — mudam por login/presença/sync, não por estudo.

## Performance & Banco de Dados

- Queries com JOIN devem ter índice nos campos de filtro. Verificar `db/indexes.py` antes de criar query nova.
- Nunca `SELECT *` em tabelas grandes (questoes, questoes_respostas) sem LIMIT ou filtro por user_id+data.
- Paginação: usar `sql_paginate()` para novos endpoints (LIMIT/OFFSET no SQL, não em Python).
- SQLite: WAL mode + busy_timeout=5000ms. Não abrir transações longas (lock contention com 2 workers).
- Flashcards/questões: prefixar queries com `AND user_id = ?` SEMPRE (multi-tenant).

## Segurança

- Nunca expor dados de um user para outro. Todo endpoint filtra por `user_id`.
- API keys: mascarar no frontend (`****...últimos4`). Backend preserva key se input vier vazio.
- Rate limiting: já existe via `rate_limit.db`. Endpoints AI têm limite diário de tokens.
- Inputs: Pydantic valida no backend. Frontend deve sanitizar HTML em campos de texto livre (XSS).
- JWT: access token curto (15min), refresh longo (30d). Não armazenar em localStorage (usar httpOnly quando possível).

## UX & Frontend

- Sempre dar feedback visual: loading state, toast de sucesso/erro, disabled em botões durante fetch.
- Mobile-first: testar em viewport 375px. Usar `flex-wrap:wrap` em containers de botões.
- Offline: SW garante app funciona sem rede. Mutations ficam em queue (Background Sync).
- Tema: suportar escuro (padrão Catppuccin Mocha) e claro. Usar variáveis CSS (`var(--text)`, `var(--bg)`, etc.).
- Acessibilidade: botões com `title`, inputs com `placeholder`, contraste mínimo 4.5:1.
- **Truncamento de texto**: Nunca usar `white-space:nowrap` + `text-overflow:ellipsis` em elementos que têm expansão via JS (onclick). O truncamento deve ser controlado pelo JS (slice + data-full), não pelo CSS. CSS ellipsis só para labels fixos (ex: nome de matéria).
- **Grids com muitas colunas**: Sempre adicionar `min-width:0` + `overflow:hidden` em items de CSS Grid/Flex para impedir que conteúdo longo quebre o layout. O container pai também precisa de `overflow:hidden`.
- **Componentes reutilizáveis**: Menus, modais e dropdowns devem ter implementação única (ex: `showProfileMenu()` em `auth.js`). Nunca duplicar lógica de UI entre páginas — importar do módulo compartilhado.
- **Modais em vez de diálogos nativos (OBRIGATÓRIO)**: NUNCA usar `confirm()`, `alert()` ou `prompt()` nativos do browser. Eles são visualmente pobres, não seguem o tema Catppuccin e bloqueiam a thread. Usar sempre os helpers de `modules/utils.js`:
  - `await confirmModal(titulo, mensagem, {type, confirmText, cancelText})` → substitui `confirm()`. Retorna `Promise<boolean>`.
  - `await alertModal(mensagem, {title, type, okText})` → substitui `alert()` de avisos/informações importantes. Retorna `Promise`.
  - `await promptModal(mensagem, {title, defaultValue, placeholder, multiline})` → substitui `prompt()`. Retorna `Promise<string|null>` (null = cancelado).
  - Para feedback rápido de sucesso/erro (não-bloqueante), preferir `toast('msg', 'tipo')` em vez de `alertModal`.
  - Todos expostos em `window` via `app.js` para uso em `onclick` inline. Em páginas fora do app principal, importar de `modules/utils.js` ou `modules/toast.js`.
  - Páginas com `<script>` clássico (não-módulo), como `admin.html`: adicionar um `<script type="module">` que importa os helpers e faz `Object.assign(window, { confirmModal, alertModal, promptModal, toast })` ANTES do script inline. Funções que usam `await confirmModal/promptModal` devem ser `async`.

## Decisões Técnicas (por que assim)

- **Sem ORM**: SQLite + queries diretas = máximo controle, zero overhead, fácil debugar.
- **Sem framework frontend**: Bundle zero, load instantâneo, PWA leve. Complexidade gerenciada por ES modules.
- **FSRS sobre SM-2**: FSRS-5 é 30% mais preciso que SM-2 em scheduling (paper com 700M+ reviews).
- **SQLite sobre PostgreSQL**: Single-user/small-team, deploy trivial (1 arquivo), backup = copiar .db.
- **Monolito**: 42 features num único deploy. Separar em microserviços só quando scaling exigir.
- **Sem WebSocket (ainda)**: Polling funciona para study room. WebSocket planejado quando real-time for crítico.

## Workflow de Desenvolvimento

```bash
# 1. Antes de codar: ler código existente do módulo afetado
# 2. Implementar alteração
# 3. Rodar testes: python3 -m pytest tests/ -q
# 4. Se teste novo necessário: criar em tests/test_{modulo}.py
# 5. Verificar: 0 falhas
# 6. Commit: git add <arquivos> && git commit -m "tipo: descrição"
# 7. Push: git push
# 8. Se alterou JS cacheado: incrementar SW version
```
