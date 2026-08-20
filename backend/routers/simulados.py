import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log
from models import SimuladoCreate, SimuladoFinalizar, SimuladoProvaReal, SimuladoResponder
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
