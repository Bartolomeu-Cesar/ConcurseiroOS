"""CRUD de questões: listar, obter, criar, editar, deletar, responder, vincular lote."""

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sanitize import sanitize_input
from schemas import (
    QuestaoCreate,
    QuestaoDiscursivaResposta,
    QuestaoResponse,
    QuestaoResposta,
    QuestaoRespostaResponse,
    QuestionLinkBatch,
    QuestionUpdate,
)

from database import get_db_session
from logger import log
from utils import sql_paginate, today_str, update_streak

router = APIRouter()


def _embaralhar_alternativas(questao: dict, user_id: int, seed: int | None = None) -> dict:
    """Embaralha as alternativas de uma questão.

    Modo DETERMINÍSTICO (seed=None): usa hash(user_id + questao_id) como semente —
    o mesmo usuário sempre vê a mesma ordem para a mesma questão (retrocompatível).

    Modo NÃO-DETERMINÍSTICO (seed fornecida): usa a semente recebida — permite ordem
    diferente a cada abertura. O frontend gera a seed, embaralha ao servir e envia a
    MESMA seed no POST /responder para o backend reconstruir a permutação e validar
    a resposta na ordem exibida (a validação continua 100% server-side).

    Retorna a questão com alternativas reordenadas + 'mapeamento' (nova_letra ->
    letra_original) + 'seed' (a semente efetivamente usada).
    """
    import hashlib

    q_id = questao.get("id", 0)
    # Semente: usa a recebida (modo não-determinístico) ou deriva de user+questão
    # (modo determinístico, comportamento legado).
    if seed is not None:
        seed_val = int(seed)
    else:
        seed_str = f"{user_id}-{q_id}"
        seed_val = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)

    # Coletar alternativas não-vazias
    letras_originais = []
    textos = []
    for letra in ["A", "B", "C", "D", "E"]:
        key = f"alternativa_{letra.lower()}"
        texto = questao.get(key, "")
        if texto and texto.strip():
            letras_originais.append(letra)
            textos.append(texto)

    # Se <= 2 alternativas (Certo/Errado), não embaralhar
    if len(letras_originais) <= 2:
        questao["embaralhada"] = False
        questao["seed"] = seed_val
        return questao

    # Criar permutação usando Fisher-Yates com a semente escolhida
    import random

    rng = random.Random(seed_val)
    indices = list(range(len(letras_originais)))
    rng.shuffle(indices)

    # Remontar alternativas na nova ordem
    novas_letras = ["A", "B", "C", "D", "E"][: len(letras_originais)]
    mapeamento = {}  # nova_letra -> letra_original

    for nova_pos, original_pos in enumerate(indices):
        nova_letra = novas_letras[nova_pos]
        letra_original = letras_originais[original_pos]
        texto_original = textos[original_pos]

        questao[f"alternativa_{nova_letra.lower()}"] = texto_original
        mapeamento[nova_letra] = letra_original

    # Limpar alternativas extras se houver (usa a lista completa de letras,
    # pois `novas_letras` foi truncada ao número de alternativas reais).
    todas_letras = ["A", "B", "C", "D", "E"]
    for i in range(len(letras_originais), 5):
        questao[f"alternativa_{todas_letras[i].lower()}"] = ""

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
    questao["seed"] = seed_val

    return questao


# Tempo mínimo (segundos) para considerar resposta "confiante" por nível de dificuldade
# Abaixo disso = provável chute → volta mais cedo na revisão
_CONFIDENCE_THRESHOLDS = {
    "Fácil": 8,
    "Médio": 12,
    "Difícil": 18,
}


def _classificar_chute(acertou: int, tempo_seg, confianca, dificuldade: str) -> dict:
    """Detecta 'chute' ao responder questão, combinando tempo e confiança.

    Sinais:
    - tempo abaixo do threshold da dificuldade (rápido demais para ler+raciocinar);
    - confiança declarada baixa (1 = "chutei"), quando disponível (opcional).

    Retorna:
    - categoria: 'chute_sortudo' | 'acerto_solido' | 'erro' | ''
    - chute: bool (True quando acertou porém há forte indício de chute)
    - mensagem: dica de hipercorreção quando for chute sortudo.

    Observação: para questões, hoje o frontend envia principalmente o tempo; a
    confiança é usada como reforço quando presente. Não altera o scheduling
    (que já trata chute como Hard); serve para feedback + estatística.
    """
    threshold = _CONFIDENCE_THRESHOLDS.get(dificuldade or "Médio", 12)
    tempo = tempo_seg if isinstance(tempo_seg, (int, float)) else 0
    rapido_demais = tempo > 0 and tempo < threshold
    baixa_confianca = confianca is not None and confianca <= 1

    if not acertou:
        return {"categoria": "erro", "chute": False, "mensagem": ""}

    if rapido_demais or baixa_confianca:
        motivo = "muito rápido" if rapido_demais else "baixa confiança"
        return {
            "categoria": "chute_sortudo",
            "chute": True,
            "mensagem": f"🎲 Você acertou, mas parece chute ({motivo}). Acertos por sorte fixam pouco — revise para consolidar.",
        }
    return {"categoria": "acerto_solido", "chute": False, "mensagem": ""}


