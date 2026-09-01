"""Router de Desafios Semanais + Desafio Diário."""
import json
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import DesafioCreate
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
    """Seleciona questões para o desafio diário com seleção inteligente.

    Usa _smart_select_questions (6 técnicas de estudo):
    - Successive Relearning: erradas recentes primeiro
    - Pre-testing: inclui nunca respondidas
    - Spacing Effect: revisita erradas antigas
    - Desirable Difficulty: questões no limiar de domínio
    - Interleaving: mistura matérias
    - Exclui dominadas: 3+ acertos consecutivos

    Também prioriza questões da tabela erros_revisao com proxima_revisao <= hoje.

    IMPORTANTE: Filtra apenas por matérias do ciclo ativo (regra #2 do projeto).
    """
    from routers.simulados import _smart_select_questions

    # 0. Buscar matérias do ciclo ativo (regra: nunca mostrar matérias de concursos inativos)
    materias_ativas = None
    try:
        rows_ciclo = conn.execute(
            "SELECT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?",
            (user_id,)
        ).fetchall()
        if rows_ciclo:
            materias_ativas = [r[0] for r in rows_ciclo]
    except Exception:
        # Fallback: tabela pode não ter coluna user_id em schemas antigos
        try:
            rows_ciclo = conn.execute(
                "SELECT materia FROM ciclo_estudos WHERE ativo = 1"
            ).fetchall()
            if rows_ciclo:
                materias_ativas = [r[0] for r in rows_ciclo]
        except Exception:
            pass  # Sem ciclo = sem filtro (usa todas as matérias)

    # 1. Verificar se há questões agendadas para revisão (erros_revisao com FSRS)
    hoje = today_str()
    revisao_pendentes = []
    try:
        # Filtrar revisão também por matérias ativas
        if materias_ativas:
            placeholders_mat = ",".join("?" * len(materias_ativas))
            rows = conn.execute(f"""
                SELECT er.questao_id FROM erros_revisao er
                JOIN questoes q ON q.id = er.questao_id AND q.user_id = er.user_id
                WHERE er.user_id = ? AND er.proxima_revisao <= ?
                AND q.materia IN ({placeholders_mat})
                ORDER BY er.proxima_revisao ASC
                LIMIT ?
            """, [user_id, hoje] + materias_ativas + [max(2, quantidade // 2)]).fetchall()
        else:
            rows = conn.execute("""
                SELECT er.questao_id FROM erros_revisao er
                WHERE er.user_id = ? AND er.proxima_revisao <= ?
                ORDER BY er.proxima_revisao ASC
                LIMIT ?
            """, (user_id, hoje, max(2, quantidade // 2))).fetchall()
        revisao_ids = [r[0] for r in rows]
        if revisao_ids:
            placeholders = ",".join("?" * len(revisao_ids))
            qs = conn.execute(f"""
                SELECT * FROM questoes WHERE id IN ({placeholders}) AND user_id = ?
            """, revisao_ids + [user_id]).fetchall()
            revisao_pendentes = [dict(q) for q in qs]
    except Exception:
        pass  # tabela erros_revisao pode não existir

    # 2. Completar com seleção inteligente (filtrada por matérias ativas).
    #    Pede `quantidade` (não só o restante) para ter folga de deduplicação —
    #    o smart pode devolver questões que já estão na revisão FSRS.
    qtd_restante = quantidade - len(revisao_pendentes)
    smart_qs = []
    if qtd_restante > 0:
        smart_qs = _smart_select_questions(conn, user_id, quantidade, materias=materias_ativas)

    # 3. Combinar: revisão agendada + smart selection (sem duplicatas)
    seen_ids = {q["id"] for q in revisao_pendentes}
    combined = list(revisao_pendentes)
    for q in smart_qs:
        if len(combined) >= quantidade:
            break
        if q["id"] not in seen_ids:
            combined.append(q)
            seen_ids.add(q["id"])

    # 4. Recompletar: se ainda faltam questões (deduplicação reduziu o total),
    #    pega quaisquer não-dominadas ainda não incluídas — priorizando nunca
    #    respondidas (Pre-testing). Garante o total sempre que houver questões
    #    suficientes no banco (dentro do ciclo ativo).
    if len(combined) < quantidade:
        faltam = quantidade - len(combined)
        excl = seen_ids or {0}
        placeholders = ",".join("?" * len(excl))
        params = [user_id]
        mat_clause = ""
        if materias_ativas:
            mat_ph = ",".join("?" * len(materias_ativas))
            mat_clause = f" AND q.materia IN ({mat_ph})"
            params += list(materias_ativas)
        params += list(excl)
        try:
            rows = conn.execute(f"""
                SELECT * FROM questoes q
                WHERE q.user_id = ?{mat_clause}
                AND q.id NOT IN ({placeholders})
                ORDER BY (q.id IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)) ASC,
                         RANDOM()
                LIMIT ?
            """, params + [user_id, faltam]).fetchall()
            for r in rows:
                q = dict(r)
                if q["id"] not in seen_ids:
                    combined.append(q)
                    seen_ids.add(q["id"])
        except Exception:
            pass

    return combined[:quantidade]


def calcular_tempo_questao(enunciado: str, num_alternativas: int) -> int:
    """Calcula tempo em segundos baseado na complexidade da questão.

    Fundamentação científica:
    - Velocidade média de leitura: ~200 palavras/min (Brysbaert, 2019)
    - Tempo de processamento por alternativa: ~3s (Kyllonen & Zu, 2016)
    - Tempo de decisão: +5s (margem para deliberação)
    - Faixa: 20s-90s (desirable difficulty sem ser punitivo)

    Para questões C/E (2 alternativas): tempo tende a ser menor.
    Para questões longas com 5 alternativas: tempo maior.
    """
    palavras = len(enunciado.split()) if enunciado else 10
    tempo_leitura = (palavras / 200) * 60  # segundos para ler o enunciado
    tempo_alternativas = num_alternativas * 3  # 3s por alternativa
    tempo_decisao = 5  # margem de deliberação
    tempo = int(tempo_leitura + tempo_alternativas + tempo_decisao)
    return max(20, min(90, tempo))  # clamp entre 20s e 90s


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
                q_dict = dict(q)
                alternativas = []
                for letra in ['a', 'b', 'c', 'd', 'e']:
                    alt = q_dict.get(f"alternativa_{letra}", "")
                    if alt:
                        alternativas.append({"letra": letra.upper(), "texto": alt})
                questoes.append({
                    "id": q_dict["id"],
                    "materia": q_dict["materia"],
                    "enunciado": q_dict["enunciado"],
                    "alternativas": alternativas,
                    "dificuldade": q_dict.get("dificuldade", "Médio"),
                    "tempo_segundos": calcular_tempo_questao(q_dict["enunciado"], len(alternativas)),
                })
        return {
            "id": existing["id"],
            "questoes": questoes,
            "total": len(questoes),
            "completado": bool(existing["completado"]),
            "pontos_possiveis": len(questoes) * 20 + 30,  # 20/questão + bônus (streak até +20, +10 perfeito)
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
            "tempo_segundos": calcular_tempo_questao(q["enunciado"], len(alternativas)),
        })

    log.info(f"Desafio Diário gerado: id={desafio_id} user={user_id} questoes={len(questoes_fmt)}")

    return {
        "id": desafio_id,
        "questoes": questoes_fmt,
        "total": len(questoes_fmt),
        "completado": False,
        "pontos_possiveis": len(questoes_fmt) * 20 + 30,  # 20/questão + bônus (streak até +20, +10 perfeito)
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
    tempo_total_seg = 0

    for resp in body.respostas:
        questao_id = resp.get("questao_id")
        resposta = resp.get("resposta", "")
        tempo_individual = resp.get("tempo_segundos", 30)  # fallback 30s se não enviado

        if not questao_id:
            continue

        # Buscar questão
        questao = conn.execute(
            "SELECT id, resposta_correta, materia, enunciado FROM questoes WHERE id = ? AND user_id = ?",
            (questao_id, user_id)
        ).fetchone()

        if not questao:
            resultados.append({"questao_id": questao_id, "acertou": False, "correta": "?"})
            total += 1
            tempo_total_seg += tempo_individual
            continue

        acertou = 1 if resposta.upper() == questao["resposta_correta"].upper() else 0
        if acertou:
            acertos += 1
        total += 1
        tempo_total_seg += tempo_individual

        # Registrar em questoes_respostas
        conn.execute("""
            INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (questao_id, resposta, acertou, tempo_individual, hoje, user_id))

        resultados.append({
            "questao_id": questao_id,
            "acertou": bool(acertou),
            "correta": questao["resposta_correta"],
        })

    # Calcular streak bonus
    streak_atual = 0
    try:
        streak_row = conn.execute(
            "SELECT streak_atual FROM streaks WHERE user_id = ?", (user_id,)
        ).fetchone()
        streak_atual = streak_row["streak_atual"] if streak_row else 0
    except Exception:
        # streak_atual column may not exist in older schemas; fall back to utils
        try:
            from utils import get_streak_info
            streak_info = get_streak_info(conn, user_id=user_id)
            streak_atual = streak_info.get("streak_atual", 0)
        except Exception:
            streak_atual = 0

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

    # Registrar sessão de estudo (tempo real baseado na complexidade das questões)
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
