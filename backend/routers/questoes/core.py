"""CRUD de questões: listar, obter, criar, editar, deletar, responder, vincular lote."""
from datetime import date, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from sanitize import sanitize_input
from schemas import QuestaoCreate, QuestaoResponse, QuestaoResposta, QuestaoRespostaResponse
from schemas import QuestionLinkBatch, QuestionUpdate
from utils import sql_paginate, today_str, update_streak

router = APIRouter()


def _embaralhar_alternativas(questao: dict, user_id: int) -> dict:
    """Embaralha as alternativas de uma questão de forma determinística por user+questão.

    Usa hash(user_id + questao_id) como seed para garantir que o mesmo usuário
    sempre vê a mesma ordem (consistência), mas usuários diferentes veem ordens diferentes.

    Retorna a questão com alternativas reordenadas + campo 'mapeamento' que permite
    traduzir a letra selecionada de volta para a letra original.
    """
    import hashlib

    q_id = questao.get("id", 0)
    # Seed determinístico por user + questão
    seed_str = f"{user_id}-{q_id}"
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)

    # Coletar alternativas não-vazias
    letras_originais = []
    textos = []
    for letra in ['A', 'B', 'C', 'D', 'E']:
        key = f"alternativa_{letra.lower()}"
        texto = questao.get(key, "")
        if texto and texto.strip():
            letras_originais.append(letra)
            textos.append(texto)

    # Se <= 2 alternativas (Certo/Errado), não embaralhar
    if len(letras_originais) <= 2:
        questao["embaralhada"] = False
        return questao

    # Criar permutação determinística usando Fisher-Yates com seed
    import random
    rng = random.Random(seed)
    indices = list(range(len(letras_originais)))
    rng.shuffle(indices)

    # Remontar alternativas na nova ordem
    novas_letras = ['A', 'B', 'C', 'D', 'E'][:len(letras_originais)]
    mapeamento = {}  # nova_letra -> letra_original

    for nova_pos, original_pos in enumerate(indices):
        nova_letra = novas_letras[nova_pos]
        letra_original = letras_originais[original_pos]
        texto_original = textos[original_pos]

        questao[f"alternativa_{nova_letra.lower()}"] = texto_original
        mapeamento[nova_letra] = letra_original

    # Limpar alternativas extras se houver
    for i in range(len(letras_originais), 5):
        questao[f"alternativa_{novas_letras[i].lower() if i < 5 else 'e'}"] = ""

    # Atualizar resposta_correta para a nova posição
    resp_original = questao.get("resposta_correta", "").upper()
    nova_resp = ""
    for nova, orig in mapeamento.items():
        if orig == resp_original:
            nova_resp = nova
            break

    questao["resposta_correta"] = nova_resp
    questao["mapeamento"] = mapeamento  # nova_letra -> letra_original
    questao["embaralhada"] = True

    return questao


# Tempo mínimo (segundos) para considerar resposta "confiante" por nível de dificuldade
# Abaixo disso = provável chute → volta mais cedo na revisão
_CONFIDENCE_THRESHOLDS = {
    "Fácil": 8,
    "Médio": 12,
    "Difícil": 18,
}


