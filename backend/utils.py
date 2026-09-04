import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pypdf import PdfReader

# ============================================================
# TEMPO ADAPTATIVO POR QUESTÃO (mais justo — inclui alternativas)
# ============================================================

# Velocidade de leitura para COMPREENSÃO de prova (não leitura casual).
# Leitura casual fica em ~200-250 wpm (Brysbaert, 2019), mas leitura analítica
# de questão de concurso — com releitura, atenção a pegadinhas e negações —
# cai para ~120-150 wpm. Usamos 130 wpm como base conservadora e mais justa.
_WPM_COMPREENSAO = 130

# Multiplicador de tempo por dificuldade declarada da questão.
_FATOR_DIFICULDADE = {
    "fácil": 1.0, "facil": 1.0,
    "médio": 1.15, "medio": 1.15, "média": 1.15, "media": 1.15,
    "difícil": 1.35, "dificil": 1.35,
}


def calcular_tempo_resposta_questao(
    enunciado: str,
    alternativas: list | None = None,
    dificuldade: str = "Médio",
    minimo: int = 30,
    maximo: int = 180,
) -> int:
    """Tempo justo (segundos) para responder uma questão de múltipla escolha.

    Melhora o cálculo antigo (que ignorava o texto das alternativas e usava
    200 wpm) considerando:

    - Leitura do enunciado E das alternativas a 130 wpm (compreensão de prova).
    - Tempo de avaliação por alternativa (comparar/eliminar): 4s cada.
    - Tempo de decisão/releitura do comando: 12s.
    - Fator por dificuldade (Fácil 1.0 / Médio 1.15 / Difícil 1.35).
    - Faixa padrão 30s–180s (questões longas de interpretação têm tempo justo).

    `alternativas` pode ser uma lista de strings ou de dicts {"texto": ...}.
    """
    palavras_enunciado = len(enunciado.split()) if enunciado else 10

    alternativas = alternativas or []
    num_alt = 0
    palavras_alt = 0
    for a in alternativas:
        texto = a.get("texto", "") if isinstance(a, dict) else str(a or "")
        texto = texto.strip()
        if not texto:
            continue
        num_alt += 1
        palavras_alt += len(texto.split())
    if num_alt == 0:
        num_alt = 4  # fallback defensivo

    total_palavras = palavras_enunciado + palavras_alt
    tempo_leitura = (total_palavras / _WPM_COMPREENSAO) * 60  # segundos
    tempo_avaliacao_alt = num_alt * 4  # avaliar/eliminar cada alternativa
    tempo_decisao = 12  # releitura do comando + decisão final

    fator = _FATOR_DIFICULDADE.get((dificuldade or "").strip().lower(), 1.15)
    tempo = int((tempo_leitura + tempo_avaliacao_alt + tempo_decisao) * fator)
    return max(minimo, min(maximo, tempo))


# Multiplicador de tempo por estado FSRS do flashcard. Cards recém-esquecidos
# (relearning) ou novos exigem mais esforço de recuperação que cards maduros.
_FATOR_FSRS_FLASHCARD = {
    0: 1.2,   # New — nunca visto, sem traço de memória
    1: 1.15,  # Learning — em fase inicial
    2: 1.0,   # Review — maduro, recall mais rápido
    3: 1.25,  # Relearning — esquecido recentemente, mais difícil
}


def calcular_tempo_flashcard(
    pergunta: str,
    resposta: str,
    fsrs_state: int = 0,
    minimo: int = 10,
    maximo: int = 120,
) -> int:
    """Tempo (segundos) de referência para revisar um flashcard, por complexidade.

    Análogo a calcular_tempo_resposta_questao, mas para o fluxo de recall ativo
    de flashcards (pergunta -> tentar lembrar -> conferir a resposta):

    - Leitura da pergunta a 130 wpm (compreensão).
    - Tempo de recuperação ativa (tentar lembrar): 8s base.
    - Leitura/conferência da resposta a 130 wpm.
    - Fator por estado FSRS (novo/relearning exigem mais esforço).
    - Faixa 10s–120s (flashcards são mais rápidos que questões).
    """
    palavras_pergunta = len(pergunta.split()) if pergunta else 4
    palavras_resposta = len(resposta.split()) if resposta else 4

    tempo_leitura_pergunta = (palavras_pergunta / _WPM_COMPREENSAO) * 60
    tempo_recuperacao = 8  # tentativa de recall ativo
    tempo_leitura_resposta = (palavras_resposta / _WPM_COMPREENSAO) * 60

    fator = _FATOR_FSRS_FLASHCARD.get(fsrs_state if fsrs_state is not None else 0, 1.15)
    tempo = int((tempo_leitura_pergunta + tempo_recuperacao + tempo_leitura_resposta) * fator)
    return max(minimo, min(maximo, tempo))
def today_str():
    return date.today().isoformat()


def get_materias_ciclo_ativo(conn, user_id: int = 1) -> list[str] | None:
    """Retorna as matérias do ciclo de estudos ativo do usuário.

    Regra do projeto (nº 2): queries de recomendação/treinador/revisão devem
    filtrar por `ciclo_estudos WHERE ativo = 1` — nunca mostrar matérias de
    concursos inativos.

    Returns:
        Lista de nomes de matéria ativas, ou None quando não há ciclo ativo
        (nesse caso o chamador deve tratar como "sem filtro" = todas as matérias).
    """
    try:
        rows = conn.execute(
            "SELECT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?",
            (user_id,),
        ).fetchall()
    except Exception:
        # Schemas antigos podem não ter a coluna user_id
        try:
            rows = conn.execute(
                "SELECT materia FROM ciclo_estudos WHERE ativo = 1"
            ).fetchall()
        except Exception:
            return None
    materias = [r[0] for r in rows] if rows else []
    return materias or None


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
    """Calcula streak atual e melhor streak histórico.

    Se hoje ainda não tem atividade, começa a contar a partir de ontem
    (o dia ainda está em andamento, não deve quebrar o streak).
    """
    rows = conn.execute(
        "SELECT data FROM streaks WHERE (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0) AND user_id = ? ORDER BY data DESC",
        (user_id,)
    ).fetchall()

    streak = 0
    check_date = date.today()

    # Se hoje ainda não tem registro, começa checando a partir de ontem
    # (o usuário ainda pode estudar hoje — não penalizar antes do dia acabar)
    if not rows or rows[0][0] != check_date.isoformat():
        check_date -= timedelta(days=1)

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
