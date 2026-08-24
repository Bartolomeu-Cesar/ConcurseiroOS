import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pypdf import PdfReader


def today_str():
    return date.today().isoformat()


def get_pdf_pages(filepath: str) -> int:
    try:
        return len(PdfReader(filepath).pages)
    except Exception:
        return 1


def build_tree(root: str) -> list:
    result = []
    root_path = Path(root).resolve()
    for entry in sorted(Path(root).iterdir()):
        if entry.is_dir():
            children = build_tree(str(entry))
            if children:
                result.append({"type": "folder", "name": entry.name, "children": children})
        elif entry.suffix.lower() == ".pdf" and ":" not in entry.name:
            rel = str(entry.resolve().relative_to(root_path))
            result.append({"type": "pdf", "name": entry.name, "path": rel})
    return result


def calculate_streak(conn, user_id: int = 1) -> dict:
    """Calcula streak atual e melhor streak histórico."""
    rows = conn.execute(
        "SELECT data FROM streaks WHERE (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0) AND user_id = ? ORDER BY data DESC",
        (user_id,)
    ).fetchall()

    streak = 0
    check_date = date.today()
    for row in rows:
        if row[0] == check_date.isoformat():
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    # Melhor streak histórico
    all_dates = [row[0] for row in rows]
    best_streak = 0
    current_best = 0
    if all_dates:
        sorted_dates = sorted(set(all_dates))
        current_best = 1
        for i in range(1, len(sorted_dates)):
            d1 = date.fromisoformat(sorted_dates[i - 1])
            d2 = date.fromisoformat(sorted_dates[i])
            if (d2 - d1).days == 1:
                current_best += 1
            else:
                best_streak = max(best_streak, current_best)
                current_best = 1
        best_streak = max(best_streak, current_best)

    return {"streak_atual": streak, "melhor_streak": best_streak}


def paginate(items: list, page: int | None, limit: int = 50) -> Any:
    """Aplica paginação a uma lista. Se page=None, retorna lista completa (retrocompatível).

    TODO: Novos endpoints devem usar sql_paginate() em vez desta função.
    paginate() carrega todos os resultados em memória antes de fatiar, o que não escala.
    """
    if page is None:
        return items
    total = len(items)
    pages = math.ceil(total / limit) if limit > 0 else 1
    start = (page - 1) * limit
    return {
        "items": items[start:start + limit],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def sql_paginate(conn, query: str, params: tuple = (), page: int | None = None, limit: int = 50) -> Any:
    """Paginação SQL real com LIMIT/OFFSET. Retorna formato idêntico ao paginate().

    Args:
        conn: sqlite3 connection (com row_factory=Row)
        query: SQL base SEM LIMIT/OFFSET (ex: "SELECT * FROM tabela WHERE x = ?")
        params: tuple de parâmetros para a query
        page: número da página (1-indexed). Se None, retorna todos os resultados.
        limit: itens por página (default 50)

    Returns:
        Se page=None: lista completa de dicts
        Se page>=1: {"items": [...], "total": N, "page": P, "limit": L, "pages": T}
    """
    if page is None:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # COUNT total via subquery
    count_query = f"SELECT COUNT(*) FROM ({query})"
    total = conn.execute(count_query, params).fetchone()[0]

    pages = math.ceil(total / limit) if limit > 0 else 1
    offset = (page - 1) * limit

    paginated_query = f"{query} LIMIT ? OFFSET ?"
    rows = conn.execute(paginated_query, (*params, limit, offset)).fetchall()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def update_streak(conn, field: str, value: int = 1, user_id: int = 1) -> None:
    """Incrementa um campo do streak de hoje. Fields: horas_estudadas, questoes_resolvidas, flashcards_revisados."""
    if field == "horas_estudadas":
        conn.execute("""
            INSERT INTO streaks (data, horas_estudadas, user_id) VALUES (?, ?, ?)
            ON CONFLICT(user_id, data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
        """, (today_str(), value, user_id, value))
    elif field == "questoes_resolvidas":
        conn.execute("""
            INSERT INTO streaks (data, questoes_resolvidas, user_id) VALUES (?, 1, ?)
            ON CONFLICT(user_id, data) DO UPDATE SET questoes_resolvidas = questoes_resolvidas + 1
        """, (today_str(), user_id))
    elif field == "flashcards_revisados":
        conn.execute("""
            INSERT INTO streaks (data, flashcards_revisados, user_id) VALUES (?, 1, ?)
            ON CONFLICT(user_id, data) DO UPDATE SET flashcards_revisados = flashcards_revisados + 1
        """, (today_str(), user_id))


def build_edital_filter(edital_nome: str = "", cargo: str = "") -> tuple[str, list]:
    """Constrói cláusula WHERE para filtros de edital_nome e cargo."""
    where = ""
    params = []
    if edital_nome:
        where += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        where += " AND cargo = ?"
        params.append(cargo)
    return where, params
