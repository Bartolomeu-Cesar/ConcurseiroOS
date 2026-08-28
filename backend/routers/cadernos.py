"""Caderno de Questões — agrupamento livre de questões em cadernos personalizados.

Permite ao estudante:
- Criar cadernos temáticos (ex: "Direito Constitucional - TRF5", "Revisão final")
- Adicionar/remover questões de qualquer caderno
- Resolver todas as questões de um caderno em sequência
- Acompanhar progresso (acertos/total) por caderno
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from database import get_db_session
from deps import get_user_id
from utils import today_str

router = APIRouter(prefix="/api/cadernos", tags=["Cadernos de Questões"])


# ==================== BACKWARD COMPATIBILITY ====================

@router.post("/{caderno_id}/adicionar", include_in_schema=False)
def add_to_caderno_legacy(
    caderno_id: int,
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Legacy endpoint — redireciona para o novo formato."""
    tipo = body.get("tipo", "questao")
    item_id = body.get("item_id")
    if tipo == "questao" and item_id:
        return adicionar_questoes(caderno_id, {"questao_ids": [item_id]}, conn, user_id)
    return {"ok": True, "adicionadas": 0}


# ==================== CRUD ====================

@router.get("", summary="Listar cadernos do usuário")
def listar_cadernos(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna todos os cadernos do usuário com contagem de questões e progresso."""
    rows = conn.execute("""
        SELECT c.*,
            (SELECT COUNT(*) FROM cadernos_questoes cq WHERE cq.caderno_id = c.id) as total_questoes,
            (SELECT COUNT(DISTINCT qr.questao_id)
             FROM cadernos_questoes cq2
             JOIN questoes_respostas qr ON qr.questao_id = cq2.questao_id AND qr.user_id = ?
             WHERE cq2.caderno_id = c.id) as respondidas
        FROM cadernos c
        WHERE c.user_id = ?
        ORDER BY c.updated_at DESC, c.created_at DESC
    """, (user_id, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("", summary="Criar caderno", status_code=201)
def criar_caderno(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Cria um novo caderno de questões.

    body: {nome: str, descricao?: str, cor?: str}
    """
    nome = (body.get("nome") or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do caderno é obrigatório")

    descricao = (body.get("descricao") or "").strip()
    cor = body.get("cor", "#89b4fa")
    now = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute("""
        INSERT INTO cadernos (user_id, nome, descricao, cor, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, nome, descricao, cor, now, now))
    conn.commit()

    return {"ok": True, "id": cursor.lastrowid, "nome": nome}


@router.get("/{caderno_id}", summary="Obter caderno por ID")
def obter_caderno(caderno_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna um caderno com suas questões."""
    caderno = conn.execute(
        "SELECT * FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id)
    ).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    questoes = conn.execute("""
        SELECT q.*, cq.ordem, cq.added_at,
            (SELECT qr.acertou FROM questoes_respostas qr
             WHERE qr.questao_id = q.id AND qr.user_id = ?
             ORDER BY qr.data DESC LIMIT 1) as ultimo_resultado
        FROM cadernos_questoes cq
        JOIN questoes q ON q.id = cq.questao_id
        WHERE cq.caderno_id = ?
        ORDER BY cq.ordem ASC, cq.added_at ASC
    """, (user_id, caderno_id)).fetchall()

    return {
        **dict(caderno),
        "questoes": [dict(q) for q in questoes],
        "total_questoes": len(questoes),
    }


@router.put("/{caderno_id}", summary="Editar caderno")
def editar_caderno(
    caderno_id: int,
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Edita nome, descrição ou cor do caderno.

    body: {nome?: str, descricao?: str, cor?: str}
    """
    caderno = conn.execute(
        "SELECT id FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id)
    ).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    updates = []
    params = []
    if "nome" in body:
        nome = (body["nome"] or "").strip()
        if not nome:
            raise HTTPException(status_code=400, detail="Nome não pode ser vazio")
        updates.append("nome = ?")
        params.append(nome)
    if "descricao" in body:
        updates.append("descricao = ?")
        params.append((body["descricao"] or "").strip())
    if "cor" in body:
        updates.append("cor = ?")
        params.append(body["cor"])

    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    updates.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.extend([caderno_id, user_id])

    conn.execute(
        f"UPDATE cadernos SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
        params
    )
    conn.commit()
    return {"ok": True}


@router.delete("/{caderno_id}", summary="Excluir caderno")
def excluir_caderno(caderno_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Exclui um caderno e todas as suas associações de questões."""
    caderno = conn.execute(
        "SELECT id FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id)
    ).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    conn.execute("DELETE FROM cadernos_questoes WHERE caderno_id = ?", (caderno_id,))
    conn.execute("DELETE FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id))
    conn.commit()
    return {"ok": True}


# ==================== GERENCIAR QUESTÕES NO CADERNO ====================

@router.post("/{caderno_id}/questoes", summary="Adicionar questões ao caderno")
def adicionar_questoes(
    caderno_id: int,
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Adiciona uma ou mais questões ao caderno.

    body: {questao_ids: list[int]} ou {questao_id: int}
    """
    caderno = conn.execute(
        "SELECT id FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id)
    ).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    # Aceitar tanto questao_id único quanto lista
    questao_ids = body.get("questao_ids") or []
    if not questao_ids and body.get("questao_id"):
        questao_ids = [body["questao_id"]]

    if not questao_ids:
        raise HTTPException(status_code=400, detail="Informe questao_id ou questao_ids")

    # Pegar próxima ordem
    max_ordem = conn.execute(
        "SELECT COALESCE(MAX(ordem), 0) FROM cadernos_questoes WHERE caderno_id = ?", (caderno_id,)
    ).fetchone()[0]

    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for i, qid in enumerate(questao_ids):
        # Verificar se questão existe
        exists = conn.execute("SELECT id FROM questoes WHERE id = ?", (qid,)).fetchone()
        if not exists:
            continue
        try:
            conn.execute("""
                INSERT INTO cadernos_questoes (caderno_id, questao_id, ordem, added_at)
                VALUES (?, ?, ?, ?)
            """, (caderno_id, qid, max_ordem + i + 1, now))
            added += 1
        except Exception:
            # Duplicate (unique constraint) — ignorar
            pass

    # Atualizar updated_at do caderno
    conn.execute(
        "UPDATE cadernos SET updated_at = ? WHERE id = ?",
        (now, caderno_id)
    )
    conn.commit()
    return {"ok": True, "adicionadas": added}


@router.delete("/{caderno_id}/questoes/{questao_id}", summary="Remover questão do caderno")
def remover_questao(
    caderno_id: int,
    questao_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Remove uma questão do caderno (não exclui a questão em si)."""
    caderno = conn.execute(
        "SELECT id FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id)
    ).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    conn.execute(
        "DELETE FROM cadernos_questoes WHERE caderno_id = ? AND questao_id = ?",
        (caderno_id, questao_id)
    )
    conn.execute(
        "UPDATE cadernos SET updated_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), caderno_id)
    )
    conn.commit()
    return {"ok": True}


# ==================== RESOLVER POR CADERNO ====================

@router.get("/{caderno_id}/resolver", summary="Obter questões do caderno para resolver")
def resolver_caderno(
    caderno_id: int,
    embaralhar: bool = Query(False, description="Embaralhar ordem das questões"),
    apenas_nao_respondidas: bool = Query(False, description="Apenas questões ainda não respondidas"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna as questões do caderno prontas para resolução em sequência.

    - embaralhar=true: randomiza a ordem
    - apenas_nao_respondidas=true: filtra questões já acertadas
    """
    caderno = conn.execute(
        "SELECT * FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id)
    ).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    query = """
        SELECT q.*, cq.ordem
        FROM cadernos_questoes cq
        JOIN questoes q ON q.id = cq.questao_id
        WHERE cq.caderno_id = ?
    """
    params = [caderno_id]

    if apenas_nao_respondidas:
        query += """
            AND q.id NOT IN (
                SELECT qr.questao_id FROM questoes_respostas qr
                WHERE qr.user_id = ? AND qr.acertou = 1
            )
        """
        params.append(user_id)

    query += " ORDER BY cq.ordem ASC, cq.added_at ASC"
    questoes = conn.execute(query, params).fetchall()
    result = [dict(q) for q in questoes]

    if embaralhar:
        import random
        random.shuffle(result)

    return {
        "caderno": dict(caderno),
        "questoes": result,
        "total": len(result),
    }


# ==================== PROGRESSO DO CADERNO ====================

@router.get("/{caderno_id}/progresso", summary="Progresso de resolução do caderno")
def progresso_caderno(
    caderno_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna estatísticas de progresso do caderno."""
    caderno = conn.execute(
        "SELECT * FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, user_id)
    ).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")

    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            (SELECT COUNT(DISTINCT qr.questao_id)
             FROM cadernos_questoes cq2
             JOIN questoes_respostas qr ON qr.questao_id = cq2.questao_id AND qr.user_id = ?
             WHERE cq2.caderno_id = ?) as respondidas,
            (SELECT COUNT(DISTINCT qr2.questao_id)
             FROM cadernos_questoes cq3
             JOIN questoes_respostas qr2 ON qr2.questao_id = cq3.questao_id AND qr2.user_id = ?
             WHERE cq3.caderno_id = ? AND qr2.acertou = 1) as acertos
        FROM cadernos_questoes
        WHERE caderno_id = ?
    """, (user_id, caderno_id, user_id, caderno_id, caderno_id)).fetchone()

    total = stats["total"]
    respondidas = stats["respondidas"] or 0
    acertos = stats["acertos"] or 0

    return {
        "caderno_id": caderno_id,
        "nome": caderno["nome"],
        "total": total,
        "respondidas": respondidas,
        "acertos": acertos,
        "erros": respondidas - acertos,
        "pct_concluido": round(respondidas / total * 100, 1) if total > 0 else 0,
        "pct_acerto": round(acertos / respondidas * 100, 1) if respondidas > 0 else 0,
    }