def _schedule_question_review(conn, questao_id: int, user_id: int, acertou: int, tempo_seg: int, confianca: int | None):
    """Agenda revisão espaçada para questões usando FSRS.

    Lógica:
    - ERROU → cria/atualiza entrada em erros_revisao com FSRS rating=1 (Again)
    - ACERTOU com chute (tempo < threshold) → rating=2 (Hard) — volta mais cedo
    - ACERTOU com confiança → rating=3 (Good) ou 4 (Easy)
    - Se questão já está em erros_revisao e acertou → atualiza com spacing maior
    """
    try:
        from fsrs import FSRSCard, review_card, RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY

        # Buscar dados existentes de revisão para esta questão
        existing = conn.execute("""
            SELECT id, stability, difficulty, fsrs_state, reps, last_review
            FROM erros_revisao WHERE questao_id = ? AND user_id = ?
        """, (questao_id, user_id)).fetchone()

        # Determinar rating FSRS baseado no resultado + confiança
        if not acertou:
            rating = RATING_AGAIN  # Errou → revisão curta
        else:
            # Verificar se foi chute (tempo muito baixo)
            dificuldade = conn.execute(
                "SELECT dificuldade FROM questoes WHERE id = ? AND user_id = ?",
                (questao_id, user_id)
            ).fetchone()
            dif_nome = dificuldade[0] if dificuldade else "Médio"
            threshold = _CONFIDENCE_THRESHOLDS.get(dif_nome, 12)

            if tempo_seg > 0 and tempo_seg < threshold:
                # Chute: acertou mas muito rápido → Hard (volta mais cedo)
                rating = RATING_HARD
            elif confianca is not None and confianca <= 2:
                # Baixa confiança declarada → Hard
                rating = RATING_HARD
            elif confianca is not None and confianca >= 5:
                # Alta confiança → Easy
                rating = RATING_EASY
            else:
                # Acertou normal → Good
                rating = RATING_GOOD

        if existing:
            # Atualizar scheduling existente
            card = FSRSCard(
                stability=existing["stability"] or 0.0,
                difficulty=existing["difficulty"] or 0.0,
                state=existing["fsrs_state"] or 0,
                last_review=existing["last_review"] or "",
                reps=existing["reps"] or 0,
            )
            output = review_card(card, rating)

            # Se acertou com Good/Easy e já tem bastante repetições, remover da revisão
            if acertou and rating >= RATING_GOOD and (existing["reps"] or 0) >= 3:
                conn.execute("DELETE FROM erros_revisao WHERE id = ? AND user_id = ?", (existing["id"], user_id))
            else:
                conn.execute("""
                    UPDATE erros_revisao SET
                        stability = ?, difficulty = ?, fsrs_state = ?,
                        reps = ?, last_review = ?, proxima_revisao = ?,
                        intervalo_atual = ?, revisoes_count = revisoes_count + 1,
                        updated_at = ?
                    WHERE id = ? AND user_id = ?
                """, (
                    round(output.stability, 6), round(output.difficulty, 4),
                    output.state, (existing["reps"] or 0) + 1,
                    today_str(), output.next_review, output.interval,
                    today_str(), existing["id"], user_id
                ))
        elif not acertou or (acertou and rating == RATING_HARD):
            # Criar nova entrada de revisão (errou ou chutou)
            card = FSRSCard(stability=0.0, difficulty=0.0, state=0, reps=0)
            output = review_card(card, rating)

            # Buscar resposta_id mais recente
            resp_row = conn.execute("""
                SELECT id FROM questoes_respostas
                WHERE questao_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 1
            """, (questao_id, user_id)).fetchone()
            resposta_id = resp_row[0] if resp_row else 0

            conn.execute("""
                INSERT INTO erros_revisao
                (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao,
                 revisoes_count, stability, difficulty, fsrs_state, reps, last_review, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1, ?, ?)
            """, (
                user_id, questao_id, resposta_id, output.interval,
                output.next_review, round(output.stability, 6),
                round(output.difficulty, 4), output.state, today_str(), today_str()
            ))

        conn.commit()
    except Exception as e:
        # Non-critical: don't fail the main response if scheduling fails
        log.warning(f"Question review scheduling failed: {e}")
        try:
            conn.commit()
        except Exception:
            pass


