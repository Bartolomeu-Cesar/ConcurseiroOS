"""Vade Mecum Digital — Leis indexadas com busca full-text, anotações e links com questões."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from utils import today_str

router = APIRouter(prefix="/api/vademecum", tags=["Vade Mecum"])


def _ensure_tables(conn):
    """Garante que as tabelas do vade mecum existem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vademecum_leis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            nome TEXT NOT NULL,
            sigla TEXT DEFAULT '',
            numero TEXT DEFAULT '',
            data_publicacao TEXT DEFAULT '',
            ementa TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vademecum_leis_user ON vademecum_leis(user_id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS vademecum_artigos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lei_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            numero TEXT NOT NULL,
            caput TEXT NOT NULL,
            paragrafos TEXT DEFAULT '',
            incisos TEXT DEFAULT '',
            alineas TEXT DEFAULT '',
            capitulo TEXT DEFAULT '',
            secao TEXT DEFAULT '',
            destacado INTEGER DEFAULT 0,
            anotacao TEXT DEFAULT '',
            FOREIGN KEY (lei_id) REFERENCES vademecum_leis(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vademecum_artigos_lei ON vademecum_artigos(lei_id, user_id)")

    # FTS5 para busca full-text
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vademecum_fts USING fts5(
                numero, caput, paragrafos, incisos, content=vademecum_artigos, content_rowid=id
            )
        """)
    except Exception:
        pass

    conn.commit()


# ============================================================
# CRUD LEIS
# ============================================================

@router.get("/leis", summary="Listar leis cadastradas")
def listar_leis(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    _ensure_tables(conn)
    rows = conn.execute("""
        SELECT l.*, COUNT(a.id) as total_artigos
        FROM vademecum_leis l
        LEFT JOIN vademecum_artigos a ON a.lei_id = l.id AND a.user_id = l.user_id
        WHERE l.user_id = ?
        GROUP BY l.id
        ORDER BY l.nome
    """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/leis", summary="Cadastrar nova lei")
def criar_lei(
    nome: str = Body(...),
    sigla: str = Body(""),
    numero: str = Body(""),
    ementa: str = Body(""),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)
    cur = conn.execute("""
        INSERT INTO vademecum_leis (user_id, nome, sigla, numero, ementa, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, nome, sigla, numero, ementa, datetime.now().isoformat()))
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/leis/{lei_id}", summary="Remover lei")
def remover_lei(lei_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    _ensure_tables(conn)
    conn.execute("DELETE FROM vademecum_artigos WHERE lei_id = ? AND user_id = ?", (lei_id, user_id))
    conn.execute("DELETE FROM vademecum_leis WHERE id = ? AND user_id = ?", (lei_id, user_id))
    conn.commit()
    return {"ok": True}


# ============================================================
# CRUD ARTIGOS
# ============================================================

@router.get("/leis/{lei_id}/artigos", summary="Listar artigos de uma lei")
def listar_artigos(
    lei_id: int,
    capitulo: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)
    query = "SELECT * FROM vademecum_artigos WHERE lei_id = ? AND user_id = ?"
    params = [lei_id, user_id]
    if capitulo:
        query += " AND capitulo = ?"
        params.append(capitulo)
    query += " ORDER BY CAST(REPLACE(numero, 'Art. ', '') AS INTEGER)"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@router.post("/leis/{lei_id}/artigos", summary="Adicionar artigo")
def criar_artigo(
    lei_id: int,
    numero: str = Body(...),
    caput: str = Body(...),
    paragrafos: str = Body(""),
    incisos: str = Body(""),
    capitulo: str = Body(""),
    secao: str = Body(""),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)
    cur = conn.execute("""
        INSERT INTO vademecum_artigos (lei_id, user_id, numero, caput, paragrafos, incisos, capitulo, secao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (lei_id, user_id, numero, caput, paragrafos, incisos, capitulo, secao))
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.post("/leis/{lei_id}/importar-texto", summary="Importar lei a partir de texto",
             description="Importa artigos automaticamente a partir de texto colado (detecta Art. X, §, incisos).")
def importar_lei_texto(
    lei_id: int,
    texto: str = Body(..., embed=True),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Parser que detecta artigos, parágrafos e incisos no texto."""
    import re
    _ensure_tables(conn)

    # Dividir por artigos
    art_pattern = r'(?:^|\n)\s*(Art\.?\s*\d+[º°]?[\-A-Z]?\.?)\s*[-–.]?\s*'
    partes = re.split(art_pattern, texto)

    artigos_importados = 0
    capitulo_atual = ""
    secao_atual = ""

    i = 1  # partes[0] é o preâmbulo
    while i < len(partes) - 1:
        numero = partes[i].strip()
        conteudo = partes[i + 1].strip() if i + 1 < len(partes) else ""
        i += 2

        if not conteudo:
            continue

        # Separar caput dos parágrafos/incisos
        linhas = conteudo.split('\n')
        caput_linhas = []
        paragrafos = []
        incisos = []

        for linha in linhas:
            linha = linha.strip()
            if not linha:
                continue
            # Detectar capítulo/seção
            if re.match(r'^(?:CAPÍTULO|CAPITULO|CAP\.)\s', linha, re.IGNORECASE):
                capitulo_atual = linha
                continue
            if re.match(r'^(?:SEÇÃO|SECAO|Seção)\s', linha, re.IGNORECASE):
                secao_atual = linha
                continue
            # Parágrafo
            if re.match(r'^(?:§\s*\d+|Parágrafo único)', linha):
                paragrafos.append(linha)
            # Inciso (I, II, III, IV...)
            elif re.match(r'^[IVXLCDM]+\s*[-–.]', linha):
                incisos.append(linha)
            # Alínea (a), b), c)...)
            elif re.match(r'^[a-z]\)', linha):
                incisos.append(linha)
            else:
                caput_linhas.append(linha)

        caput = ' '.join(caput_linhas).strip()
        if not caput or len(caput) < 5:
            continue

        conn.execute("""
            INSERT INTO vademecum_artigos (lei_id, user_id, numero, caput, paragrafos, incisos, capitulo, secao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (lei_id, user_id, numero, caput, '\n'.join(paragrafos), '\n'.join(incisos), capitulo_atual, secao_atual))
        artigos_importados += 1

    conn.commit()
    log.info(f"Vade mecum: {artigos_importados} artigos importados para lei {lei_id}")
    return {"ok": True, "artigos_importados": artigos_importados}


# ============================================================
# BUSCA FULL-TEXT
# ============================================================

@router.get("/busca", summary="Buscar no vade mecum",
            description="Busca full-text em todos os artigos de todas as leis cadastradas.")
def buscar(
    q: str = Query(..., min_length=2, description="Termo de busca"),
    lei_id: int = Query(0, description="Filtrar por lei (0 = todas)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)

    # Busca por LIKE (funciona sem FTS5)
    termo = f"%{q}%"
    query = """
        SELECT a.id, a.numero, a.caput, a.paragrafos, a.incisos, a.capitulo,
               a.destacado, a.anotacao, l.nome as lei_nome, l.sigla as lei_sigla
        FROM vademecum_artigos a
        JOIN vademecum_leis l ON l.id = a.lei_id
        WHERE a.user_id = ? AND (a.caput LIKE ? OR a.paragrafos LIKE ? OR a.incisos LIKE ? OR a.numero LIKE ?)
    """
    params = [user_id, termo, termo, termo, termo]

    if lei_id > 0:
        query += " AND a.lei_id = ?"
        params.append(lei_id)

    query += " ORDER BY l.nome, CAST(REPLACE(a.numero, 'Art. ', '') AS INTEGER) LIMIT 50"
    rows = conn.execute(query, params).fetchall()

    return {
        "resultados": [dict(r) for r in rows],
        "total": len(rows),
        "termo": q,
    }


# ============================================================
# ANOTAÇÕES E DESTAQUES
# ============================================================

@router.put("/artigos/{artigo_id}/anotar", summary="Anotar ou destacar artigo")
def anotar_artigo(
    artigo_id: int,
    anotacao: str = Body(""),
    destacado: bool = Body(False),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)
    conn.execute("""
        UPDATE vademecum_artigos SET anotacao = ?, destacado = ?
        WHERE id = ? AND user_id = ?
    """, (anotacao, int(destacado), artigo_id, user_id))
    conn.commit()
    return {"ok": True}


@router.get("/destaques", summary="Artigos destacados")
def artigos_destacados(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    _ensure_tables(conn)
    rows = conn.execute("""
        SELECT a.id, a.numero, a.caput, a.anotacao, l.nome as lei_nome, l.sigla
        FROM vademecum_artigos a
        JOIN vademecum_leis l ON l.id = a.lei_id
        WHERE a.user_id = ? AND a.destacado = 1
        ORDER BY l.nome, a.numero
    """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# LINK ARTIGO ↔ QUESTÕES
# ============================================================

@router.get("/artigos/{artigo_id}/questoes-relacionadas", summary="Questões que citam este artigo")
def questoes_relacionadas(
    artigo_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Busca questões cujo enunciado menciona o artigo."""
    _ensure_tables(conn)
    artigo = conn.execute(
        "SELECT numero, caput FROM vademecum_artigos WHERE id = ? AND user_id = ?",
        (artigo_id, user_id)
    ).fetchone()
    if not artigo:
        raise HTTPException(404, "Artigo não encontrado")

    # Buscar por número do artigo no enunciado das questões
    numero = artigo["numero"].replace("Art. ", "").replace("º", "").strip()
    termo = f"%art%{numero}%"
    questoes = conn.execute("""
        SELECT id, enunciado, materia, resposta_correta
        FROM questoes WHERE user_id = ? AND enunciado LIKE ?
        LIMIT 10
    """, (user_id, termo)).fetchall()

    return {
        "artigo": artigo["numero"],
        "questoes": [dict(q) for q in questoes],
        "total": len(questoes),
    }