def _schedule_question_review(conn, questao_id: int, user_id: int, acertou: int, tempo_seg: int, confianca: int | None):
    """Agenda revisão espaçada para questões usando FSRS.

    Lógica:
    - ERROU → cria/atualiza entrada em erros_revisao com FSRS rating=1 (Again)
    - ACERTOU com chute (tempo < threshold) → rating=2 (Hard) — volta mais cedo
    - ACERTOU com confiança → rating=3 (Good) ou 4 (Easy)
    - Se questão já está em erros_revisao e acertou → atualiza com spacing maior
    """
    try:
        from fsrs import RATING_AGAIN, RATING_EASY, RATING_GOOD, RATING_HARD, FSRSCard, review_card

        # Buscar dados existentes de revisão para esta questão
        existing = conn.execute(
            """
            SELECT id, stability, difficulty, fsrs_state, reps, last_review
            FROM erros_revisao WHERE questao_id = ? AND user_id = ?
        """,
            (questao_id, user_id),
        ).fetchone()

        # Determinar rating FSRS baseado no resultado + confiança
        if not acertou:
            rating = RATING_AGAIN  # Errou → revisão curta
        else:
            # Verificar se foi chute (tempo muito baixo)
            dificuldade = conn.execute(
                "SELECT dificuldade FROM questoes WHERE id = ? AND user_id = ?", (questao_id, user_id)
            ).fetchone()
            dif_nome = dificuldade[0] if dificuldade else "Médio"
            threshold = _CONFIDENCE_THRESHOLDS.get(dif_nome, 12)

            if tempo_seg > 0 and tempo_seg < threshold:
                # Chute: acertou mas muito rápido → Hard (volta mais cedo)
                rating = RATING_HARD
            elif confianca is not None and confianca <= 2:
                # Baixa confiança declarada → Hard
                rating = RATING_HARD
            elif confianca is not None and confianca >= 3:
                # Alta confiança (escala 1-3: 3=certeza) → Easy
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
                conn.execute(
                    """
                    UPDATE erros_revisao SET
                        stability = ?, difficulty = ?, fsrs_state = ?,
                        reps = ?, last_review = ?, proxima_revisao = ?,
                        intervalo_atual = ?, revisoes_count = revisoes_count + 1,
                        updated_at = ?
                    WHERE id = ? AND user_id = ?
                """,
                    (
                        round(output.stability, 6),
                        round(output.difficulty, 4),
                        output.state,
                        (existing["reps"] or 0) + 1,
                        today_str(),
                        output.next_review,
                        output.interval,
                        today_str(),
                        existing["id"],
                        user_id,
                    ),
                )
        elif not acertou or (acertou and rating == RATING_HARD):
            # Criar nova entrada de revisão (errou ou chutou)
            card = FSRSCard(stability=0.0, difficulty=0.0, state=0, reps=0)
            output = review_card(card, rating)

            # Buscar resposta_id mais recente
            resp_row = conn.execute(
                """
                SELECT id FROM questoes_respostas
                WHERE questao_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 1
            """,
                (questao_id, user_id),
            ).fetchone()
            resposta_id = resp_row[0] if resp_row else 0

            conn.execute(
                """
                INSERT INTO erros_revisao
                (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao,
                 revisoes_count, stability, difficulty, fsrs_state, reps, last_review, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1, ?, ?)
            """,
                (
                    user_id,
                    questao_id,
                    resposta_id,
                    output.interval,
                    output.next_review,
                    round(output.stability, 6),
                    round(output.difficulty, 4),
                    output.state,
                    today_str(),
                    today_str(),
                ),
            )

        conn.commit()
    except Exception as e:
        # Non-critical: don't fail the main response if scheduling fails
        log.warning(f"Question review scheduling failed: {e}")
        try:
            conn.commit()
        except Exception:
            pass


