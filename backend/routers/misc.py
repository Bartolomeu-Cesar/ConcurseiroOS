import random
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backup import create_backup, list_backups, restore_backup
from database import get_db_session, rebuild_search_index
from logger import log
from models import (
    BookmarkCreate,
    CadernoAddItem,
    CadernoCreate,
    FeynmanCreate,
    HealthResponse,
    NotaCreate,
    OkResponse,
    PlanejadorItem,
)
from settings import settings
from utils import today_str

router = APIRouter(prefix="", tags=["Utilidades"])

# Set from main.py
APP_START_TIME = None
DB_PATH = "./progress.db"


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/api/health", response_model=HealthResponse, summary="Health Check", description="Verifica o status da aplicação, conexão com banco e métricas básicas")
def health_check(conn=Depends(get_db_session)):
    """Retorna status do sistema, uptime, estado do banco de dados e métricas."""
    db_status = "connected"
    tables_count = 0
    edital_count = 0

    try:
        conn.execute("SELECT 1")
        tables_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        edital_count = conn.execute("SELECT COUNT(*) FROM edital").fetchone()[0]
    except Exception as e:
        db_status = "error"
        log.error(f"Health check DB error: {e}")

    uptime = time.time() - APP_START_TIME if APP_START_TIME else 0

    return {
        "status": "ok",
        "uptime_seconds": round(uptime, 1),
        "database": db_status,
        "version": settings.APP_VERSION,
        "tables_count": tables_count,
        "edital_count": edital_count,
        "timestamp": datetime.now().isoformat()
    }


# ============================================================
# BACKUP ENDPOINTS
# ============================================================

class RestoreRequest(BaseModel):
    filename: str


@router.get("/api/backups", summary="Listar backups", description="Lista todos os backups disponíveis com tamanho e data de criação")
def get_backups():
    """Lista backups disponíveis."""
    return list_backups()


@router.post("/api/backups", summary="Criar backup", description="Cria um backup manual do banco de dados")
def create_backup_endpoint():
    """Cria backup manual do banco de dados."""
    path = create_backup(DB_PATH)
    log.info(f"Manual backup created: {path}")
    return {"ok": True, "path": path}


@router.post("/api/backups/restore", summary="Restaurar backup", description="Restaura o banco de dados a partir de um backup específico")
def restore_backup_endpoint(body: RestoreRequest):
    """Restaura um backup específico."""
    success = restore_backup(body.filename, DB_PATH)
    if not success:
        raise HTTPException(status_code=404, detail="Backup não encontrado")
    log.info(f"Backup restored: {body.filename}")
    return {"ok": True, "restored": body.filename}


# ============================================================
# BUSCA GLOBAL (FTS5)
# ============================================================

@router.get("/api/search", summary="Busca global", description="Busca full-text em todos os conteúdos (edital, questões, flashcards, notas)")
def global_search(q: str = Query(..., min_length=1), conn=Depends(get_db_session)):
    """Busca full-text usando FTS5 em todos os conteúdos indexados."""
    try:
        rows = conn.execute("""
            SELECT source, source_id, title,
                   snippet(search_index, 3, '<b>', '</b>', '...', 32) as snippet,
                   rank
            FROM search_index
            WHERE search_index MATCH ?
            ORDER BY rank
            LIMIT 50
        """, (q,)).fetchall()
    except Exception as e:
        log.error(f"Search error: {e}")
        # Fallback: try with quoted query
        try:
            rows = conn.execute("""
                SELECT source, source_id, title,
                       snippet(search_index, 3, '<b>', '</b>', '...', 32) as snippet,
                       rank
                FROM search_index
                WHERE search_index MATCH ?
                ORDER BY rank
                LIMIT 50
            """, (f'"{q}"',)).fetchall()
        except Exception:
            return []

    return [
        {
            "source": r[0],
            "source_id": int(r[1]) if r[1] else None,
            "title": r[2],
            "snippet": r[3],
            "rank": r[4]
        }
        for r in rows
    ]


@router.post("/api/search/reindex", summary="Reindexar busca", description="Reconstrói o índice de busca full-text com todos os dados atuais")
def reindex_search(conn=Depends(get_db_session)):
    """Reconstrói o índice de busca FTS5."""
    rebuild_search_index(conn)
    log.info("Search index manually rebuilt")
    return {"ok": True, "message": "Índice reconstruído com sucesso"}


# ============================================================
# NOTIFICAÇÕES
# ============================================================

