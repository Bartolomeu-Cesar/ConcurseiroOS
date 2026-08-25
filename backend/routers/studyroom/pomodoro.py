"""Endpoints de Pomodoro: focus score, break cards (micro-retrieval), mindfulness."""
import random
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from deps import get_user_id

from .helpers import get_user_name
from .tables import ensure_commitment_tables, ensure_studyroom_tables, run_studyroom_migrations

router = APIRouter(prefix="/api/studyroom", tags=["Study Room"])


# ============================================================
# MICRO-RETRIEVAL: Break Cards (mostrar flashcards/súmulas na pausa)
# ============================================================


@router.get("/break-cards")
def get_break_cards(
    quantidade: int = 5,
    materia: str = "",
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna 3-5 cards para micro-retrieval durante pausas do Pomodoro.

    Seleciona itens com base nas técnicas de estudo:
    - Prioriza itens com recall baixo (quase esquecendo)
    - Mistura flashcards + súmulas para variação (contextual interference)
    - Prefere itens da matéria da sessão atual (se definida)
    - Limita a 5 para não sobrecarregar a pausa (5min)
    """
    from study_ordering import order_items_intelligently
    from utils import today_str

    quantidade = min(quantidade, 5)  # Máx 5 na pausa
    hoje = today_str()

    # === Buscar flashcards pendentes ===
    fc_query = """
        SELECT id, pergunta, resposta, intervalo_dias, easiness_factor, repetitions, materia,
               'flashcard' as tipo
        FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?
    """
    fc_params = [hoje, user_id]
    if materia:
        fc_query += " AND materia = ?"
        fc_params.append(materia)
    fc_query += " LIMIT 20"
    flashcards = [dict(r) for r in conn.execute(fc_query, fc_params).fetchall()]

    # === Buscar súmulas pendentes ===
    sm_query = """
        SELECT id, tribunal, numero, enunciado, tema, vinculante,
               intervalo_dias, easiness_factor, repetitions,
               'sumula' as tipo
        FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?
    """
    sm_params = [hoje, user_id]
    if materia:
        sm_query += " AND tema = ?"
        sm_params.append(materia)
    sm_query += " LIMIT 20"
    sumulas = [dict(r) for r in conn.execute(sm_query, sm_params).fetchall()]

    # === Combinar e ordenar com técnicas de estudo ===
    all_items = flashcards + sumulas

    if not all_items:
        # Fallback: buscar flashcards/súmulas aleatórias (mesmo que não pendentes)
        fallback_fc = conn.execute(
            "SELECT id, pergunta, resposta, intervalo_dias, easiness_factor, repetitions, materia, 'flashcard' as tipo FROM flashcards WHERE user_id = ? ORDER BY RANDOM() LIMIT ?",
            (user_id, quantidade)
        ).fetchall()
        all_items = [dict(r) for r in fallback_fc]

    if not all_items:
        return {"cards": [], "total_pendentes": 0}

    # Usar ordering inteligente
    ordered = order_items_intelligently(
        all_items,
        materia_key="materia",
    )

    # Limpar campos internos e pegar apenas a quantidade pedida
    cards = []
    for item in ordered[:quantidade]:
        item.pop("_expanding_retrieval", None)
        cards.append(item)

    # Total pendentes (para mostrar "X restantes")
    total_pendentes = len(flashcards) + len(sumulas)

    return {
        "cards": cards,
        "total_pendentes": total_pendentes,
        "tecnicas_ativas": ["micro-retrieval", "interleaving", "desirable-difficulty"],
    }


# ============================================================
# FOCUS SCORE
# ============================================================


@router.get("/focus-score/{codigo}")
def get_focus_score(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Calcula score de foco 0-100 baseado em múltiplos fatores."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)
    ensure_commitment_tables(conn)

    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    participant = conn.execute("""
        SELECT * FROM study_room_participants
        WHERE room_id = ? AND user_id = ?
    """, (room["id"], user_id)).fetchone()

    if not participant:
        raise HTTPException(status_code=404, detail="Você não está nesta sala")

    # 1. pct_tempo_focando (40%) — % do tempo na sala em status 'focando'
    tempo_estudado = participant["tempo_estudado_seg"] or 0
    room_created = datetime.fromisoformat(room["created_at"])
    elapsed_total = (datetime.now() - room_created).total_seconds()
    if elapsed_total > 0:
        pct_foco = min(tempo_estudado / max(elapsed_total, 1), 1.0)
    else:
        pct_foco = 0.0
    score_foco = pct_foco * 40

    # 2. ciclos_completos (20%) — baseado no número esperado vs realizado
    ciclo_foco_seg = room["ciclo_foco_min"] * 60
    ciclos_esperados = max(elapsed_total / (ciclo_foco_seg + room["ciclo_pausa_min"] * 60), 1)
    ciclos_realizados = tempo_estudado / ciclo_foco_seg if ciclo_foco_seg > 0 else 0
    pct_ciclos = min(ciclos_realizados / ciclos_esperados, 1.0)
    score_ciclos = pct_ciclos * 20

    # 3. cards_revisados_pausa (20%) — check break cards viewed
    try:
        cards_count = conn.execute("""
            SELECT COUNT(*) as cnt FROM study_room_chat
            WHERE room_id = ? AND user_id = ? AND mensagem LIKE '%[break-card]%'
        """, (room["id"], user_id)).fetchone()
        cards_revisados = cards_count["cnt"] if cards_count else 0
    except Exception:
        cards_revisados = 0
    pct_cards = min(cards_revisados / max(ciclos_realizados, 1), 1.0)
    score_cards = pct_cards * 20

    # 4. meta_definida (10%) — se tem meta/goal definida
    meta = participant["meta"] if participant["meta"] else ""
    score_meta = 10 if meta.strip() else 0

    # 5. commitment_cumprido (10%) — se tem commitment resolvido positivamente
    commitment_ok = conn.execute("""
        SELECT COUNT(*) as cnt FROM study_room_commitments
        WHERE room_id = ? AND user_id = ? AND cumprida = 1
    """, (room["id"], user_id)).fetchone()
    has_commitment_ok = (commitment_ok["cnt"] if commitment_ok else 0) > 0
    score_commitment = 10 if has_commitment_ok else 0

    # Score total
    score = int(score_foco + score_ciclos + score_cards + score_meta + score_commitment)
    score = max(0, min(100, score))

    # Nível
    if score >= 90:
        nivel = "lendário"
    elif score >= 70:
        nivel = "mestre"
    elif score >= 40:
        nivel = "focado"
    else:
        nivel = "iniciante"

    # Dicas
    dicas = []
    if pct_foco < 0.5:
        dicas.append("Tente manter o foco por períodos mais longos sem interrupção.")
    if not meta.strip():
        dicas.append("Defina uma meta para a sessão — ajuda na direção do estudo.")
    if cards_revisados == 0:
        dicas.append("Aproveite as pausas para revisar flashcards e consolidar o aprendizado.")
    if not has_commitment_ok:
        dicas.append("Faça um commitment público para aumentar sua responsabilidade.")
    if pct_ciclos < 0.5:
        dicas.append("Complete ciclos inteiros de Pomodoro para maximizar retenção.")

    return {
        "score": score,
        "breakdown": {
            "pct_tempo_focando": round(score_foco, 1),
            "ciclos_completos": round(score_ciclos, 1),
            "cards_revisados_pausa": round(score_cards, 1),
            "meta_definida": round(score_meta, 1),
            "commitment_cumprido": round(score_commitment, 1),
        },
        "nivel": nivel,
        "dicas": dicas,
    }


# ============================================================
# GUIDED MINDFULNESS BREAK
# ============================================================


@router.get("/mindfulness")
def get_mindfulness_exercise(
    user_id: int = Depends(get_user_id),
):
    """Retorna um exercício guiado de respiração para pausa mindfulness."""
    mensagens_motivacionais = [
        "Você está no caminho certo. Cada minuto de estudo te aproxima do objetivo. 🌟",
        "A consistência vence o talento. Continue firme! 💪",
        "Respire fundo. Você está investindo no seu futuro. 🎯",
        "Sua dedicação já te diferencia. Orgulhe-se do esforço! 🏆",
        "Lembre-se: descanso inteligente faz parte da alta performance. 🧠",
        "Você já provou que consegue. Agora é só manter. 🚀",
    ]

    # 8 ciclos de respiração: Inspire 4s, Segure 4s, Expire 6s = 14s por ciclo
    passos = []
    for i in range(8):
        passos.append({"instrucao": "Inspire profundamente pelo nariz... 🌬️", "duracao_seg": 4})
        passos.append({"instrucao": "Segure o ar suavemente... ⏸️", "duracao_seg": 4})
        passos.append({"instrucao": "Expire lentamente pela boca... 💨", "duracao_seg": 6})

    # Adicionar mensagem final
    passos.append({"instrucao": "Exercício completo. Você está pronto para voltar ao foco! ✅", "duracao_seg": 8})

    return {
        "duracao_seg": 120,
        "passos": passos,
        "mensagem_motivacional": random.choice(mensagens_motivacionais),
    }