@router.get(
    "/api/questoes",
    summary="Listar questões",
    description="Lista todas as questões do banco, com filtros por matéria/tópico e paginação opcional",
)
def list_questoes(
    materia: str = "",
    topico: str = "",
    dificuldade: str = "",
    banca: str = "",
    tipo: str = "",
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
        # Excluir sem gabarito (a menos que explicitamente pedido).
        # Discursivas não têm resposta_correta — nunca excluir por isso.
        if not sem_gabarito:
            query += " AND (q.tipo = 'discursiva' OR (q.resposta_correta != '' AND q.resposta_correta IS NOT NULL))"
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
        if tipo:
            query += " AND q.tipo = ?"
            params.append(tipo)
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
        if tipo:
            query += " AND q.tipo = ?"
            params.append(tipo)
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
        # Excluir sem gabarito por padrão (a menos que explicitamente pedido).
        # Discursivas não têm resposta_correta — nunca excluir por isso.
        if not sem_gabarito:
            query += " AND (tipo = 'discursiva' OR (resposta_correta != '' AND resposta_correta IS NOT NULL))"
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
        if tipo:
            query += " AND tipo = ?"
            params.append(tipo)
        if sem_gabarito:
            query += " AND (resposta_correta = '' OR resposta_correta IS NULL)"

    query += " ORDER BY q.id DESC" if (needs_join or needs_not_in or respondidas == 1) else " ORDER BY id DESC"

    return sql_paginate(conn, query, tuple(params), page, limit)


@router.get(
    "/api/questoes/materias",
    summary="Listar matérias disponíveis",
    description="Retorna lista de matérias distintas presentes no banco de questões do usuário.",
)
def list_questoes_materias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        "SELECT DISTINCT materia FROM questoes WHERE user_id = ? ORDER BY materia", (user_id,)
    ).fetchall()
    return [r[0] for r in rows]


@router.get(
    "/api/questoes/topicos",
    summary="Listar assuntos/tópicos das questões",
    description="Lista os assuntos (tópicos) com contagem, para o filtro por assunto "
    "(ex.: Crase, Sistemas Operacionais, Redes). Filtra por matéria se informada. "
    "Ignora questões sem assunto.",
)
def list_questoes_topicos(
    materia: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)
):
    query = (
        "SELECT COALESCE(topico,'') AS topico, materia, COUNT(*) AS total FROM questoes "
        "WHERE user_id = ? AND COALESCE(topico,'') != ''"
    )
    params = [user_id]
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    query += " GROUP BY topico, materia ORDER BY total DESC"
    rows = conn.execute(query, tuple(params)).fetchall()
    return [{"topico": r["topico"], "materia": r["materia"] or "Sem matéria", "total": r["total"]} for r in rows]


