# ConcurseiroOS — Regras do Projeto (Skill)

## Regras Invioláveis

1. **SW Version**: Sempre incrementar `CACHE_VERSION` no `frontend/sw.js` ao alterar qualquer JS listado em `PRECACHE_URLS`.
2. **Filtro Ciclo Ativo**: Queries de recomendação/treinador/study-intelligence devem filtrar por `ciclo_estudos WHERE ativo = 1` — nunca mostrar matérias de concursos inativos.
3. **Testes antes de push**: Sempre rodar `python3 -m pytest tests/ -q` e confirmar que TODOS os testes passam antes de commit. Nunca fazer push com testes falhando.
4. **window.funcao**: Em ES modules, toda função usada em `onclick` inline deve ser exposta com `window.funcao = funcao`.
5. **Streak tolerante**: `calculate_streak()` em `utils.py` deve começar de ontem se hoje não tem atividade (dia em andamento).
6. **Auth Depends**: Todo endpoint novo precisa de `user_id: int = Depends(get_user_id)` e `conn = Depends(get_db_session)`.
7. **Commits**: Usar conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`). Commit + push após cada alteração validada.
8. **Criar testes para toda alteração**: Toda feature nova ou bug fix DEVE ter teste correspondente. Se não existe teste para o código alterado, criar um. Objetivo: nunca diminuir a cobertura.
9. **Não quebrar funcionalidades existentes**: Antes de refatorar ou alterar um módulo, verificar TODOS os imports e chamadores. Manter backward compatibility (re-exportar funções movidas, preservar assinaturas). Se um endpoint muda formato de retorno, garantir que o frontend consome corretamente.
10. **Testar regressão**: Após qualquer fix, rodar os testes do módulo afetado E os testes que dependem dele. Se um teste falha que antes passava = regressão — corrigir antes de continuar.

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
- `progress.db` no git: é o banco real. Cuidado com conflitos no pull (usar `git checkout -- backend/progress.db` se necessário).
