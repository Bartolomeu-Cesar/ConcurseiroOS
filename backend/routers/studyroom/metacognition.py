"""Endpoints metacognitivos: intention, reflection, elaboration prompts, goal suggestion, session summary."""
import random
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log

from .tables import ensure_intention_tables, ensure_reflection_tables, ensure_studyroom_tables, run_studyroom_migrations

router = APIRouter(prefix="/api/studyroom", tags=["Study Room"])


# ============================================================
# ELABORATIVE INTERROGATION PROMPTS
# ============================================================

ELABORATION_PROMPTS = [
    {"prompt": "Por que esse conceito funciona dessa forma?", "tipo": "causal", "ciclo_sugerido": "foco"},
    {"prompt": "Como isso se conecta com o que você já sabe?", "tipo": "conexão", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual seria um exemplo prático disso?", "tipo": "aplicação", "ciclo_sugerido": "foco"},
    {"prompt": "Se tivesse que explicar para alguém, como faria?", "tipo": "ensino", "ciclo_sugerido": "pausa"},
    {"prompt": "O que aconteceria se o contrário fosse verdade?", "tipo": "contra-factual", "ciclo_sugerido": "foco"},
    {"prompt": "Quais são as exceções ou limitações desse conceito?", "tipo": "crítica", "ciclo_sugerido": "foco"},
    {"prompt": "Como esse tema aparece em provas anteriores?", "tipo": "aplicação", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual a diferença entre esse conceito e outros semelhantes?", "tipo": "comparação", "ciclo_sugerido": "foco"},
    {"prompt": "Que analogia você usaria para explicar isso?", "tipo": "analogia", "ciclo_sugerido": "pausa"},
    {"prompt": "Quais são as consequências práticas de não entender isso?", "tipo": "consequência", "ciclo_sugerido": "foco"},
    {"prompt": "Como você resumiria isso em uma frase?", "tipo": "síntese", "ciclo_sugerido": "pausa"},
    {"prompt": "Que pergunta você faria a um professor sobre isso?", "tipo": "curiosidade", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual a relação entre esse conceito e a questão que errei antes?", "tipo": "conexão", "ciclo_sugerido": "foco"},
    {"prompt": "Se fosse cair na prova, como seria a questão?", "tipo": "simulação", "ciclo_sugerido": "foco"},
    {"prompt": "O que eu ainda não entendi completamente sobre isso?", "tipo": "metacognição", "ciclo_sugerido": "pausa"},
    {"prompt": "Como eu poderia desenhar ou esquematizar esse conceito?", "tipo": "visual", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual a origem histórica ou lógica desse princípio?", "tipo": "fundamento", "ciclo_sugerido": "foco"},
    {"prompt": "Quais palavras-chave são essenciais para lembrar?", "tipo": "memorização", "ciclo_sugerido": "foco"},
    {"prompt": "Como esse assunto se relaciona com casos reais ou jurisprudência?", "tipo": "aplicação", "ciclo_sugerido": "foco"},
    {"prompt": "Se eu esquecesse tudo amanhã, qual seria o ponto central a reter?", "tipo": "essência", "ciclo_sugerido": "pausa"},
]


@router.get("/elaboration-prompt")
def get_elaboration_prompt(
    user_id: int = Depends(get_user_id),
):
    """Retorna uma pergunta metacognitiva aleatória para interrogação elaborativa."""
    prompt = random.choice(ELABORATION_PROMPTS)
    return prompt


# ============================================================
# SESSION INTENTION
# ============================================================


@router.post("/intention/{codigo}")
def criar_intention(
    codigo: str,
    intencao: str = Body(..., embed=True),
    como_vou_estudar: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Salva intenção de início de sessão."""
    ensure_intention_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    if not intencao or not intencao.strip():
        raise HTTPException(status_code=400, detail="Intenção não pode ser vazia")
    if not como_vou_estudar or not como_vou_estudar.strip():
        raise HTTPException(status_code=400, detail="'Como vou estudar' não pode ser vazio")

    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_intentions (room_id, user_id, intencao, como_vou_estudar, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (room["id"], user_id, intencao.strip(), como_vou_estudar.strip(), now))
    conn.commit()

    log.info(f"Intention saved by user {user_id} in room {codigo}")
    return {"ok": True, "intencao": intencao.strip(), "como_vou_estudar": como_vou_estudar.strip()}


# ============================================================
# SESSION REFLECTION
# ============================================================


@router.post("/reflection/{codigo}")
def criar_reflection(
    codigo: str,
    o_que_aprendi: str = Body(..., embed=True),
    o_que_foi_dificil: str = Body(..., embed=True),
    proximo_passo: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Salva reflexão de fim de sessão."""
    ensure_reflection_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    if not o_que_aprendi or not o_que_aprendi.strip():
        raise HTTPException(status_code=400, detail="'O que aprendi' não pode ser vazio")
    if not o_que_foi_dificil or not o_que_foi_dificil.strip():
        raise HTTPException(status_code=400, detail="'O que foi difícil' não pode ser vazio")
    if not proximo_passo or not proximo_passo.strip():
        raise HTTPException(status_code=400, detail="'Próximo passo' não pode ser vazio")

    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_reflections (room_id, user_id, o_que_aprendi, o_que_foi_dificil, proximo_passo, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (room["id"], user_id, o_que_aprendi.strip(), o_que_foi_dificil.strip(), proximo_passo.strip(), now))
    conn.commit()

    log.info(f"Reflection saved by user {user_id} in room {codigo}")
    return {
        "ok": True,
        "o_que_aprendi": o_que_aprendi.strip(),
        "o_que_foi_dificil": o_que_foi_dificil.strip(),
        "proximo_passo": proximo_passo.strip(),
    }


@router.get("/reflections")
def listar_reflections(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna as últimas 10 reflexões do usuário."""
    ensure_reflection_tables(conn)

    rows = conn.execute("""
        SELECT r.id, r.o_que_aprendi, r.o_que_foi_dificil, r.proximo_passo, r.created_at,
               s.codigo, s.titulo
        FROM study_room_reflections r
        JOIN study_rooms s ON s.id = r.room_id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
        LIMIT 10
    """, (user_id,)).fetchall()

    return {
        "reflections": [
            {
                "id": r["id"],
                "o_que_aprendi": r["o_que_aprendi"],
                "o_que_foi_dificil": r["o_que_foi_dificil"],
                "proximo_passo": r["proximo_passo"],
                "sala_codigo": r["codigo"],
                "sala_titulo": r["titulo"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


# ============================================================
# GOAL SUGGESTION: Meta SMART vinculada ao edital + ROI
# ============================================================


@router.get("/goal-suggestion")
def get_goal_suggestion(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Sugere uma meta SMART para a sessão baseada no ROI das matérias do edital.

    Analisa: peso da banca × gap de acertos / horas investidas
    Retorna: matéria sugerida + quantidade específica + justificativa.
    """
    from utils import today_str

    hoje = today_str()

    # 1. Buscar matérias do edital ativo
    materias_edital = conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE user_id = ? AND arquivado = 0",
        (user_id,)
    ).fetchall()
    materias_edital = [r[0] for r in materias_edital]

    # 2. Calcular ROI por matéria
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes WHERE user_id = ?", (user_id,)).fetchone()[0] or 1

    resultados = []
    for materia in materias_edital:
        # Peso na banca (% de questões)
        qtd_mat = conn.execute(
            "SELECT COUNT(*) FROM questoes WHERE materia = ? AND user_id = ?",
            (materia, user_id)
        ).fetchone()[0]
        peso = round(qtd_mat / total_questoes * 100, 1) if total_questoes > 0 else 0

        # Acertos
        acertos = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
            WHERE q.materia = ? AND qr.user_id = ?
        """, (materia, user_id)).fetchone()
        pct_acerto = round((acertos["acertos"] / acertos["total"]) * 100, 1) if acertos["total"] > 0 else 0
        gap = 100 - pct_acerto

        # Horas investidas
        horas = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ? AND user_id = ?",
            (materia, user_id)
        ).fetchone()[0]

        # Pendentes hoje (flashcards + súmulas)
        fc_pendentes = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE materia = ? AND proxima_revisao <= ? AND user_id = ?",
            (materia, hoje, user_id)
        ).fetchone()[0]
        sm_pendentes = conn.execute(
            "SELECT COUNT(*) FROM sumulas WHERE tema = ? AND proxima_revisao <= ? AND user_id = ?",
            (materia, hoje, user_id)
        ).fetchone()[0]

        roi = round((peso * gap) / (horas + 1), 2)

        resultados.append({
            "materia": materia,
            "peso_banca": peso,
            "pct_acerto": pct_acerto,
            "gap": gap,
            "horas_investidas": round(horas, 1),
            "roi": roi,
            "pendentes_flashcards": fc_pendentes,
            "pendentes_sumulas": sm_pendentes,
        })

    if not resultados:
        return {
            "sugestao": None,
            "motivo": "Nenhuma matéria no edital. Cadastre seu edital primeiro.",
        }

    # Ordenar por ROI descendente
    resultados.sort(key=lambda x: x["roi"], reverse=True)
    top = resultados[0]

    # Gerar meta SMART
    atividades = []
    if top["pendentes_flashcards"] > 0:
        fc_qty = min(top["pendentes_flashcards"], 15)
        atividades.append(f"Revisar {fc_qty} flashcards de {top['materia']}")
    if top["pendentes_sumulas"] > 0:
        sm_qty = min(top["pendentes_sumulas"], 10)
        atividades.append(f"Revisar {sm_qty} súmulas de {top['materia']}")
    if top["gap"] > 30:
        atividades.append(f"Resolver 10 questões de {top['materia']}")

    if not atividades:
        atividades.append(f"Estudar {top['materia']} por 25 minutos (1 Pomodoro)")

    meta_texto = atividades[0]  # Principal sugestão

    return {
        "sugestao": {
            "meta": meta_texto,
            "materia": top["materia"],
            "roi": top["roi"],
            "peso_banca": top["peso_banca"],
            "gap": top["gap"],
            "atividades_sugeridas": atividades,
        },
        "alternativas": [
            {"meta": a, "materia": top["materia"]}
            for a in atividades[1:]
        ],
        "top_materias_roi": resultados[:3],
        "motivo": f"{top['materia']} tem maior ROI: peso {top['peso_banca']}% na banca com {top['gap']}% de gap",
    }


# ============================================================
# SESSION SUMMARY: Métricas pós-sessão
# ============================================================


@router.get("/session-summary/{codigo}")
def get_session_summary(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna resumo completo da sessão de estudo ao sair da sala.

    Métricas: tempo focado, ciclos completados, cards revisados,
    comparação com meta, XP ganho, sugestões para próxima sessão.
    """
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)
    from utils import today_str

    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    participant = conn.execute(
        "SELECT * FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=404, detail="Participante não encontrado")

    # Calcular tempo focado (inclui tempo desde último checkin se ainda focando)
    tempo_total = participant["tempo_estudado_seg"] or 0
    if participant["status"] == "focando" and participant["ultimo_checkin"]:
        try:
            last = datetime.fromisoformat(participant["ultimo_checkin"])
            tempo_total += int((datetime.now() - last).total_seconds())
        except (ValueError, TypeError):
            pass

    # Calcular ciclos completados
    ciclo_foco = (room.get("ciclo_foco_min") or 25) * 60
    ciclo_pausa = (room.get("ciclo_pausa_min") or 5) * 60
    ciclo_completo = ciclo_foco + ciclo_pausa
    ciclos_completados = tempo_total // ciclo_completo if ciclo_completo > 0 else 0

    # Buscar cards revisados hoje
    hoje = today_str()
    flashcards_revisados = conn.execute(
        "SELECT COALESCE(flashcards_revisados, 0) FROM streaks WHERE data = ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()
    flashcards_revisados = flashcards_revisados[0] if flashcards_revisados else 0

    sumulas_revisadas = conn.execute(
        "SELECT COALESCE(sumulas_revisadas, 0) FROM streaks WHERE data = ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()
    sumulas_revisadas = sumulas_revisadas[0] if sumulas_revisadas else 0

    questoes_resolvidas = conn.execute(
        "SELECT COALESCE(questoes_resolvidas, 0) FROM streaks WHERE data = ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()
    questoes_resolvidas = questoes_resolvidas[0] if questoes_resolvidas else 0

    # Meta da sessão
    meta = participant["meta"] if participant.get("meta") else ""
    meta_cumprida = bool(meta and tempo_total > 0)  # Simplificado; ideally check specific goal

    # XP estimado
    horas = tempo_total / 3600.0
    xp_ganho = int(20 * horas)

    # Ranking na sala
    all_participants = conn.execute(
        "SELECT user_id, nome, tempo_estudado_seg FROM study_room_participants WHERE room_id = ? ORDER BY tempo_estudado_seg DESC",
        (room["id"],)
    ).fetchall()
    ranking_pos = 1
    for i, p in enumerate(all_participants):
        if p["user_id"] == user_id:
            ranking_pos = i + 1
            break

    # Sugestões para próxima sessão
    sugestoes = []
    if tempo_total < 25 * 60:
        sugestoes.append("💡 Tente completar ao menos 1 ciclo Pomodoro (25min) na próxima vez")
    if flashcards_revisados == 0:
        sugestoes.append("🃏 Aproveite as pausas para revisar flashcards pendentes")
    if ciclos_completados >= 4:
        sugestoes.append("🎯 Excelente! Experimente aumentar para 30min de foco no próximo ciclo")

    # Pendentes restantes
    pendentes_flashcards = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()[0]
    pendentes_sumulas = conn.execute(
        "SELECT COUNT(*) FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()[0]

    return {
        "sessao": {
            "titulo": room["titulo"],
            "tecnica": room["tecnica"],
            "codigo": room["codigo"],
            "tempo_focado_seg": tempo_total,
            "tempo_focado_min": round(tempo_total / 60, 1),
            "ciclos_completados": ciclos_completados,
            "ciclos_total": room.get("ciclos_total") or 4,
        },
        "progresso": {
            "flashcards_revisados": flashcards_revisados,
            "sumulas_revisadas": sumulas_revisadas,
            "questoes_resolvidas": questoes_resolvidas,
            "xp_ganho": xp_ganho,
            "ranking_posicao": ranking_pos,
            "total_participantes": len(all_participants),
        },
        "meta": {
            "texto": meta,
            "cumprida": meta_cumprida,
        },
        "pendentes": {
            "flashcards": pendentes_flashcards,
            "sumulas": pendentes_sumulas,
        },
        "sugestoes": sugestoes,
    }