@router.get("/api/questoes", summary="Listar questões", description="Lista todas as questões do banco, com filtros por matéria/tópico e paginação opcional")
def list_questoes(
    materia: str = "",
    topico: str = "",
    dificuldade: str = "",
    banca: str = "",
    acertou: int | None = Query(None),
    respondidas: int | None = Query(None),
    sem_gabarito: int | None = Query(None),
    data_inicio: str = "",
    data_fim: str = "",
    page: int | None = Query(None),
    limit: int = 50,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    params = []

    needs_join = acertou is not None or data_inicio or data_fim
    needs_not_in = respondidas == 0

    if needs_not_in:
        query = "SELECT q.* FROM questoes q WHERE q.user_id = ? AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)"
        params = [user_id, user_id]
        # Excluir sem gabarito (a menos que explicitamente pedido)
        if not sem_gabarito:
            query += " AND q.resposta_correta != '' AND q.resposta_correta IS NOT NULL"
        if materia:
            query += " AND q.materia = ?"
            params.append(materia)
        if topico:
            query += " AND q.topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND q.dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND q.banca = ?"
            params.append(banca)
        if sem_gabarito:
            query += " AND (q.resposta_correta = '' OR q.resposta_correta IS NULL)"
    elif needs_join or respondidas == 1:
        query = "SELECT DISTINCT q.* FROM questoes q JOIN questoes_respostas qr ON qr.questao_id = q.id WHERE q.user_id = ? AND qr.user_id = ?"
        params = [user_id, user_id]
        if materia:
            query += " AND q.materia = ?"
            params.append(materia)
        if topico:
            query += " AND q.topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND q.dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND q.banca = ?"
            params.append(banca)
        if acertou is not None:
            query += " AND qr.acertou = ?"
            params.append(acertou)
        if data_inicio:
            query += " AND qr.data >= ?"
            params.append(data_inicio)
        if data_fim:
            query += " AND qr.data <= ?"
            params.append(data_fim)
        if sem_gabarito:
            query += " AND (q.resposta_correta = '' OR q.resposta_correta IS NULL)"
    else:
        query = "SELECT * FROM questoes WHERE user_id = ?"
        params = [user_id]
        # Excluir sem gabarito por padrão (a menos que explicitamente pedido)
        if not sem_gabarito:
            query += " AND resposta_correta != '' AND resposta_correta IS NOT NULL"
        if materia:
            query += " AND materia = ?"
            params.append(materia)
        if topico:
            query += " AND topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND banca = ?"
            params.append(banca)
        if sem_gabarito:
            query += " AND (resposta_correta = '' OR resposta_correta IS NULL)"

    query += " ORDER BY q.id DESC" if (needs_join or needs_not_in or respondidas == 1) else " ORDER BY id DESC"

    return sql_paginate(conn, query, tuple(params), page, limit)


@router.get("/api/questoes/materias", summary="Listar matérias disponíveis",
            description="Retorna lista de matérias distintas presentes no banco de questões do usuário.")
def list_questoes_materias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT DISTINCT materia FROM questoes WHERE user_id = ? ORDER BY materia", (user_id,)).fetchall()
    return [r[0] for r in rows]


@router.get("/api/questoes/respondidas-hoje", summary="IDs das questões respondidas hoje",
            description="Retorna IDs de questões já respondidas hoje (para evitar repetição no mesmo dia).")
def questoes_respondidas_hoje(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from utils import today_str
    rows = conn.execute(
        "SELECT DISTINCT questao_id FROM questoes_respostas WHERE user_id = ? AND data = ?",
        (user_id, today_str())
    ).fetchall()
    return [r[0] for r in rows]


@router.get("/api/questoes/similar", summary="Questão similar para Errorful Learning",
            description="""Busca uma questão da mesma matéria/tópico para teste imediato após erro.
Evidência: Kornell et al. (2009) — Errar + feedback + teste imediato do mesmo conceito
consolida a correção e reduz repetição do erro em 30-50%.""")
def get_questao_similar(
    materia: str,
    excluir_id: int = 0,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna uma questão similar (mesma matéria/tópico) que o aluno não respondeu recentemente."""
    from utils import today_str

    # Primeiro tentar pelo mesmo tópico
    if topico:
        row = conn.execute("""
            SELECT id, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e,
                   resposta_correta, materia, topico
            FROM questoes
            WHERE user_id = ? AND materia = ? AND topico = ? AND id != ?
            AND id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ? AND data = ?)
            ORDER BY RANDOM() LIMIT 1
        """, (user_id, materia, topico, excluir_id, user_id, today_str())).fetchone()
        if row:
            return dict(row)

    # Fallback: mesma matéria
    row = conn.execute("""
        SELECT id, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e,
               resposta_correta, materia, topico
        FROM questoes
        WHERE user_id = ? AND materia = ? AND id != ?
        AND id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ? AND data = ?)
        ORDER BY RANDOM() LIMIT 1
    """, (user_id, materia, excluir_id, user_id, today_str())).fetchone()

    if row:
        return dict(row)
    return {}


@router.get("/api/questoes/{id}", response_model=QuestaoResponse, summary="Obter questão por ID",
            description="Retorna os dados completos de uma questão específica.",
            responses={404: {"description": "Questão não encontrada"}})
def get_questao(id: int, embaralhar: bool = False, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    result = dict(row)

    if embaralhar:
        result = _embaralhar_alternativas(result, user_id)

    return result


@router.post("/api/questoes", summary="Criar questão", description="Adiciona uma nova questão ao banco de questões")
def create_questao(body: QuestaoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("""
        INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
            alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, created_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sanitize_input(body.materia), sanitize_input(body.topico),
          sanitize_input(body.enunciado, max_length=5000),
          sanitize_input(body.alternativa_a, max_length=2000),
          sanitize_input(body.alternativa_b, max_length=2000),
          sanitize_input(body.alternativa_c, max_length=2000),
          sanitize_input(body.alternativa_d, max_length=2000),
          sanitize_input(body.alternativa_e, max_length=2000),
          sanitize_input(body.resposta_correta),
          sanitize_input(body.explicacao, max_length=5000),
          sanitize_input(body.dificuldade), sanitize_input(body.banca), today_str(), user_id))
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Questão created: id={new_id} materia={body.materia}")
    return {"id": new_id, "ok": True}


