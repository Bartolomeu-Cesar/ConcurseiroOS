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

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from database import get_db_session
from deps import get_user_id
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
    origem_uid: int          # de qual conta copiar o recurso
    ref: str = ""            # identificador do recurso (edital_nome, caderno_id, materia, lei_id)


# ==================== LISTAGEM PÚBLICA ====================

@router.get("", summary="Listar itens do catálogo público")
def listar_catalogo(
    categoria: str = "",
    tipo: str = "",
    busca: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista itens ativos do catálogo, com filtro opcional por categoria/tipo/busca."""
    query = "SELECT c.*, u.nome as curador_nome FROM catalogo_itens c LEFT JOIN users u ON c.curador_uid = u.id WHERE c.ativo = 1"
    params = []
    if categoria:
        query += " AND c.categoria = ?"
        params.append(categoria)
    if tipo:
        query += " AND c.tipo = ?"
        params.append(tipo)
    if busca:
        query += " AND (c.titulo LIKE ? OR c.descricao LIKE ?)"
        params.extend([f"%{busca}%", f"%{busca}%"])
    query += " ORDER BY c.downloads DESC, c.publicado_em DESC"

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
            "downloads": r["downloads"],
            "publicado_em": r["publicado_em"],
        })

    # Categorias disponíveis (para filtros)
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT categoria FROM catalogo_itens WHERE ativo = 1 ORDER BY categoria"
    ).fetchall()]

    return {"itens": itens, "total": len(itens), "categorias": cats}


@router.get("/categorias", summary="Categorias disponíveis no catálogo")
def listar_categorias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cats = [r[0] for r in conn.execute(
        "SELECT DISTINCT categoria FROM catalogo_itens WHERE ativo = 1 ORDER BY categoria"
    ).fetchall()]
    return {"categorias": cats}


# ==================== IMPORTAÇÃO (ESTUDANTE) ====================

@router.post("/{item_id}/importar", summary="Importar um item do catálogo para sua conta")
def importar_item(
    item_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Copia o material do catálogo para a conta do estudante logado."""
    item = conn.execute(
        "SELECT * FROM catalogo_itens WHERE id = ? AND ativo = 1", (item_id,)
    ).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado ou indisponível.")

    origem_uid = item["origem_uid"]
    if origem_uid == user_id:
        raise HTTPException(status_code=400, detail="Este material já é da sua conta.")

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
        copiados = _importar_deck(conn, "sumulas", origem_uid, user_id, "")
    else:
        raise HTTPException(status_code=400, detail=f"Tipo de item desconhecido: {tipo}")

    # Incrementar contador de downloads
    conn.execute("UPDATE catalogo_itens SET downloads = downloads + 1 WHERE id = ?", (item_id,))
    conn.commit()

    log.info(f"[catalogo] user={user_id} importou item={item_id} tipo={tipo} ({copiados} registros)")
    return {"ok": True, "tipo": tipo, "titulo": item["titulo"], "importados": copiados}


# ==================== PUBLICAÇÃO (ADMIN) ====================

@router.post("/publicar", summary="Publicar um recurso no catálogo (admin)")
def publicar_item(
    body: PublicarItem,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Publica um recurso da conta de origem no catálogo público."""
    _require_admin(conn, user_id)

    if body.tipo not in TIPOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Válidos: {list(TIPOS_VALIDOS)}")

    origem = conn.execute("SELECT id FROM users WHERE id = ?", (body.origem_uid,)).fetchone()
    if not origem:
        raise HTTPException(status_code=404, detail="Usuário de origem não encontrado.")

    # Validar que o recurso existe na origem
    if not _recurso_existe(conn, body.tipo, body.origem_uid, body.ref):
        raise HTTPException(status_code=404, detail="Recurso não encontrado na conta de origem.")

    conn.execute("""
        INSERT INTO catalogo_itens (tipo, titulo, descricao, categoria, curador_uid, origem_uid, ref, downloads, ativo, publicado_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?)
    """, (body.tipo, body.titulo.strip(), body.descricao.strip(), body.categoria.strip() or "Geral",
          user_id, body.origem_uid, str(body.ref), datetime.now(timezone.utc).isoformat()))
    conn.commit()

    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log.info(f"[catalogo] Publicado: id={new_id} tipo={body.tipo} titulo={body.titulo}")
    return {"ok": True, "id": new_id}


@router.delete("/{item_id}", summary="Remover item do catálogo (admin)")
def remover_item(item_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Remove (desativa) um item do catálogo."""
    _require_admin(conn, user_id)
    item = conn.execute("SELECT id FROM catalogo_itens WHERE id = ?", (item_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    conn.execute("UPDATE catalogo_itens SET ativo = 0 WHERE id = ?", (item_id,))
    conn.commit()
    log.info(f"[catalogo] Removido item={item_id}")
    return {"ok": True}


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

    Ex: para tipo=edital retorna os edital_nome; para deck_flashcards retorna
    as matérias; para vademecum retorna as leis (id + nome).
    """
    _require_admin(conn, user_id)
    refs = []
    try:
        if tipo == "edital":
            rows = conn.execute(
                "SELECT edital_nome, COUNT(*) as n FROM edital WHERE user_id = ? GROUP BY edital_nome ORDER BY edital_nome",
                (origem_uid,)
            ).fetchall()
            refs = [{"ref": r["edital_nome"], "label": f"{r['edital_nome']} ({r['n']} tópicos)"} for r in rows]
        elif tipo == "caderno":
            rows = conn.execute("SELECT id, nome FROM cadernos WHERE user_id = ? ORDER BY nome", (origem_uid,)).fetchall()
            refs = [{"ref": str(r["id"]), "label": r["nome"]} for r in rows]
        elif tipo == "vademecum":
            rows = conn.execute("SELECT id, nome, sigla FROM vademecum_leis WHERE user_id = ? ORDER BY nome", (origem_uid,)).fetchall()
            refs = [{"ref": str(r["id"]), "label": f"{r['nome']} ({r['sigla']})" if r["sigla"] else r["nome"]} for r in rows]
        elif tipo in ("deck_flashcards", "deck_questoes"):
            tabela = "flashcards" if tipo == "deck_flashcards" else "questoes"
            rows = conn.execute(
                f"SELECT materia, COUNT(*) as n FROM {tabela} WHERE user_id = ? AND materia != '' GROUP BY materia ORDER BY materia",
                (origem_uid,)
            ).fetchall()
            refs = [{"ref": r["materia"], "label": f"{r['materia']} ({r['n']})"} for r in rows]
        elif tipo == "deck_sumulas":
            n = conn.execute("SELECT COUNT(*) FROM sumulas WHERE user_id = ?", (origem_uid,)).fetchone()[0]
            if n > 0:
                refs = [{"ref": "", "label": f"Todas as súmulas ({n})"}]
    except Exception:
        refs = []
    return {"refs": refs}


# ==================== HELPERS ====================

def _tabela_colunas(conn, tabela: str) -> list:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})").fetchall()]


def _recurso_existe(conn, tipo: str, origem_uid: int, ref: str) -> bool:
    """Valida se o recurso referenciado existe na conta de origem."""
    try:
        if tipo == "edital":
            return conn.execute("SELECT 1 FROM edital WHERE user_id = ? AND edital_nome = ? LIMIT 1", (origem_uid, ref)).fetchone() is not None
        if tipo == "caderno":
            return conn.execute("SELECT 1 FROM cadernos WHERE user_id = ? AND id = ? LIMIT 1", (origem_uid, int(ref))).fetchone() is not None
        if tipo == "vademecum":
            return conn.execute("SELECT 1 FROM vademecum_leis WHERE user_id = ? AND id = ? LIMIT 1", (origem_uid, int(ref))).fetchone() is not None
        if tipo == "deck_flashcards":
            return conn.execute("SELECT 1 FROM flashcards WHERE user_id = ? AND materia = ? LIMIT 1", (origem_uid, ref)).fetchone() is not None
        if tipo == "deck_questoes":
            return conn.execute("SELECT 1 FROM questoes WHERE user_id = ? AND materia = ? LIMIT 1", (origem_uid, ref)).fetchone() is not None
        if tipo == "deck_sumulas":
            return conn.execute("SELECT 1 FROM sumulas WHERE user_id = ? LIMIT 1", (origem_uid,)).fetchone() is not None
    except (ValueError, TypeError):
        return False
    return False


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


def _importar_edital(conn, origem_uid: int, destino_uid: int, edital_nome: str) -> int:
    """Copia um edital específico (por nome) + info + resumos + notas, resetando progresso."""
    from utils import today_str as _today
    now = _today()

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
