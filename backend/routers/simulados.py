import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

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
    """Monta simulado priorizando matérias com pior desempenho"""
    # Matérias ordenadas por % erro (pior primeiro)
    materias = conn.execute("""
        SELECT q.materia,
               CAST(SUM(CASE WHEN qr.acertou=0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) as pct_erro
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        ORDER BY pct_erro DESC
    """, (user_id,)).fetchall()

    questoes_ids = []
    if materias:
        # 60% das questões das matérias fracas, 40% aleatórias
        fracas = [r[0] for r in materias[:3]]
        qtd_fracas = int(qtd * 0.6)
        qtd_aleatorio = qtd - qtd_fracas

        for mat in fracas:
            rows = conn.execute("SELECT id FROM questoes WHERE materia = ? AND user_id = ? ORDER BY RANDOM() LIMIT ?",
                                (mat, user_id, qtd_fracas // len(fracas) + 1)).fetchall()
            questoes_ids.extend([r[0] for r in rows])

        rows_rand = conn.execute("SELECT id FROM questoes WHERE user_id = ? ORDER BY RANDOM() LIMIT ?", (user_id, qtd_aleatorio)).fetchall()
        questoes_ids.extend([r[0] for r in rows_rand])
    else:
        rows = conn.execute("SELECT id FROM questoes WHERE user_id = ? ORDER BY RANDOM() LIMIT ?", (user_id, qtd)).fetchall()
        questoes_ids = [r[0] for r in rows]

    # Deduplicate and limit
    questoes_ids = list(dict.fromkeys(questoes_ids))[:qtd]

    return {"questao_ids": questoes_ids, "total": len(questoes_ids), "estrategia": "60% matérias fracas + 40% aleatório"}


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

    # Construir query base
    base_query = "SELECT id, materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, dificuldade FROM questoes WHERE user_id = ?"
    base_params = [user_id]

    # Filtrar por matérias se especificadas
    if body.materias:
        placeholders = ",".join(["?" for _ in body.materias])
        base_query += f" AND materia IN ({placeholders})"
        base_params.extend(body.materias)

    # Buscar questões por dificuldade segundo o mix
    questoes_selecionadas = []
    mix = body.dificuldade_mix

    dificuldade_map = [
        ("Fácil", mix.facil),
        ("Médio", mix.medio),
        ("Difícil", mix.dificil),
    ]

    for dif_nome, qtd_alvo in dificuldade_map:
        if qtd_alvo <= 0:
            continue
        query = base_query + " AND dificuldade = ? ORDER BY RANDOM() LIMIT ?"
        params = base_params + [dif_nome, qtd_alvo]
        rows = conn.execute(query, params).fetchall()
        questoes_selecionadas.extend([dict(r) for r in rows])

    # Se não conseguiu o total, completar com qualquer dificuldade
    ids_selecionados = {q["id"] for q in questoes_selecionadas}
    faltando = body.questoes_total - len(questoes_selecionadas)
    if faltando > 0:
        excl_placeholders = ",".join(["?" for _ in ids_selecionados]) if ids_selecionados else "0"
        query_extra = base_query + f" AND id NOT IN ({excl_placeholders}) ORDER BY RANDOM() LIMIT ?"
        params_extra = base_params + list(ids_selecionados) + [faltando]
        rows_extra = conn.execute(query_extra, params_extra).fetchall()
        questoes_selecionadas.extend([dict(r) for r in rows_extra])

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
