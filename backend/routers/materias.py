"""Router neutro de matérias (disciplinas).

Operações que afetam a "taxonomia de matérias" do estudante de forma transversal
— usadas tanto pela tela do edital quanto pelo banco de questões — para manter os
nomes consistentes em todo o sistema (sem divergência entre telas).
"""

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException
from sanitize import sanitize_input
from schemas import RenomearMateriaGlobalRequest

from database import get_db_session
from logger import log
from utils import renomear_materia_cascata

router = APIRouter(prefix="", tags=["Matérias"])


@router.put(
    "/api/materias/renomear",
    summary="Renomear matéria (cascata global)",
    description="Renomeia uma matéria em cascata por todo o sistema (edital, questões, "
                "flashcards, sessões, ciclo, calendário, planejador, trilha, desafios). "
                "O escopo edital_nome/cargo, quando informado, restringe apenas a tabela edital.",
)
def renomear_materia_global(
    body: RenomearMateriaGlobalRequest,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    antiga = sanitize_input(body.materia_antiga).strip()
    nova = sanitize_input(body.materia_nova).strip()
    if not antiga or not nova:
        raise HTTPException(status_code=400, detail="Informe a matéria antiga e a nova.")
    if antiga == nova:
        raise HTTPException(status_code=400, detail="O novo nome é igual ao atual.")

    edital_nome = sanitize_input(body.edital_nome).strip()
    cargo = sanitize_input(body.cargo).strip()

    afetados = renomear_materia_cascata(conn, user_id, antiga, nova, edital_nome, cargo)
    total = sum(afetados.values())
    if total == 0:
        raise HTTPException(status_code=404, detail=f"Nenhum registro com a matéria '{antiga}'.")

    conn.commit()
    log.info(f"Matéria renomeada (cascata): '{antiga}' -> '{nova}' {afetados}")
    return {
        "ok": True,
        "materia_antiga": antiga,
        "materia_nova": nova,
        "afetados": afetados,
        "total": total,
    }
