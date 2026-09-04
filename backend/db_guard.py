#!/usr/bin/env python3
"""db_guard — detecta se o diff do progress.db é dado REAL ou espúrio de teste.

Problema que resolve
--------------------
`progress.db` é versionado no git para sincronizar dados reais entre estações.
Rodar a suíte de testes / smoke toca o arquivo (FTS, schema_version, PRAGMAs,
páginas internas do SQLite) sem inserir dado real, gerando um diff binário
"espúrio". Decidir manualmente se um diff é espúrio ou dado real é frágil e
propenso a erro (regra imutável nº 12 do projeto: nunca descartar dado real).

Esta ferramenta compara o CONTEÚDO das tabelas de DADOS REAIS entre o
`progress.db` do working tree e uma referência git (HEAD por padrão),
IGNORANDO tabelas efêmeras/derivadas. Assim a decisão vira determinística:

  - exit 0  → diff ESPÚRIO (nenhuma tabela de dado real mudou). Seguro restaurar
              o .db (`git checkout -- backend/progress.db`) e commitar só código.
  - exit 1  → há DADO REAL novo/alterado. Deve entrar em commit dedicado
              `chore: atualizar progress.db (...)` e push.
  - exit 2  → erro de uso/execução (não foi possível decidir com segurança).

Uso
---
    python3 db_guard.py                     # compara backend/progress.db vs HEAD
    python3 db_guard.py --db path/to.db     # outro arquivo
    python3 db_guard.py --base origin/main  # outra referência git
    python3 db_guard.py --json              # saída legível por máquina
    python3 db_guard.py --verbose           # mostra tabelas espúrias também

Em caso de DÚVIDA (ex.: não há versão no HEAD, arquivo corrompido), a ferramenta
falha para o lado seguro (exit 1 / trata como dado real) — jamais sugere
descartar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Classificação de tabelas
# ---------------------------------------------------------------------------
# Tabelas EFÊMERAS/DERIVADAS: mudam ao rodar app/testes sem representar dado
# real do usuário. São ignoradas na comparação de conteúdo.
#
# - search_index*  / vademecum_fts* : índices FTS5 derivados (reconstruídos no
#   init_db). Conteúdo é função das tabelas-fonte, não é dado original.
# - schema_version : controle de migrations (muda ao aplicar migration).
# - auth_attempts / auth_codes : credenciais efêmeras (rate limit / OTP).
# - sessao_adaptativa* : estado transitório de sessão adaptativa.
# - generation_responses : cache de respostas de geração (derivado/efêmero).
# - user_status : presença online/offline/estudando — muda ao subir/derrubar o
#   app ou rodar testes; não é dado de estudo real.
# - notification_log : log de envio de notificações (efêmero).
_EFEMERAS_EXATAS = {
    "schema_version",
    "auth_attempts",
    "auth_codes",
    "sessao_adaptativa",
    "sessao_adaptativa_respostas",
    "generation_responses",
    "user_status",
    "notification_log",
}
# Prefixos de tabelas derivadas (FTS5 cria *_data/_idx/_docsize/_content/_config).
_EFEMERAS_PREFIXOS = (
    "search_index",
    "vademecum_fts",
)


def _e_efemera(nome: str) -> bool:
    if nome in _EFEMERAS_EXATAS:
        return True
    return any(nome.startswith(p) for p in _EFEMERAS_PREFIXOS)


# Colunas efêmeras (a ignorar no hash de conteúdo): mudam por atividade técnica
# (login, presença, sincronização) sem representar dado de estudo real.
# Ex.: users.last_login muda a cada login (inclusive nos testes que autenticam).
_COLUNAS_EFEMERAS = {
    "last_login",
    "last_seen",
    "updated_at",
    "atualizado_em",
}


# ---------------------------------------------------------------------------
# Leitura do banco
# ---------------------------------------------------------------------------
def _tabelas_reais(conn: sqlite3.Connection) -> list[str]:
    """Nomes de tabelas de dados reais (exclui sqlite_* e efêmeras/derivadas)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows if not _e_efemera(r[0])]