@router.get(
    "/api/questoes/respondidas-hoje",
    summary="IDs das questões respondidas hoje",
    description="Retorna IDs de questões já respondidas hoje (para evitar repetição no mesmo dia).",
)
def questoes_respondidas_hoje(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from utils import today_str

    rows = conn.execute(
        "SELECT DISTINCT questao_id FROM questoes_respostas WHERE user_id = ? AND data = ?", (user_id, today_str())
    ).fetchall()
    return [r[0] for r in rows]


@router.get(
    "/api/questoes/codigo/{codigo}",
    summary="Buscar questão pelo código",
    description="""Busca uma questão diretamente pelo seu código/ID (inspirado no QConcursos).
Aceita o número puro (ex: 123) ou prefixado com Q (ex: Q123). Atalho de UX para ir
direto a uma questão específica sem navegar pelos filtros.""",
)
def get_questao_por_codigo(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    # Normaliza: aceita "Q123", "q123", "123", "#123" e espaços.
    raw = (codigo or "").strip().lstrip("Qq#").strip()
    if not raw.isdigit():
        raise HTTPException(status_code=400, detail="Código inválido. Use apenas números (ex: 123 ou Q123).")
    qid = int(raw)
    row = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (qid, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Questão Q{qid} não encontrada.")
    return dict(row)


@router.get(
    "/api/questoes/similar",
    summary="Questão similar para Errorful Learning",
    description="""Busca uma questão da mesma matéria/tópico para teste imediato após erro.
Evidência: Kornell et al. (2009) — Errar + feedback + teste imediato do mesmo conceito
consolida a correção e reduz repetição do erro em 30-50%.""",
)
def get_questao_similar(
    materia: str,
    excluir_id: int = 0,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna uma questão similar (mesma matéria/tópico) que o aluno não respondeu recentemente."""
    from utils import today_str

    # Primeiro tentar pelo mesmo tópico
    if topico:
        row = conn.execute(
            """
            SELECT id, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e,
                   resposta_correta, materia, topico
            FROM questoes
            WHERE user_id = ? AND materia = ? AND topico = ? AND id != ?
            AND id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ? AND data = ?)
            ORDER BY RANDOM() LIMIT 1
        """,
            (user_id, materia, topico, excluir_id, user_id, today_str()),
        ).fetchone()
        if row:
            return dict(row)

    # Fallback: mesma matéria
    row = conn.execute(
        """
        SELECT id, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e,
               resposta_correta, materia, topico
        FROM questoes
        WHERE user_id = ? AND materia = ? AND id != ?
        AND id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ? AND data = ?)
        ORDER BY RANDOM() LIMIT 1
    """,
        (user_id, materia, excluir_id, user_id, today_str()),
    ).fetchone()

    if row:
        return dict(row)
    return {}


@router.get(
    "/api/questoes/{id}",
    response_model=QuestaoResponse,
    summary="Obter questão por ID",
    description="Retorna os dados completos de uma questão específica.",
    responses={404: {"description": "Questão não encontrada"}},
)
def get_questao(
    id: int,
    embaralhar: bool = False,
    seed: int | None = None,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    row = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    result = dict(row)

    if embaralhar:
        # seed opcional: se enviada, embaralhamento NÃO-determinístico (muda a cada
        # abertura); sem seed, mantém o determinístico por user+questão (legado).
        result = _embaralhar_alternativas(result, user_id, seed=seed)

    return result


@router.post("/api/questoes", summary="Criar questão", description="Adiciona uma nova questão ao banco de questões")
def create_questao(body: QuestaoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from plans import enforce_plan_limit

    enforce_plan_limit(conn, user_id, "questoes_banco")

    cur = conn.execute(
        """
        INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
            alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, tipo, resposta_esperada, created_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            sanitize_input(body.materia),
            sanitize_input(body.topico),
            sanitize_input(body.enunciado, max_length=5000),
            sanitize_input(body.alternativa_a, max_length=2000),
            sanitize_input(body.alternativa_b, max_length=2000),
            sanitize_input(body.alternativa_c, max_length=2000),
            sanitize_input(body.alternativa_d, max_length=2000),
            sanitize_input(body.alternativa_e, max_length=2000),
            sanitize_input(body.resposta_correta),
            sanitize_input(body.explicacao, max_length=5000),
            sanitize_input(body.dificuldade),
            sanitize_input(body.banca),
            sanitize_input(body.tipo),
            sanitize_input(body.resposta_esperada, max_length=10000),
            today_str(),
            user_id,
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Questão created: id={new_id} materia={body.materia}")
    return {"id": new_id, "ok": True}


@router.post(
    "/api/questoes/{id}/responder-discursiva",
    summary="Responder questão discursiva",
    description="""Registra a resposta em TEXTO LIVRE de uma questão discursiva e a
autoavaliação (0-100) que o usuário dá à própria resposta comparando com a resposta esperada.
Não há correção automática — segue a técnica de Self-Explanation/Retrieval Practice.
Retorna a resposta esperada (gabarito) para o usuário comparar.""",
)
def responder_discursiva(
    id: int, body: QuestaoDiscursivaResposta, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)
):
    from plans import enforce_plan_limit

    enforce_plan_limit(conn, user_id, "questoes_dia")

    questao = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    if (questao["tipo"] or "objetiva") != "discursiva":
        raise HTTPException(status_code=400, detail="Esta questão não é discursiva. Use /responder.")

    resposta_texto = sanitize_input(body.resposta_texto, max_length=10000)
    if not resposta_texto.strip():
        raise HTTPException(status_code=400, detail="A resposta não pode estar vazia.")

    # Autoavaliação (0-100): normaliza/clampa. None = ainda não avaliada.
    autoaval = body.autoavaliacao
    if autoaval is not None:
        autoaval = max(0, min(100, int(autoaval)))

    # Numa discursiva "acertou" é derivado da autoavaliação (>= 60 = acerto).
    # Se ainda não houve autoavaliação, gravamos acertou=0 sem penalizar streak de acerto.
    acertou = 1 if (autoaval is not None and autoaval >= 60) else 0

    conn.execute(
        """
        INSERT INTO questoes_respostas
            (questao_id, resposta_usuario, resposta_texto, autoavaliacao, acertou, tempo_segundos, data, user_id)
        VALUES (?, '', ?, ?, ?, ?, ?, ?)
    """,
        (id, resposta_texto, autoaval, acertou, body.tempo_segundos, today_str(), user_id),
    )
    update_streak(conn, "questoes_resolvidas", user_id=user_id)

    # Registrar tempo como sessão de estudo (qualquer tempo > 0; cap 10min/questão).
    if body.tempo_segundos and body.tempo_segundos > 0:
        horas = min(body.tempo_segundos, 600) / 3600
        materia = questao["materia"] or "Questões"
        existing = conn.execute(
            "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'questoes' AND user_id = ?",
            (today_str(), materia, user_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                (horas, existing["id"], user_id),
            )
        else:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'questoes', ?)",
                (materia, horas, today_str(), user_id),
            )
        update_streak(conn, "horas_estudadas", horas, user_id=user_id)

    conn.commit()

    return {
        "ok": True,
        "acertou": bool(acertou),
        "autoavaliacao": autoaval,
        "resposta_esperada": questao["resposta_esperada"] or "",
    }


