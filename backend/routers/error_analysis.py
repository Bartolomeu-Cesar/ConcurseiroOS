"""Endpoints de Error Analysis — categorizar por que errou."""
from datetime import datetime

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sanitize import sanitize_input

from database import get_db_session

router = APIRouter(prefix="", tags=["Error Analysis"])

# Motivos válidos para categorização
MOTIVOS_VALIDOS = [
    "leitura_incompleta",   # Não leu o enunciado inteiro / leu rápido demais
    "conceito_errado",      # Não sabia ou confundiu o conceito
    "excecao_regra",        # Sabia a regra geral mas não a exceção
    "pegadinha",            # Enunciado com pegadinha / dupla negação
    "chute",               # Chutou (não sabia nada)
    "desatencao",          # Sabia mas marcou errado / trocou alternativa
    "tempo",               # Não teve tempo de analisar direito
]


@router.post("/api/questoes/erros/analise", summary="Registrar análise de erro",
             description="Categoriza o motivo do erro em uma resposta de questão. Motivos: leitura_incompleta, conceito_errado, excecao_regra, pegadinha, chute, desatencao, tempo.")
def create_error_analysis(
    resposta_id: int = Body(..., embed=True),
    motivo: str = Body(..., embed=True),
    detalhe: str = Body("", embed=True),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra por que o usuário errou uma questão."""
    # Validar motivo
    if motivo not in MOTIVOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Motivo inválido. Válidos: {', '.join(MOTIVOS_VALIDOS)}"
        )

    # Verificar que a resposta existe e pertence ao user
    resposta = conn.execute(
        "SELECT id FROM questoes_respostas WHERE id = ? AND user_id = ?",
        (resposta_id, user_id)
    ).fetchone()
    if not resposta:
        raise HTTPException(status_code=404, detail="Resposta não encontrada")

    # Verificar se já existe análise para esta resposta
    existing = conn.execute(
        "SELECT id FROM error_analysis WHERE resposta_id = ? AND user_id = ?",
        (resposta_id, user_id)
    ).fetchone()

    detalhe_sanitizado = sanitize_input(detalhe, max_length=500) if detalhe else ""
    now = datetime.now().isoformat()

    if existing:
        # Atualizar análise existente
        conn.execute(
            "UPDATE error_analysis SET motivo = ?, detalhe = ?, created_at = ? WHERE id = ?",
            (motivo, detalhe_sanitizado, now, existing["id"])
        )
        conn.commit()
        return {"ok": True, "id": existing["id"], "updated": True}

    # Criar nova análise
    cur = conn.execute(
        "INSERT INTO error_analysis (resposta_id, motivo, detalhe, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
        (resposta_id, motivo, detalhe_sanitizado, now, user_id)
    )
    conn.commit()
    return {"ok": True, "id": cur.lastrowid, "updated": False}


@router.get("/api/questoes/erros/analise/stats", summary="Estatísticas de erros por motivo",
            description="Retorna agregados de motivos de erro do usuário, opcionalmente filtrado por matéria ou período.")
def get_error_stats(
    materia: str = "",
    dias: int = Query(0, description="Últimos N dias (0 = todos)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna distribuição de motivos de erro."""
    query = """
        SELECT ea.motivo, COUNT(*) as total
        FROM error_analysis ea
        JOIN questoes_respostas qr ON qr.id = ea.resposta_id
    """
    params = []
    conditions = ["ea.user_id = ?"]
    params.append(user_id)

    if materia:
        query += " JOIN questoes q ON q.id = qr.questao_id"
        conditions.append("q.materia = ?")
        params.append(materia)

    if dias > 0:
        conditions.append(f"ea.created_at >= date('now', '-{dias} days')")

    query += " WHERE " + " AND ".join(conditions)
    query += " GROUP BY ea.motivo ORDER BY total DESC"

    rows = conn.execute(query, tuple(params)).fetchall()

    total_erros = sum(r["total"] for r in rows)
    stats = []
    for r in rows:
        stats.append({
            "motivo": r["motivo"],
            "total": r["total"],
            "percentual": round(r["total"] / total_erros * 100, 1) if total_erros > 0 else 0
        })

    # Top motivo e dica
    top_motivo = stats[0]["motivo"] if stats else None
    dica = _get_dica(top_motivo) if top_motivo else None

    return {
        "total_analisados": total_erros,
        "stats": stats,
        "top_motivo": top_motivo,
        "dica": dica,
    }


@router.get("/api/questoes/erros/analise/{resposta_id}", summary="Consultar análise de uma resposta")
def get_error_analysis(
    resposta_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna a análise de erro de uma resposta específica."""
    row = conn.execute(
        "SELECT * FROM error_analysis WHERE resposta_id = ? AND user_id = ?",
        (resposta_id, user_id)
    ).fetchone()
    if not row:
        return {"found": False}
    return {"found": True, **dict(row)}


@router.delete("/api/questoes/erros/analise/{resposta_id}", summary="Remover análise de erro")
def delete_error_analysis(
    resposta_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Remove a análise de erro de uma resposta."""
    conn.execute(
        "DELETE FROM error_analysis WHERE resposta_id = ? AND user_id = ?",
        (resposta_id, user_id)
    )
    conn.commit()
    return {"ok": True}


def _get_dica(motivo: str) -> str:
    """Retorna dica personalizada baseada no motivo mais frequente."""
    dicas = {
        "leitura_incompleta": "💡 Tente sublinhar palavras-chave no enunciado antes de ler as alternativas.",
        "conceito_errado": "💡 Revise os conceitos fundamentais. Flashcards e Feynman ajudam a fixar.",
        "excecao_regra": "💡 Crie flashcards específicos para exceções. São cobradas em prova!",
        "pegadinha": "💡 Procure dupla negação, advérbios absolutos (sempre, nunca, todos) e palavras-chave.",
        "chute": "💡 Se não sabe nada, estude a matéria antes de praticar. Leitura → Questões.",
        "desatencao": "💡 Revise sua resposta antes de confirmar. Marque com calma.",
        "tempo": "💡 Pratique simulados cronometrados para melhorar sua velocidade.",
    }
    return dicas.get(motivo, "")
