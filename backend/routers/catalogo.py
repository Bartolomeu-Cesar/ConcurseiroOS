"""Catálogo público de materiais de estudo.

Curadores (admin) publicam materiais no catálogo apontando para recursos das
suas contas. Estudantes navegam e importam para a própria conta (cópia).

Tipos suportados (granular, por item):
- edital           → ref = edital_nome (copia edital verticalizado + info + resumos + notas)
- caderno          → ref = caderno_id (copia caderno + questões associadas)
- vademecum        → ref = lei_id (copia lei + artigos)
- deck_flashcards  → ref = materia (copia flashcards da matéria)
- deck_questoes    → ref = materia (copia questões da matéria)
- deck_sumulas     → ref = '' (copia todas as súmulas do curador)

O item aponta para o recurso na conta do curador (origem_uid). Importar =
copiar daquela conta para a do estudante, resetando progresso/SRS.
"""
from datetime import datetime, timezone

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from database import get_db_session
from logger import log
from utils import today_str

router = APIRouter(prefix="/api/catalogo", tags=["Catálogo"])

TIPOS_VALIDOS = {
    "edital": {"label": "Edital verticalizado", "emoji": "📋"},
    "caderno": {"label": "Caderno de questões", "emoji": "📓"},
    "vademecum": {"label": "Lei (Vade Mécum)", "emoji": "📜"},
    "deck_flashcards": {"label": "Deck de flashcards", "emoji": "🧠"},
    "deck_questoes": {"label": "Pacote de questões", "emoji": "❓"},
    "deck_sumulas": {"label": "Súmulas", "emoji": "⚖️"},
    "revisao": {"label": "Caderno de Revisão", "emoji": "🗂️"},
}


def _require_admin(conn, user_id: int):
    user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem publicar/remover no catálogo.")


class PublicarItem(BaseModel):
    tipo: str
    titulo: str
    descricao: str = ""
    categoria: str = "Geral"
    origem_uid: int = 0      # de qual conta copiar (0 = própria; só admin pode usar outra)
    ref: str = ""            # identificador do recurso (edital_nome, caderno_id, materia, lei_id)
    preco_creditos: int = 0  # preço em créditos inteiros (0 = gratuito)
    concurso: str = ""       # vínculo opcional a um concurso/edital
    cargo: str = ""          # vínculo opcional a um cargo específico


# ==================== LISTAGEM PÚBLICA ====================

@router.get("/config", summary="Configuração pública do catálogo (taxa do marketplace)")
def catalogo_config(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Expõe a taxa da plataforma para o vendedor calcular quanto vai receber."""
    from plans import get_marketplace_taxa
    taxa = get_marketplace_taxa()
    return {"taxa_pct": round(taxa * 100, 2)}


@router.get("", summary="Listar itens do catálogo público")
def listar_catalogo(
    categoria: str = "",
    tipo: str = "",
    busca: str = "",
    concurso: str = "",
    cargo: str = "",
    ordenar: str = "avaliacao",  # avaliacao | downloads | recente
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista itens aprovados e ativos do catálogo, com média de estrelas e selo do curador."""
    query = """
        SELECT c.*, u.nome as curador_nome, COALESCE(u.curador_verificado, 0) as curador_verificado,
               COALESCE(AVG(a.nota), 0) as media_estrelas, COUNT(a.id) as total_avaliacoes,
               MAX(CASE WHEN comp.comprador_uid = ? THEN 1 ELSE 0 END) as ja_comprado
        FROM catalogo_itens c
        LEFT JOIN users u ON c.curador_uid = u.id
        LEFT JOIN catalogo_avaliacoes a ON a.item_id = c.id
        LEFT JOIN catalogo_compras comp ON comp.item_id = c.id
        WHERE c.ativo = 1 AND COALESCE(c.status, 'aprovado') = 'aprovado'
    """
    params = [user_id]
    if categoria:
        query += " AND c.categoria = ?"
        params.append(categoria)
    if tipo:
        query += " AND c.tipo = ?"
        params.append(tipo)
    if concurso:
        query += " AND c.concurso = ?"
        params.append(concurso)
    if cargo:
        query += " AND c.cargo = ?"
        params.append(cargo)
    if busca:
        query += " AND (c.titulo LIKE ? OR c.descricao LIKE ?)"
        params.extend([f"%{busca}%", f"%{busca}%"])
    query += " GROUP BY c.id"

    if ordenar == "downloads":
        query += " ORDER BY c.downloads DESC, media_estrelas DESC"
    elif ordenar == "recente":
        query += " ORDER BY c.publicado_em DESC"
    else:  # avaliacao (default): verificados e bem avaliados primeiro
        query += " ORDER BY curador_verificado DESC, media_estrelas DESC, total_avaliacoes DESC, c.downloads DESC"

    rows = conn.execute(query, params).fetchall()
    itens = []
    for r in rows:
        info = TIPOS_VALIDOS.get(r["tipo"], {"label": r["tipo"], "emoji": "📦"})
        itens.append({
            "id": r["id"],
            "tipo": r["tipo"],
            "tipo_label": info["label"],
            "tipo_emoji": info["emoji"],
            "titulo": r["titulo"],
            "descricao": r["descricao"],
            "categoria": r["categoria"],
            "curador_nome": r["curador_nome"] or "Equipe",
            "curador_verificado": bool(r["curador_verificado"]),
            "eh_meu": (r["curador_uid"] == user_id) or (r["origem_uid"] == user_id),
            "preco_creditos": r["preco_creditos"] if "preco_creditos" in r.keys() else 0,
            "concurso": (r["concurso"] if "concurso" in r.keys() else "") or "",
            "cargo": (r["cargo"] if "cargo" in r.keys() else "") or "",
            "ja_comprado": bool(r["ja_comprado"]),
            "downloads": r["downloads"],
            "media_estrelas": round(r["media_estrelas"], 1),
            "total_avaliacoes": r["total_avaliacoes"],
            "publicado_em": r["publicado_em"],
        })

    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT categoria FROM catalogo_itens WHERE ativo = 1 AND COALESCE(status,'aprovado')='aprovado' ORDER BY categoria"
    ).fetchall()]

    return {"itens": itens, "total": len(itens), "categorias": cats}


@router.get("/categorias", summary="Categorias disponíveis no catálogo")
def listar_categorias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT categoria FROM catalogo_itens WHERE ativo = 1 ORDER BY categoria"
    ).fetchall()]
    return {"categorias": cats}


# ==================== AVALIAÇÕES (ESTRELAS) ====================

