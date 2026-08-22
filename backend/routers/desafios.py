"""Router de Desafios Semanais + Desafio Diário."""
import json
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db_session
from deps import get_user_id
from logger import log
from models import DesafioCreate
from utils import today_str, update_streak

router = APIRouter(prefix="", tags=["Desafios"])


# ============================================================
# Desafios Semanais (existente)
# ============================================================


@router.get("/api/desafios")
def list_desafios(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM desafios WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/desafios")
def create_desafio(body: DesafioCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO desafios (titulo, meta_tipo, meta_valor, materia, dias, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.titulo, body.meta_tipo, body.meta_valor, body.materia, body.dias, datetime.now().isoformat(), user_id)
    )
    conn.commit()
    log.info(f"Desafio created: {body.titulo}")
    return {"id": cur.lastrowid, "ok": True}


@router.put("/api/desafios/{id}/progresso")
def update_desafio_progresso(id: int, valor: int = 1, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("UPDATE desafios SET progresso = progresso + ? WHERE id = ? AND user_id = ?", (valor, id, user_id))
    # Verificar se completou
    desafio = conn.execute("SELECT * FROM desafios WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if desafio and desafio["progresso"] >= desafio["meta_valor"]:
        conn.execute("UPDATE desafios SET finalizado = 1 WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True, "progresso": desafio["progresso"] if desafio else 0}


@router.delete("/api/desafios/{id}")
def delete_desafio(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM desafios WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


# ============================================================
# Desafio Diário (novo)
# ============================================================


def _ensure_desafio_diario_table(conn):
    """Cria a tabela desafio_diario se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS desafio_diario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            data TEXT NOT NULL,
            questao_ids TEXT NOT NULL DEFAULT '[]',
            completado INTEGER NOT NULL DEFAULT 0,
            pontos INTEGER NOT NULL DEFAULT 0,
            acertos INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_desafio_diario_user_data
        ON desafio_diario(user_id, data)
    """)
    conn.commit()


def _select_challenge_questions(conn, user_id: int, quantidade: int = 5) -> list[dict]:
    """Seleciona questões para o desafio diário baseado em fraquezas e revisão.

    Estratégia:
    - 2 questões: tópicos com maior taxa de erro (pontos fracos)
    - 2 questões: matérias que não foram estudadas recentemente (FSRS/revisão)
    - 1 questão: aleatória (variedade)
    """
    selected_ids = set()
    questions = []

    # 1. Questões de tópicos fracos (maior taxa de erro)
    weak_topics = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(CASE WHEN qr.acertou = 0 THEN 1 ELSE 0 END) as erros
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        HAVING total >= 3
        ORDER BY CAST(erros AS FLOAT) / total DESC
        LIMIT 5
    """, (user_id,)).fetchall()

    weak_materias = [r["materia"] for r in weak_topics]

    for materia in weak_materias:
        if len(questions) >= 2:
            break
        # Pegar questão não respondida dessa matéria, ou respondida errada
        q = conn.execute("""
            SELECT q.* FROM questoes q
            WHERE q.user_id = ? AND q.materia = ?
            AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ? AND acertou = 1)
            ORDER BY RANDOM()
            LIMIT 1
        """, (user_id, materia, user_id)).fetchone()
        if q and q["id"] not in selected_ids:
            questions.append(dict(q))
            selected_ids.add(q["id"])

    # 2. Questões de matérias não estudadas recentemente (revisão)
    neglected = conn.execute("""
        SELECT materia, MAX(data) as ultima
        FROM sessoes_estudo
        WHERE user_id = ?
        GROUP BY materia
        ORDER BY ultima ASC
        LIMIT 5
    """, (user_id,)).fetchall()

    neglected_materias = [r["materia"] for r in neglected if r["materia"]]

    for materia in neglected_materias:
        if len(questions) >= 4:
            break
        q = conn.execute("""
            SELECT q.* FROM questoes q
            WHERE q.user_id = ? AND q.materia = ?
            AND q.id NOT IN (?)
            ORDER BY RANDOM()
            LIMIT 1
        """.replace("NOT IN (?)", f"NOT IN ({','.join(str(i) for i in selected_ids) or '0'})"),
            (user_id, materia)).fetchone()
        if q and q["id"] not in selected_ids:
            questions.append(dict(q))
            selected_ids.add(q["id"])

    # 3. Preencher restante com questões aleatórias
    remaining = quantidade - len(questions)
    if remaining > 0:
        exclude_clause = f"AND q.id NOT IN ({','.join(str(i) for i in selected_ids)})" if selected_ids else ""
        random_qs = conn.execute(f"""
            SELECT q.* FROM questoes q
            WHERE q.user_id = ? {exclude_clause}
            ORDER BY RANDOM()
            LIMIT ?
        """, (user_id, remaining)).fetchall()
        for q in random_qs:
            questions.append(dict(q))
            selected_ids.add(q["id"])

    return questions[:quantidade]


class DesafioDiarioResposta(BaseModel):
    respostas: list[dict]  # [{questao_id: int, resposta: str}]


@router.get("/api/desafio-diario", summary="Retorna o desafio diário (5 questões)")
def get_desafio_diario(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna o desafio diário. Se já gerado hoje, retorna o mesmo set."""
    _ensure_desafio_diario_table(conn)

    hoje = today_str()

    # Verificar se já existe desafio para hoje
    existing = conn.execute(
        "SELECT * FROM desafio_diario WHERE user_id = ? AND data = ?",
        (user_id, hoje)
    ).fetchone()

    if existing:
        # Retornar desafio existente
        questao_ids = json.loads(existing["questao_ids"])
        questoes = []
        for qid in questao_ids:
            q = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (qid, user_id)).fetchone()
            if q:
                alternativas = []
                for letra in ['a', 'b', 'c', 'd', 'e']:
                    alt = q[f"alternativa_{letra}"]
                    if alt:
                        alternativas.append({"letra": letra.upper(), "texto": alt})
                questoes.append({
                    "id": q["id"],
                    "materia": q["materia"],
                    "enunciado": q["enunciado"],
                    "alternativas": alternativas,
                    "dificuldade": q.get("dificuldade", "Médio"),
                })
        return {
            "id": existing["id"],
            "questoes": questoes,
            "completado": bool(existing["completado"]),
            "pontos_possiveis": 100 + 20,  # 5*20 base + streak bonus potencial
            "acertos": existing["acertos"],
            "pontos": existing["pontos"],
        }

    # Gerar novo desafio
    questions = _select_challenge_questions(conn, user_id, 5)

    if not questions:
        return {
            "id": None,
            "questoes": [],
            "completado": False,
            "pontos_possiveis": 0,
            "message": "Sem questões disponíveis. Adicione questões ao banco primeiro."
        }

    questao_ids = [q["id"] for q in questions]

    cur = conn.execute(
        """INSERT INTO desafio_diario (user_id, data, questao_ids, completado, pontos, acertos, total, created_at)
           VALUES (?, ?, ?, 0, 0, 0, ?, ?)""",
        (user_id, hoje, json.dumps(questao_ids), len(questao_ids), datetime.now().isoformat())
    )
    conn.commit()
    desafio_id = cur.lastrowid

    # Formatar questões para resposta
    questoes_fmt = []
    for q in questions:
        alternativas = []
        for letra in ['a', 'b', 'c', 'd', 'e']:
            alt = q.get(f"alternativa_{letra}", "")
            if alt:
                alternativas.append({"letra": letra.upper(), "texto": alt})
        questoes_fmt.append({
            "id": q["id"],
            "materia": q["materia"],
            "enunciado": q["enunciado"],
            "alternativas": alternativas,
            "dificuldade": q.get("dificuldade", "Médio"),
        })

    log.info(f"Desafio Diário gerado: id={desafio_id} user={user_id} questoes={len(questoes_fmt)}")

    return {
        "id": desafio_id,
        "questoes": questoes_fmt,
        "completado": False,
        "pontos_possiveis": 100 + 20,
        "acertos": 0,
        "pontos": 0,
    }


@router.post("/api/desafio-diario/responder", summary="Submeter respostas do desafio diário")
def responder_desafio_diario(body: DesafioDiarioResposta, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Submete todas as respostas do desafio diário de uma vez.

    Calcula XP: 20pts por acerto + streak bonus.
    Registra em questoes_respostas e sessoes_estudo.
    """
    _ensure_desafio_diario_table(conn)

    hoje = today_str()

    # Buscar desafio de hoje
    desafio = conn.execute(
        "SELECT * FROM desafio_diario WHERE user_id = ? AND data = ?",
        (user_id, hoje)
    ).fetchone()

    if not desafio:
        raise HTTPException(status_code=404, detail="Nenhum desafio diário encontrado para hoje. Gere um primeiro.")

    if desafio["completado"]:
        raise HTTPException(status_code=400, detail="Desafio diário já foi completado hoje.")

    # Processar respostas
    acertos = 0
    total = 0
    resultados = []

    for resp in body.respostas:
        questao_id = resp.get("questao_id")
        resposta = resp.get("resposta", "")

        if not questao_id:
            continue

        # Buscar questão
        questao = conn.execute(
            "SELECT id, resposta_correta, materia FROM questoes WHERE id = ? AND user_id = ?",
            (questao_id, user_id)
        ).fetchone()

        if not questao:
            resultados.append({"questao_id": questao_id, "acertou": False, "correta": "?"})
            total += 1
            continue

        acertou = 1 if resposta.upper() == questao["resposta_correta"].upper() else 0
        if acertou:
            acertos += 1
        total += 1

        # Registrar em questoes_respostas
        conn.execute("""
            INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (questao_id, resposta, acertou, 15, hoje, user_id))

        resultados.append({
            "questao_id": questao_id,
            "acertou": bool(acertou),
            "correta": questao["resposta_correta"],
        })

    # Calcular streak bonus
    streak_row = conn.execute(
        "SELECT streak_atual FROM streaks WHERE user_id = ?", (user_id,)
    ).fetchone()
    streak_atual = streak_row["streak_atual"] if streak_row else 0

    # Calcular pontos
    pontos_base = acertos * 20  # 20pts por acerto
    streak_bonus = min(streak_atual * 2, 20)  # até +20pts de bonus por streak
    # Bonus por perfeito
    if acertos == total and total > 0:
        streak_bonus += 10  # Bonus de 10 pts extra por 5/5

    pontos_ganhos = pontos_base + streak_bonus

    # Atualizar desafio como completado
    conn.execute("""
        UPDATE desafio_diario
        SET completado = 1, pontos = ?, acertos = ?
        WHERE id = ? AND user_id = ?
    """, (pontos_ganhos, acertos, desafio["id"], user_id))

    # Atualizar streak de questões resolvidas
    for _ in range(total):
        update_streak(conn, "questoes_resolvidas", user_id=user_id)

    # Registrar sessão de estudo (tempo = total * 15seg por questão)
    tempo_total_seg = total * 15
    horas = tempo_total_seg / 3600
    existing_sessao = conn.execute(
        "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'desafio_diario' AND user_id = ?",
        (hoje, "Desafio Diário", user_id)
    ).fetchone()
    if existing_sessao:
        conn.execute(
            "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
            (horas, existing_sessao["id"], user_id)
        )
    else:
        conn.execute(
            "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, 'desafio_diario', ?, ?)",
            ("Desafio Diário", horas, hoje, user_id, datetime.now().isoformat())
        )

    conn.commit()

    log.info(f"Desafio Diário respondido: user={user_id} acertos={acertos}/{total} pontos={pontos_ganhos}")

    return {
        "acertos": acertos,
        "total": total,
        "pontos_ganhos": pontos_ganhos,
        "streak_bonus": streak_bonus,
        "resultados": resultados,
    }
