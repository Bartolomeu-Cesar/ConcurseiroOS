import random
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import (
    SimuladoCreate,
    SimuladoCronometradoCreate,
    SimuladoCronometradoFinalizar,
    SimuladoFinalizar,
    SimuladoProvaReal,
    SimuladoResponder,
)
from utils import today_str, update_streak

router = APIRouter(prefix="", tags=["Simulados"])


# ============================================================
# SELEÇÃO INTELIGENTE DE QUESTÕES (reutilizável)
# ============================================================

def _smart_select_questions(
    conn, user_id: int, qtd: int,
    materias: list[str] | None = None,
    dificuldade: str | None = None,
) -> list[dict]:
    """Seleciona questões aplicando 6 técnicas de estudo com evidência científica.

    Estratégia de priorização (baseada em pesquisa):
    1. Questões ERRADAS recentemente (Successive Relearning — Rawson & Dunlosky 2011)
    2. Questões NUNCA respondidas (Pre-testing Effect — Richland et al. 2009)
    3. Questões erradas há mais tempo (Spacing Effect — Cepeda et al. 2006)
    4. Questões acertadas com baixa confiança (Desirable Difficulty — Bjork 1994)
    5. Questões com poucos acertos (< 3 consecutivos)

    Filtra OUT:
    - Questões DOMINADAS (3+ acertos consecutivos) — evita overlearning

    Aplica:
    - Interleaving: mistura matérias na sequência final (Rohrer 2012)
    - Desirable Difficulty: prioriza questões no limiar de domínio

    Args:
        conn: DB connection
        user_id: user ID
        qtd: quantidade de questões desejada
        materias: lista de matérias para filtrar (None = todas)
        dificuldade: filtrar por dificuldade (None = todas)

    Returns:
        Lista de dicts com dados das questões selecionadas
    """
    # === Identificar questões DOMINADAS (excluir) ===
    # Dominada = 3+ acertos consecutivos mais recentes
    dominadas_ids = set()
    try:
        all_questions = conn.execute(
            "SELECT DISTINCT questao_id FROM questoes_respostas WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        for row in all_questions:
            qid = row[0]
            ultimas = conn.execute("""
                SELECT acertou FROM questoes_respostas
                WHERE questao_id = ? AND user_id = ?
                ORDER BY id DESC LIMIT 3
            """, (qid, user_id)).fetchall()
            if len(ultimas) >= 3 and all(r[0] == 1 for r in ultimas):
                dominadas_ids.add(qid)
    except Exception:
        pass

    # === Build base query com filtros ===
    base_where = "WHERE q.user_id = ?"
    base_params = [user_id]

    if materias:
        placeholders = ",".join("?" * len(materias))
        base_where += f" AND q.materia IN ({placeholders})"
        base_params.extend(materias)

    if dificuldade:
        base_where += " AND q.dificuldade = ?"
        base_params.append(dificuldade)

    # Excluir dominadas
    if dominadas_ids:
        excl = ",".join(str(i) for i in dominadas_ids)
        base_where += f" AND q.id NOT IN ({excl})"

    # === POOL 1: Questões ERRADAS recentemente (últimos 14 dias) ===
    erradas_recentes = conn.execute(f"""
        SELECT DISTINCT q.id FROM questoes q
        JOIN questoes_respostas qr ON qr.questao_id = q.id AND qr.user_id = q.user_id
        {base_where}
        AND qr.acertou = 0
        AND qr.data >= date('now', '-14 days')
        ORDER BY qr.data DESC
    """, base_params).fetchall()
    pool_erradas_recentes = [r[0] for r in erradas_recentes]

    # === POOL 2: Questões NUNCA respondidas ===
    nunca_respondidas = conn.execute(f"""
        SELECT q.id FROM questoes q
        {base_where}
        AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)
        ORDER BY RANDOM()
    """, base_params + [user_id]).fetchall()
    pool_nunca = [r[0] for r in nunca_respondidas]

    # === POOL 3: Questões erradas há mais tempo (spacing > 14 dias) ===
    erradas_antigas = conn.execute(f"""
        SELECT DISTINCT q.id FROM questoes q
        JOIN questoes_respostas qr ON qr.questao_id = q.id AND qr.user_id = q.user_id
        {base_where}
        AND qr.acertou = 0
        AND qr.data < date('now', '-14 days')
        ORDER BY RANDOM()
    """, base_params).fetchall()
    pool_erradas_antigas = [r[0] for r in erradas_antigas]

    # === POOL 4: Questões com poucos acertos (1-2 acertos, não dominadas) ===
    fracas = conn.execute(f"""
        SELECT q.id FROM questoes q
        {base_where}
        AND q.id IN (
            SELECT questao_id FROM questoes_respostas WHERE user_id = ?
            GROUP BY questao_id
            HAVING SUM(acertou) BETWEEN 1 AND 2
        )
        ORDER BY RANDOM()
    """, base_params + [user_id]).fetchall()
    pool_fracas = [r[0] for r in fracas]

    # === Montar seleção com prioridade ===
    # Distribuição: 30% erradas recentes, 30% nunca vistas, 20% erradas antigas, 20% fracas
    selected_ids = []
    seen = set()

    def _add_from_pool(pool, max_count):
        added = 0
        for qid in pool:
            if qid not in seen and added < max_count:
                selected_ids.append(qid)
                seen.add(qid)
                added += 1
        return added

    qtd_erradas_rec = max(1, int(qtd * 0.30))
    qtd_nunca = max(1, int(qtd * 0.30))
    qtd_erradas_ant = max(1, int(qtd * 0.20))
    qtd_fracas = max(1, int(qtd * 0.20))

    _add_from_pool(pool_erradas_recentes, qtd_erradas_rec)
    _add_from_pool(pool_nunca, qtd_nunca)
    _add_from_pool(pool_erradas_antigas, qtd_erradas_ant)
    _add_from_pool(pool_fracas, qtd_fracas)

    # Completar com restantes se não atingiu o total
    faltando = qtd - len(selected_ids)
    if faltando > 0:
        # Pegar de qualquer pool disponível (prioridade: nunca > erradas > fracas)
        for pool in [pool_nunca, pool_erradas_recentes, pool_erradas_antigas, pool_fracas]:
            _add_from_pool(pool, faltando)
            faltando = qtd - len(selected_ids)
            if faltando <= 0:
                break

    # Se AINDA falta (banco pequeno), pegar aleatórias (exceto dominadas)
    if len(selected_ids) < qtd:
        faltando = qtd - len(selected_ids)
        excl_ids = ",".join(str(i) for i in (seen | dominadas_ids)) if (seen | dominadas_ids) else "0"
        extras = conn.execute(f"""
            SELECT q.id FROM questoes q
            {base_where}
            AND q.id NOT IN ({excl_ids})
            ORDER BY RANDOM() LIMIT ?
        """, base_params + [faltando]).fetchall()
        for r in extras:
            if r[0] not in seen:
                selected_ids.append(r[0])
                seen.add(r[0])

    # === Aplicar INTERLEAVING na sequência final ===
    # Buscar dados das questões selecionadas
    if not selected_ids:
        return []

    placeholders = ",".join("?" * len(selected_ids))
    questoes = conn.execute(f"""
        SELECT id, materia, enunciado, alternativa_a, alternativa_b,
               alternativa_c, alternativa_d, alternativa_e, resposta_correta,
               dificuldade, explicacao
        FROM questoes WHERE id IN ({placeholders}) AND user_id = ?
    """, selected_ids + [user_id]).fetchall()
    questoes_map = {r["id"]: dict(r) for r in questoes}

    # Interleaving: ordenar alternando matérias (evita blocked practice)
    resultado = [questoes_map[qid] for qid in selected_ids if qid in questoes_map]

    # Agrupar por matéria e intercalar
    by_materia = {}
    for q in resultado:
        mat = q.get("materia", "Sem matéria")
        if mat not in by_materia:
            by_materia[mat] = []
        by_materia[mat].append(q)

    interleaved = []
    mat_lists = list(by_materia.values())
    while mat_lists:
        # Round-robin: pega 1 de cada matéria
        empty = []
        for i, mlist in enumerate(mat_lists):
            if mlist:
                interleaved.append(mlist.pop(0))
            else:
                empty.append(i)
        for idx in sorted(empty, reverse=True):
            mat_lists.pop(idx)

    return interleaved[:qtd]


@router.get("/api/simulados")
def list_simulados(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM simulados WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/simulados/{id}")
def get_simulado(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    sim = conn.execute("SELECT * FROM simulados WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not sim:
        raise HTTPException(status_code=404, detail="Simulado não encontrado")
    questoes = conn.execute("""
        SELECT sq.*, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c,
               q.alternativa_d, q.alternativa_e, q.resposta_correta, q.materia, q.explicacao
        FROM simulado_questoes sq
        JOIN questoes q ON q.id = sq.questao_id
        WHERE sq.simulado_id = ? AND sq.user_id = ?
        ORDER BY sq.ordem
    """, (id, user_id)).fetchall()
    return {"simulado": dict(sim), "questoes": [dict(q) for q in questoes]}


@router.post("/api/simulados")
def create_simulado(body: SimuladoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from plans import enforce_plan_limit
    enforce_plan_limit(conn, user_id, "simulados")

    cur = conn.execute("""
        INSERT INTO simulados (titulo, tempo_limite_min, total_questoes, created_at, user_id)
        VALUES (?, ?, ?, ?, ?)
    """, (body.titulo, body.tempo_limite_min, len(body.questao_ids), today_str(), user_id))
    sim_id = cur.lastrowid
    for i, qid in enumerate(body.questao_ids):
        conn.execute("INSERT INTO simulado_questoes (simulado_id, questao_id, ordem, user_id) VALUES (?, ?, ?, ?)",
                     (sim_id, qid, i, user_id))
    conn.commit()
    return {"id": sim_id, "ok": True}


@router.post("/api/simulados/{id}/responder")
def responder_simulado(id: int, body: SimuladoResponder, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    questao = conn.execute("SELECT resposta_correta FROM questoes WHERE id = ? AND user_id = ?", (body.questao_id, user_id)).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
    conn.execute("""
        UPDATE simulado_questoes SET resposta_usuario = ?, acertou = ?
        WHERE simulado_id = ? AND questao_id = ? AND user_id = ?
    """, (body.resposta, acertou, id, body.questao_id, user_id))
    conn.commit()
    return {"acertou": bool(acertou), "resposta_correta": questao[0]}


@router.post("/api/simulados/{id}/finalizar")
def finalizar_simulado(id: int, body: SimuladoFinalizar, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    results = conn.execute("""
        SELECT COUNT(*) as total, SUM(CASE WHEN acertou = 1 THEN 1 ELSE 0 END) as acertos
        FROM simulado_questoes WHERE simulado_id = ? AND user_id = ?
    """, (id, user_id)).fetchone()
    total = results[0]
    acertos = results[1] or 0
    nota = round((acertos / total * 100) if total > 0 else 0, 1)
    conn.execute("""
        UPDATE simulados SET status = 'finalizado', nota = ?, acertos = ?,
               tempo_gasto_seg = ?, finalizado_at = ?
        WHERE id = ? AND user_id = ?
    """, (nota, acertos, body.tempo_gasto_seg, datetime.now().isoformat(), id, user_id))

    # Registrar tempo do simulado como sessão de estudo
    if body.tempo_gasto_seg > 0:
        horas = body.tempo_gasto_seg / 3600
        # Identificar matérias do simulado para registrar por matéria
        materias_sim = conn.execute("""
            SELECT DISTINCT q.materia FROM simulado_questoes sq
            JOIN questoes q ON q.id = sq.questao_id
            WHERE sq.simulado_id = ? AND sq.user_id = ?
        """, (id, user_id)).fetchall()
        if materias_sim:
            horas_por_mat = horas / len(materias_sim)
            for row in materias_sim:
                mat = row[0] or "Simulado"
                existing = conn.execute(
                    "SELECT id FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'simulado' AND user_id = ?",
                    (today_str(), mat, user_id)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                        (horas_por_mat, existing[0], user_id)
                    )
                else:
                    conn.execute(
                        "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'simulado', ?)",
                        (mat, horas_por_mat, today_str(), user_id)
                    )
        else:
            # Fallback: registrar genérico
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'simulado', ?)",
                ("Simulado", horas, today_str(), user_id)
            )
        # Atualizar streak de horas do dia (meta diária)
        update_streak(conn, "horas_estudadas", horas, user_id=user_id)

    conn.commit()
    log.info(f"Simulado {id} finalizado: nota={nota}% ({acertos}/{total}) tempo={body.tempo_gasto_seg}s")
    return {"nota": nota, "acertos": acertos, "total": total}


@router.delete("/api/simulados/{id}")
def delete_simulado(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM simulado_questoes WHERE simulado_id = ? AND user_id = ?", (id, user_id))
    conn.execute("DELETE FROM simulados WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


@router.post("/api/simulados/prova-real")
def simulado_prova_real(body: SimuladoProvaReal, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Monta simulado baseado na distribuição real do edital (proporção de tópicos por matéria)"""
    from plans import enforce_plan_limit
    enforce_plan_limit(conn, user_id, "simulados")

    log.info(f"POST /api/simulados/prova-real edital={body.edital_nome} cargo={body.cargo}")
    # Buscar matérias do edital com contagem de tópicos
    query = "SELECT materia, COUNT(*) as topicos FROM edital WHERE user_id = ?"
    params = [user_id]
    if body.edital_nome:
        query += " AND edital_nome = ?"
        params.append(body.edital_nome)
    if body.cargo:
        query += " AND cargo = ?"
        params.append(body.cargo)
    query += " GROUP BY materia ORDER BY topicos DESC"
    materias = conn.execute(query, params).fetchall()

    if not materias:
        raise HTTPException(status_code=400, detail="Nenhuma matéria encontrada no edital. Cadastre tópicos primeiro.")

    # Calcular total de tópicos (proxy para peso)
    total_topicos = sum(r[1] for r in materias)

    # Determinar total de questões (entre 60-120 dependendo do disponível)
    total_questoes_banco = conn.execute("SELECT COUNT(*) FROM questoes WHERE user_id = ?", (user_id,)).fetchone()[0]
    total_desejado = min(120, max(60, total_questoes_banco))

    # Calcular distribuição proporcional
    distribuicao = []
    questoes_selecionadas = []
    for r in materias:
        mat = r[0]
        peso = r[1] / total_topicos
        qtd_alvo = max(1, round(total_desejado * peso))

        # Buscar questões disponíveis dessa matéria
        rows = conn.execute(
            "SELECT id FROM questoes WHERE materia = ? AND user_id = ? ORDER BY RANDOM() LIMIT ?",
            (mat, user_id, qtd_alvo)
        ).fetchall()

        ids = [row[0] for row in rows]
        questoes_selecionadas.extend(ids)
        distribuicao.append({
            "materia": mat,
            "topicos": r[1],
            "peso_pct": round(peso * 100, 1),
            "questoes_alvo": qtd_alvo,
            "questoes_selecionadas": len(ids)
        })

    # Deduplicate
    questoes_selecionadas = list(dict.fromkeys(questoes_selecionadas))

    if not questoes_selecionadas:
        raise HTTPException(status_code=400, detail="Nenhuma questão disponível no banco para as matérias do edital.")

    # Criar simulado
    cur = conn.execute("""
        INSERT INTO simulados (titulo, tempo_limite_min, total_questoes, created_at, user_id)
        VALUES (?, ?, ?, ?, ?)
    """, (body.titulo, body.tempo_limite_min, len(questoes_selecionadas), today_str(), user_id))
    sim_id = cur.lastrowid

    # Vincular questões
    random.shuffle(questoes_selecionadas)
    for i, qid in enumerate(questoes_selecionadas):
        conn.execute("INSERT INTO simulado_questoes (simulado_id, questao_id, ordem, user_id) VALUES (?, ?, ?, ?)",
                     (sim_id, qid, i, user_id))
    conn.commit()

    log.info(f"Simulado prova-real criado: id={sim_id} questoes={len(questoes_selecionadas)}")
    return {
        "id": sim_id,
        "ok": True,
        "titulo": body.titulo,
        "total_questoes": len(questoes_selecionadas),
        "tempo_limite_min": body.tempo_limite_min,
        "distribuicao": distribuicao
    }


@router.get("/api/simulado-inteligente")
def simulado_inteligente(qtd: int = 10, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Monta simulado priorizando questões erradas, nunca vistas e matérias fracas.

    Aplica 6 técnicas de estudo:
    - Successive Relearning: prioriza erradas recentes
    - Pre-testing: inclui questões nunca respondidas
    - Spacing Effect: revisita erradas antigas
    - Desirable Difficulty: foca no limiar de domínio
    - Interleaving: mistura matérias na sequência
    - Filtra dominadas: exclui 3+ acertos consecutivos
    """
    questoes = _smart_select_questions(conn, user_id, qtd)

    if not questoes:
        # Fallback: aleatório se não tem histórico
        rows = conn.execute("SELECT id FROM questoes WHERE user_id = ? ORDER BY RANDOM() LIMIT ?", (user_id, qtd)).fetchall()
        return {"questao_ids": [r[0] for r in rows], "total": len(rows), "estrategia": "aleatório (sem histórico)"}

    ids = [q["id"] for q in questoes]
    return {
        "questao_ids": ids,
        "total": len(ids),
        "estrategia": "smart: erradas recentes 30% + nunca vistas 30% + spacing 20% + fracas 20% (dominadas excluídas, interleaving aplicado)"
    }


@router.get("/api/simulado-adaptativo")
def simulado_adaptativo(materia: str = "", qtd: int = 10, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Monta simulado adaptativo baseado no nível do usuário"""
    # Verificar nível por acertos recentes
    recentes = conn.execute("""
        SELECT qr.acertou, q.dificuldade FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        ORDER BY qr.id DESC LIMIT 20
    """, (user_id,)).fetchall()

    # Calcular taxa de acerto recente
    if recentes:
        taxa = sum(1 for r in recentes if r[0]) / len(recentes)
    else:
        taxa = 0.5

    # Definir dificuldade alvo
    if taxa >= 0.8:
        dificuldades = ['Difícil', 'Médio', 'Difícil']
    elif taxa >= 0.5:
        dificuldades = ['Médio', 'Difícil', 'Fácil']
    else:
        dificuldades = ['Fácil', 'Médio', 'Fácil']

    query = "SELECT id FROM questoes WHERE user_id = ?"
    params = [user_id]
    if materia:
        query += " AND materia = ?"
        params.append(materia)

    # Buscar questoes por dificuldade
    ids = []
    for dif in dificuldades:
        rows = conn.execute(query + " AND dificuldade = ? ORDER BY RANDOM() LIMIT ?",
                            params + [dif, qtd // len(dificuldades) + 1]).fetchall()
        ids.extend([r[0] for r in rows])

    # Completar com aleatórias se não tiver suficiente
    if len(ids) < qtd:
        extras = conn.execute(query + " ORDER BY RANDOM() LIMIT ?", params + [qtd]).fetchall()
        ids.extend([r[0] for r in extras])

    ids = list(dict.fromkeys(ids))[:qtd]
    return {"questao_ids": ids, "total": len(ids), "nivel_detectado": round(taxa * 100),
            "dificuldade_alvo": dificuldades[0]}


# ============================================================
# SIMULADO CRONOMETRADO REALISTA
# ============================================================


@router.post("/api/simulados/cronometrado")
def criar_simulado_cronometrado(
    body: SimuladoCronometradoCreate,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Cria simulado cronometrado realista com seleção automática de questões por dificuldade/matéria."""
    log.info(f"POST /api/simulados/cronometrado titulo={body.titulo} tempo={body.tempo_total_min}min questoes={body.questoes_total}")

    # Selecionar questões com inteligência (por dificuldade)
    questoes_selecionadas = []
    mix = body.dificuldade_mix
    materias_filtro = body.materias if body.materias else None

    dificuldade_map = [
        ("Fácil", mix.facil),
        ("Médio", mix.medio),
        ("Difícil", mix.dificil),
    ]

    for dif_nome, qtd_alvo in dificuldade_map:
        if qtd_alvo <= 0:
            continue
        # Usar seleção inteligente por dificuldade
        smart_qs = _smart_select_questions(conn, user_id, qtd_alvo, materias=materias_filtro, dificuldade=dif_nome)
        questoes_selecionadas.extend(smart_qs)

    # Se não conseguiu o total, completar com seleção inteligente sem filtro de dificuldade
    faltando = body.questoes_total - len(questoes_selecionadas)
    if faltando > 0:
        ids_ja = {q["id"] for q in questoes_selecionadas}
        extras = _smart_select_questions(conn, user_id, faltando, materias=materias_filtro)
        for q in extras:
            if q["id"] not in ids_ja:
                questoes_selecionadas.append(q)
                ids_ja.add(q["id"])

    if not questoes_selecionadas:
        raise HTTPException(status_code=400, detail="Nenhuma questão disponível no banco para os critérios selecionados.")

    # Embaralhar
    random.shuffle(questoes_selecionadas)

    # Limitar ao total solicitado
    questoes_selecionadas = questoes_selecionadas[: body.questoes_total]

    # Criar registro do simulado
    cur = conn.execute("""
        INSERT INTO simulados (titulo, tempo_limite_min, total_questoes, created_at, user_id, tipo)
        VALUES (?, ?, ?, ?, ?, 'cronometrado')
    """, (body.titulo, body.tempo_total_min, len(questoes_selecionadas), datetime.now().isoformat(), user_id))
    sim_id = cur.lastrowid

    # Vincular questões
    questoes_response = []
    for i, q in enumerate(questoes_selecionadas):
        conn.execute(
            "INSERT INTO simulado_questoes (simulado_id, questao_id, ordem, user_id) VALUES (?, ?, ?, ?)",
            (sim_id, q["id"], i, user_id),
        )
        alternativas = [
            {"letra": "A", "texto": q["alternativa_a"]},
            {"letra": "B", "texto": q["alternativa_b"]},
            {"letra": "C", "texto": q["alternativa_c"]},
            {"letra": "D", "texto": q["alternativa_d"]},
        ]
        if q.get("alternativa_e"):
            alternativas.append({"letra": "E", "texto": q["alternativa_e"]})

        questoes_response.append({
            "id": q["id"],
            "num": i + 1,
            "materia": q["materia"],
            "enunciado": q["enunciado"],
            "alternativas": alternativas,
        })

    conn.commit()
    log.info(f"Simulado cronometrado criado: id={sim_id} questoes={len(questoes_selecionadas)}")

    return {
        "id": sim_id,
        "titulo": body.titulo,
        "tempo_total_min": body.tempo_total_min,
        "total_questoes": len(questoes_selecionadas),
        "questoes": questoes_response,
    }


@router.post("/api/simulados/cronometrado/{id}/finalizar")
def finalizar_simulado_cronometrado(
    id: int,
    body: SimuladoCronometradoFinalizar,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Finaliza simulado cronometrado com cálculo de TRI, nota por matéria e comparação com nota de corte."""
    log.info(f"POST /api/simulados/cronometrado/{id}/finalizar respostas={len(body.respostas)} tempo={body.tempo_total_seg}s")

    # Verificar que o simulado existe
    sim = conn.execute("SELECT * FROM simulados WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not sim:
        raise HTTPException(status_code=404, detail="Simulado não encontrado")

    # Processar cada resposta
    total_acertos = 0
    total_erros = 0
    total_em_branco = 0
    por_materia = {}  # materia -> {acertos, total}
    tempos = []

    for resp in body.respostas:
        # Buscar questão para verificar resposta correta
        questao = conn.execute(
            "SELECT resposta_correta, materia FROM questoes WHERE id = ? AND user_id = ?",
            (resp.questao_id, user_id),
        ).fetchone()
        if not questao:
            continue

        correta = questao[0].upper() if questao[0] else ""
        materia = questao[1] or "Sem matéria"
        respondeu = resp.resposta.strip().upper() if resp.resposta else ""

        # Inicializar matéria
        if materia not in por_materia:
            por_materia[materia] = {"acertos": 0, "total": 0}
        por_materia[materia]["total"] += 1

        if not respondeu:
            total_em_branco += 1
        elif respondeu == correta:
            total_acertos += 1
            por_materia[materia]["acertos"] += 1
        else:
            total_erros += 1

        # Registrar resposta no banco
        acertou = 1 if respondeu == correta else 0
        conn.execute("""
            UPDATE simulado_questoes SET resposta_usuario = ?, acertou = ?
            WHERE simulado_id = ? AND questao_id = ? AND user_id = ?
        """, (respondeu if respondeu else None, acertou if respondeu else None, id, resp.questao_id, user_id))

        if resp.tempo_seg > 0:
            tempos.append(resp.tempo_seg)

    total_respondidas = total_acertos + total_erros
    total_questoes = total_acertos + total_erros + total_em_branco

    # Nota bruta (percentual de acertos sobre total)
    nota_bruta = round((total_acertos / total_questoes * 100) if total_questoes > 0 else 0, 2)

    # TRI estimada simples: pontuação com penalidade de -0.25 por erro
    pontos_tri = total_acertos - (total_erros * 0.25)
    nota_tri = round(max(0, (pontos_tri / total_questoes * 100)) if total_questoes > 0 else 0, 2)

    # Tempo médio por questão
    tempo_medio = round(sum(tempos) / len(tempos), 1) if tempos else (
        round(body.tempo_total_seg / total_respondidas, 1) if total_respondidas > 0 else 0
    )

    # Comparar com nota de corte histórica (buscar na tabela se existir)
    aprovado_estimado = None
    nota_corte = None
    try:
        corte_row = conn.execute(
            "SELECT nota_corte FROM notas_corte WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if corte_row:
            nota_corte = corte_row[0]
            aprovado_estimado = nota_bruta >= nota_corte
    except Exception:
        # Tabela pode não existir
        pass

    # Atualizar simulado
    conn.execute("""
        UPDATE simulados SET status = 'finalizado', nota = ?, acertos = ?,
               tempo_gasto_seg = ?, finalizado_at = ?
        WHERE id = ? AND user_id = ?
    """, (nota_bruta, total_acertos, body.tempo_total_seg, datetime.now().isoformat(), id, user_id))

    # Registrar tempo como sessão de estudo
    if body.tempo_total_seg > 0:
        horas = body.tempo_total_seg / 3600
        materias_list = list(por_materia.keys())
        if materias_list:
            horas_por_mat = horas / len(materias_list)
            for mat in materias_list:
                existing = conn.execute(
                    "SELECT id FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'simulado' AND user_id = ?",
                    (today_str(), mat, user_id),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                        (horas_por_mat, existing[0], user_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'simulado', ?)",
                        (mat, horas_por_mat, today_str(), user_id),
                    )
        else:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'simulado', ?)",
                ("Simulado", horas, today_str(), user_id),
            )
        update_streak(conn, "horas_estudadas", horas, user_id=user_id)

    conn.commit()

    # Montar resposta por matéria
    por_materia_list = [
        {"materia": mat, "acertos": dados["acertos"], "total": dados["total"]}
        for mat, dados in sorted(por_materia.items())
    ]

    result = {
        "nota_bruta": nota_bruta,
        "nota_tri": nota_tri,
        "total_acertos": total_acertos,
        "total_erros": total_erros,
        "total_em_branco": total_em_branco,
        "total_questoes": total_questoes,
        "por_materia": por_materia_list,
        "tempo_medio_por_questao": tempo_medio,
        "tempo_total_seg": body.tempo_total_seg,
        "aprovado_estimado": aprovado_estimado,
        "nota_corte": nota_corte,
    }

    log.info(f"Simulado cronometrado {id} finalizado: bruta={nota_bruta}% tri={nota_tri}% ({total_acertos}/{total_questoes})")
    return result


@router.get("/api/simulados/cronometrado/{id}")
def get_simulado_cronometrado(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna detalhes do simulado cronometrado com questões e resultados."""
    sim = conn.execute("SELECT * FROM simulados WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not sim:
        raise HTTPException(status_code=404, detail="Simulado não encontrado")

    sim_dict = dict(sim)

    questoes = conn.execute("""
        SELECT sq.*, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c,
               q.alternativa_d, q.alternativa_e, q.resposta_correta, q.materia, q.explicacao, q.dificuldade
        FROM simulado_questoes sq
        JOIN questoes q ON q.id = sq.questao_id
        WHERE sq.simulado_id = ? AND sq.user_id = ?
        ORDER BY sq.ordem
    """, (id, user_id)).fetchall()

    questoes_list = []
    for q in questoes:
        qd = dict(q)
        alternativas = [
            {"letra": "A", "texto": qd["alternativa_a"]},
            {"letra": "B", "texto": qd["alternativa_b"]},
            {"letra": "C", "texto": qd["alternativa_c"]},
            {"letra": "D", "texto": qd["alternativa_d"]},
        ]
        if qd.get("alternativa_e"):
            alternativas.append({"letra": "E", "texto": qd["alternativa_e"]})

        questoes_list.append({
            "id": qd["questao_id"],
            "num": qd["ordem"] + 1,
            "materia": qd["materia"],
            "enunciado": qd["enunciado"],
            "alternativas": alternativas,
            "resposta_usuario": qd.get("resposta_usuario"),
            "acertou": qd.get("acertou"),
            "resposta_correta": qd["resposta_correta"],
            "explicacao": qd.get("explicacao", ""),
            "dificuldade": qd.get("dificuldade", ""),
        })

    return {
        "simulado": sim_dict,
        "questoes": questoes_list,
    }


# ============================================================
# SIMULADO PERIÓDICO AUTOMÁTICO (#5)
# ============================================================


@router.get("/api/simulado/pendente", summary="Verificar se há simulado periódico pendente",
            description="Retorna se já passou 2 semanas desde o último simulado e sugere realizar um novo.")
def simulado_pendente(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Verifica se está na hora de fazer um simulado (a cada 14 dias)."""

    INTERVALO_DIAS = 14  # A cada 2 semanas

    # Último simulado finalizado
    ultimo = conn.execute("""
        SELECT finalizado_at, nota, acertos, total_questoes
        FROM simulados WHERE user_id = ? AND status = 'finalizado'
        ORDER BY finalizado_at DESC LIMIT 1
    """, (user_id,)).fetchone()

    hoje = date.today()

    if ultimo and ultimo["finalizado_at"]:
        try:
            ultima_data = date.fromisoformat(ultimo["finalizado_at"][:10])
            dias_desde = (hoje - ultima_data).days
        except (ValueError, TypeError):
            dias_desde = 999
    else:
        dias_desde = 999  # Nunca fez simulado

    pendente = dias_desde >= INTERVALO_DIAS
    proximo_em = max(0, INTERVALO_DIAS - dias_desde)

    return {
        "pendente": pendente,
        "dias_desde_ultimo": dias_desde,
        "proximo_em_dias": proximo_em,
        "intervalo_dias": INTERVALO_DIAS,
        "ultimo_simulado": {
            "nota": ultimo["nota"] if ultimo else None,
            "acertos": ultimo["acertos"] if ultimo else None,
            "total": ultimo["total_questoes"] if ultimo else None,
            "data": ultimo["finalizado_at"][:10] if ultimo and ultimo["finalizado_at"] else None,
        },
        "mensagem": "📝 Hora do simulado! Faça um para calibrar seu progresso." if pendente
                    else f"✅ Próximo simulado em {proximo_em} dias.",
    }


@router.post("/api/simulado/auto-gerar", summary="Gerar simulado automático proporcional ao edital",
             description="Gera simulado com distribuição de questões proporcional ao peso de cada matéria no edital. Tempo real de prova.")
def auto_gerar_simulado(
    total_questoes: int = Body(40, embed=True),
    tempo_limite_min: int = Body(120, embed=True),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Gera simulado automático com proporção do edital.

    Lógica:
    1. Calcula peso de cada matéria (tópicos no edital do ciclo ativo)
    2. Distribui questões proporcionalmente
    3. Mínimo 2 questões por matéria presente
    4. Mistura dificuldades: 30% fácil, 50% médio, 20% difícil
    5. Tempo proporcional à prova real
    """
    import json

    # Matérias do ciclo ativo com peso pelo edital
    ciclo_materias = conn.execute(
        "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
    ).fetchall()
    if not ciclo_materias:
        raise HTTPException(status_code=400, detail="Adicione matérias ao ciclo primeiro.")

    ciclo_mats = [m["materia"] for m in ciclo_materias]

    # Calcular peso por matéria (tópicos no edital)
    pesos = {}
    for mat in ciclo_mats:
        count = conn.execute(
            "SELECT COUNT(*) FROM edital WHERE materia = ? AND user_id = ? AND arquivado = 0",
            (mat, user_id)
        ).fetchone()[0]
        pesos[mat] = count
    total_topicos = sum(pesos.values()) or 1

    # Distribuir questões proporcionalmente (mínimo 2 por matéria)
    distribuicao = {}
    questoes_alocadas = 0
    for mat in ciclo_mats:
        proporcao = pesos[mat] / total_topicos
        qtd = max(2, round(total_questoes * proporcao))
        distribuicao[mat] = qtd
        questoes_alocadas += qtd

    # Ajustar para não exceder total
    while questoes_alocadas > total_questoes:
        # Reduzir da matéria com mais questões
        mat_max = max(distribuicao, key=distribuicao.get)
        if distribuicao[mat_max] > 2:
            distribuicao[mat_max] -= 1
            questoes_alocadas -= 1

    # Buscar questões por matéria com mix de dificuldade
    questao_ids = []
    distribuicao_real = {}

    for mat, qtd_alvo in distribuicao.items():
        # Buscar com prioridade: 30% fácil, 50% médio, 20% difícil
        faceis = int(qtd_alvo * 0.3)
        medias = int(qtd_alvo * 0.5)
        dificeis = qtd_alvo - faceis - medias

        ids_mat = []

        # Fáceis
        rows = conn.execute("""
            SELECT id FROM questoes WHERE materia = ? AND user_id = ?
            AND dificuldade = 'Fácil' AND resposta_correta IS NOT NULL AND resposta_correta != ''
            ORDER BY RANDOM() LIMIT ?
        """, (mat, user_id, faceis)).fetchall()
        ids_mat.extend([r["id"] for r in rows])

        # Médias
        rows = conn.execute("""
            SELECT id FROM questoes WHERE materia = ? AND user_id = ?
            AND (dificuldade = 'Médio' OR dificuldade IS NULL OR dificuldade = '')
            AND resposta_correta IS NOT NULL AND resposta_correta != ''
            AND id NOT IN ({})
            ORDER BY RANDOM() LIMIT ?
        """.format(','.join(str(i) for i in ids_mat) or '0'), (mat, user_id, medias)).fetchall()
        ids_mat.extend([r["id"] for r in rows])

        # Difíceis
        rows = conn.execute("""
            SELECT id FROM questoes WHERE materia = ? AND user_id = ?
            AND dificuldade = 'Difícil'
            AND resposta_correta IS NOT NULL AND resposta_correta != ''
            AND id NOT IN ({})
            ORDER BY RANDOM() LIMIT ?
        """.format(','.join(str(i) for i in ids_mat) or '0'), (mat, user_id, dificeis)).fetchall()
        ids_mat.extend([r["id"] for r in rows])

        # Completar se não atingiu o alvo (com qualquer dificuldade)
        if len(ids_mat) < qtd_alvo:
            falta = qtd_alvo - len(ids_mat)
            rows = conn.execute("""
                SELECT id FROM questoes WHERE materia = ? AND user_id = ?
                AND resposta_correta IS NOT NULL AND resposta_correta != ''
                AND id NOT IN ({})
                ORDER BY RANDOM() LIMIT ?
            """.format(','.join(str(i) for i in ids_mat) or '0'), (mat, user_id, falta)).fetchall()
            ids_mat.extend([r["id"] for r in rows])

        questao_ids.extend(ids_mat)
        distribuicao_real[mat] = len(ids_mat)

    if not questao_ids:
        raise HTTPException(status_code=400, detail="Sem questões suficientes. Adicione mais questões ao banco.")

    # Embaralhar ordem (simula prova real)
    import random
    random.shuffle(questao_ids)

    # Criar o simulado
    hoje = date.today()
    titulo = f"Simulado Automático — {hoje.strftime('%d/%m/%Y')} ({len(questao_ids)}q)"
    cur = conn.execute("""
        INSERT INTO simulados (titulo, tempo_limite_min, total_questoes, status, created_at, user_id, tipo)
        VALUES (?, ?, ?, 'pendente', ?, ?, 'automatico')
    """, (titulo, tempo_limite_min, len(questao_ids), datetime.now().isoformat(), user_id))
    sim_id = cur.lastrowid

    for i, qid in enumerate(questao_ids):
        conn.execute(
            "INSERT INTO simulado_questoes (simulado_id, questao_id, ordem, user_id) VALUES (?, ?, ?, ?)",
            (sim_id, qid, i, user_id)
        )
    conn.commit()

    log.info(f"Simulado automático gerado: id={sim_id}, {len(questao_ids)} questões, {tempo_limite_min}min")

    return {
        "id": sim_id,
        "titulo": titulo,
        "total_questoes": len(questao_ids),
        "tempo_limite_min": tempo_limite_min,
        "distribuicao": [
            {"materia": mat, "questoes": qtd, "peso_pct": round(pesos.get(mat, 0) / total_topicos * 100, 1)}
            for mat, qtd in distribuicao_real.items() if qtd > 0
        ],
        "mensagem": f"Simulado gerado com {len(questao_ids)} questões distribuídas por {len(distribuicao_real)} matérias. Tempo: {tempo_limite_min}min.",
    }