class AvaliarItem(BaseModel):
    nota: int
    comentario: str = ""


@router.post("/{item_id}/avaliar", summary="Avaliar um material (1-5 estrelas)")
def avaliar_item(
    item_id: int,
    body: AvaliarItem,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Registra/atualiza a avaliação do usuário para um material (upsert)."""
    if body.nota < 1 or body.nota > 5:
        raise HTTPException(status_code=400, detail="Nota deve ser entre 1 e 5.")

    item = conn.execute("SELECT id, curador_uid FROM catalogo_itens WHERE id = ? AND ativo = 1", (item_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Material não encontrado.")
    if item["curador_uid"] == user_id:
        raise HTTPException(status_code=400, detail="Você não pode avaliar o próprio material.")

    comentario = (body.comentario or "").strip()[:500]
    conn.execute("""
        INSERT INTO catalogo_avaliacoes (item_id, user_id, nota, comentario, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(item_id, user_id) DO UPDATE SET
            nota = excluded.nota, comentario = excluded.comentario, created_at = excluded.created_at
    """, (item_id, user_id, body.nota, comentario, datetime.now(timezone.utc).isoformat()))
    conn.commit()

    agg = conn.execute(
        "SELECT AVG(nota) as media, COUNT(*) as total FROM catalogo_avaliacoes WHERE item_id = ?", (item_id,)
    ).fetchone()
    return {"ok": True, "media_estrelas": round(agg["media"] or 0, 1), "total_avaliacoes": agg["total"]}


@router.get("/{item_id}/avaliacoes", summary="Listar avaliações de um material")
def listar_avaliacoes(item_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna avaliações do material + média + a avaliação do próprio usuário."""
    rows = conn.execute("""
        SELECT a.nota, a.comentario, a.created_at, u.nome, u.avatar
        FROM catalogo_avaliacoes a LEFT JOIN users u ON a.user_id = u.id
        WHERE a.item_id = ? ORDER BY a.created_at DESC LIMIT 50
    """, (item_id,)).fetchall()
    agg = conn.execute(
        "SELECT AVG(nota) as media, COUNT(*) as total FROM catalogo_avaliacoes WHERE item_id = ?", (item_id,)
    ).fetchone()
    minha = conn.execute(
        "SELECT nota, comentario FROM catalogo_avaliacoes WHERE item_id = ? AND user_id = ?", (item_id, user_id)
    ).fetchone()
    return {
        "media_estrelas": round(agg["media"] or 0, 1),
        "total_avaliacoes": agg["total"],
        "minha_avaliacao": {"nota": minha["nota"], "comentario": minha["comentario"]} if minha else None,
        "avaliacoes": [
            {"nota": r["nota"], "comentario": r["comentario"], "nome": r["nome"] or "Anônimo",
             "avatar": r["avatar"] or "👤", "created_at": r["created_at"]}
            for r in rows
        ],
    }


# ==================== IMPORTAÇÃO (ESTUDANTE) ====================

@router.post("/{item_id}/importar", summary="Importar um item do catálogo para sua conta")
def importar_item(
    item_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Copia o material do catálogo para a conta do estudante logado.

    Se o item tiver preço (preco_creditos > 0), cobra créditos do comprador e
    credita o vendedor (menos a taxa da plataforma) na PRIMEIRA importação. Itens
    já comprados (registro em catalogo_compras) e itens gratuitos importam sem custo.
    """
    item = conn.execute(
        "SELECT * FROM catalogo_itens WHERE id = ? AND ativo = 1", (item_id,)
    ).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado ou indisponível.")

    origem_uid = item["origem_uid"]
    if origem_uid == user_id:
        raise HTTPException(status_code=400, detail="Este material já é da sua conta.")

    item_keys = item.keys()
    preco = int(item["preco_creditos"]) if "preco_creditos" in item_keys and item["preco_creditos"] else 0
    vendedor_uid = item["curador_uid"]

    # Não pode comprar o próprio material (curador é o vendedor)
    if preco > 0 and vendedor_uid == user_id:
        raise HTTPException(status_code=400, detail="Você não pode comprar o seu próprio material.")

    # Idempotência: já comprou antes? Então reimporta de graça.
    ja_comprou = conn.execute(
        "SELECT 1 FROM catalogo_compras WHERE item_id = ? AND comprador_uid = ?", (item_id, user_id)
    ).fetchone() is not None

    cobrar = preco > 0 and not ja_comprou

    if cobrar:
        from plans import get_marketplace_taxa, mover_creditos

        saldo = conn.execute(
            "SELECT COALESCE(creditos_saldo, 0) FROM users WHERE id = ?", (user_id,)
        ).fetchone()[0]
        if int(saldo or 0) < preco:
            raise HTTPException(
                status_code=402,
                detail=f"Saldo insuficiente. Este material custa {preco} crédito(s) e você tem {int(saldo or 0)}.",
            )

        taxa = get_marketplace_taxa()
        creditos_vendedor = int(preco * (1 - taxa))  # floor; o restante fica com a plataforma

        # Débito do comprador e crédito do vendedor (saldo puro, sem auto-premium).
        mover_creditos(conn, user_id, -preco, "marketplace_compra",
                       f"Compra do item #{item_id}: {item['titulo']}")
        if creditos_vendedor > 0:
            mover_creditos(conn, vendedor_uid, creditos_vendedor, "marketplace_venda",
                           f"Venda do item #{item_id}: {item['titulo']}")

        conn.execute("""
            INSERT INTO catalogo_compras (item_id, comprador_uid, vendedor_uid, preco_creditos, taxa_pct, creditos_vendedor, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (item_id, user_id, vendedor_uid, preco, taxa, creditos_vendedor,
              datetime.now(timezone.utc).isoformat()))

    tipo = item["tipo"]
    ref = item["ref"]

    if tipo == "edital":
        copiados = _importar_edital(conn, origem_uid, user_id, ref)
    elif tipo == "caderno":
        copiados = _importar_caderno(conn, origem_uid, user_id, ref)
    elif tipo == "vademecum":
        copiados = _importar_vademecum(conn, origem_uid, user_id, ref)
    elif tipo == "deck_flashcards":
        copiados = _importar_deck(conn, "flashcards", origem_uid, user_id, ref)
    elif tipo == "deck_questoes":
        copiados = _importar_deck(conn, "questoes", origem_uid, user_id, ref)
    elif tipo == "deck_sumulas":
        copiados = _importar_sumulas(conn, origem_uid, user_id, ref)  # ref = tribunal ou '' (todas)
    elif tipo == "revisao":
        copiados = _importar_revisao(conn, origem_uid, user_id, ref)  # ref = pdf_path
    else:
        raise HTTPException(status_code=400, detail=f"Tipo de item desconhecido: {tipo}")

    # Registrar aquisição também para itens GRÁTIS (idempotente via UNIQUE), para
    # que o catálogo marque como "já adquirido" e evite reimportar/duplicar.
    if not cobrar and not ja_comprou:
        conn.execute("""
            INSERT OR IGNORE INTO catalogo_compras (item_id, comprador_uid, vendedor_uid, preco_creditos, taxa_pct, creditos_vendedor, created_at)
            VALUES (?, ?, ?, 0, 0, 0, ?)
        """, (item_id, user_id, vendedor_uid, datetime.now(timezone.utc).isoformat()))

    # Incrementar contador de downloads
    conn.execute("UPDATE catalogo_itens SET downloads = downloads + 1 WHERE id = ?", (item_id,))
    conn.commit()

    log.info(f"[catalogo] user={user_id} importou item={item_id} tipo={tipo} ({copiados} registros) cobrado={cobrar}")
    return {"ok": True, "tipo": tipo, "titulo": item["titulo"], "importados": copiados,
            "cobrado": bool(cobrar), "preco_creditos": preco if cobrar else 0}


# ==================== PUBLICAÇÃO (ADMIN + PREMIUM) ====================

def _pode_publicar(conn, user_id: int):
    """Retorna (pode, is_admin, is_verificado). Publicam: admin, premium/vitalício.

    - admin ou curador_verificado → publica direto (status aprovado)
    - premium/vitalício não-verificado → publica com status 'pendente' (moderação)
    - free/guest → não pode
    """
    from plans import get_plan
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return (False, False, False)
    user_dict = dict(user)
    is_admin = user_dict.get("role") == "admin"
    is_verificado = bool(user_dict.get("curador_verificado"))
    plano = get_plan(user_dict)
    pode = is_admin or plano in ("premium", "ilimitado")
    return (pode, is_admin, is_verificado)


@router.post("/publicar", summary="Publicar um recurso no catálogo (admin ou premium)")
def publicar_item(
    body: PublicarItem,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Publica um recurso no catálogo.

    - Admin/curador verificado: publica aprovado (visível na hora).
    - Premium/vitalício: publica pendente (aguarda moderação do admin).
    - Free: bloqueado.
    Sempre publica a partir da PRÓPRIA conta (origem_uid = user_id), exceto admin
    que pode publicar de qualquer conta.
    """
    pode, is_admin, is_verificado = _pode_publicar(conn, user_id)
    if not pode:
        raise HTTPException(status_code=403, detail="Apenas usuários Premium ou administradores podem publicar no catálogo. Faça upgrade!")

    if body.tipo not in TIPOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Válidos: {list(TIPOS_VALIDOS)}")

    # Admin pode publicar de qualquer conta; premium só da própria.
    # A página do Catálogo (catalogo.js) envia origem_uid=0 (placeholder "própria
    # conta"). Para admin, um origem_uid inválido (0/None/negativo) cai na própria
    # conta em vez de falhar com "usuário de origem não encontrado".
    if is_admin and body.origem_uid and body.origem_uid > 0:
        origem_uid = body.origem_uid
    else:
        origem_uid = user_id
    origem = conn.execute("SELECT id FROM users WHERE id = ?", (origem_uid,)).fetchone()
    if not origem:
        raise HTTPException(status_code=404, detail="Usuário de origem não encontrado.")

    if not _recurso_existe(conn, body.tipo, origem_uid, body.ref):
        raise HTTPException(status_code=404, detail="Recurso não encontrado na sua conta.")

    # Preço: inteiro >= 0. Só quem pode vender (premium/vitalício/verificado/admin)
    # pode definir preço > 0; free/guest nem chega aqui (bloqueado acima).
    preco = int(body.preco_creditos or 0)
    if preco < 0:
        raise HTTPException(status_code=400, detail="Preço não pode ser negativo.")

    # Status: aprovado se admin ou verificado; pendente caso contrário
    status = "aprovado" if (is_admin or is_verificado) else "pendente"

    conn.execute("""
        INSERT INTO catalogo_itens (tipo, titulo, descricao, categoria, curador_uid, origem_uid, ref, downloads, ativo, status, publicado_em, preco_creditos, concurso, cargo)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?)
    """, (body.tipo, body.titulo.strip(), body.descricao.strip(), body.categoria.strip() or "Geral",
          user_id, origem_uid, str(body.ref), status, datetime.now(timezone.utc).isoformat(),
          preco, body.concurso.strip(), body.cargo.strip()))
    conn.commit()

    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log.info(f"[catalogo] Publicado: id={new_id} tipo={body.tipo} status={status} por user={user_id}")
    return {"ok": True, "id": new_id, "status": status,
            "mensagem": "Publicado!" if status == "aprovado" else "Enviado para moderação. Será revisado pela equipe."}


@router.get("/meus", summary="Meus materiais publicados")
def meus_materiais(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista os materiais publicados pelo usuário logado (qualquer status)."""
    rows = conn.execute("""
        SELECT c.*, COALESCE(AVG(a.nota),0) as media_estrelas, COUNT(a.id) as total_avaliacoes
        FROM catalogo_itens c LEFT JOIN catalogo_avaliacoes a ON a.item_id = c.id
        WHERE c.curador_uid = ? AND c.ativo = 1 GROUP BY c.id ORDER BY c.publicado_em DESC
    """, (user_id,)).fetchall()
    itens = []
    for r in rows:
        info = TIPOS_VALIDOS.get(r["tipo"], {"label": r["tipo"], "emoji": "📦"})
        itens.append({
            "id": r["id"], "tipo": r["tipo"], "tipo_emoji": info["emoji"], "titulo": r["titulo"],
            "categoria": r["categoria"], "status": r["status"] or "aprovado", "downloads": r["downloads"],
            "media_estrelas": round(r["media_estrelas"], 1), "total_avaliacoes": r["total_avaliacoes"],
            "preco_creditos": r["preco_creditos"] if "preco_creditos" in r.keys() else 0,
            "concurso": (r["concurso"] if "concurso" in r.keys() else "") or "",
            "cargo": (r["cargo"] if "cargo" in r.keys() else "") or "",
        })
    return {"itens": itens}


@router.get("/vendas", summary="Painel de vendas do vendedor")
def minhas_vendas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Resumo das vendas do usuário logado: total de vendas, créditos recebidos e detalhamento por item."""
    linhas = conn.execute("""
        SELECT comp.item_id, comp.preco_creditos, comp.creditos_vendedor, comp.created_at,
               c.titulo, comp.comprador_uid, u.nome as comprador_nome
        FROM catalogo_compras comp
        LEFT JOIN catalogo_itens c ON c.id = comp.item_id
        LEFT JOIN users u ON u.id = comp.comprador_uid
        WHERE comp.vendedor_uid = ?
        ORDER BY comp.created_at DESC
    """, (user_id,)).fetchall()
    total_vendas = len(linhas)
    total_creditos = sum(int(r["creditos_vendedor"] or 0) for r in linhas)
    vendas = [{
        "item_id": r["item_id"],
        "titulo": r["titulo"] or "(removido)",
        "preco_creditos": r["preco_creditos"],
        "creditos_recebidos": r["creditos_vendedor"],
        "comprador_nome": r["comprador_nome"] or "Anônimo",
        "created_at": r["created_at"],
    } for r in linhas]
    # Info do vendedor para a UI de resgate (saldo atual + se pode PIX = vitalício)
    u = conn.execute("SELECT plano, plano_expira, COALESCE(creditos_saldo,0) as saldo FROM users WHERE id = ?", (user_id,)).fetchone()
    pode_pix = _eh_vitalicio(u) if u else False
    saldo = int(u["saldo"]) if u else 0
    return {
        "total_vendas": total_vendas,
        "total_creditos_recebidos": total_creditos,
        "vendas": vendas,
        "saldo_creditos": saldo,
        "pode_resgatar_pix": pode_pix,
    }


def _eh_vitalicio(user_row) -> bool:
    """True se o usuário é vitalício (ilimitado, ou premium sem expiração/marcado)."""
    plano = (user_row["plano"] if "plano" in user_row.keys() else "") or ""
    exp = ((user_row["plano_expira"] if "plano_expira" in user_row.keys() else "") or "").strip().lower()
    if plano == "ilimitado" or exp in ("vitalicio", "vitalício", "lifetime"):
        return True
    return bool(plano == "premium" and not exp)


class ResgatarCreditos(BaseModel):
    tipo: str            # 'pix' (vitalício) | 'premium' (converter em dias)
    creditos: int
    chave_pix: str = ""  # obrigatório para tipo 'pix'


@router.post("/resgatar", summary="Resgatar créditos de vendas (PIX para vitalício, tempo para premium)")
def resgatar_creditos(
    body: ResgatarCreditos,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Resgata os créditos ganhos com vendas.

    - tipo 'premium': converte créditos em dias de Premium na hora (imediato).
    - tipo 'pix': cria uma solicitação PENDENTE e notifica o admin para negociar
      o pagamento via PIX. Disponível apenas para usuários vitalícios.
    Em ambos os casos os créditos são debitados na solicitação (reservados);
    um resgate PIX recusado pelo admin estorna os créditos.
    """
    from datetime import datetime, timedelta, timezone

    from plans import calcular_dias_creditos, mover_creditos

    creditos = int(body.creditos or 0)
    if creditos < 1:
        raise HTTPException(status_code=400, detail="Informe ao menos 1 crédito para resgatar.")

    user = conn.execute("SELECT id, nome, plano, plano_expira, COALESCE(creditos_saldo,0) as saldo FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if creditos > int(user["saldo"]):
        raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Você tem {int(user['saldo'])} crédito(s).")

    tipo = (body.tipo or "").strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    if tipo == "premium":
        # Converte créditos em dias de Premium imediatamente (estende se já ativo).
        dias = calcular_dias_creditos(creditos)
        if dias < 1:
            raise HTTPException(status_code=400, detail="Créditos insuficientes para 1 dia de acesso.")
        plano_atual = user["plano"] or "free"
        exp = (user["plano_expira"] or "")
        base = datetime.now(timezone.utc)
        if plano_atual == "premium" and exp and exp.lower() not in ("vitalicio", "vitalício", "lifetime"):
            try:
                dt = datetime.fromisoformat(exp)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt > base:
                    base = dt
            except (ValueError, TypeError):
                pass
        nova_expira = (base + timedelta(days=dias)).isoformat()
        mover_creditos(conn, user_id, -creditos, "resgate_premium", f"Resgate: {dias} dias de Premium")
        conn.execute("UPDATE users SET plano = 'premium', plano_expira = ? WHERE id = ?", (nova_expira, user_id))
        conn.execute("""
            INSERT INTO resgate_solicitacoes (user_id, tipo, creditos, status, dias_creditados, created_at, resolved_at)
            VALUES (?, 'premium', ?, 'concluido', ?, ?, ?)
        """, (user_id, creditos, dias, now, now))
        conn.commit()
        log.info(f"[resgate] user={user_id} converteu {creditos} créditos em {dias} dias premium")
        return {"ok": True, "tipo": "premium", "dias_creditados": dias, "expira": nova_expira,
                "mensagem": f"✅ {dias} dias de Premium adicionados!"}

    if tipo == "pix":
        if not _eh_vitalicio(user):
            raise HTTPException(status_code=403, detail="Resgate por PIX é exclusivo para usuários vitalícios. Você pode resgatar como tempo de Premium.")
        chave = (body.chave_pix or "").strip()
        if not chave:
            raise HTTPException(status_code=400, detail="Informe sua chave PIX para o resgate.")
        # Debita (reserva) os créditos e cria a solicitação pendente.
        mover_creditos(conn, user_id, -creditos, "resgate_pix_reserva", f"Resgate PIX solicitado ({creditos} créditos)")
        cur = conn.execute("""
            INSERT INTO resgate_solicitacoes (user_id, tipo, creditos, status, chave_pix, created_at)
            VALUES (?, 'pix', ?, 'pendente', ?, ?)
        """, (user_id, creditos, chave, now))
        req_id = cur.lastrowid

        # Notifica os admins (push best-effort) para negociarem o pagamento.
        try:
            from routers.notifications import _send_push_to_user
            admins = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
            for a in admins:
                try:
                    _send_push_to_user(conn, a["id"], "💸 Novo resgate PIX",
                                       f"{user['nome'] or 'Usuário'} solicitou resgate de {creditos} créditos via PIX.",
                                       url="/admin.html", tag="resgate")
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"[resgate] push admin indisponível: {e}")

        conn.commit()
        log.info(f"[resgate] user={user_id} solicitou PIX de {creditos} créditos (req={req_id})")
        return {"ok": True, "tipo": "pix", "id": req_id, "status": "pendente",
                "mensagem": "✅ Solicitação enviada! O administrador entrará em contato para o pagamento via PIX."}

    raise HTTPException(status_code=400, detail="tipo deve ser 'pix' ou 'premium'.")


@router.get("/resgates", summary="Minhas solicitações de resgate")
def meus_resgates(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista as solicitações de resgate do usuário logado."""
    rows = conn.execute("""
        SELECT id, tipo, creditos, status, dias_creditados, admin_obs, created_at, resolved_at
        FROM resgate_solicitacoes WHERE user_id = ? ORDER BY id DESC LIMIT 50
    """, (user_id,)).fetchall()
    return {"resgates": [dict(r) for r in rows]}


@router.delete("/{item_id}", summary="Remover item do catálogo (admin ou dono)")
def remover_item(item_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Remove (desativa) um item. Admin remove qualquer um; usuário remove os próprios."""
    item = conn.execute("SELECT id, curador_uid FROM catalogo_itens WHERE id = ?", (item_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    is_admin = user and user["role"] == "admin"
    if not is_admin and item["curador_uid"] != user_id:
        raise HTTPException(status_code=403, detail="Você só pode remover seus próprios materiais.")
    conn.execute("UPDATE catalogo_itens SET ativo = 0 WHERE id = ?", (item_id,))
    conn.commit()
    log.info(f"[catalogo] Removido item={item_id}")
    return {"ok": True}


class EditarItem(BaseModel):
    titulo: str | None = None
    descricao: str | None = None
    categoria: str | None = None
    concurso: str | None = None
    cargo: str | None = None
    preco_creditos: int | None = None


@router.patch("/{item_id}", summary="Editar um material publicado (dono ou admin)")
def editar_item(
    item_id: int,
    body: EditarItem,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Edita campos de um item já publicado. Permite, entre outros, alterar o
    preço (grátis→pago ou pago→grátis) posteriormente.

    - Só o dono (curador_uid) ou admin pode editar.
    - Definir preço > 0 exige poder de venda (premium/vitalício/verificado/admin);
      caso contrário, retorna 403.
    - Compras já feitas (catalogo_compras) não são afetadas: quem já adquiriu
      mantém o acesso e reimporta de graça.
    """
    item = conn.execute("SELECT * FROM catalogo_itens WHERE id = ? AND ativo = 1", (item_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")

    user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    is_admin = bool(user and user["role"] == "admin")
    if not is_admin and item["curador_uid"] != user_id:
        raise HTTPException(status_code=403, detail="Você só pode editar seus próprios materiais.")

    campos = []
    valores = []

    if body.titulo is not None:
        titulo = body.titulo.strip()
        if not titulo:
            raise HTTPException(status_code=400, detail="Título não pode ficar vazio.")
        campos.append("titulo = ?")
        valores.append(titulo)
    if body.descricao is not None:
        campos.append("descricao = ?")
        valores.append(body.descricao.strip())
    if body.categoria is not None:
        campos.append("categoria = ?")
        valores.append(body.categoria.strip() or "Geral")
    if body.concurso is not None:
        campos.append("concurso = ?")
        valores.append(body.concurso.strip())
    if body.cargo is not None:
        campos.append("cargo = ?")
        valores.append(body.cargo.strip())
    if body.preco_creditos is not None:
        preco = int(body.preco_creditos)
        if preco < 0:
            raise HTTPException(status_code=400, detail="Preço não pode ser negativo.")
        # Colocar preço > 0 exige poder de venda (mesma regra da publicação).
        if preco > 0:
            pode, _adm, _ver = _pode_publicar(conn, item["curador_uid"] if is_admin else user_id)
            if not pode and not is_admin:
                raise HTTPException(status_code=403, detail="Apenas usuários Premium ou administradores podem definir preço. Faça upgrade!")
        campos.append("preco_creditos = ?")
        valores.append(preco)

    if not campos:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    valores.append(item_id)
    conn.execute(f"UPDATE catalogo_itens SET {', '.join(campos)} WHERE id = ?", valores)
    conn.commit()
    log.info(f"[catalogo] Editado item={item_id} por user={user_id} campos={[c.split(' =')[0] for c in campos]}")

    novo = conn.execute("SELECT preco_creditos, titulo FROM catalogo_itens WHERE id = ?", (item_id,)).fetchone()
    return {"ok": True, "id": item_id, "preco_creditos": novo["preco_creditos"], "titulo": novo["titulo"]}


@router.get("/admin/todos", summary="Listar todos os itens (admin, inclui inativos)")
def listar_todos_admin(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista todos os itens do catálogo (incluindo inativos) para gestão."""
    _require_admin(conn, user_id)
    rows = conn.execute("""
        SELECT c.*, u.nome as curador_nome FROM catalogo_itens c
        LEFT JOIN users u ON c.curador_uid = u.id ORDER BY c.publicado_em DESC
    """).fetchall()
    return {"itens": [dict(r) for r in rows]}


@router.get("/admin/refs", summary="Listar refs disponíveis de um usuário por tipo (admin)")
def listar_refs(
    origem_uid: int = Query(...),
    tipo: str = Query(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista as opções de 'ref' publicáveis para um tipo/usuário.

    Ex: para tipo=edital retorna os edital_nome e também cada cargo do edital;
    para deck_sumulas retorna cada tribunal; para revisao retorna cada caderno
    de revisão (por PDF).
    """
    _require_admin(conn, user_id)
    return {"refs": _refs_para(conn, tipo, origem_uid)}


def _refs_para(conn, tipo: str, uid: int) -> list:
    """Opções de 'ref' publicáveis para um tipo, na conta de `uid`.

    Convenções de ref:
    - edital: "edital_nome" (todos os cargos) ou "edital_nome::cargo" (um cargo).
    - deck_sumulas: "" (todas) ou "tribunal" (ex.: "STF").
    - revisao: "pdf_path" (um caderno de revisão por PDF).
    """
    refs = []
    try:
        if tipo == "edital":
            rows = conn.execute(
                "SELECT edital_nome, COUNT(*) as n FROM edital WHERE user_id = ? GROUP BY edital_nome ORDER BY edital_nome",
                (uid,)
            ).fetchall()
            for r in rows:
                nome = r["edital_nome"]
                refs.append({"ref": nome, "label": f"{nome} — todos os cargos ({r['n']} tópicos)"})
                # Cada cargo específico daquele edital vira uma ref "nome::cargo"
                cargos = conn.execute(
                    "SELECT cargo, COUNT(*) as n FROM edital WHERE user_id = ? AND edital_nome = ? AND COALESCE(cargo,'') != '' GROUP BY cargo ORDER BY cargo",
                    (uid, nome)
                ).fetchall()
                for cg in cargos:
                    refs.append({"ref": f"{nome}::{cg['cargo']}", "label": f"{nome} · {cg['cargo']} ({cg['n']} tópicos)"})
        elif tipo == "caderno":
            rows = conn.execute("SELECT id, nome FROM cadernos WHERE user_id = ? ORDER BY nome", (uid,)).fetchall()
            refs = [{"ref": str(r["id"]), "label": r["nome"]} for r in rows]
        elif tipo == "vademecum":
            rows = conn.execute("SELECT id, nome, sigla FROM vademecum_leis WHERE user_id = ? ORDER BY nome", (uid,)).fetchall()
            refs = [{"ref": str(r["id"]), "label": f"{r['nome']} ({r['sigla']})" if r["sigla"] else r["nome"]} for r in rows]
        elif tipo in ("deck_flashcards", "deck_questoes"):
            tabela = "flashcards" if tipo == "deck_flashcards" else "questoes"
            rows = conn.execute(
                f"SELECT materia, COUNT(*) as n FROM {tabela} WHERE user_id = ? AND materia != '' GROUP BY materia ORDER BY materia",
                (uid,)
            ).fetchall()
            refs = [{"ref": r["materia"], "label": f"{r['materia']} ({r['n']})"} for r in rows]
        elif tipo == "deck_sumulas":
            total = conn.execute("SELECT COUNT(*) FROM sumulas WHERE user_id = ?", (uid,)).fetchone()[0]
            if total > 0:
                refs.append({"ref": "", "label": f"Todas as súmulas ({total})"})
                tribunais = conn.execute(
                    "SELECT tribunal, COUNT(*) as n FROM sumulas WHERE user_id = ? AND COALESCE(tribunal,'') != '' GROUP BY tribunal ORDER BY tribunal",
                    (uid,)
                ).fetchall()
                for t in tribunais:
                    refs.append({"ref": t["tribunal"], "label": f"{t['tribunal']} ({t['n']} súmulas)"})
        elif tipo == "revisao":
            rows = conn.execute(
                "SELECT pdf_path, COUNT(*) as n FROM revisao_blocos WHERE user_id = ? AND COALESCE(pdf_path,'') != '' GROUP BY pdf_path ORDER BY pdf_path",
                (uid,)
            ).fetchall()
            for r in rows:
                nome = (r["pdf_path"] or "").split("/")[-1] or r["pdf_path"]
                refs.append({"ref": r["pdf_path"], "label": f"{nome} ({r['n']} blocos)"})
    except Exception:
        refs = []
    return refs


@router.get("/meus/refs", summary="Listar refs da própria conta (premium publicando)")
def listar_meus_refs(
    tipo: str = Query(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Como /admin/refs, mas restrito à conta do próprio usuário (para premium publicar)."""
    pode, _, _ = _pode_publicar(conn, user_id)
    if not pode:
        raise HTTPException(status_code=403, detail="Apenas Premium/admin podem publicar.")
    return {"refs": _refs_para(conn, tipo, user_id)}


# ==================== MODERAÇÃO (ADMIN) ====================

@router.get("/admin/pendentes", summary="Listar materiais pendentes de moderação (admin)")
def listar_pendentes(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista itens com status 'pendente' aguardando aprovação."""
    _require_admin(conn, user_id)
    rows = conn.execute("""
        SELECT c.*, u.nome as curador_nome FROM catalogo_itens c
        LEFT JOIN users u ON c.curador_uid = u.id
        WHERE c.ativo = 1 AND c.status = 'pendente' ORDER BY c.publicado_em ASC
    """).fetchall()
    return {"itens": [dict(r) for r in rows]}


@router.post("/{item_id}/moderar", summary="Aprovar ou rejeitar material pendente (admin)")
def moderar_item(
    item_id: int,
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Aprova (status=aprovado) ou rejeita (ativo=0) um material pendente.

    body: {acao: "aprovar" | "rejeitar"}
    """
    _require_admin(conn, user_id)
    item = conn.execute("SELECT id FROM catalogo_itens WHERE id = ?", (item_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    acao = body.get("acao")
    if acao == "aprovar":
        conn.execute("UPDATE catalogo_itens SET status = 'aprovado' WHERE id = ?", (item_id,))
    elif acao == "rejeitar":
        conn.execute("UPDATE catalogo_itens SET ativo = 0, status = 'rejeitado' WHERE id = ?", (item_id,))
    else:
        raise HTTPException(status_code=400, detail="acao deve ser 'aprovar' ou 'rejeitar'.")
    conn.commit()
    log.info(f"[catalogo] Moderação: item={item_id} {acao} por admin={user_id}")
    return {"ok": True, "acao": acao}


@router.post("/curador/{uid}/verificar", summary="Conceder/remover selo de curador verificado (admin)")
def verificar_curador(
    uid: int,
    body: dict = Body(default={}),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Concede (verificado=1) ou remove (verificado=0) o selo de curador verificado.

    body: {verificado: bool} (default true)
    """
    _require_admin(conn, user_id)
    user = conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    verificado = 1 if body.get("verificado", True) else 0
    conn.execute("UPDATE users SET curador_verificado = ? WHERE id = ?", (verificado, uid))
    conn.commit()
    log.info(f"[catalogo] Curador {uid} verificado={verificado} por admin={user_id}")
    return {"ok": True, "curador_verificado": bool(verificado)}


# ==================== HELPERS ====================

def _tabela_colunas(conn, tabela: str) -> list:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})").fetchall()]


def _recurso_existe(conn, tipo: str, origem_uid: int, ref: str) -> bool:
    """Valida se o recurso referenciado existe na conta de origem."""
    try:
        if tipo == "edital":
            nome, cargo = _split_edital_ref(ref)
            if cargo:
                return conn.execute("SELECT 1 FROM edital WHERE user_id = ? AND edital_nome = ? AND cargo = ? LIMIT 1", (origem_uid, nome, cargo)).fetchone() is not None
            return conn.execute("SELECT 1 FROM edital WHERE user_id = ? AND edital_nome = ? LIMIT 1", (origem_uid, nome)).fetchone() is not None
        if tipo == "caderno":
            return conn.execute("SELECT 1 FROM cadernos WHERE user_id = ? AND id = ? LIMIT 1", (origem_uid, int(ref))).fetchone() is not None
        if tipo == "vademecum":
            return conn.execute("SELECT 1 FROM vademecum_leis WHERE user_id = ? AND id = ? LIMIT 1", (origem_uid, int(ref))).fetchone() is not None
        if tipo == "deck_flashcards":
            return conn.execute("SELECT 1 FROM flashcards WHERE user_id = ? AND materia = ? LIMIT 1", (origem_uid, ref)).fetchone() is not None
        if tipo == "deck_questoes":
            return conn.execute("SELECT 1 FROM questoes WHERE user_id = ? AND materia = ? LIMIT 1", (origem_uid, ref)).fetchone() is not None
        if tipo == "deck_sumulas":
            if ref:  # tribunal específico
                return conn.execute("SELECT 1 FROM sumulas WHERE user_id = ? AND tribunal = ? LIMIT 1", (origem_uid, ref)).fetchone() is not None
            return conn.execute("SELECT 1 FROM sumulas WHERE user_id = ? LIMIT 1", (origem_uid,)).fetchone() is not None
        if tipo == "revisao":
            return conn.execute("SELECT 1 FROM revisao_blocos WHERE user_id = ? AND pdf_path = ? LIMIT 1", (origem_uid, ref)).fetchone() is not None
    except (ValueError, TypeError):
        return False
    return False


def _split_edital_ref(ref: str):
    """Separa a ref de edital em (edital_nome, cargo). '::' separa o cargo opcional."""
    if ref and "::" in ref:
        nome, _, cargo = ref.partition("::")
        return nome, cargo
    return ref, ""


def _importar_deck(conn, tabela: str, origem_uid: int, destino_uid: int, materia: str) -> int:
    """Copia flashcards/questoes/sumulas de uma matéria (ou todas se materia vazia)."""
    cols = _tabela_colunas(conn, tabela)
    if "user_id" not in cols:
        return 0
    insert_cols = [c for c in cols if c != "id"]

    if materia:
        rows = conn.execute(f"SELECT * FROM {tabela} WHERE user_id = ? AND materia = ?", (origem_uid, materia)).fetchall()
    else:
        rows = conn.execute(f"SELECT * FROM {tabela} WHERE user_id = ?", (origem_uid,)).fetchall()

    resets = {
        "proxima_revisao": today_str(), "intervalo_dias": 1, "easiness_factor": 2.5,
        "repetitions": 0, "stability": 0, "difficulty": 0, "difficulty_sumulas": 0, "fsrs_state": 0,
    }
    resets = {k: v for k, v in resets.items() if k in insert_cols}

    ph = ", ".join("?" for _ in insert_cols)
    n = 0
    for row in rows:
        vals = []
        for c in insert_cols:
            if c == "user_id":
                vals.append(destino_uid)
            elif c in resets:
                vals.append(resets[c])
            else:
                vals.append(row[c])
        conn.execute(f"INSERT INTO {tabela} ({', '.join(insert_cols)}) VALUES ({ph})", vals)
        n += 1
    return n


def _importar_sumulas(conn, origem_uid: int, destino_uid: int, tribunal: str) -> int:
    """Copia súmulas: todas (tribunal vazio) ou apenas de um tribunal específico."""
    cols = _tabela_colunas(conn, "sumulas")
    if "user_id" not in cols:
        return 0
    insert_cols = [c for c in cols if c != "id"]

    if tribunal:
        rows = conn.execute("SELECT * FROM sumulas WHERE user_id = ? AND tribunal = ?", (origem_uid, tribunal)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sumulas WHERE user_id = ?", (origem_uid,)).fetchall()

    resets = {
        "proxima_revisao": today_str(), "intervalo_dias": 1, "easiness_factor": 2.5,
        "repetitions": 0, "stability": 0, "difficulty": 0, "fsrs_state": 0,
    }
    resets = {k: v for k, v in resets.items() if k in insert_cols}
    ph = ", ".join("?" for _ in insert_cols)
    n = 0
    for row in rows:
        vals = [destino_uid if c == "user_id" else (resets[c] if c in resets else row[c]) for c in insert_cols]
        conn.execute(f"INSERT INTO sumulas ({', '.join(insert_cols)}) VALUES ({ph})", vals)
        n += 1
    return n


def _importar_revisao(conn, origem_uid: int, destino_uid: int, pdf_path: str) -> int:
    """Copia um Caderno de Revisão (revisao_blocos de um pdf_path), resetando
    o agendamento espaçado do destinatário para começar do zero."""
    cols = _tabela_colunas(conn, "revisao_blocos")
    if "user_id" not in cols or not pdf_path:
        return 0
    insert_cols = [c for c in cols if c != "id"]
    rows = conn.execute("SELECT * FROM revisao_blocos WHERE user_id = ? AND pdf_path = ? ORDER BY ordem, id", (origem_uid, pdf_path)).fetchall()
    if not rows:
        return 0
    ph = ", ".join("?" for _ in insert_cols)
    n = 0
    for row in rows:
        vals = [destino_uid if c == "user_id" else row[c] for c in insert_cols]
        conn.execute(f"INSERT INTO revisao_blocos ({', '.join(insert_cols)}) VALUES ({ph})", vals)
        n += 1
    # Semeia a agenda de revisão espaçada do destinatário (começa hoje) se a tabela existir.
    try:
        ag_cols = _tabela_colunas(conn, "revisao_agenda")
        if ag_cols and "user_id" in ag_cols:
            ja = conn.execute("SELECT 1 FROM revisao_agenda WHERE user_id = ? AND pdf_path = ? LIMIT 1", (destino_uid, pdf_path)).fetchone()
            if not ja:
                conn.execute(
                    "INSERT INTO revisao_agenda (user_id, pdf_path, proxima_revisao, intervalo_dias, revisoes_count, created_at) VALUES (?, ?, ?, 1, 0, ?)",
                    (destino_uid, pdf_path, today_str(), today_str())
                )
    except Exception:
        pass
    return n


def _importar_caderno(conn, origem_uid: int, destino_uid: int, caderno_id_ref: str) -> int:
    """Copia um caderno específico + suas questões associadas."""
    from utils import today_str as _today
    now = _today()
    try:
        caderno_id = int(caderno_id_ref)
    except (ValueError, TypeError):
        return 0

    cad = conn.execute("SELECT * FROM cadernos WHERE id = ? AND user_id = ?", (caderno_id, origem_uid)).fetchone()
    if not cad:
        return 0

    cad_cols = _tabela_colunas(conn, "cadernos")
    icols = [c for c in cad_cols if c != "id"]
    vals = [destino_uid if c == "user_id" else cad[c] for c in icols]
    ph = ", ".join("?" for _ in icols)
    cur = conn.execute(f"INSERT INTO cadernos ({', '.join(icols)}) VALUES ({ph})", vals)
    novo_caderno_id = cur.lastrowid

    tem_cq = bool(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cadernos_questoes'").fetchone())
    if not tem_cq:
        return 1

    q_cols = _tabela_colunas(conn, "questoes")
    q_icols = [c for c in q_cols if c != "id"]
    qph = ", ".join("?" for _ in q_icols)
    assoc = conn.execute("SELECT questao_id, ordem FROM cadernos_questoes WHERE caderno_id = ?", (caderno_id,)).fetchall()
    for a in assoc:
        q = conn.execute("SELECT * FROM questoes WHERE id = ?", (a["questao_id"],)).fetchone()
        if not q:
            continue
        qvals = [destino_uid if c == "user_id" else q[c] for c in q_icols]
        qcur = conn.execute(f"INSERT INTO questoes ({', '.join(q_icols)}) VALUES ({qph})", qvals)
        conn.execute(
            "INSERT INTO cadernos_questoes (caderno_id, questao_id, ordem, added_at) VALUES (?, ?, ?, ?)",
            (novo_caderno_id, qcur.lastrowid, a["ordem"], now)
        )
    return 1


def _importar_vademecum(conn, origem_uid: int, destino_uid: int, lei_id_ref: str) -> int:
    """Copia uma lei específica + seus artigos."""
    try:
        lei_id = int(lei_id_ref)
    except (ValueError, TypeError):
        return 0

    lei = conn.execute("SELECT * FROM vademecum_leis WHERE id = ? AND user_id = ?", (lei_id, origem_uid)).fetchone()
    if not lei:
        return 0

    lei_cols = _tabela_colunas(conn, "vademecum_leis")
    icols = [c for c in lei_cols if c != "id"]
    vals = [destino_uid if c == "user_id" else lei[c] for c in icols]
    ph = ", ".join("?" for _ in icols)
    cur = conn.execute(f"INSERT INTO vademecum_leis ({', '.join(icols)}) VALUES ({ph})", vals)
    nova_lei_id = cur.lastrowid

    art_cols = _tabela_colunas(conn, "vademecum_artigos")
    if "lei_id" in art_cols:
        a_icols = [c for c in art_cols if c != "id"]
        aph = ", ".join("?" for _ in a_icols)
        artigos = conn.execute("SELECT * FROM vademecum_artigos WHERE lei_id = ?", (lei_id,)).fetchall()
        for art in artigos:
            avals = []
            for c in a_icols:
                if c == "user_id":
                    avals.append(destino_uid)
                elif c == "lei_id":
                    avals.append(nova_lei_id)
                elif c == "destacado":
                    avals.append(0)
                elif c == "anotacao":
                    avals.append("")
                else:
                    avals.append(art[c])
            conn.execute(f"INSERT INTO vademecum_artigos ({', '.join(a_icols)}) VALUES ({aph})", avals)
    return 1


def _importar_edital(conn, origem_uid: int, destino_uid: int, edital_ref: str) -> int:
    """Copia um edital (por nome, opcionalmente restrito a um cargo) + info +
    resumos + notas, resetando progresso. Ref no formato 'nome' ou 'nome::cargo'."""
    from utils import today_str as _today
    now = _today()
    edital_nome, cargo = _split_edital_ref(edital_ref)

    edital_cols = _tabela_colunas(conn, "edital")
    if "user_id" not in edital_cols:
        return 0
    insert_cols = [c for c in edital_cols if c != "id"]

    resets = {
        "status": "Não Iniciado", "horas_estudadas": 0, "proxima_revisao": "",
        "intervalo_revisao": 0, "easiness_factor_edital": 2.5, "repetitions_edital": 0,
        "stability_edital": 0, "difficulty_edital": 0, "fsrs_state_edital": 0,
        "mastery_level": 0, "mastery_updated_at": "", "arquivado": 0,
    }
    resets = {k: v for k, v in resets.items() if k in insert_cols}

    if cargo:
        rows = conn.execute("SELECT * FROM edital WHERE user_id = ? AND edital_nome = ? AND cargo = ?", (origem_uid, edital_nome, cargo)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM edital WHERE user_id = ? AND edital_nome = ?", (origem_uid, edital_nome)).fetchall()
    if not rows:
        return 0

    id_map = {}
    ph = ", ".join("?" for _ in insert_cols)
    for row in rows:
        vals = []
        for c in insert_cols:
            if c == "user_id":
                vals.append(destino_uid)
            elif c in resets:
                vals.append(resets[c])
            else:
                vals.append(row[c])
        cur = conn.execute(f"INSERT INTO edital ({', '.join(insert_cols)}) VALUES ({ph})", vals)
        id_map[row["id"]] = cur.lastrowid

    # edital_info do mesmo edital_nome
    try:
        info_cols = _tabela_colunas(conn, "edital_info")
        if "user_id" in info_cols:
            i_icols = [c for c in info_cols if c != "id"]
            iph = ", ".join("?" for _ in i_icols)
            infos = conn.execute("SELECT * FROM edital_info WHERE user_id = ? AND edital_nome = ?", (origem_uid, edital_nome)).fetchall()
            for info in infos:
                ivals = [destino_uid if c == "user_id" else info[c] for c in i_icols]
                conn.execute(f"INSERT INTO edital_info ({', '.join(i_icols)}) VALUES ({iph})", ivals)
    except Exception:
        pass

    # resumos e notas_topico dos tópicos copiados
    for tabela in ("resumos", "notas_topico"):
        try:
            cols = _tabela_colunas(conn, tabela)
            if "user_id" not in cols or "edital_id" not in cols:
                continue
            icols = [c for c in cols if c != "id"]
            tph = ", ".join("?" for _ in icols)
            for antigo_id, novo_id in id_map.items():
                deps = conn.execute(f"SELECT * FROM {tabela} WHERE user_id = ? AND edital_id = ?", (origem_uid, antigo_id)).fetchall()
                for d in deps:
                    vals = []
                    for c in icols:
                        if c == "user_id":
                            vals.append(destino_uid)
                        elif c == "edital_id":
                            vals.append(novo_id)
                        elif c == "created_at":
                            vals.append(now)
                        else:
                            vals.append(d[c])
                    conn.execute(f"INSERT INTO {tabela} ({', '.join(icols)}) VALUES ({tph})", vals)
        except Exception:
            pass

    return len(rows)