@router.post(
    "/api/questoes/{id}/responder",
    response_model=QuestaoRespostaResponse,
    summary="Responder questão",
    description="Registra a resposta do usuário e retorna se acertou ou errou",
)
def responder_questao(
    id: int, body: QuestaoResposta, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)
):
    from plans import enforce_plan_limit

    enforce_plan_limit(conn, user_id, "questoes_dia")

    questao = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    gabarito = (questao["resposta_correta"] or "").strip().upper()
    # Sem gabarito cadastrado: NÃO registrar resposta nem contabilizar como erro.
    # Antes, a comparação com string vazia marcava SEMPRE "errou", independente da
    # alternativa escolhida. Retorna sinal explícito para o frontend avisar.
    if not gabarito:
        return {
            "acertou": None,
            "sem_gabarito": True,
            "resposta_correta": "",
            "mensagem": "Esta questão está sem gabarito cadastrado, então não é possível corrigir. Importe o gabarito para respondê-la.",
        }

    resposta_usuario = body.resposta.upper()
    # Se a questão foi servida EMBARALHADA (Opção A), o usuário viu as alternativas
    # numa ordem determinística (semente user+questão). Reaplicamos o mesmo
    # embaralhamento para: (a) comparar a resposta com o gabarito NA ORDEM EXIBIDA e
    # (b) traduzir a letra escolhida de volta para a letra ORIGINAL antes de gravar
    # (mantém o banco/relatórios coerentes com a ordem canônica das alternativas).
    if getattr(body, "embaralhada", False):
        # Reaplica a MESMA permutação que o usuário viu. Se veio `seed` (modo
        # não-determinístico), reconstrói com ela; senão usa a semente determinística.
        emb = _embaralhar_alternativas(dict(questao), user_id, seed=getattr(body, "seed", None))
        if emb.get("embaralhada"):
            gabarito = (emb.get("resposta_correta") or "").strip().upper()
            mapeamento = emb.get("mapeamento", {})  # nova_letra -> letra_original
            resposta_usuario = (mapeamento.get(resposta_usuario) or resposta_usuario).upper()

    acertou = 1 if body.resposta.upper() == gabarito else 0
    conn.execute(
        """
        INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, confianca, data, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (id, resposta_usuario, acertou, body.tempo_segundos, body.confianca, today_str(), user_id),
    )
    update_streak(conn, "questoes_resolvidas", user_id=user_id)

    # Registrar tempo como sessão de estudo. Antes o limiar era > 10s POR QUESTÃO,
    # o que descartava silenciosamente todo o tempo de respostas rápidas (uma
    # sessão de 28 questões podia perder metade do tempo real). Agora conta
    # qualquer tempo > 0, com cap de 10min/questão (evita timer abandonado).
    if body.tempo_segundos and body.tempo_segundos > 0:
        horas = min(body.tempo_segundos, 600) / 3600
        materia = questao["materia"] or "Questões"
        existing = conn.execute(
            "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'questoes' AND user_id = ?",
            (today_str(), materia, user_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                (horas, existing["id"], user_id),
            )
        else:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'questoes', ?)",
                (materia, horas, today_str(), user_id),
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
        questao_full = conn.execute(
            "SELECT materia, topico FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)
        ).fetchone()
        if questao_full and questao_full["topico"]:
            edital_topic = conn.execute(
                "SELECT id FROM edital WHERE (topico LIKE ? OR materia = ?) AND user_id = ? LIMIT 1",
                (f"%{questao_full['topico']}%", questao_full["materia"], user_id),
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
        ultimas_mats = conn.execute(
            """
            SELECT q.materia FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND qr.data = ?
            ORDER BY qr.id DESC LIMIT 10
        """,
            (user_id, today_str()),
        ).fetchall()
        if len(ultimas_mats) >= 8:
            current_mat = ultimas_mats[0]["materia"]
            streak = sum(1 for r in ultimas_mats if r["materia"] == current_mat)
            if streak >= 8:
                outra = conn.execute(
                    """
                    SELECT materia FROM ciclo_estudos
                    WHERE user_id = ? AND ativo = 1 AND materia != ?
                    ORDER BY horas_cumpridas / horas_alvo ASC LIMIT 1
                """,
                    (user_id, current_mat),
                ).fetchone()
                blocked_alert = {
                    "tipo": "blocked_practice",
                    "streak": streak,
                    "mensagem": f"⚠️ {streak} questões seguidas de {current_mat}. Intercale para +30% retenção!",
                    "sugestao_materia": outra["materia"] if outra else None,
                }
    except Exception:
        pass

    # `gabarito` já reflete a ordem EXIBIDA (remapeado quando embaralhada; original
    # caso contrário) — o frontend usa para destacar a alternativa correta na tela.
    result = {"acertou": bool(acertou), "resposta_correta": gabarito}

    # Detecção de chute (tempo/confiança) → feedback de hipercorreção ao aluno.
    chute_info = _classificar_chute(acertou, body.tempo_segundos, body.confianca, questao["dificuldade"] if "dificuldade" in questao.keys() else "Médio")
    result["chute"] = chute_info["chute"]
    result["categoria_resposta"] = chute_info["categoria"]
    if chute_info["mensagem"]:
        result["chute_mensagem"] = chute_info["mensagem"]

    if blocked_alert:
        result["alerta"] = blocked_alert
    return result


@router.put(
    "/api/questoes/vincular-lote",
    summary="Vincular disciplina em lote",
    description="Atualiza matéria/tópico/banca de todas as questões que correspondem ao filtro",
)
def vincular_questoes_lote(body: QuestionLinkBatch, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    filtro = body.filtro
    atualizar = body.atualizar.model_dump(exclude_unset=True)

    if not atualizar:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # Monta os parâmetros do WHERE separadamente dos do SET.
    # IMPORTANTE: na query final o SET vem ANTES do WHERE, então os params do
    # SET precisam preceder os do WHERE (bug anterior: ordem trocada zerava o UPDATE).
    where = "WHERE user_id = ?"
    where_params = [user_id]
    if filtro.created_at:
        where += " AND created_at = ?"
        where_params.append(filtro.created_at)
    if filtro.sem_materia:
        where += " AND (materia IS NULL OR materia = '')"
    elif filtro.materia_atual:
        where += " AND materia = ?"
        where_params.append(filtro.materia_atual)
    elif filtro.materia_atual == "":
        where += " AND (materia IS NULL OR materia = '')"
    if filtro.banca:
        where += " AND banca = ?"
        where_params.append(filtro.banca)
    if filtro.prova_origem:
        where += " AND prova_origem = ?"
        where_params.append(filtro.prova_origem)

    campos_permitidos = ["materia", "topico", "banca", "dificuldade"]
    sets = []
    set_params = []
    for campo in campos_permitidos:
        if campo in atualizar:
            sets.append(f"{campo} = ?")
            set_params.append(atualizar[campo])

    if not sets:
        raise HTTPException(status_code=400, detail="Nenhum campo válido para atualizar")

    query = f"UPDATE questoes SET {', '.join(sets)} {where}"
    result = conn.execute(query, set_params + where_params)
    conn.commit()
    count = result.rowcount
    log.info(f"Questões atualizadas em lote: {count} (filtro={filtro}, atualizar={atualizar})")
    return {"ok": True, "atualizadas": count}


@router.put(
    "/api/questoes/{id}",
    summary="Editar questão",
    description="Atualiza campos de uma questão existente. Campos não enviados permanecem inalterados.",
    responses={404: {"description": "Questão não encontrada"}, 400: {"description": "Nenhum campo para atualizar"}},
)
def update_questao(id: int, body: QuestionUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT id FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    data = body.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    text_fields = {
        "materia",
        "topico",
        "enunciado",
        "alternativa_a",
        "alternativa_b",
        "alternativa_c",
        "alternativa_d",
        "alternativa_e",
        "resposta_correta",
        "explicacao",
        "dificuldade",
        "banca",
    }
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


@router.delete(
    "/api/questoes/{id}",
    summary="Excluir questão",
    description="Remove permanentemente uma questão e todas as respostas associadas.",
)
def delete_questao(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM questoes_respostas WHERE questao_id = ? AND user_id = ?", (id, user_id))
    conn.execute("DELETE FROM questoes WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Questão deleted: id={id}")
    return {"ok": True}


# ============================================================
# COMENTÁRIOS EM QUESTÕES — explicações + IA auto-comment
# ============================================================


def _ensure_comentarios_tables(conn):
    """Garante as tabelas de comentários (idempotente).

    O schema canônico vem da migration 97; este helper cobre bancos que ainda
    não migraram (ex.: testes com DB fresco) sem duplicar lógica.
    """
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comentario_votos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comentario_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (comentario_id) REFERENCES comentarios_questoes(id)
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_comentario_votos_uniq "
        "ON comentario_votos(comentario_id, user_id)"
    )


@router.get("/api/questoes/{id}/comentarios", summary="Listar comentários de uma questão")
def listar_comentarios(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna comentários/explicações de uma questão.

    Inclui: comentários do próprio usuário e comentários de IA. Cada item traz
    `voted` (se o usuário atual já votou) e `is_owner` (se pode deletar).
    """
    _ensure_comentarios_tables(conn)

    rows = conn.execute(
        """
        SELECT c.id, c.conteudo, c.tipo, c.votos, c.created_at, c.user_id,
               EXISTS(SELECT 1 FROM comentario_votos v
                      WHERE v.comentario_id = c.id AND v.user_id = ?) AS voted
        FROM comentarios_questoes c
        WHERE c.questao_id = ? AND (c.user_id = ? OR c.tipo = 'ia')
        ORDER BY c.votos DESC, c.created_at DESC
    """,
        (user_id, id, user_id),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["voted"] = bool(d.pop("voted"))
        d["is_owner"] = (d["user_id"] == user_id)
        result.append(d)
    return result


@router.post("/api/questoes/{id}/comentarios", summary="Adicionar comentário a uma questão")
def adicionar_comentario(
    id: int,
    conteudo: str = Body(..., embed=True),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Adiciona comentário/explicação a uma questão."""
    from datetime import datetime

    _ensure_comentarios_tables(conn)
    conteudo_limpo = sanitize_input(conteudo, max_length=3000)
    if not conteudo_limpo or not conteudo_limpo.strip():
        raise HTTPException(status_code=422, detail="Comentário vazio.")
    cur = conn.execute(
        """
        INSERT INTO comentarios_questoes (questao_id, user_id, conteudo, tipo, created_at)
        VALUES (?, ?, ?, 'user', ?)
    """,
        (id, user_id, conteudo_limpo, datetime.now().isoformat()),
    )
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.post("/api/questoes/{id}/comentarios/ia", summary="Gerar comentário via IA")
def gerar_comentario_ia(
    id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera explicação automática da questão via AI Tutor (call_llm_sync).

    Ordem de resolução do conteúdo:
    1. Se já existe comentário IA para a questão → retorna do cache.
    2. Tenta o LLM real (AI Tutor). Se indisponível/erro → fallback:
       2a. usa a `explicacao` cadastrada na questão (se houver); senão
       2b. um resumo estruturado (template) — nunca falha para o usuário.
    """
    from datetime import datetime

    _ensure_comentarios_tables(conn)

    # 1. Cache: um comentário IA por questão
    existing = conn.execute(
        "SELECT id, conteudo FROM comentarios_questoes WHERE questao_id = ? AND tipo = 'ia' LIMIT 1", (id,)
    ).fetchone()
    if existing:
        return {"id": existing["id"], "conteudo": existing["conteudo"], "cached": True}

    questao = conn.execute(
        """
        SELECT enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d,
               alternativa_e, resposta_correta, materia, explicacao
        FROM questoes WHERE id = ? AND user_id = ?
    """,
        (id, user_id),
    ).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    # Monta o texto das alternativas (2 ou 5).
    alternativas = f"A) {questao['alternativa_a']}\nB) {questao['alternativa_b']}"
    if questao["alternativa_c"]:
        alternativas += f"\nC) {questao['alternativa_c']}\nD) {questao['alternativa_d']}"
        if questao["alternativa_e"]:
            alternativas += f"\nE) {questao['alternativa_e']}"

    conteudo = None
    fonte = "template"

    # 2. Tenta o LLM real (AI Tutor). Falha graciosa se não configurado.
    try:
        from routers.ai_tutor import call_llm_sync

        prompt = (
            "Você é um professor de concursos. Explique de forma didática e concisa "
            "(máx. ~180 palavras) por que a alternativa correta está certa e por que as "
            "demais são distratores. Use markdown leve.\n\n"
            f"Matéria: {questao['materia']}\n"
            f"Enunciado: {questao['enunciado']}\n"
            f"Alternativas:\n{alternativas}\n"
            f"Resposta correta: {questao['resposta_correta']}\n"
        )
        messages = [
            {"role": "system", "content": "Você explica questões de concurso com precisão e clareza."},
            {"role": "user", "content": prompt},
        ]
        texto, _tokens = call_llm_sync(messages, max_tokens=400)
        if texto and texto.strip():
            conteudo = texto.strip()
            fonte = "llm"
    except HTTPException:
        # IA não configurada (503) ou erro do provedor → cai no fallback.
        conteudo = None
    except Exception as e:  # noqa: BLE001 — nunca deixar a geração derrubar o endpoint
        log.warning(f"gerar_comentario_ia: LLM indisponível ({e}); usando fallback")
        conteudo = None

    # 2a/2b. Fallback gracioso.
    if not conteudo:
        if questao["explicacao"] and len(questao["explicacao"]) > 20:
            conteudo = questao["explicacao"]
            fonte = "explicacao"
        else:
            conteudo = (
                f"📝 **Resposta correta: {questao['resposta_correta']}**\n\n"
                f"**Matéria:** {questao['materia']}\n\n"
                f"**Análise:** Esta questão cobra conhecimento sobre {questao['materia']}. "
                f"A alternativa {questao['resposta_correta']} está correta porque atende ao que o enunciado pede. "
                f"As demais alternativas contêm distratores comuns nesse tema.\n\n"
                f"💡 **Dica:** Configure uma chave de IA nas configurações para explicações detalhadas por IA. "
                f"Revise este tópico no edital e faça mais questões semelhantes."
            )

    cur = conn.execute(
        """
        INSERT INTO comentarios_questoes (questao_id, user_id, conteudo, tipo, created_at)
        VALUES (?, ?, ?, 'ia', ?)
    """,
        (id, user_id, conteudo, datetime.now().isoformat()),
    )
    conn.commit()

    return {"id": cur.lastrowid, "conteudo": conteudo, "cached": False, "fonte": fonte}


@router.post("/api/questoes/{id}/comentarios/{comentario_id}/votar", summary="Votar em comentário (toggle)")
def votar_comentario(
    id: int,
    comentario_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Voto ÚNICO por usuário (toggle). Registrar/remover em comentario_votos e
    recalcular o total de votos a partir da contagem real — idempotente e sem
    inflar (o antigo `votos = votos + 1` permitia voto infinito)."""
    _ensure_comentarios_tables(conn)

    coment = conn.execute(
        "SELECT id FROM comentarios_questoes WHERE id = ? AND questao_id = ?", (comentario_id, id)
    ).fetchone()
    if not coment:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    ja_votou = conn.execute(
        "SELECT 1 FROM comentario_votos WHERE comentario_id = ? AND user_id = ?", (comentario_id, user_id)
    ).fetchone()

    if ja_votou:
        conn.execute(
            "DELETE FROM comentario_votos WHERE comentario_id = ? AND user_id = ?", (comentario_id, user_id)
        )
        voted = False
    else:
        from datetime import datetime

        conn.execute(
            "INSERT OR IGNORE INTO comentario_votos (comentario_id, user_id, created_at) VALUES (?, ?, ?)",
            (comentario_id, user_id, datetime.now().isoformat()),
        )
        voted = True

    # Recalcula o total real de votos (fonte da verdade = comentario_votos).
    total = conn.execute(
        "SELECT COUNT(*) FROM comentario_votos WHERE comentario_id = ?", (comentario_id,)
    ).fetchone()[0]
    conn.execute("UPDATE comentarios_questoes SET votos = ? WHERE id = ?", (total, comentario_id))
    conn.commit()
    return {"ok": True, "voted": voted, "votos": total}


@router.delete("/api/questoes/{id}/comentarios/{comentario_id}", summary="Remover o próprio comentário")
def deletar_comentario(
    id: int,
    comentario_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Remove um comentário do PRÓPRIO usuário (não permite apagar de outros).

    Comentários de IA (tipo='ia') podem ser removidos pelo dono da questão para
    permitir regeneração. Também limpa os votos associados.
    """
    _ensure_comentarios_tables(conn)

    coment = conn.execute(
        "SELECT id, user_id, tipo FROM comentarios_questoes WHERE id = ? AND questao_id = ?",
        (comentario_id, id),
    ).fetchone()
    if not coment:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    # Só o autor pode remover (comentário de IA fica atrelado ao user que gerou).
    if coment["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Você só pode remover seus próprios comentários.")

    conn.execute("DELETE FROM comentario_votos WHERE comentario_id = ?", (comentario_id,))
    conn.execute("DELETE FROM comentarios_questoes WHERE id = ? AND user_id = ?", (comentario_id, user_id))
    conn.commit()
    return {"ok": True}
