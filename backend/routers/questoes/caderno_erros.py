"""Caderno de erros: listagem inteligente com FSRS + revisão interativa."""
from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException
from schemas import RevisarErroRequest

from database import get_db_session
from utils import today_str

router = APIRouter()


@router.get("/api/questoes/erros/caderno", summary="Caderno de erros inteligente",
            description="Retorna questões erradas com repetição espaçada FSRS, agrupadas por padrão de erro.")
def caderno_erros(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from datetime import datetime, timedelta

    from fsrs import STATE_NEW, _retrievability

    hoje = today_str()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS erros_revisao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            questao_id INTEGER NOT NULL,
            resposta_id INTEGER NOT NULL,
            intervalo_atual INTEGER DEFAULT 1,
            proxima_revisao TEXT NOT NULL,
            revisoes_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT '',
            stability REAL DEFAULT NULL,
            difficulty REAL DEFAULT NULL,
            fsrs_state INTEGER DEFAULT 0,
            reps INTEGER DEFAULT 0,
            last_review TEXT DEFAULT NULL,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)

    erros = conn.execute("""
        SELECT q.id, q.materia, q.topico, q.enunciado, q.resposta_correta,
               q.alternativa_a, q.alternativa_b, q.alternativa_c, q.alternativa_d, q.alternativa_e,
               qr.resposta_usuario, qr.data, qr.id as resposta_id
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0 AND qr.user_id = ?
        ORDER BY qr.data DESC
    """, (user_id,)).fetchall()

    # Regra nº 2: filtrar apenas por matérias do ciclo ativo (nunca mostrar
    # matérias de concursos inativos). Aplicado em Python para preservar o
    # fallback "sem ciclo = todas as matérias".
    from utils import get_materias_ciclo_ativo

    materias_ativas = get_materias_ciclo_ativo(conn, user_id)
    if materias_ativas is not None:
        _ativas = set(materias_ativas)
        erros = [e for e in erros if e["materia"] in _ativas]

    existing_revisoes = conn.execute(
        "SELECT questao_id, last_review, created_at FROM erros_revisao WHERE user_id = ?", (user_id,)
    ).fetchall()
    # Uma entrada por QUESTÃO (não por resposta). Guardamos a referência de
    # quando a entrada foi vista pela última vez para decidir reset de prazo.
    existing_por_questao = {
        r["questao_id"]: {"last_review": r["last_review"], "created_at": r["created_at"]}
        for r in existing_revisoes
    }

    # Agrupa os erros por questão, guardando o erro MAIS RECENTE (maior data) e a
    # resposta_id correspondente (referência histórica).
    erros_por_questao = {}
    for erro in erros:
        qid = erro["id"]
        prev = erros_por_questao.get(qid)
        if prev is None or (erro["data"] or "") >= (prev["data"] or ""):
            erros_por_questao[qid] = erro

    for qid, erro in erros_por_questao.items():
        try:
            data_erro = datetime.strptime(erro["data"], "%Y-%m-%d")
        except (ValueError, TypeError):
            data_erro = datetime.now()

        if qid not in existing_por_questao:
            # Nova questão no caderno: agenda para o dia seguinte ao erro.
            proxima = (data_erro + timedelta(days=1)).strftime("%Y-%m-%d")
            conn.execute("""
                INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao,
                    revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review)
                VALUES (?, ?, ?, 1, ?, 0, ?, ?, 0, 0, 0, NULL)
            """, (user_id, qid, erro["resposta_id"], proxima, hoje, STATE_NEW))
            existing_por_questao[qid] = {"last_review": None, "created_at": hoje}
        else:
            # Questão JÁ está no caderno. Se o estudante errou de novo DEPOIS da
            # última revisão registrada, ZERA o prazo (volta a ser pendente hoje)
            # sem criar outra linha — o erro recente indica que o conteúdo não
            # está dominado e precisa voltar ao topo da fila.
            info = existing_por_questao[qid]
            referencia = info.get("last_review") or info.get("created_at") or ""
            erro_str = erro["data"] or ""
            if referencia and erro_str > referencia:
                conn.execute("""
                    UPDATE erros_revisao
                    SET proxima_revisao = ?, intervalo_atual = 1, fsrs_state = ?,
                        stability = 0, difficulty = 0, reps = 0, last_review = NULL,
                        updated_at = ?
                    WHERE user_id = ? AND questao_id = ?
                """, (hoje, STATE_NEW, hoje, user_id, qid))
    conn.commit()

    revisoes_map = {}
    revisoes_rows = conn.execute(
        """SELECT questao_id, intervalo_atual, proxima_revisao, revisoes_count,
                  stability, difficulty, fsrs_state, reps, last_review
           FROM erros_revisao WHERE user_id = ?""",
        (user_id,)
    ).fetchall()
    for r in revisoes_rows:
        revisoes_map[r["questao_id"]] = {
            "intervalo_atual": r["intervalo_atual"],
            "proxima_revisao": r["proxima_revisao"],
            "revisoes_count": r["revisoes_count"],
            "stability": r["stability"],
            "difficulty": r["difficulty"],
            "fsrs_state": r["fsrs_state"],
            "reps": r["reps"],
            "last_review": r["last_review"],
        }

    pendentes_hoje = []
    todos_erros = []
    por_materia = {}
    padroes_raw = {}

    hoje_date = datetime.strptime(hoje, "%Y-%m-%d")

    # --- Padrões de erro: analisam TODAS as respostas erradas (uma questão pode
    # ter marcado alternativas erradas diferentes ao longo do tempo). ---
    for erro in erros:
        padrao_key = f"{erro['materia']}|{erro['topico']}|{erro['resposta_usuario']}"
        if padrao_key not in padroes_raw:
            padroes_raw[padrao_key] = {
                "padrao": f"{erro['materia']} - {erro['topico'] or 'Geral'}: sempre marca '{erro['resposta_usuario']}'",
                "materia": erro["materia"],
                "topico": erro["topico"] or "Geral",
                "resposta_errada": erro["resposta_usuario"],
                "count": 0,
                "questoes": []
            }
        padroes_raw[padrao_key]["count"] += 1
        if erro["id"] not in padroes_raw[padrao_key]["questoes"] and len(padroes_raw[padrao_key]["questoes"]) < 5:
            padroes_raw[padrao_key]["questoes"].append(erro["id"])

    # --- Caderno de erros: UMA entrada por QUESTÃO (unidade de revisão). ---
    for qid, erro in erros_por_questao.items():
        item = dict(erro)
        rev = revisoes_map.get(qid, {})
        item["proxima_revisao"] = rev.get("proxima_revisao", hoje)
        item["intervalo_atual"] = rev.get("intervalo_atual", 1)
        item["revisoes_count"] = rev.get("revisoes_count", 0)

        stability = rev.get("stability")
        last_review_str = rev.get("last_review")
        if stability and stability > 0 and last_review_str:
            try:
                last_review_date = datetime.strptime(last_review_str, "%Y-%m-%d")
                elapsed = max(0, (hoje_date - last_review_date).days)
                item["recall_estimado"] = round(_retrievability(elapsed, stability), 4)
            except (ValueError, TypeError):
                item["recall_estimado"] = 0.0
        else:
            item["recall_estimado"] = 0.0

        todos_erros.append(item)

        mat = erro["materia"] or "Sem matéria"
        por_materia[mat] = por_materia.get(mat, 0) + 1

        if item["proxima_revisao"] <= hoje:
            pendentes_hoje.append(item)

    # Ordenação inteligente
    from study_ordering import order_items_intelligently

    if pendentes_hoje:
        pendentes_hoje = order_items_intelligently(
            pendentes_hoje,
            materia_key="materia",
            reps_key="revisoes_count",
            interval_key="intervalo_atual",
            ef_key="recall_estimado",
            stability_key="recall_estimado",
        )
        for item in pendentes_hoje:
            item.pop("_expanding_retrieval", None)

    padroes_erro = sorted(
        [p for p in padroes_raw.values() if p["count"] >= 2],
        key=lambda x: x["count"],
        reverse=True
    )[:20]

    return {
        "pendentes_hoje": pendentes_hoje,
        "total_erros": len(todos_erros),
        "por_materia": por_materia,
        "padroes_erro": padroes_erro,
    }