@router.get("/api/notificacoes")
def get_notificacoes(conn=Depends(get_db_session)):
    """Retorna lembretes/notificações pendentes"""
    notifs = []

    # Flashcards pendentes
    flash_pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)
    ).fetchone()[0]
    if flash_pendentes > 0:
        notifs.append({
            "tipo": "flashcard",
            "icon": "🧠",
            "msg": f"Você tem {flash_pendentes} flashcard(s) para revisar hoje!",
            "prioridade": "alta"
        })

    # Metas não cumpridas
    config = conn.execute("SELECT meta_horas, meta_questoes, meta_flashcards FROM metas_config WHERE id = 1").fetchone()
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()
    if config and hoje:
        horas_hoje = float(hoje["horas_estudadas"] or 0)
        questoes_hoje = int(hoje["questoes_resolvidas"] or 0)
        if horas_hoje < float(config["meta_horas"]):
            falta = float(config["meta_horas"]) - horas_hoje
            notifs.append({"tipo": "meta", "icon": "⏱", "msg": f"Faltam {falta:.1f}h para bater a meta de hoje", "prioridade": "media"})
        if questoes_hoje < int(config["meta_questoes"]):
            falta = int(config["meta_questoes"]) - questoes_hoje
            notifs.append({"tipo": "meta", "icon": "❓", "msg": f"Faltam {falta} questões para a meta de hoje", "prioridade": "media"})
    elif config:
        notifs.append({"tipo": "meta", "icon": "📖", "msg": "Você ainda não estudou hoje! Que tal começar?", "prioridade": "alta"})

    # Streak em risco
    ontem = (date.today() - timedelta(days=1)).isoformat()
    streak_ontem = conn.execute("SELECT * FROM streaks WHERE data = ?", (ontem,)).fetchone()
    if not hoje and streak_ontem:
        notifs.append({"tipo": "streak", "icon": "🔥", "msg": "Seu streak está em risco! Estude hoje para não perder.", "prioridade": "alta"})

    return notifs


# ============================================================
# PLANEJADOR SEMANAL
# ============================================================

@router.get("/api/planejador")
def get_planejador(conn=Depends(get_db_session)):
    rows = conn.execute("SELECT id, dia_semana, materia, horas FROM planejador_semanal ORDER BY dia_semana, id").fetchall()
    return [dict(r) for r in rows]


@router.post("/api/planejador")
def add_planejador(body: PlanejadorItem, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO planejador_semanal (dia_semana, materia, horas) VALUES (?, ?, ?)",
                       (body.dia_semana, body.materia, body.horas))
    conn.commit()
    log.info(f"Planejador item added: {body.materia} dia {body.dia_semana}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/planejador/{id}", response_model=OkResponse)
