"""Endpoint da Trilha de Estudo Diária — GET /api/trilha-diaria."""
from deps import get_user_id
from fastapi import APIRouter, Depends, Query

from database import get_db_session
from logger import log
from utils import today_str

from .analise import (
    _dias_ate_prova,
    _distribute_time,
    _get_last_session_by_subject,
    _get_pending_reviews,
    _get_performance_by_subject,
    _get_priority_activities,
)

router = APIRouter(prefix="", tags=["Treinador Inteligente"])


@router.get("/api/trilha-diaria", summary="Trilha de Estudo Diária",
            description="Gera uma trilha personalizada de atividades para o dia baseada nas horas disponíveis. Prioriza revisões pendentes, depois matérias fracas e novos conteúdos.")
def trilha_diaria(edital_nome: str = "", cargo: str = "", horas_disponiveis: float = Query(default=3.0), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    tempo_total_min = int(horas_disponiveis * 60)
    tempo_restante = tempo_total_min
    atividades = []
    ordem = 1

    pending = _get_pending_reviews(conn, user_id)

    if pending["flashcards"] > 0 and tempo_restante > 0:
        tempo_flash = min(max(5, pending["flashcards"] * 2), 20)
        tempo_flash = min(tempo_flash, tempo_restante)
        atividades.append({"ordem": ordem, "tipo": "revisao",
                           "descricao": f"Revisar {pending['flashcards']} flashcard{'s' if pending['flashcards'] > 1 else ''} pendente{'s' if pending['flashcards'] > 1 else ''}",
                           "tempo_min": tempo_flash})
        tempo_restante -= tempo_flash
        ordem += 1

    if pending["topicos"] > 0 and tempo_restante > 0:
        tempo_top = min(max(5, pending["topicos"] * 5), 30)
        tempo_top = min(tempo_top, tempo_restante)
        atividades.append({"ordem": ordem, "tipo": "revisao",
                           "descricao": f"Revisar {pending['topicos']} tópico{'s' if pending['topicos'] > 1 else ''} com baixa retenção",
                           "tempo_min": tempo_top})
        tempo_restante -= tempo_top
        ordem += 1

    desempenho = _get_performance_by_subject(conn, user_id)
    ultima_sessao = _get_last_session_by_subject(conn, user_id)
    top_materias = _get_priority_activities(conn, desempenho, ultima_sessao, user_id, edital_nome, cargo)
    new_atividades, ordem = _distribute_time(conn, top_materias, tempo_restante, ordem, user_id, edital_nome, cargo)
    atividades.extend(new_atividades)

    tempo_total_real = sum(a["tempo_min"] for a in atividades)
    foco_principal = top_materias[0]["materia"] if top_materias else "Revisão"
    motivo = ""
    if top_materias:
        m = top_materias[0]
        motivos = []
        if m["pct"] > 0:
            motivos.append(f"Menor % de acerto ({m['pct']}%)")
        if m["dias_sem"] > 0:
            motivos.append(f"{m['dias_sem']} dias sem estudar")
        dias_prova_val = _dias_ate_prova(conn, user_id, edital_nome, cargo) if edital_nome else None
        if dias_prova_val is not None:
            motivos.append(f"prova em {dias_prova_val} dias")
        motivo = " + ".join(motivos) if motivos else "Matéria prioritária"

    log.info(f"Trilha diária gerada: {len(atividades)} atividades, {tempo_total_real}min, foco={foco_principal}")
    return {"data": today_str(), "horas_disponiveis": horas_disponiveis, "atividades": atividades,
            "tempo_total_min": tempo_total_real, "foco_principal": foco_principal, "motivo": motivo}