@router.post("/api/questoes/erros/revisar/{id}", summary="Revisar questão errada",
             description="Marca uma questão do caderno de erros como revisada. Usa FSRS para calcular próximo intervalo.")
def revisar_erro(id: int, body: RevisarErroRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from fsrs import (
        RATING_AGAIN,
        RATING_GOOD,
        STATE_NEW,
        FSRSCard,
        review_card,
    )

    DESIRED_RETENTION = 0.85
    acertou = body.acertou
    hoje = today_str()

    if not acertou:
        rating = RATING_AGAIN
    elif body.facilidade is not None:
        rating = max(1, min(4, body.facilidade))
    else:
        rating = RATING_GOOD

    revisao = conn.execute(
        """SELECT id, intervalo_atual, revisoes_count, stability, difficulty, fsrs_state, reps, last_review
           FROM erros_revisao WHERE questao_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1""",
        (id, user_id)
    ).fetchone()

    if not revisao:
        erro = conn.execute(
            "SELECT id FROM questoes_respostas WHERE questao_id = ? AND acertou = 0 AND user_id = ? LIMIT 1",
            (id, user_id)
        ).fetchone()
        if not erro:
            raise HTTPException(status_code=404, detail="Questão não encontrada no caderno de erros")
        conn.execute("""
            INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao,
                revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review)
            VALUES (?, ?, ?, 1, ?, 0, ?, ?, 0, 0, 0, NULL)
        """, (user_id, id, erro["id"], hoje, hoje, STATE_NEW))
        conn.commit()
        revisao = conn.execute(
            """SELECT id, intervalo_atual, revisoes_count, stability, difficulty, fsrs_state, reps, last_review
               FROM erros_revisao WHERE questao_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1""",
            (id, user_id)
        ).fetchone()

    fsrs_state = revisao["fsrs_state"] if revisao["fsrs_state"] is not None else STATE_NEW
    stability = revisao["stability"] if revisao["stability"] is not None else 0.0
    difficulty = revisao["difficulty"] if revisao["difficulty"] is not None else 0.0
    reps = revisao["reps"] if revisao["reps"] is not None else 0
    last_review = revisao["last_review"] or ""

    card = FSRSCard(
        stability=stability,
        difficulty=difficulty,
        state=fsrs_state,
        last_review=last_review,
        reps=reps,
    )

    output = review_card(card, rating, desired_retention=DESIRED_RETENTION, review_date=hoje)

    # Successive Relearning com exigência de ALTA FACILIDADE: a questão só é
    # considerada DOMINADA (e graduada — sai do caderno) quando o acerto foi
    # confortável, não sofrido. Critério:
    #   (1) acertou; e
    #   (2) já acumulou revisões suficientes (reps >= GRADUACAO_REPS_MIN); e
    #   (3) o acerto teve ALTA FACILIDADE, ou seja:
    #       - rating >= RATING_GOOD (não "Hard": um acerto difícil NÃO gradua); e
    #       - a dificuldade FSRS resultante ficou baixa (<= GRADUACAO_DIFFICULTY_MAX),
    #         confirmando domínio real do conteúdo (difficulty é 1-10, menor = mais fácil).
    # Assim, acertar "raspando" (Hard) ou com card ainda difícil mantém a questão
    # em revisão espaçada, em vez de removê-la cedo demais.
    facil = rating >= RATING_GOOD and output.difficulty <= GRADUACAO_DIFFICULTY_MAX
    graduou = bool(acertou and reps >= GRADUACAO_REPS_MIN and facil)

    # IMPORTANTE: uma questão pode ter VÁRIAS linhas em erros_revisao (uma por
    # resposta_id — cada vez que foi errada em contexto diferente). A revisão é
    # por QUESTÃO, então o efeito (graduar ou avançar o agendamento) deve valer
    # para TODAS as linhas daquele questao_id. Caso contrário, entradas antigas
    # ficam com proxima_revisao no passado e a questão reaparece como pendente
    # ao dar refresh, mesmo já tendo sido revisada hoje.
    if graduou:
        conn.execute(
            "DELETE FROM erros_revisao WHERE questao_id = ? AND user_id = ?",
            (id, user_id),
        )
    else:
        conn.execute("""
            UPDATE erros_revisao
            SET intervalo_atual = ?, proxima_revisao = ?, revisoes_count = revisoes_count + 1, updated_at = ?,
                stability = ?, difficulty = ?, fsrs_state = ?, reps = reps + 1, last_review = ?
            WHERE questao_id = ? AND user_id = ?
        """, (
            output.interval,
            output.next_review,
            hoje,
            output.stability,
            output.difficulty,
            output.state,
            hoje,
            id,
            user_id,
        ))

    # Registrar tempo de revisão (tempo real se enviado, senão ~2min por questão) + atualizar streak
    from utils import update_streak
    if body.tempo_segundos and body.tempo_segundos > 0:
        horas_revisao = min(body.tempo_segundos, 600) / 3600  # Cap em 10min (evita inflado)
    else:
        horas_revisao = 2 / 60  # Fallback: ~2 minutos por revisão
    materia = conn.execute("SELECT materia FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    mat_nome = materia["materia"] if materia else "Caderno de Erros"

    existing = conn.execute(
        "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'caderno_erros' AND user_id = ?",
        (hoje, mat_nome, user_id)
    ).fetchone()
    if existing:
        conn.execute("UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                     (horas_revisao, existing["id"], user_id))
    else:
        from datetime import datetime as dt
        conn.execute(
            "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, 'caderno_erros', ?, ?)",
            (mat_nome, horas_revisao, hoje, user_id, dt.now().isoformat())
        )
    update_streak(conn, "questoes_resolvidas", user_id=user_id)
    update_streak(conn, "horas_estudadas", horas_revisao, user_id=user_id)

    conn.commit()

    return {
        "ok": True,
        "acertou": acertou,
        "graduou": graduou,
        "novo_intervalo": output.interval,
        "proxima_revisao": output.next_review,
        "revisoes_count": revisao["revisoes_count"] + 1,
        "stability": round(output.stability, 4),
        "difficulty": round(output.difficulty, 4),
        "recall_estimado": round(output.retrievability, 4),
    }


# Nº de revisões acertadas a partir do qual uma questão é considerada DOMINADA e
# graduada (removida do caderho de erros). Alinhado ao critério já usado em
# core._schedule_question_review (reps >= 3) e à noção de "dominada" de
# _smart_select_questions (3+ acertos). Successive Relearning: a questão saiu do
# relearning e atingiu retenção durável.
GRADUACAO_REPS_MIN = 3

# Teto de dificuldade FSRS (escala 1-10; menor = mais fácil) para considerar o
# acerto como de ALTA FACILIDADE na graduação. Só grada quando, além de reps
# suficientes e rating >= Good, a dificuldade resultante ficou <= este valor —
# ou seja, o conteúdo está realmente confortável, não apenas "acertado". Valor
# 5.0 = metade da escala: exige que o card esteja no lado "fácil".
GRADUACAO_DIFFICULTY_MAX = 5.0


def atualizar_fsrs_ao_responder(conn, questao_id: int, acertou: bool, user_id: int = 1) -> dict | None:
    """Atualiza o FSRS de uma questão em `erros_revisao` quando ela é respondida
    fora do fluxo de revisão dedicado (ex.: desafio diário, simulado).

    Sem isto, questões que entraram no caderno de erros ficam presas com
    `proxima_revisao` no passado e reaparecem todos os dias, mesmo sendo
    acertadas repetidamente (não graduavam).

    Comportamento:
    - Se a questão NÃO está em `erros_revisao`, não faz nada (retorna None).
    - Acerto → RATING_GOOD; erro → RATING_AGAIN. Avança o card FSRS.
    - Se acertou e já acumulou >= GRADUACAO_REPS_MIN revisões, a questão GRADUA:
      a entrada é removida do caderho de erros e para de ser sorteada como
      pendente (mesmo critério de core._schedule_question_review).

    Returns:
        dict com o resultado (graduou/novo_intervalo/proxima_revisao) ou None se
        a questão não estava no caderno de erros.
    """
    from fsrs import (
        RATING_AGAIN,
        RATING_GOOD,
        STATE_NEW,
        FSRSCard,
        review_card,
    )

    DESIRED_RETENTION = 0.85
    hoje = today_str()

    revisao = conn.execute(
        """SELECT id, intervalo_atual, revisoes_count, stability, difficulty, fsrs_state, reps, last_review
           FROM erros_revisao WHERE questao_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1""",
        (questao_id, user_id),
    ).fetchone()

    if not revisao:
        return None  # questão não está no caderno de erros → nada a fazer

    rating = RATING_GOOD if acertou else RATING_AGAIN
    reps_atual = revisao["reps"] if revisao["reps"] is not None else 0

    card = FSRSCard(
        stability=revisao["stability"] if revisao["stability"] is not None else 0.0,
        difficulty=revisao["difficulty"] if revisao["difficulty"] is not None else 0.0,
        state=revisao["fsrs_state"] if revisao["fsrs_state"] is not None else STATE_NEW,
        last_review=revisao["last_review"] or "",
        reps=reps_atual,
    )

    output = review_card(card, rating, desired_retention=DESIRED_RETENTION, review_date=hoje)

    # Graduação: acertou e já tem revisões suficientes → sai do caderno de erros.
    # Afeta TODAS as linhas do questao_id (ver nota em revisar_erro).
    if acertou and reps_atual >= GRADUACAO_REPS_MIN:
        conn.execute(
            "DELETE FROM erros_revisao WHERE questao_id = ? AND user_id = ?",
            (questao_id, user_id),
        )
        return {
            "graduou": True,
            "novo_intervalo": output.interval,
            "proxima_revisao": output.next_review,
        }

    conn.execute("""
        UPDATE erros_revisao
        SET intervalo_atual = ?, proxima_revisao = ?, revisoes_count = revisoes_count + 1, updated_at = ?,
            stability = ?, difficulty = ?, fsrs_state = ?, reps = reps + 1, last_review = ?
        WHERE questao_id = ? AND user_id = ?
    """, (
        output.interval,
        output.next_review,
        hoje,
        output.stability,
        output.difficulty,
        output.state,
        hoje,
        questao_id,
        user_id,
    ))
    return {
        "graduou": False,
        "novo_intervalo": output.interval,
        "proxima_revisao": output.next_review,
    }
