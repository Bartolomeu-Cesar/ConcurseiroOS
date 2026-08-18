import random
from datetime import datetime

from fastapi import APIRouter, HTTPException

from database import get_db
from logger import log
from models import SimuladoCreate, SimuladoResponder, SimuladoFinalizar, SimuladoProvaReal
from utils import today_str

router = APIRouter(prefix="", tags=["Simulados"])


@router.get("/api/simulados")
def list_simulados():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM simulados ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/simulados/{id}")
def get_simulado(id: int):
    with get_db() as conn:
        sim = conn.execute("SELECT * FROM simulados WHERE id = ?", (id,)).fetchone()
        if not sim:
            raise HTTPException(404)
        questoes = conn.execute("""
            SELECT sq.*, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c,
                   q.alternativa_d, q.alternativa_e, q.resposta_correta, q.materia, q.explicacao
            FROM simulado_questoes sq
            JOIN questoes q ON q.id = sq.questao_id
            WHERE sq.simulado_id = ?
            ORDER BY sq.ordem
        """, (id,)).fetchall()
    return {"simulado": dict(sim), "questoes": [dict(q) for q in questoes]}


@router.post("/api/simulados")
def create_simulado(body: SimuladoCreate):
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO simulados (titulo, tempo_limite_min, total_questoes, created_at)
            VALUES (?, ?, ?, ?)
        """, (body.titulo, body.tempo_limite_min, len(body.questao_ids), today_str()))
        sim_id = cur.lastrowid
        for i, qid in enumerate(body.questao_ids):
            conn.execute("INSERT INTO simulado_questoes (simulado_id, questao_id, ordem) VALUES (?, ?, ?)",
                         (sim_id, qid, i))
        conn.commit()
    return {"id": sim_id, "ok": True}


@router.post("/api/simulados/{id}/responder")
def responder_simulado(id: int, body: SimuladoResponder):
    with get_db() as conn:
        questao = conn.execute("SELECT resposta_correta FROM questoes WHERE id = ?", (body.questao_id,)).fetchone()
        if not questao:
            raise HTTPException(404)
        acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
        conn.execute("""
            UPDATE simulado_questoes SET resposta_usuario = ?, acertou = ?
            WHERE simulado_id = ? AND questao_id = ?
        """, (body.resposta, acertou, id, body.questao_id))
        conn.commit()
    return {"acertou": bool(acertou), "resposta_correta": questao[0]}


@router.post("/api/simulados/{id}/finalizar")
def finalizar_simulado(id: int, body: SimuladoFinalizar):
    with get_db() as conn:
        results = conn.execute("""
            SELECT COUNT(*) as total, SUM(CASE WHEN acertou = 1 THEN 1 ELSE 0 END) as acertos
            FROM simulado_questoes WHERE simulado_id = ?
        """, (id,)).fetchone()
        total = results[0]
        acertos = results[1] or 0
        nota = round((acertos / total * 100) if total > 0 else 0, 1)
        conn.execute("""
            UPDATE simulados SET status = 'finalizado', nota = ?, acertos = ?,
                   tempo_gasto_seg = ?, finalizado_at = ?
            WHERE id = ?
        """, (nota, acertos, body.tempo_gasto_seg, datetime.now().isoformat(), id))
        conn.commit()
    return {"nota": nota, "acertos": acertos, "total": total}


@router.delete("/api/simulados/{id}")
def delete_simulado(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM simulado_questoes WHERE simulado_id = ?", (id,))
        conn.execute("DELETE FROM simulados WHERE id = ?", (id,))
        conn.commit()
    return {"ok": True}


@router.post("/api/simulados/prova-real")
def simulado_prova_real(body: SimuladoProvaReal):
    """Monta simulado baseado na distribuição real do edital (proporção de tópicos por matéria)"""
    log.info(f"POST /api/simulados/prova-real edital={body.edital_nome} cargo={body.cargo}")
    with get_db() as conn:
        # Buscar matérias do edital com contagem de tópicos
        query = "SELECT materia, COUNT(*) as topicos FROM edital WHERE 1=1"
        params = []
        if body.edital_nome:
            query += " AND edital_nome = ?"
            params.append(body.edital_nome)
        if body.cargo:
            query += " AND cargo = ?"
            params.append(body.cargo)
        query += " GROUP BY materia ORDER BY topicos DESC"
        materias = conn.execute(query, params).fetchall()

        if not materias:
            from fastapi import HTTPException
            raise HTTPException(400, "Nenhuma matéria encontrada no edital. Cadastre tópicos primeiro.")

        # Calcular total de tópicos (proxy para peso)
        total_topicos = sum(r[1] for r in materias)

        # Determinar total de questões (entre 60-120 dependendo do disponível)
        total_questoes_banco = conn.execute("SELECT COUNT(*) FROM questoes").fetchone()[0]
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
                "SELECT id FROM questoes WHERE materia = ? ORDER BY RANDOM() LIMIT ?",
                (mat, qtd_alvo)
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
            from fastapi import HTTPException
            raise HTTPException(400, "Nenhuma questão disponível no banco para as matérias do edital.")

        # Criar simulado
        cur = conn.execute("""
            INSERT INTO simulados (titulo, tempo_limite_min, total_questoes, created_at)
            VALUES (?, ?, ?, ?)
        """, (body.titulo, body.tempo_limite_min, len(questoes_selecionadas), today_str()))
        sim_id = cur.lastrowid

        # Vincular questões
        random.shuffle(questoes_selecionadas)
        for i, qid in enumerate(questoes_selecionadas):
            conn.execute("INSERT INTO simulado_questoes (simulado_id, questao_id, ordem) VALUES (?, ?, ?)",
                         (sim_id, qid, i))
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
def simulado_inteligente(qtd: int = 10):
    """Monta simulado priorizando matérias com pior desempenho"""
    with get_db() as conn:
        # Matérias ordenadas por % erro (pior primeiro)
        materias = conn.execute("""
            SELECT q.materia,
                   CAST(SUM(CASE WHEN qr.acertou=0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) as pct_erro
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            GROUP BY q.materia
            ORDER BY pct_erro DESC
        """).fetchall()

        questoes_ids = []
        if materias:
            # 60% das questões das matérias fracas, 40% aleatórias
            fracas = [r[0] for r in materias[:3]]
            qtd_fracas = int(qtd * 0.6)
            qtd_aleatorio = qtd - qtd_fracas

            for mat in fracas:
                rows = conn.execute("SELECT id FROM questoes WHERE materia = ? ORDER BY RANDOM() LIMIT ?",
                                    (mat, qtd_fracas // len(fracas) + 1)).fetchall()
                questoes_ids.extend([r[0] for r in rows])

            rows_rand = conn.execute("SELECT id FROM questoes ORDER BY RANDOM() LIMIT ?", (qtd_aleatorio,)).fetchall()
            questoes_ids.extend([r[0] for r in rows_rand])
        else:
            rows = conn.execute("SELECT id FROM questoes ORDER BY RANDOM() LIMIT ?", (qtd,)).fetchall()
            questoes_ids = [r[0] for r in rows]

    # Deduplicate and limit
    questoes_ids = list(dict.fromkeys(questoes_ids))[:qtd]

    return {"questao_ids": questoes_ids, "total": len(questoes_ids), "estrategia": "60% matérias fracas + 40% aleatório"}


@router.get("/api/simulado-adaptativo")
def simulado_adaptativo(materia: str = "", qtd: int = 10):
    """Monta simulado adaptativo baseado no nível do usuário"""
    with get_db() as conn:
        # Verificar nível por acertos recentes
        recentes = conn.execute("""
            SELECT qr.acertou, q.dificuldade FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            ORDER BY qr.id DESC LIMIT 20
        """).fetchall()

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

        query = "SELECT id FROM questoes WHERE 1=1"
        params = []
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