def _hash_tabela(conn: sqlite3.Connection, tabela: str) -> tuple[int, str]:
    """Retorna (num_linhas, hash_conteudo) de uma tabela.

    O hash é estável a ordenação: ordena as linhas por todas as colunas para não
    depender da ordem física (que muda com VACUUM). Colunas são lidas via
    PRAGMA para montar um SELECT determinístico.
    """
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{tabela}")').fetchall()]
    if not cols:
        return (0, "")
    # Ignora colunas efêmeras (last_login etc.) no conteúdo hasheado — elas mudam
    # por login/presença/sync, não por estudo real. Mantém pelo menos 1 coluna.
    cols_significativas = [c for c in cols if c not in _COLUNAS_EFEMERAS] or cols
    col_list = ", ".join(f'"{c}"' for c in cols_significativas)
    # Bots/oponentes simulados usam user_id negativo (ex.: ranking de ligas). Seu
    # estado (weekly_xp etc.) é gerado pela simulação, não é dado real do
    # estudante — filtramos para não gerar falso positivo de "dado real".
    where = ""
    if "user_id" in cols:
        where = ' WHERE "user_id" >= 0'
    try:
        rows = conn.execute(f'SELECT {col_list} FROM "{tabela}"{where}').fetchall()
    except sqlite3.DatabaseError:
        # Tabela ilegível → trata como "mudou" no lado seguro.
        return (-1, "ILEGIVEL")
    # Normaliza cada linha em texto e ordena para hash estável.
    linhas_norm = sorted(repr(tuple(r)) for r in rows)
    h = hashlib.sha256()
    for ln in linhas_norm:
        h.update(ln.encode("utf-8", "replace"))
        h.update(b"\x00")
    return (len(rows), h.hexdigest())


def _conectar_ro(db_path: str) -> sqlite3.Connection:
    """Abre o SQLite preferindo read-only imutável; faz fallback tolerante.

    O modo `?mode=ro` pode lançar 'disk I/O error' quando o SQLite espera um
    -wal/-journal ausente (ex.: arquivo extraído do git via `git show`, sem os
    sidecars). Tentamos, em ordem:
      1) ro + immutable=1  (não exige sidecars, ideal p/ snapshot do git)
      2) ro
      3) conexão normal (o arquivo é uma cópia descartável ou já consistente)
    """
    p = Path(db_path).as_posix()
    tentativas = (
        f"file:{p}?mode=ro&immutable=1",
        f"file:{p}?mode=ro",
    )
    for uri in tentativas:
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=10)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            return conn
        except sqlite3.DatabaseError:
            continue
    # Último recurso: conexão normal (arquivo já é cópia local/descartável).
    return sqlite3.connect(db_path, timeout=10)