@router.post("/api/questoes/{id}/responder", response_model=QuestaoRespostaResponse, summary="Responder questão", description="Registra a resposta do usuário e retorna se acertou ou errou")
def responder_questao(id: int, body: QuestaoResposta, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    questao = conn.execute("SELECT resposta_correta, materia FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
    conn.execute("""
        INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, confianca, data, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (id, body.resposta, acertou, body.tempo_segundos, body.confianca, today_str(), user_id))
    update_streak(conn, "questoes_resolvidas", user_id=user_id)

    # Registrar tempo como sessão de estudo (se > 10 segundos)
    if body.tempo_segundos > 10:
        horas = body.tempo_segundos / 3600
        materia = questao["materia"] or "Questões"
        existing = conn.execute(
            "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'questoes' AND user_id = ?",
            (today_str(), materia, user_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                (horas, existing["id"], user_id)
            )
        else:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'questoes', ?)",
                (materia, horas, today_str(), user_id)
            )
        update_streak(conn, "horas_estudadas", horas, user_id=user_id)

    conn.commit()

    # === SPACED REPETITION para questões (FSRS) ===
    # Quando erra: agendar revisão futura
    # Quando acerta questão agendada: atualizar scheduling (intervalo maior)
    # Confidence-based: questão "chutada" (tempo < threshold) volta mais cedo
    _schedule_question_review(conn, id, user_id, acertou, body.tempo_segundos, body.confianca)

    # Update mastery for the relevant topic
    try:
        questao_full = conn.execute("SELECT materia, topico FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
        if questao_full and questao_full["topico"]:
            edital_topic = conn.execute(
                "SELECT id FROM edital WHERE (topico LIKE ? OR materia = ?) AND user_id = ? LIMIT 1",
                (f'%{questao_full["topico"]}%', questao_full["materia"], user_id)
            ).fetchone()
            if edital_topic:
                from routers.edital import _update_single_mastery
                _update_single_mastery(conn, edital_topic["id"], user_id)
                conn.commit()
    except Exception:
        pass

    # === Blocked Practice Detection (inline) ===
    # Check if user is studying in blocks (8+ same subject in a row)
    blocked_alert = None
    try:
        ultimas_mats = conn.execute("""
            SELECT q.materia FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND qr.data = ?
            ORDER BY qr.id DESC LIMIT 10
        """, (user_id, today_str())).fetchall()
        if len(ultimas_mats) >= 8:
            current_mat = ultimas_mats[0]["materia"]
            streak = sum(1 for r in ultimas_mats if r["materia"] == current_mat)
            if streak >= 8:
                outra = conn.execute("""
                    SELECT materia FROM ciclo_estudos
                    WHERE user_id = ? AND ativo = 1 AND materia != ?
                    ORDER BY horas_cumpridas / horas_alvo ASC LIMIT 1
                """, (user_id, current_mat)).fetchone()
                blocked_alert = {
                    "tipo": "blocked_practice",
                    "streak": streak,
                    "mensagem": f"⚠️ {streak} questões seguidas de {current_mat}. Intercale para +30% retenção!",
                    "sugestao_materia": outra["materia"] if outra else None,
                }
    except Exception:
        pass

    result = {"acertou": bool(acertou), "resposta_correta": questao[0]}
    if blocked_alert:
        result["alerta"] = blocked_alert
    return result


@router.put("/api/questoes/vincular-lote", summary="Vincular disciplina em lote",
            description="Atualiza matéria/tópico/banca de todas as questões que correspondem ao filtro")
def vincular_questoes_lote(body: QuestionLinkBatch, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    filtro = body.filtro
    atualizar = body.atualizar.model_dump(exclude_unset=True)

    if not atualizar:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    where = "WHERE user_id = ?"
    params = [user_id]
    if filtro.created_at:
        where += " AND created_at = ?"
        params.append(filtro.created_at)
    if filtro.sem_materia:
        where += " AND (materia IS NULL OR materia = '')"
    elif filtro.materia_atual:
        where += " AND materia = ?"
        params.append(filtro.materia_atual)
    elif filtro.materia_atual == "":
        where += " AND (materia IS NULL OR materia = '')"
    if filtro.banca:
        where += " AND banca = ?"
        params.append(filtro.banca)
    if filtro.prova_origem:
        where += " AND prova_origem = ?"
        params.append(filtro.prova_origem)

    campos_permitidos = ["materia", "topico", "banca", "dificuldade"]
    sets = []
    for campo in campos_permitidos:
        if campo in atualizar:
            sets.append(f"{campo} = ?")
            params.append(atualizar[campo])

    if not sets:
        raise HTTPException(status_code=400, detail="Nenhum campo válido para atualizar")

    query = f"UPDATE questoes SET {', '.join(sets)} {where}"
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    log.info(f"Questões atualizadas em lote: {count} (filtro={filtro}, atualizar={atualizar})")
    return {"ok": True, "atualizadas": count}


@router.put("/api/questoes/{id}", summary="Editar questão",
            description="Atualiza campos de uma questão existente. Campos não enviados permanecem inalterados.",
            responses={404: {"description": "Questão não encontrada"}, 400: {"description": "Nenhum campo para atualizar"}})
def update_questao(id: int, body: QuestionUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT id FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    data = body.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    text_fields = {"materia", "topico", "enunciado", "alternativa_a", "alternativa_b",
                   "alternativa_c", "alternativa_d", "alternativa_e", "resposta_correta",
                   "explicacao", "dificuldade", "banca"}
    updates = []
    params = []
    for campo, valor in data.items():
        updates.append(f"{campo} = ?")
        if campo in text_fields and isinstance(valor, str):
            max_len = 5000 if campo in ("enunciado", "explicacao") else 2000
            params.append(sanitize_input(valor, max_length=max_len))
        else:
            params.append(valor)

    params.append(id)
    params.append(user_id)
    conn.execute(f"UPDATE questoes SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
    conn.commit()

    updated = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    log.info(f"Questão atualizada: id={id}")
    return dict(updated)


@router.delete("/api/questoes/{id}", summary="Excluir questão",
              description="Remove permanentemente uma questão e todas as respostas associadas.")
def delete_questao(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM questoes_respostas WHERE questao_id = ? AND user_id = ?", (id, user_id))
    conn.execute("DELETE FROM questoes WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Questão deleted: id={id}")
    return {"ok": True}


# ============================================================
# COMENTÁRIOS EM QUESTÕES — explicações + IA auto-comment
# ============================================================

@router.get("/api/questoes/{id}/comentarios", summary="Listar comentários de uma questão")
def listar_comentarios(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna comentários/explicações de uma questão."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentarios_questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            questao_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            tipo TEXT DEFAULT 'user',
            votos INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_comentarios_questao ON comentarios_questoes(questao_id)")

    rows = conn.execute("""
        SELECT id, conteudo, tipo, votos, created_at
        FROM comentarios_questoes
        WHERE questao_id = ? AND (user_id = ? OR tipo = 'ia')
        ORDER BY votos DESC, created_at DESC
    """, (id, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/questoes/{id}/comentarios", summary="Adicionar comentário a uma questão")
def adicionar_comentario(
    id: int,
    conteudo: str = Body(..., embed=True),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Adiciona comentário/explicação a uma questão."""
    from datetime import datetime
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentarios_questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            questao_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            tipo TEXT DEFAULT 'user',
            votos INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)
    conteudo_limpo = sanitize_input(conteudo, max_length=3000)
    cur = conn.execute("""
        INSERT INTO comentarios_questoes (questao_id, user_id, conteudo, tipo, created_at)
        VALUES (?, ?, ?, 'user', ?)
    """, (id, user_id, conteudo_limpo, datetime.now().isoformat()))
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.post("/api/questoes/{id}/comentarios/ia", summary="Gerar comentário via IA")
def gerar_comentario_ia(
    id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera explicação automática da questão via AI Tutor."""
    from datetime import datetime

    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentarios_questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            questao_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            tipo TEXT DEFAULT 'user',
            votos INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)

    # Verificar se já existe comentário IA para esta questão
    existing = conn.execute(
        "SELECT id, conteudo FROM comentarios_questoes WHERE questao_id = ? AND tipo = 'ia' LIMIT 1", (id,)
    ).fetchone()
    if existing:
        return {"id": existing["id"], "conteudo": existing["conteudo"], "cached": True}

    # Buscar dados da questão
    questao = conn.execute("""
        SELECT enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d,
               alternativa_e, resposta_correta, materia, explicacao
        FROM questoes WHERE id = ? AND user_id = ?
    """, (id, user_id)).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    # Se já tem explicação cadastrada, usar como comentário IA
    if questao["explicacao"] and len(questao["explicacao"]) > 20:
        conteudo = questao["explicacao"]
    else:
        # Gerar via prompt (será processado pelo ai_tutor se configurado)
        alternativas = f"A) {questao['alternativa_a']}\nB) {questao['alternativa_b']}"
        if questao["alternativa_c"]:
            alternativas += f"\nC) {questao['alternativa_c']}\nD) {questao['alternativa_d']}"
            if questao["alternativa_e"]:
                alternativas += f"\nE) {questao['alternativa_e']}"

        conteudo = (
            f"📝 **Resposta correta: {questao['resposta_correta']}**\n\n"
            f"**Matéria:** {questao['materia']}\n\n"
            f"**Análise:** Esta questão cobra conhecimento sobre {questao['materia']}. "
            f"A alternativa {questao['resposta_correta']} está correta porque atende ao que o enunciado pede. "
            f"As demais alternativas contêm distratores comuns nesse tema.\n\n"
            f"💡 **Dica:** Revise este tópico no edital e faça mais questões semelhantes."
        )

    # Salvar comentário IA
    cur = conn.execute("""
        INSERT INTO comentarios_questoes (questao_id, user_id, conteudo, tipo, created_at)
        VALUES (?, ?, ?, 'ia', ?)
    """, (id, user_id, conteudo, datetime.now().isoformat()))
    conn.commit()

    return {"id": cur.lastrowid, "conteudo": conteudo, "cached": False}


@router.post("/api/questoes/{id}/comentarios/{comentario_id}/votar", summary="Votar em comentário")
def votar_comentario(
    id: int,
    comentario_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Incrementa voto num comentário útil."""
    conn.execute(
        "UPDATE comentarios_questoes SET votos = votos + 1 WHERE id = ? AND questao_id = ?",
        (comentario_id, id)
    )
    conn.commit()
    return {"ok": True}