def delete_planejador(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM planejador_semanal WHERE id = ?", (id,))
    conn.commit()
    log.info(f"Planejador item deleted: {id}")
    return {"ok": True}


@router.post("/api/planejador/gerar", summary="Gerar planejador automaticamente",
             description="Distribui matérias do ciclo nos dias da semana com scoring inteligente")
def gerar_planejador(horas_dia: float = Query(default=3.0), conn=Depends(get_db_session)):
    """
    Gera planejador semanal inteligente. Cascata:
    1. Verifica se há ciclo ativo → se não, gera automaticamente dos editais
    2. Distribui matérias nos dias otimizando aprendizado:
       - Intercalação forçada (mesma matéria nunca em dias consecutivos)
       - Matérias difíceis (pior desempenho + menos horas) = mais frequentes
       - Espaçamento otimizado para retenção de longo prazo
       - Variação cognitiva (2-3 matérias/dia para evitar fadiga)
    """
    # 1. Verificar ciclo ativo
    ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 ORDER BY ordem, id").fetchall()

    ciclo_gerado = False
    if not ciclo:
        # Gerar ciclo automaticamente dos editais
        from routers.ciclo import _gerar_ciclo_automatico
        result = _gerar_ciclo_automatico(conn, horas_dia)
        if not result["ok"]:
            from fastapi import HTTPException as HE
            raise HE(status_code=400, detail="Não há matérias no edital para gerar o planejador")
        ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 ORDER BY ordem, id").fetchall()
        ciclo_gerado = True

    # 2. Calcular scoring por matéria (desempenho + horas + gaps)
    materias_scored = []
    for c in ciclo:
        mat = c["materia"]

        # Desempenho em questões
        desemp = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE q.materia = ?
        """, (mat,)).fetchone()
        total_q = desemp[0] or 0
        pct_acerto = (desemp[1] / total_q * 100) if total_q > 0 else 0

        # Horas já estudadas
        horas_estudadas = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ?", (mat,)
        ).fetchone()[0]

        # Tópicos pendentes
        pendentes = conn.execute(
            "SELECT COUNT(*) FROM edital WHERE materia = ? AND status != 'Concluído' AND arquivado = 0",
            (mat,)
        ).fetchone()[0]

        # Dias sem estudar
        ultima = conn.execute(
            "SELECT MAX(data) FROM sessoes_estudo WHERE materia = ?", (mat,)
        ).fetchone()[0]
        if ultima:
            try:
                dias_sem = (date.today() - date.fromisoformat(ultima)).days
            except (ValueError, TypeError):
                dias_sem = 30
        else:
            dias_sem = 999

        # SCORING para distribuição semanal:
        # Maior score = precisa aparecer mais vezes na semana
        score = 0.0
        score += (100 - pct_acerto) * 0.35  # Pior acerto = mais frequente (0-35)
        score += min(pendentes * 2, 25)      # Mais pendentes = mais urgente (0-25)
        score += c["horas_alvo"] * 5          # Respeitar proporção do ciclo (0-20)

        # Penalizar matérias com pouco estudo acumulado
        if horas_estudadas < c["horas_alvo"] * 2:
            score += 10  # Ainda precisa de muito estudo

        # Matéria nunca estudada / muito tempo sem estudar
        if dias_sem >= 999:
            score += 15
        elif dias_sem >= 7:
            score += 8
        elif dias_sem >= 3:
            score += 4

        # Nunca fez questão = risco, precisa praticar
        if total_q == 0:
            score += 8

        materias_scored.append({
            "materia": mat,
            "score": round(score, 2),
            "horas_alvo": c["horas_alvo"],
            "pct_acerto": round(pct_acerto, 1),
            "horas_estudadas": round(horas_estudadas, 1),
            "pendentes": pendentes,
            "dias_sem": dias_sem if dias_sem < 999 else None,
        })

    # 3. Ordenar por score (maior prioridade primeiro)
    materias_scored.sort(key=lambda x: -x["score"])

    # 4. Determinar frequência semanal por matéria
    # Dividir em tiers: difíceis 3x/semana, médias 2x, fáceis 1x
    total_mats = len(materias_scored)
    for i, m in enumerate(materias_scored):
        pos_relativa = i / max(total_mats, 1)
        if pos_relativa < 0.3:
            m["freq"] = 3  # Top 30% mais difíceis: 3x/semana
        elif pos_relativa < 0.65:
            m["freq"] = 2  # Meio: 2x/semana
        else:
            m["freq"] = 1  # Mais fáceis: 1x/semana

    # 5. Distribuir nos 6 dias úteis (domingo = descanso/revisão leve)
    DIAS_ESTUDO = 6  # Seg a Sáb
    SLOTS_POR_DIA = [3, 2, 3, 2, 3, 2]  # Alternância para variedade
    dias = [[] for _ in range(7)]  # 0=Seg, 6=Dom

    # Criar pool de matérias repetidas pela frequência
    pool = []
    for m in materias_scored:
        pool.extend([m] * m["freq"])

    # Distribuir com intercalação forçada
    last_day_materias = set()
    pool_idx = 0

    for dia in range(DIAS_ESTUDO):
        target_slots = SLOTS_POR_DIA[dia]
        used_today = set()
        attempts = 0
        search_idx = pool_idx

        while len(dias[dia]) < target_slots and attempts < len(pool) * 3:
            if not pool:
                break
            candidate = pool[search_idx % len(pool)]
            cand_name = candidate["materia"]

            # INTERCALAÇÃO: não repetir do dia anterior NEM no mesmo dia
            if cand_name not in last_day_materias and cand_name not in used_today:
                # Horas proporcionais ao score e tempo disponível
                horas_slot = round(horas_dia / target_slots, 1)
                # Matérias mais difíceis ganham um pouco mais de tempo
                if candidate["score"] > 50:
                    horas_slot = round(horas_slot * 1.2, 1)
                horas_slot = min(horas_slot, 2.0)  # Cap 2h por slot
                horas_slot = max(horas_slot, 0.5)  # Min 30min

                dias[dia].append({
                    "materia": cand_name,
                    "horas": horas_slot,
                    "score": candidate["score"],
                    "pct_acerto": candidate["pct_acerto"],
                })
                used_today.add(cand_name)
                pool_idx = (search_idx + 1) % len(pool)

            search_idx += 1
            attempts += 1

        # Fallback: se não preencheu, relaxar restrição
        if len(dias[dia]) < target_slots:
            for m in materias_scored:
                if m["materia"] not in used_today:
                    horas_slot = round(horas_dia / target_slots, 1)
                    dias[dia].append({
                        "materia": m["materia"],
                        "horas": horas_slot,
                        "score": m["score"],
                        "pct_acerto": m["pct_acerto"],
                    })
                    used_today.add(m["materia"])
                    if len(dias[dia]) >= target_slots:
                        break

        last_day_materias = used_today

    # Domingo: revisão leve das matérias mais fracas
    weakest = materias_scored[:2] if len(materias_scored) >= 2 else materias_scored
    for m in weakest:
        dias[6].append({
            "materia": m["materia"],
            "horas": 0.5,
            "score": m["score"],
            "pct_acerto": m["pct_acerto"],
        })

    # 6. Salvar no banco (limpar e recriar)
    conn.execute("DELETE FROM planejador_semanal")
    count = 0
    for dia_idx, slots in enumerate(dias):
        for slot in slots:
            conn.execute(
                "INSERT INTO planejador_semanal (dia_semana, materia, horas) VALUES (?, ?, ?)",
                (dia_idx, slot["materia"], slot["horas"])
            )
            count += 1
    conn.commit()

    log.info(f"Planejador gerado: {count} slots em 7 dias (ciclo_gerado={ciclo_gerado})")

    # Retornar resumo
    nomes_dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    resumo_dias = []
    for i, slots in enumerate(dias):
        resumo_dias.append({
            "dia": nomes_dias[i],
            "dia_semana": i,
            "materias": [{"materia": s["materia"], "horas": s["horas"]} for s in slots],
            "horas_total": round(sum(s["horas"] for s in slots), 1),
        })

    return {
        "ok": True,
        "ciclo_gerado": ciclo_gerado,
        "total_slots": count,
        "horas_dia": horas_dia,
        "dias": resumo_dias,
        "scoring": materias_scored[:10],  # Top 10 para referência
    }


# ============================================================
# CADERNOS
# ============================================================

@router.get("/api/cadernos")
def list_cadernos(conn=Depends(get_db_session)):
    cadernos = conn.execute("SELECT * FROM cadernos ORDER BY created_at DESC").fetchall()
    result = []
    for c in cadernos:
        count = conn.execute("SELECT COUNT(*) FROM caderno_itens WHERE caderno_id = ?", (c[0],)).fetchone()[0]
        d = dict(c)
        d["total_itens"] = count
        result.append(d)
    return result


@router.post("/api/cadernos")
def create_caderno(body: CadernoCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO cadernos (nome, descricao, created_at) VALUES (?, ?, ?)",
                       (body.nome, body.descricao, datetime.now().isoformat()))
    conn.commit()
    log.info(f"Caderno created: {body.nome}")
    return {"id": cur.lastrowid, "ok": True}


@router.post("/api/cadernos/{id}/adicionar")
def add_to_caderno(id: int, body: CadernoAddItem, conn=Depends(get_db_session)):
    conn.execute("INSERT INTO caderno_itens (caderno_id, tipo, item_id) VALUES (?, ?, ?)",
                 (id, body.tipo, body.item_id))
    conn.commit()
    return {"ok": True}


@router.get("/api/cadernos/{id}")
def get_caderno(id: int, conn=Depends(get_db_session)):
    caderno = conn.execute("SELECT * FROM cadernos WHERE id = ?", (id,)).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    itens = conn.execute("SELECT * FROM caderno_itens WHERE caderno_id = ?", (id,)).fetchall()
    return {"caderno": dict(caderno), "itens": [dict(i) for i in itens]}


@router.delete("/api/cadernos/{id}")
def delete_caderno(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM caderno_itens WHERE caderno_id = ?", (id,))
    conn.execute("DELETE FROM cadernos WHERE id = ?", (id,))
    conn.commit()
    log.info(f"Caderno deleted: {id}")
    return {"ok": True}


# ============================================================
# BOOKMARKS
# ============================================================

@router.get("/api/bookmarks/{path:path}")
def get_bookmarks(path: str, conn=Depends(get_db_session)):
    rows = conn.execute("SELECT * FROM bookmarks_pdf WHERE pdf_path = ? ORDER BY pagina", (path,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/bookmarks")
def create_bookmark(body: BookmarkCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO bookmarks_pdf (pdf_path, pagina, label, cor, created_at) VALUES (?, ?, ?, ?, ?)",
                       (body.pdf_path, body.pagina, body.label, body.cor, datetime.now().isoformat()))
    conn.commit()
    log.info(f"Bookmark created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/bookmarks/{id}", response_model=OkResponse)
def delete_bookmark(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM bookmarks_pdf WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}


# ============================================================
# FEYNMAN
# ============================================================

@router.get("/api/feynman/{edital_id}")
def get_feynman(edital_id: int, conn=Depends(get_db_session)):
    """Retorna explicações Feynman de um tópico"""
    rows = conn.execute("SELECT * FROM feynman WHERE edital_id = ? ORDER BY created_at DESC", (edital_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/feynman")
def create_feynman(body: FeynmanCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO feynman (edital_id, explicacao, created_at) VALUES (?, ?, ?)",
                       (body.edital_id, body.explicacao, datetime.now().isoformat()))
    conn.commit()
    log.info(f"Feynman explanation added for edital_id={body.edital_id}")
    return {"id": cur.lastrowid, "ok": True}


# ============================================================
# NOTAS POR PDF
# ============================================================

@router.get("/api/notas/{path:path}")
def get_notas_pdf(path: str, conn=Depends(get_db_session)):
    rows = conn.execute("SELECT * FROM notas_pdf WHERE pdf_path = ? ORDER BY pagina, id", (path,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/notas")
def create_nota(body: NotaCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at) VALUES (?, ?, ?, ?)",
                       (body.pdf_path, body.pagina, body.conteudo, datetime.now().isoformat()))
    conn.commit()
    log.info(f"Nota created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas/{id}", response_model=OkResponse)
def delete_nota(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM notas_pdf WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}


# ============================================================
# MODO FOCO
# ============================================================

@router.get("/api/modo-foco/status")
def get_modo_foco():
    """Retorna status do modo foco (controlado pelo frontend)"""
    return {"disponivel": True, "dica": "Use F11 para tela cheia + o botão Modo Foco na interface"}


# ============================================================
# COUNTDOWN
# ============================================================

@router.get("/api/countdown")
def get_countdown(conn=Depends(get_db_session)):
    """Retorna countdowns para as próximas provas"""
    try:
        rows = conn.execute("""
            SELECT edital_nome, cargo, data_prova_objetiva, data_prova_discursiva, local_prova
            FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital'
            ORDER BY data_prova_objetiva
        """).fetchall()
    except Exception as e:
        log.warning(f"Could not fetch countdown data: {e}")
        rows = []
    result = []
    for r in rows:
        result.append({
            "edital": r[0],
            "cargo": r[1],
            "data_objetiva": r[2],
            "data_discursiva": r[3],
            "local": r[4]
        })
    return result


# ============================================================
# ESTUDO ALEATÓRIO
# ============================================================

@router.get("/api/estudo/aleatorio")
def topico_aleatorio(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Sorteia um tópico aleatório não concluído para estudo"""
    query = "SELECT id, edital_nome, cargo, materia, topico FROM edital WHERE status != 'Concluído'"
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    rows = conn.execute(query, params).fetchall()
    if not rows:
        return {"message": "Todos os tópicos foram concluídos! 🎉"}
    chosen = random.choice(rows)
    return dict(chosen)


# ============================================================
# REGISTRAR SESSÃO DE ESTUDO (Timer genérico)
# ============================================================

class SessaoEstudoRegistrar(BaseModel):
    horas: float
    materia: str = "Leitura PDF"
    tipo: str = "timer"


@router.post("/api/sessoes-estudo/registrar", summary="Registrar sessão de estudo",
             description="Registra tempo estudado pelo timer genérico")
def registrar_sessao_estudo(body: SessaoEstudoRegistrar, conn=Depends(get_db_session)):
    """Registra uma sessão de estudo (usada pelo timer principal e viewer)."""
    if body.horas <= 0:
        return {"ok": False, "message": "Tempo inválido"}
    conn.execute(
        "INSERT INTO sessoes_estudo (materia, horas, data, tipo) VALUES (?, ?, ?, ?)",
        (body.materia, body.horas, today_str(), body.tipo)
    )
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas) VALUES (?, ?)
        ON CONFLICT(data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, body.horas))
    conn.commit()
    log.info(f"Session registered: {body.horas:.2f}h ({body.materia})")
    return {"ok": True, "horas": body.horas}