def _snapshot(db_path: str) -> dict[str, tuple[int, str]]:
    """Mapa {tabela_real: (num_linhas, hash)} do banco (read-only quando possível)."""
    conn = _conectar_ro(db_path)
    try:
        conn.row_factory = None
        return {t: _hash_tabela(conn, t) for t in _tabelas_reais(conn)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Referência git
# ---------------------------------------------------------------------------
def _git_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def _extrair_do_git(base_ref: str, rel_path: str, destino: str) -> bool:
    """Extrai `rel_path` na ref `base_ref` para `destino`. False se inexistente."""
    try:
        out = subprocess.run(
            ["git", "show", f"{base_ref}:{rel_path}"],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return False
    with open(destino, "wb") as f:
        f.write(out.stdout)
    return True


# ---------------------------------------------------------------------------
# Comparação
# ---------------------------------------------------------------------------
def diff_snapshots(snap_atual: dict, snap_base: dict) -> dict:
    """Compara dois snapshots {tabela: (linhas, hash)} e classifica o diff.

    Função pura (sem git/IO) — o coração da decisão, fácil de testar.
    """
    detalhe: dict[str, dict] = {}
    tabelas = set(snap_atual) | set(snap_base)
    for t in sorted(tabelas):
        na, ha = snap_atual.get(t, (0, "__ausente__"))
        nb, hb = snap_base.get(t, (0, "__ausente__"))
        if ha != hb:
            detalhe[t] = {"linhas_base": nb, "linhas_atual": na, "delta": na - nb}
    if detalhe:
        return {
            "decisao": "dado_real",
            "motivo": "Tabelas de dados reais foram alteradas.",
            "tabelas_alteradas": sorted(detalhe.keys()),
            "detalhe": detalhe,
        }
    return {
        "decisao": "espurio",
        "motivo": "Nenhuma tabela de dado real mudou (diff é espúrio de teste/FTS/PRAGMA).",
        "tabelas_alteradas": [],
        "detalhe": {},
    }


def comparar(db_atual: str, base_ref: str) -> dict:
    """Compara db_atual com a versão em base_ref. Retorna relatório estruturado."""
    root = _git_root()
    rel = os.path.relpath(os.path.abspath(db_atual), root).replace(os.sep, "/")

    snap_atual = _snapshot(db_atual)

    with tempfile.NamedTemporaryFile(suffix="_base.db", delete=False) as tmp:
        base_tmp = tmp.name
    try:
        existe_base = _extrair_do_git(base_ref, rel, base_tmp)
        if not existe_base:
            # Sem base no git → não dá para provar que é espúrio. Lado seguro.
            return {
                "decisao": "dado_real",
                "motivo": f"{rel} não existe em {base_ref} (novo arquivo — tratado como dado real)",
                "tabelas_alteradas": sorted(snap_atual.keys()),
                "detalhe": {},
            }
        snap_base = _snapshot(base_tmp)
    finally:
        try:
            os.unlink(base_tmp)
        except OSError:
            pass

    return diff_snapshots(snap_atual, snap_base)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="Caminho do .db (default: backend/progress.db do repo)")
    ap.add_argument("--base", default="HEAD", help="Referência git para comparar (default: HEAD)")
    ap.add_argument("--json", action="store_true", help="Saída JSON")
    ap.add_argument("--verbose", "-v", action="store_true", help="Mostra também tabelas efêmeras ignoradas")
    args = ap.parse_args(argv)

    try:
        root = _git_root()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("db_guard: não está dentro de um repositório git.", file=sys.stderr)
        return 2

    db_path = args.db or str(root / "backend" / "progress.db")
    if not Path(db_path).exists():
        print(f"db_guard: arquivo não encontrado: {db_path}", file=sys.stderr)
        return 2

    try:
        rel = comparar(db_path, args.base)
    except Exception as e:  # falha → lado seguro
        print(f"db_guard: erro ao comparar ({e}). Tratando como DADO REAL por segurança.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(rel, ensure_ascii=False, indent=2))
    else:
        if rel["decisao"] == "espurio":
            print("✅ DIFF ESPÚRIO — seguro restaurar o .db e commitar só código.")
            print(f"   {rel['motivo']}")
            print("   Sugestão: git checkout -- backend/progress.db")
        else:
            print("🟡 DADO REAL detectado — faça commit dedicado do progress.db.")
            print(f"   {rel['motivo']}")
            if rel["tabelas_alteradas"]:
                print("   Tabelas alteradas:")
                for t in rel["tabelas_alteradas"]:
                    d = rel["detalhe"].get(t)
                    if d:
                        sinal = f"+{d['delta']}" if d["delta"] >= 0 else str(d["delta"])
                        print(f"     - {t}: {d['linhas_base']} → {d['linhas_atual']} linhas ({sinal})")
                    else:
                        print(f"     - {t}")
            print(
                "   Sugestão: git add backend/progress.db && "
                "git commit -m 'chore: atualizar progress.db (<descrição>)' && git push"
            )

    return 0 if rel["decisao"] == "espurio" else 1


if __name__ == "__main__":
    raise SystemExit(main())
