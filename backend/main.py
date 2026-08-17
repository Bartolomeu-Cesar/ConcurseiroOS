import mimetypes

# Força o MIME type correto para arquivos .mjs e .js (necessário para PDF.js)
mimetypes.add_type("application/javascript", ".mjs", strict=True)
mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("text/javascript", ".mjs", strict=True)
mimetypes.add_type("text/javascript", ".js", strict=True)

import os
import sqlite3
import json
import tempfile
import mimetypes
import random

from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader

PDF_ROOT = os.environ.get("PDF_ROOT", "./pdfs")
DB_PATH = "./progress.db"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Tabela de progresso de PDFs (existente)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            path TEXT PRIMARY KEY,
            current_page INTEGER DEFAULT 1,
            total_pages INTEGER DEFAULT 1
        )
    """)

    # Edital verticalizado
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edital (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_nome TEXT DEFAULT 'Geral',
            cargo TEXT DEFAULT '',
            materia TEXT NOT NULL,
            topico TEXT NOT NULL,
            status TEXT DEFAULT 'Não Iniciado',
            horas_estudadas REAL DEFAULT 0.0
        )
    """)
    # Migração: adicionar colunas se não existirem
    try:
        conn.execute("SELECT edital_nome FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN edital_nome TEXT DEFAULT 'Geral'")
    try:
        conn.execute("SELECT cargo FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN cargo TEXT DEFAULT ''")

    # Flashcards SRS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pergunta TEXT NOT NULL,
            resposta TEXT NOT NULL,
            proxima_revisao TEXT NOT NULL,
            intervalo_dias INTEGER DEFAULT 1
        )
    """)

    # Banco de Questões
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            materia TEXT NOT NULL,
            topico TEXT DEFAULT '',
            enunciado TEXT NOT NULL,
            alternativa_a TEXT NOT NULL,
            alternativa_b TEXT NOT NULL,
            alternativa_c TEXT NOT NULL,
            alternativa_d TEXT NOT NULL,
            alternativa_e TEXT DEFAULT '',
            resposta_correta TEXT NOT NULL,
            explicacao TEXT DEFAULT '',
            dificuldade TEXT DEFAULT 'Médio',
            created_at TEXT NOT NULL
        )
    """)

    # Respostas do usuário nas questões
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questoes_respostas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            questao_id INTEGER NOT NULL,
            resposta_usuario TEXT NOT NULL,
            acertou INTEGER NOT NULL,
            tempo_segundos INTEGER DEFAULT 0,
            data TEXT NOT NULL,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)

    # Simulados
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            tempo_limite_min INTEGER DEFAULT 60,
            status TEXT DEFAULT 'pendente',
            nota REAL DEFAULT 0.0,
            total_questoes INTEGER DEFAULT 0,
            acertos INTEGER DEFAULT 0,
            tempo_gasto_seg INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            finalizado_at TEXT DEFAULT ''
        )
    """)

    # Questões vinculadas a simulados
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulado_questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simulado_id INTEGER NOT NULL,
            questao_id INTEGER NOT NULL,
            ordem INTEGER DEFAULT 0,
            resposta_usuario TEXT DEFAULT '',
            acertou INTEGER DEFAULT -1,
            FOREIGN KEY (simulado_id) REFERENCES simulados(id),
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)

    # Ciclo de Estudos
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ciclo_estudos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            materia TEXT NOT NULL,
            horas_alvo REAL DEFAULT 1.0,
            horas_cumpridas REAL DEFAULT 0.0,
            ordem INTEGER DEFAULT 0,
            ativo INTEGER DEFAULT 1
        )
    """)

    # Registro de sessões de estudo (alimenta dashboard)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessoes_estudo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            materia TEXT NOT NULL,
            horas REAL NOT NULL,
            data TEXT NOT NULL,
            tipo TEXT DEFAULT 'edital'
        )
    """)

    # Streaks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT UNIQUE NOT NULL,
            horas_estudadas REAL DEFAULT 0.0,
            questoes_resolvidas INTEGER DEFAULT 0,
            flashcards_revisados INTEGER DEFAULT 0
        )
    """)

    # Metas diárias
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metas_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            meta_horas REAL DEFAULT 3.0,
            meta_questoes INTEGER DEFAULT 30,
            meta_flashcards INTEGER DEFAULT 10,
            meta_paginas INTEGER DEFAULT 20
        )
    """)

    # Notas/Anotações por PDF
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notas_pdf (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_path TEXT NOT NULL,
            pagina INTEGER DEFAULT 1,
            conteudo TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Inserir config padrão de metas se não existir
    conn.execute("""
        INSERT OR IGNORE INTO metas_config (id, meta_horas, meta_questoes, meta_flashcards, meta_paginas)
        VALUES (1, 3.0, 30, 10, 20)
    """)

    # Metadados dos editais (datas, locais, horários)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edital_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_nome TEXT NOT NULL,
            cargo TEXT DEFAULT '',
            orgao TEXT DEFAULT '',
            banca TEXT DEFAULT '',
            vagas TEXT DEFAULT '',
            subsidio TEXT DEFAULT '',
            inscricoes TEXT DEFAULT '',
            data_prova_objetiva TEXT DEFAULT '',
            data_prova_discursiva TEXT DEFAULT '',
            horario TEXT DEFAULT '',
            local_prova TEXT DEFAULT '',
            taxa_inscricao TEXT DEFAULT '',
            link_edital TEXT DEFAULT '',
            observacoes TEXT DEFAULT ''
        )
    """)

    conn.commit()
    return conn


def today_str():
    return date.today().isoformat()


# ============================================================
# PDF PROGRESS (existente)
# ============================================================

def get_pdf_pages(filepath: str) -> int:
    try:
        return len(PdfReader(filepath).pages)
    except Exception:
        return 1


def build_tree(root: str) -> list:
    result = []
    root_path = Path(root).resolve()
    for entry in sorted(Path(root).iterdir()):
        if entry.is_dir():
            children = build_tree(str(entry))
            if children:
                result.append({"type": "folder", "name": entry.name, "children": children})
        elif entry.suffix.lower() == ".pdf" and ":" not in entry.name:
            rel = str(entry.resolve().relative_to(root_path))
            result.append({"type": "pdf", "name": entry.name, "path": rel})
    return result


@app.get("/api/tree")
def get_tree():
    if not Path(PDF_ROOT).exists():
        return []
    return build_tree(PDF_ROOT)


@app.get("/api/progress/{path:path}")
def get_progress(path: str):
    conn = get_db()
    row = conn.execute("SELECT current_page, total_pages FROM progress WHERE path = ?", (path,)).fetchone()
    conn.close()
    if row:
        return {"current_page": row[0], "total_pages": row[1]}
    total = get_pdf_pages(str(Path(PDF_ROOT) / path))
    return {"current_page": 1, "total_pages": total}


class ProgressUpdate(BaseModel):
    current_page: int
    total_pages: int


@app.post("/api/progress/{path:path}")
def save_progress(path: str, body: ProgressUpdate):
    conn = get_db()
    conn.execute("""
        INSERT INTO progress (path, current_page, total_pages)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET current_page=excluded.current_page, total_pages=excluded.total_pages
    """, (path, body.current_page, body.total_pages))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/progress-bulk")
def get_progress_bulk():
    conn = get_db()
    rows = conn.execute("SELECT path, current_page, total_pages FROM progress").fetchall()
    conn.close()
    return {r[0]: {"current_page": r[1], "total_pages": r[2]} for r in rows}


@app.get("/pdf/{path:path}")
def serve_pdf(path: str):
    full = Path(PDF_ROOT) / path
    if not full.exists() or full.suffix.lower() != ".pdf":
        raise HTTPException(404)
    return FileResponse(str(full), media_type="application/pdf")


@app.get("/api/export")
def export_progress():
    conn = get_db()
    rows = conn.execute("SELECT path, current_page, total_pages FROM progress").fetchall()
    conn.close()
    data = [{"path": r[0], "current_page": r[1], "total_pages": r[2]} for r in rows]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="leitor_progress.json", background=None)


@app.post("/api/import")
async def import_progress(file: UploadFile = File(...)):
    content = await file.read()
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(400, "Arquivo JSON inválido")
    conn = get_db()
    for item in data:
        conn.execute("""
            INSERT INTO progress (path, current_page, total_pages)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                current_page = MAX(current_page, excluded.current_page),
                total_pages  = excluded.total_pages
        """, (item["path"], item["current_page"], item["total_pages"]))
    conn.commit()
    conn.close()
    return {"ok": True, "imported": len(data)}


# ============================================================
# EDITAL
# ============================================================

class EditalCreate(BaseModel):
    materia: str
    topico: str
    edital_nome: str = "Geral"
    cargo: str = ""


class EditalHoras(BaseModel):
    horas: float


@app.get("/api/edital/nomes")
def list_edital_nomes():
    """Lista hierarquia: concursos > cargos com contagens"""
    conn = get_db()
    rows = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos
        FROM edital GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """).fetchall()
    conn.close()
    # Agrupar por concurso
    tree = {}
    for r in rows:
        concurso = r[0]
        if concurso not in tree:
            tree[concurso] = {"concurso": concurso, "cargos": [], "total": 0, "concluidos": 0}
        tree[concurso]["cargos"].append({"cargo": r[1], "total": r[2], "concluidos": r[3]})
        tree[concurso]["total"] += r[2]
        tree[concurso]["concluidos"] += r[3]
    return list(tree.values())


@app.get("/api/edital/info")
def get_edital_info(edital_nome: str = ""):
    """Retorna metadados dos editais (datas, locais, horários)"""
    conn = get_db()
    if edital_nome:
        rows = conn.execute("SELECT * FROM edital_info WHERE edital_nome = ?", (edital_nome,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM edital_info ORDER BY edital_nome, cargo").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/edital")
def list_edital(edital_nome: str = "", cargo: str = ""):
    conn = get_db()
    query = "SELECT id, edital_nome, cargo, materia, topico, status, horas_estudadas FROM edital WHERE 1=1"
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " ORDER BY edital_nome, cargo, materia, id"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/edital")
def create_edital(body: EditalCreate):
    conn = get_db()
    cur = conn.execute("INSERT INTO edital (edital_nome, cargo, materia, topico) VALUES (?, ?, ?, ?)", (body.edital_nome, body.cargo, body.materia, body.topico))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "edital_nome": body.edital_nome, "cargo": body.cargo, "materia": body.materia, "topico": body.topico, "status": "Não Iniciado", "horas_estudadas": 0.0}


@app.put("/api/edital/{id}/status")
def toggle_edital_status(id: int):
    cycle = ["Não Iniciado", "Em Andamento", "Concluído"]
    conn = get_db()
    row = conn.execute("SELECT status FROM edital WHERE id = ?", (id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    current = row[0]
    next_status = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else cycle[0]
    conn.execute("UPDATE edital SET status = ? WHERE id = ?", (next_status, id))
    conn.commit()
    conn.close()
    return {"id": id, "status": next_status}


@app.put("/api/edital/{id}/horas")
def add_edital_horas(id: int, body: EditalHoras):
    conn = get_db()
    row = conn.execute("SELECT horas_estudadas, materia FROM edital WHERE id = ?", (id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    new_horas = row[0] + body.horas
    conn.execute("UPDATE edital SET horas_estudadas = ? WHERE id = ?", (new_horas, id))
    # Registrar sessão de estudo
    conn.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo) VALUES (?, ?, ?, 'edital')",
                 (row[1], body.horas, today_str()))
    # Atualizar streak do dia
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas) VALUES (?, ?)
        ON CONFLICT(data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, body.horas))
    conn.commit()
    conn.close()
    return {"id": id, "horas_estudadas": new_horas}


@app.delete("/api/edital/{id}")
def delete_edital(id: int):
    conn = get_db()
    conn.execute("DELETE FROM edital WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============================================================
# FLASHCARDS SRS
# ============================================================

class FlashcardCreate(BaseModel):
    pergunta: str
    resposta: str


class FlashcardReview(BaseModel):
    acertou: bool


@app.get("/api/flashcards")
def list_flashcards():
    conn = get_db()
    rows = conn.execute("SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias FROM flashcards").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/flashcards/today")
def get_flashcards_today():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias FROM flashcards WHERE proxima_revisao <= ?",
        (today_str(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/flashcards")
def create_flashcard(body: FlashcardCreate):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao) VALUES (?, ?, ?)",
        (body.pergunta, body.resposta, today_str())
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "pergunta": body.pergunta, "resposta": body.resposta, "proxima_revisao": today_str(), "intervalo_dias": 1}


@app.post("/api/flashcards/{id}/review")
def review_flashcard(id: int, body: FlashcardReview):
    conn = get_db()
    row = conn.execute("SELECT intervalo_dias FROM flashcards WHERE id = ?", (id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    new_intervalo = row[0] * 2 if body.acertou else 1
    proxima = (date.today() + timedelta(days=new_intervalo)).isoformat()
    conn.execute("UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ? WHERE id = ?",
                 (new_intervalo, proxima, id))
    # Atualizar streak
    conn.execute("""
        INSERT INTO streaks (data, flashcards_revisados) VALUES (?, 1)
        ON CONFLICT(data) DO UPDATE SET flashcards_revisados = flashcards_revisados + 1
    """, (today_str(),))
    conn.commit()
    conn.close()
    return {"id": id, "intervalo_dias": new_intervalo, "proxima_revisao": proxima}


@app.delete("/api/flashcards/{id}")
def delete_flashcard(id: int):
    conn = get_db()
    conn.execute("DELETE FROM flashcards WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============================================================
# BANCO DE QUESTÕES
# ============================================================

class QuestaoCreate(BaseModel):
    materia: str
    topico: str = ""
    enunciado: str
    alternativa_a: str
    alternativa_b: str
    alternativa_c: str
    alternativa_d: str
    alternativa_e: str = ""
    resposta_correta: str
    explicacao: str = ""
    dificuldade: str = "Médio"


class QuestaoResposta(BaseModel):
    resposta: str
    tempo_segundos: int = 0


@app.get("/api/questoes")
def list_questoes(materia: str = "", topico: str = ""):
    conn = get_db()
    query = "SELECT * FROM questoes WHERE 1=1"
    params = []
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    if topico:
        query += " AND topico = ?"
        params.append(topico)
    query += " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/questoes/materias")
def list_questoes_materias():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT materia FROM questoes ORDER BY materia").fetchall()
    conn.close()
    return [r[0] for r in rows]


# Caderno de Erros (DEVE ficar antes de /api/questoes/{id})
@app.get("/api/questoes/erros/caderno")
def caderno_erros():
    conn = get_db()
    rows = conn.execute("""
        SELECT q.id, q.materia, q.topico, q.enunciado, q.resposta_correta, qr.resposta_usuario, qr.data
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0
        ORDER BY qr.data DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Estatísticas de questões (DEVE ficar antes de /api/questoes/{id})
@app.get("/api/questoes/stats/geral")
def questoes_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]
    por_materia = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
        ORDER BY q.materia
    """).fetchall()
    conn.close()
    return {
        "total_resolvidas": total,
        "total_acertos": acertos,
        "percentual": round((acertos / total * 100) if total > 0 else 0, 1),
        "por_materia": [dict(r) for r in por_materia]
    }


@app.get("/api/questoes/{id}")
def get_questao(id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM questoes WHERE id = ?", (id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    return dict(row)


@app.post("/api/questoes")
def create_questao(body: QuestaoCreate):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
            alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (body.materia, body.topico, body.enunciado, body.alternativa_a, body.alternativa_b,
          body.alternativa_c, body.alternativa_d, body.alternativa_e, body.resposta_correta,
          body.explicacao, body.dificuldade, today_str()))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "ok": True}


@app.post("/api/questoes/{id}/responder")
def responder_questao(id: int, body: QuestaoResposta):
    conn = get_db()
    questao = conn.execute("SELECT resposta_correta FROM questoes WHERE id = ?", (id,)).fetchone()
    if not questao:
        conn.close()
        raise HTTPException(404)
    acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
    conn.execute("""
        INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data)
        VALUES (?, ?, ?, ?, ?)
    """, (id, body.resposta, acertou, body.tempo_segundos, today_str()))
    # Atualizar streak
    conn.execute("""
        INSERT INTO streaks (data, questoes_resolvidas) VALUES (?, 1)
        ON CONFLICT(data) DO UPDATE SET questoes_resolvidas = questoes_resolvidas + 1
    """, (today_str(),))
    conn.commit()
    conn.close()
    return {"acertou": bool(acertou), "resposta_correta": questao[0]}


@app.delete("/api/questoes/{id}")
def delete_questao(id: int):
    conn = get_db()
    conn.execute("DELETE FROM questoes_respostas WHERE questao_id = ?", (id,))
    conn.execute("DELETE FROM questoes WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return {"ok": True}



# ============================================================
# SIMULADOS
# ============================================================

class SimuladoCreate(BaseModel):
    titulo: str
    tempo_limite_min: int = 60
    questao_ids: List[int]


class SimuladoResponder(BaseModel):
    questao_id: int
    resposta: str


@app.get("/api/simulados")
def list_simulados():
    conn = get_db()
    rows = conn.execute("SELECT * FROM simulados ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/simulados/{id}")
def get_simulado(id: int):
    conn = get_db()
    sim = conn.execute("SELECT * FROM simulados WHERE id = ?", (id,)).fetchone()
    if not sim:
        conn.close()
        raise HTTPException(404)
    questoes = conn.execute("""
        SELECT sq.*, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c,
               q.alternativa_d, q.alternativa_e, q.resposta_correta, q.materia, q.explicacao
        FROM simulado_questoes sq
        JOIN questoes q ON q.id = sq.questao_id
        WHERE sq.simulado_id = ?
        ORDER BY sq.ordem
    """, (id,)).fetchall()
    conn.close()
    return {"simulado": dict(sim), "questoes": [dict(q) for q in questoes]}


@app.post("/api/simulados")
def create_simulado(body: SimuladoCreate):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO simulados (titulo, tempo_limite_min, total_questoes, created_at)
        VALUES (?, ?, ?, ?)
    """, (body.titulo, body.tempo_limite_min, len(body.questao_ids), today_str()))
    sim_id = cur.lastrowid
    for i, qid in enumerate(body.questao_ids):
        conn.execute("INSERT INTO simulado_questoes (simulado_id, questao_id, ordem) VALUES (?, ?, ?)",
                     (sim_id, qid, i))
    conn.commit()
    conn.close()
    return {"id": sim_id, "ok": True}


@app.post("/api/simulados/{id}/responder")
def responder_simulado(id: int, body: SimuladoResponder):
    conn = get_db()
    questao = conn.execute("SELECT resposta_correta FROM questoes WHERE id = ?", (body.questao_id,)).fetchone()
    if not questao:
        conn.close()
        raise HTTPException(404)
    acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
    conn.execute("""
        UPDATE simulado_questoes SET resposta_usuario = ?, acertou = ?
        WHERE simulado_id = ? AND questao_id = ?
    """, (body.resposta, acertou, id, body.questao_id))
    conn.commit()
    conn.close()
    return {"acertou": bool(acertou), "resposta_correta": questao[0]}


class SimuladoFinalizar(BaseModel):
    tempo_gasto_seg: int = 0


@app.post("/api/simulados/{id}/finalizar")
def finalizar_simulado(id: int, body: SimuladoFinalizar):
    conn = get_db()
    results = conn.execute("""
        SELECT COUNT(*) as total, SUM(CASE WHEN acertou = 1 THEN 1 ELSE 0 END) as acertos
        FROM simulado_questoes WHERE simulado_id = ?
    """, (id,)).fetchone()
    total = results[0]
    acertos = results[1] or 0
    nota = round((acertos / total * 100) if total > 0 else 0, 1)
    conn.execute("""
        UPDATE simulados SET status = 'finalizado', nota = ?, acertos = ?,
               tempo_gasto_seg = ?, finalizado_at = ?
        WHERE id = ?
    """, (nota, acertos, body.tempo_gasto_seg, datetime.now().isoformat(), id))
    conn.commit()
    conn.close()
    return {"nota": nota, "acertos": acertos, "total": total}


@app.delete("/api/simulados/{id}")
def delete_simulado(id: int):
    conn = get_db()
    conn.execute("DELETE FROM simulado_questoes WHERE simulado_id = ?", (id,))
    conn.execute("DELETE FROM simulados WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============================================================
# CICLO DE ESTUDOS
# ============================================================

class CicloCreate(BaseModel):
    materia: str
    horas_alvo: float = 1.0


class CicloUpdate(BaseModel):
    horas_alvo: Optional[float] = None
    ativo: Optional[int] = None
    ordem: Optional[int] = None


@app.get("/api/ciclo")
def list_ciclo():
    conn = get_db()
    rows = conn.execute("SELECT * FROM ciclo_estudos ORDER BY ordem, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/ciclo/proximo")
def proximo_ciclo():
    """Retorna a próxima matéria a estudar no ciclo (menor % cumprido)"""
    conn = get_db()
    rows = conn.execute("""
        SELECT *, (horas_cumpridas / horas_alvo) as progresso
        FROM ciclo_estudos WHERE ativo = 1
        ORDER BY progresso ASC, ordem ASC LIMIT 1
    """).fetchone()
    conn.close()
    if rows:
        return dict(rows)
    return {"materia": "Nenhuma matéria no ciclo", "horas_alvo": 0, "horas_cumpridas": 0}


@app.post("/api/ciclo")
def create_ciclo(body: CicloCreate):
    conn = get_db()
    max_ordem = conn.execute("SELECT COALESCE(MAX(ordem), 0) FROM ciclo_estudos").fetchone()[0]
    cur = conn.execute("INSERT INTO ciclo_estudos (materia, horas_alvo, ordem) VALUES (?, ?, ?)",
                       (body.materia, body.horas_alvo, max_ordem + 1))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "ok": True}


@app.post("/api/ciclo/resetar")
def resetar_ciclo():
    """Reseta as horas cumpridas de todas as matérias para iniciar novo ciclo"""
    conn = get_db()
    conn.execute("UPDATE ciclo_estudos SET horas_cumpridas = 0")
    conn.commit()
    conn.close()
    return {"ok": True}


@app.put("/api/ciclo/{id}")
def update_ciclo(id: int, body: CicloUpdate):
    conn = get_db()
    if body.horas_alvo is not None:
        conn.execute("UPDATE ciclo_estudos SET horas_alvo = ? WHERE id = ?", (body.horas_alvo, id))
    if body.ativo is not None:
        conn.execute("UPDATE ciclo_estudos SET ativo = ? WHERE id = ?", (body.ativo, id))
    if body.ordem is not None:
        conn.execute("UPDATE ciclo_estudos SET ordem = ? WHERE id = ?", (body.ordem, id))
    conn.commit()
    conn.close()
    return {"ok": True}


class CicloHoras(BaseModel):
    horas: float


@app.put("/api/ciclo/{id}/horas")
def add_ciclo_horas(id: int, body: CicloHoras):
    conn = get_db()
    row = conn.execute("SELECT materia, horas_cumpridas FROM ciclo_estudos WHERE id = ?", (id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    new_horas = row[1] + body.horas
    conn.execute("UPDATE ciclo_estudos SET horas_cumpridas = ? WHERE id = ?", (new_horas, id))
    # Registrar sessão
    conn.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo) VALUES (?, ?, ?, 'ciclo')",
                 (row[0], body.horas, today_str()))
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas) VALUES (?, ?)
        ON CONFLICT(data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, body.horas))
    conn.commit()
    conn.close()
    return {"id": id, "horas_cumpridas": new_horas}


@app.delete("/api/ciclo/{id}")
def delete_ciclo(id: int):
    conn = get_db()
    conn.execute("DELETE FROM ciclo_estudos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============================================================
# STREAKS E METAS
# ============================================================

@app.get("/api/streaks")
def get_streaks():
    """Retorna streak atual (dias consecutivos) e dados de hoje"""
    conn = get_db()
    # Dados de hoje
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()
    hoje_data = dict(hoje) if hoje else {"data": today_str(), "horas_estudadas": 0, "questoes_resolvidas": 0, "flashcards_revisados": 0}

    # Calcular streak (dias consecutivos)
    rows = conn.execute("SELECT data FROM streaks WHERE horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0 ORDER BY data DESC").fetchall()
    streak = 0
    check_date = date.today()
    for row in rows:
        if row[0] == check_date.isoformat():
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    # Melhor streak histórico
    all_dates = [row[0] for row in rows]
    best_streak = 0
    current_best = 0
    if all_dates:
        sorted_dates = sorted(set(all_dates))
        current_best = 1
        for i in range(1, len(sorted_dates)):
            d1 = date.fromisoformat(sorted_dates[i - 1])
            d2 = date.fromisoformat(sorted_dates[i])
            if (d2 - d1).days == 1:
                current_best += 1
            else:
                best_streak = max(best_streak, current_best)
                current_best = 1
        best_streak = max(best_streak, current_best)

    conn.close()
    return {
        "streak_atual": streak,
        "melhor_streak": best_streak,
        "hoje": hoje_data
    }


@app.get("/api/metas")
def get_metas():
    conn = get_db()
    config = conn.execute("SELECT * FROM metas_config WHERE id = 1").fetchone()
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()
    conn.close()

    config_dict = dict(config) if config else {"meta_horas": 3.0, "meta_questoes": 30, "meta_flashcards": 10, "meta_paginas": 20}
    hoje_dict = dict(hoje) if hoje else {"horas_estudadas": 0, "questoes_resolvidas": 0, "flashcards_revisados": 0}

    return {
        "config": config_dict,
        "progresso": {
            "horas": hoje_dict.get("horas_estudadas", 0),
            "questoes": hoje_dict.get("questoes_resolvidas", 0),
            "flashcards": hoje_dict.get("flashcards_revisados", 0)
        }
    }


class MetasUpdate(BaseModel):
    meta_horas: float = 3.0
    meta_questoes: int = 30
    meta_flashcards: int = 10
    meta_paginas: int = 20


@app.put("/api/metas")
def update_metas(body: MetasUpdate):
    conn = get_db()
    conn.execute("""
        UPDATE metas_config SET meta_horas = ?, meta_questoes = ?, meta_flashcards = ?, meta_paginas = ?
        WHERE id = 1
    """, (body.meta_horas, body.meta_questoes, body.meta_flashcards, body.meta_paginas))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============================================================
# NOTAS POR PDF
# ============================================================

class NotaCreate(BaseModel):
    pdf_path: str
    pagina: int = 1
    conteudo: str


@app.get("/api/notas/{path:path}")
def get_notas_pdf(path: str):
    conn = get_db()
    rows = conn.execute("SELECT * FROM notas_pdf WHERE pdf_path = ? ORDER BY pagina, id", (path,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/notas")
def create_nota(body: NotaCreate):
    conn = get_db()
    cur = conn.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at) VALUES (?, ?, ?, ?)",
                       (body.pdf_path, body.pagina, body.conteudo, datetime.now().isoformat()))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "ok": True}


@app.delete("/api/notas/{id}")
def delete_nota(id: int):
    conn = get_db()
    conn.execute("DELETE FROM notas_pdf WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============================================================
# DASHBOARD / RELATÓRIOS / PRÁTICA DELIBERADA
# ============================================================

@app.get("/api/dashboard")
def get_dashboard():
    conn = get_db()

    # Horas por dia (últimos 14 dias)
    horas_dia = conn.execute("""
        SELECT data, SUM(horas) as total_horas
        FROM sessoes_estudo
        WHERE data >= ?
        GROUP BY data ORDER BY data
    """, ((date.today() - timedelta(days=13)).isoformat(),)).fetchall()

    # Total de horas
    total_horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]

    # Progresso do edital
    edital_total = conn.execute("SELECT COUNT(*) FROM edital").fetchone()[0]
    edital_concluido = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído'").fetchone()[0]

    # Questões stats
    questoes_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    questoes_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]

    # Evolução de acertos por dia (últimos 14 dias)
    acertos_dia = conn.execute("""
        SELECT data,
               COUNT(*) as total,
               SUM(acertou) as acertos
        FROM questoes_respostas
        WHERE data >= ?
        GROUP BY data ORDER BY data
    """, ((date.today() - timedelta(days=13)).isoformat(),)).fetchall()

    # Horas por matéria
    horas_materia = conn.execute("""
        SELECT materia, SUM(horas) as total
        FROM sessoes_estudo
        GROUP BY materia ORDER BY total DESC
    """).fetchall()

    # Flashcards pendentes
    flashcards_pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)
    ).fetchone()[0]

    # Total flashcards
    flashcards_total = conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0]

    conn.close()

    return {
        "horas_por_dia": [dict(r) for r in horas_dia],
        "total_horas": round(total_horas, 1),
        "edital": {"total": edital_total, "concluido": edital_concluido},
        "questoes": {
            "total": questoes_total,
            "acertos": questoes_acertos,
            "percentual": round((questoes_acertos / questoes_total * 100) if questoes_total > 0 else 0, 1)
        },
        "acertos_por_dia": [dict(r) for r in acertos_dia],
        "horas_por_materia": [dict(r) for r in horas_materia],
        "flashcards": {"pendentes": flashcards_pendentes, "total": flashcards_total}
    }


@app.get("/api/relatorio-semanal")
def relatorio_semanal():
    conn = get_db()
    inicio_semana = (date.today() - timedelta(days=date.today().weekday())).isoformat()

    # Horas da semana
    horas = conn.execute("""
        SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ?
    """, (inicio_semana,)).fetchone()[0]

    # Questões da semana
    questoes = conn.execute("""
        SELECT COUNT(*) as total, SUM(acertou) as acertos
        FROM questoes_respostas WHERE data >= ?
    """, (inicio_semana,)).fetchone()

    # Matéria mais fraca (menor % acerto com pelo menos 5 questões)
    materia_fraca = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.data >= ?
        GROUP BY q.materia
        HAVING total >= 3
        ORDER BY pct ASC
        LIMIT 3
    """, (inicio_semana,)).fetchall()

    # Dias estudados na semana
    dias = conn.execute("""
        SELECT COUNT(DISTINCT data) FROM streaks
        WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0)
    """, (inicio_semana,)).fetchone()[0]

    conn.close()

    return {
        "periodo": f"{inicio_semana} a {today_str()}",
        "total_horas": round(horas, 1),
        "questoes_total": questoes[0] or 0,
        "questoes_acertos": questoes[1] or 0,
        "questoes_percentual": round((questoes[1] / questoes[0] * 100) if questoes[0] else 0, 1),
        "materias_fracas": [dict(r) for r in materia_fraca],
        "dias_estudados": dias,
        "sugestao_foco": [r["materia"] for r in materia_fraca] if materia_fraca else ["Resolver mais questões para obter análise"]
    }


@app.get("/api/pratica-deliberada")
def pratica_deliberada():
    """Identifica as matérias com pior desempenho e sugere foco"""
    conn = get_db()
    materias = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total_questoes,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as percentual
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
        ORDER BY percentual ASC
    """).fetchall()

    # Matérias com questões disponíveis mas nunca respondidas
    nao_estudadas = conn.execute("""
        SELECT DISTINCT materia FROM questoes
        WHERE materia NOT IN (
            SELECT DISTINCT q.materia FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
        )
    """).fetchall()

    conn.close()

    sugestoes = []
    for m in materias:
        if m[3] < 70:  # Menos de 70% de acerto
            sugestoes.append({
                "materia": m[0],
                "total_questoes": m[1],
                "percentual": m[3],
                "prioridade": "ALTA" if m[3] < 50 else "MÉDIA"
            })

    return {
        "materias_para_focar": sugestoes,
        "materias_nao_estudadas": [r[0] for r in nao_estudadas],
        "recomendacao": "Foque nas matérias com menor percentual de acerto. Resolva pelo menos 10 questões de cada antes de avançar."
    }


# Importar edital de PDF
@app.post("/api/edital/importar-pdf")
async def importar_edital_pdf(file: UploadFile = File(...), edital_nome: str = "Importado"):
    """Extrai texto do PDF e tenta identificar matérias/tópicos"""
    content = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(content)
    tmp.close()

    try:
        reader = PdfReader(tmp.name)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
    except Exception:
        os.unlink(tmp.name)
        raise HTTPException(400, "Não foi possível ler o PDF")

    os.unlink(tmp.name)

    # Heurística: cada linha com texto relevante vira um tópico
    linhas = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 5]

    # Agrupar por seções (linhas em maiúsculas ou numeradas são matérias)
    itens = []
    materia_atual = "Geral"
    for linha in linhas:
        # Se a linha parece um título (maiúscula, curta, ou numerada)
        if (linha.isupper() and len(linha) < 80) or (len(linha) < 60 and linha[0].isdigit()):
            materia_atual = linha.title()
        elif len(linha) > 10:
            itens.append({"materia": materia_atual, "topico": linha[:200]})

    # Limitar a 100 itens para não sobrecarregar
    itens = itens[:100]

    conn = get_db()
    count = 0
    for item in itens:
        conn.execute("INSERT INTO edital (edital_nome, materia, topico) VALUES (?, ?, ?)", (edital_nome, item["materia"], item["topico"]))
        count += 1
    conn.commit()
    conn.close()

    return {"ok": True, "importados": count, "itens": itens[:20]}


# Exportar estatísticas completas
@app.get("/api/exportar-stats")
def exportar_estatisticas():
    conn = get_db()
    data = {
        "exportado_em": datetime.now().isoformat(),
        "edital": [dict(r) for r in conn.execute("SELECT * FROM edital").fetchall()],
        "questoes_stats": {
            "total": conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0],
            "acertos": conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0],
        },
        "sessoes": [dict(r) for r in conn.execute("SELECT * FROM sessoes_estudo ORDER BY data DESC LIMIT 100").fetchall()],
        "streaks": [dict(r) for r in conn.execute("SELECT * FROM streaks ORDER BY data DESC LIMIT 30").fetchall()],
        "simulados": [dict(r) for r in conn.execute("SELECT * FROM simulados").fetchall()],
    }
    conn.close()

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="estatisticas_completas.json", background=None)


# ============================================================
# COMPARATIVO ENTRE CARGOS
# ============================================================

@app.get("/api/comparativo")
def comparativo_cargos(edital1: str = "", cargo1: str = "", edital2: str = "", cargo2: str = ""):
    """Compara disciplinas entre dois cargos/editais"""
    conn = get_db()
    mat1 = set(r[0] for r in conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE edital_nome = ? AND cargo = ?", (edital1, cargo1)
    ).fetchall())
    mat2 = set(r[0] for r in conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE edital_nome = ? AND cargo = ?", (edital2, cargo2)
    ).fetchall())
    conn.close()
    comuns = sorted(mat1 & mat2)
    apenas1 = sorted(mat1 - mat2)
    apenas2 = sorted(mat2 - mat1)
    return {
        "cargo1": f"{edital1} - {cargo1}",
        "cargo2": f"{edital2} - {cargo2}",
        "comuns": comuns,
        "apenas_cargo1": apenas1,
        "apenas_cargo2": apenas2,
        "total_comuns": len(comuns),
        "total_apenas1": len(apenas1),
        "total_apenas2": len(apenas2)
    }


# ============================================================
# MODO RANDÔMICO + PREVISÃO APROVAÇÃO
# ============================================================

@app.get("/api/estudo/aleatorio")
def topico_aleatorio(edital_nome: str = "", cargo: str = ""):
    """Sorteia um tópico aleatório não concluído para estudo"""
    import random
    conn = get_db()
    query = "SELECT id, edital_nome, cargo, materia, topico FROM edital WHERE status != 'Concluído'"
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    if not rows:
        return {"message": "Todos os tópicos foram concluídos! 🎉"}
    chosen = random.choice(rows)
    return dict(chosen)


@app.get("/api/previsao-aprovacao")
def previsao_aprovacao(edital_nome: str = "", cargo: str = ""):
    """Calcula previsão de aprovação baseado em progresso e acertos"""
    conn = get_db()
    # Progresso do edital
    query_base = "SELECT COUNT(*) FROM edital WHERE 1=1"
    query_done = "SELECT COUNT(*) FROM edital WHERE status = 'Concluído'"
    params = []
    if edital_nome:
        query_base += " AND edital_nome = ?"
        query_done += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query_base += " AND cargo = ?"
        query_done += " AND cargo = ?"
        params.append(cargo)
    
    total_topicos = conn.execute(query_base, params).fetchone()[0]
    topicos_concluidos = conn.execute(query_done, params).fetchone()[0]
    
    # % acerto em questões
    q_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    q_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]
    
    # Horas estudadas
    horas_total = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]
    
    conn.close()
    
    # Cálculo da previsão (fórmula simplificada)
    pct_edital = (topicos_concluidos / total_topicos * 100) if total_topicos > 0 else 0
    pct_questoes = (q_acertos / q_total * 100) if q_total > 0 else 0
    
    # Pesos: 40% edital concluído + 50% acerto questões + 10% horas
    fator_horas = min(100, horas_total * 2)  # 50h = 100%
    score = (pct_edital * 0.4) + (pct_questoes * 0.5) + (fator_horas * 0.1)
    
    # Classificação
    if score >= 80:
        nivel = "Excelente"
        emoji = "🏆"
    elif score >= 60:
        nivel = "Bom"
        emoji = "✅"
    elif score >= 40:
        nivel = "Regular"
        emoji = "⚠️"
    elif score >= 20:
        nivel = "Iniciante"
        emoji = "📖"
    else:
        nivel = "Começando"
        emoji = "🌱"
    
    return {
        "score": round(score, 1),
        "nivel": nivel,
        "emoji": emoji,
        "detalhes": {
            "edital_pct": round(pct_edital, 1),
            "questoes_pct": round(pct_questoes, 1),
            "horas_total": round(horas_total, 1),
            "topicos_concluidos": topicos_concluidos,
            "topicos_total": total_topicos,
            "questoes_total": q_total,
            "questoes_acertos": q_acertos
        }
    }


# ============================================================
# COUNTDOWN PARA PROVAS
# ============================================================

@app.get("/api/countdown")
def get_countdown():
    """Retorna countdowns para as próximas provas"""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT edital_nome, cargo, data_prova_objetiva, data_prova_discursiva, local_prova
            FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital'
            ORDER BY data_prova_objetiva
        """).fetchall()
    except Exception:
        rows = []
    conn.close()
    
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
# EXPORTAR PDF DE RESUMO
# ============================================================

@app.get("/api/exportar-resumo")
def exportar_resumo():
    """Gera um resumo completo em formato texto/HTML para impressão"""
    conn = get_db()
    
    # Progresso por edital
    editais = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as done,
               SUM(horas_estudadas) as horas
        FROM edital GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """).fetchall()
    
    # Questões
    q_stats = conn.execute("SELECT COUNT(*), SUM(acertou) FROM questoes_respostas").fetchone()
    
    # Streaks
    streaks = conn.execute("SELECT data, horas_estudadas, questoes_resolvidas FROM streaks ORDER BY data DESC LIMIT 30").fetchall()
    
    conn.close()
    
    # Montar HTML para impressão
    html = f"""<!DOCTYPE html>
<html><head><meta charset='UTF-8'><title>Resumo de Estudos - ConcurseiroOS</title>
<style>
  body {{ font-family: sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }}
  h1 {{ color: #6c3483; border-bottom: 2px solid #6c3483; padding-bottom: 8px; }}
  h2 {{ color: #2980b9; margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f4f4f4; }}
  .stat {{ display: inline-block; margin: 8px 16px 8px 0; padding: 8px 16px; background: #f0f0f0; border-radius: 8px; }}
  .stat strong {{ font-size: 1.3rem; }}
  @media print {{ body {{ padding: 20px; }} }}
</style></head><body>
<h1>📚 Resumo de Estudos - ConcurseiroOS</h1>
<p>Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}</p>

<h2>📊 Estatísticas Gerais</h2>
<div class='stat'>Questões: <strong>{q_stats[0] or 0}</strong> resolvidas ({q_stats[1] or 0} acertos)</div>
<div class='stat'>Aproveitamento: <strong>{round((q_stats[1]/q_stats[0]*100) if q_stats[0] else 0, 1)}%</strong></div>

<h2>📋 Progresso por Edital/Cargo</h2>
<table><tr><th>Edital</th><th>Cargo</th><th>Tópicos</th><th>Concluídos</th><th>%</th><th>Horas</th></tr>"""
    
    for e in editais:
        pct = round(e[3]/e[2]*100, 1) if e[2] > 0 else 0
        html += f"<tr><td>{e[0]}</td><td>{e[1]}</td><td>{e[2]}</td><td>{e[3]}</td><td>{pct}%</td><td>{e[4]:.1f}h</td></tr>"
    
    html += "</table>"
    
    if streaks:
        html += "<h2>🔥 Últimos 30 dias de Estudo</h2><table><tr><th>Data</th><th>Horas</th><th>Questões</th></tr>"
        for s in streaks:
            html += f"<tr><td>{s[0]}</td><td>{s[1]:.1f}h</td><td>{s[2]}</td></tr>"
        html += "</table>"
    
    html += "</body></html>"
    
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
    tmp.write(html)
    tmp.close()
    return FileResponse(tmp.name, media_type="text/html", filename="resumo_estudos.html", background=None)


# ============================================================
# GAMIFICAÇÃO (XP + NÍVEIS + BADGES)
# ============================================================

# XP rewards:
# - Estudar 1 hora = 100 XP
# - Resolver questão = 10 XP (acertar = +5 bonus)
# - Revisar flashcard = 5 XP
# - Completar tópico do edital = 25 XP
# - Completar simulado = 50 XP
# - Streak de 7 dias = 200 XP bonus

# Levels: cada 500 XP = 1 nível
LEVEL_XP = 500

BADGES = [
    {"id": "first_hour", "name": "Primeira Hora", "desc": "Estudou 1 hora no total", "icon": "⏱", "condition": "horas >= 1"},
    {"id": "ten_hours", "name": "Maratonista", "desc": "Estudou 10 horas no total", "icon": "🏃", "condition": "horas >= 10"},
    {"id": "fifty_hours", "name": "Dedicado", "desc": "Estudou 50 horas no total", "icon": "💪", "condition": "horas >= 50"},
    {"id": "first_question", "name": "Primeira Questão", "desc": "Resolveu a primeira questão", "icon": "❓", "condition": "questoes >= 1"},
    {"id": "hundred_questions", "name": "Centurião", "desc": "Resolveu 100 questões", "icon": "💯", "condition": "questoes >= 100"},
    {"id": "five_hundred_questions", "name": "Mestre das Questões", "desc": "Resolveu 500 questões", "icon": "🎓", "condition": "questoes >= 500"},
    {"id": "streak_7", "name": "Semana Perfeita", "desc": "7 dias consecutivos de estudo", "icon": "🔥", "condition": "streak >= 7"},
    {"id": "streak_30", "name": "Mês de Ferro", "desc": "30 dias consecutivos de estudo", "icon": "⚡", "condition": "streak >= 30"},
    {"id": "first_simulado", "name": "Simulador", "desc": "Completou o primeiro simulado", "icon": "📝", "condition": "simulados >= 1"},
    {"id": "accuracy_80", "name": "Precisão Cirúrgica", "desc": "80%+ de acerto em questões", "icon": "🎯", "condition": "accuracy >= 80"},
    {"id": "ten_topics", "name": "Explorador", "desc": "Concluiu 10 tópicos do edital", "icon": "🗺", "condition": "topicos >= 10"},
    {"id": "fifty_topics", "name": "Conquistador", "desc": "Concluiu 50 tópicos do edital", "icon": "🏆", "condition": "topicos >= 50"},
    {"id": "all_flashcards", "name": "Memória de Elefante", "desc": "Revisou todos os flashcards do dia", "icon": "🧠", "condition": "flashcards_dia_ok"},
    {"id": "night_owl", "name": "Coruja Noturna", "desc": "Estudou após as 22h", "icon": "🦉", "condition": "special"},
    {"id": "early_bird", "name": "Madrugador", "desc": "Estudou antes das 6h", "icon": "🌅", "condition": "special"},
]


@app.get("/api/gamification")
def get_gamification():
    """Retorna XP, nível, badges e progresso do usuário"""
    conn = get_db()
    
    # Calcular XP baseado nas atividades
    horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]
    questoes_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    questoes_certas = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]
    flashcards_rev = conn.execute("SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks").fetchone()[0]
    topicos_concluidos = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído'").fetchone()[0]
    simulados_feitos = conn.execute("SELECT COUNT(*) FROM simulados WHERE status = 'finalizado'").fetchone()[0]
    
    # Streak atual
    streak_rows = conn.execute("SELECT data FROM streaks WHERE horas_estudadas > 0 OR questoes_resolvidas > 0 ORDER BY data DESC").fetchall()
    streak = 0
    check_date = date.today()
    for row in streak_rows:
        if row[0] == check_date.isoformat():
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break
    
    conn.close()
    
    # Calcular XP
    xp = int(
        horas * 100 +
        questoes_total * 10 +
        questoes_certas * 5 +
        flashcards_rev * 5 +
        topicos_concluidos * 25 +
        simulados_feitos * 50 +
        (streak // 7) * 200
    )
    
    nivel = (xp // LEVEL_XP) + 1
    xp_no_nivel = xp % LEVEL_XP
    xp_para_proximo = LEVEL_XP
    
    # Verificar badges
    accuracy = (questoes_certas / questoes_total * 100) if questoes_total > 0 else 0
    badges_earned = []
    for badge in BADGES:
        earned = False
        cond = badge["condition"]
        if cond == "horas >= 1" and horas >= 1: earned = True
        elif cond == "horas >= 10" and horas >= 10: earned = True
        elif cond == "horas >= 50" and horas >= 50: earned = True
        elif cond == "questoes >= 1" and questoes_total >= 1: earned = True
        elif cond == "questoes >= 100" and questoes_total >= 100: earned = True
        elif cond == "questoes >= 500" and questoes_total >= 500: earned = True
        elif cond == "streak >= 7" and streak >= 7: earned = True
        elif cond == "streak >= 30" and streak >= 30: earned = True
        elif cond == "simulados >= 1" and simulados_feitos >= 1: earned = True
        elif cond == "accuracy >= 80" and accuracy >= 80 and questoes_total >= 20: earned = True
        elif cond == "topicos >= 10" and topicos_concluidos >= 10: earned = True
        elif cond == "topicos >= 50" and topicos_concluidos >= 50: earned = True
        
        if earned:
            badges_earned.append(badge)
    
    return {
        "xp": xp,
        "nivel": nivel,
        "xp_no_nivel": xp_no_nivel,
        "xp_para_proximo": xp_para_proximo,
        "pct_nivel": round(xp_no_nivel / xp_para_proximo * 100),
        "badges_earned": badges_earned,
        "badges_total": len(BADGES),
        "stats": {
            "horas": round(horas, 1),
            "questoes": questoes_total,
            "acertos": questoes_certas,
            "accuracy": round(accuracy, 1),
            "streak": streak,
            "topicos": topicos_concluidos,
            "simulados": simulados_feitos,
            "flashcards": flashcards_rev
        }
    }


# ============================================================
# GRÁFICO RADAR - DESEMPENHO POR MATÉRIA
# ============================================================

@app.get("/api/radar")
def get_radar(edital_nome: str = "", cargo: str = ""):
    """Retorna dados para gráfico radar de desempenho por matéria"""
    conn = get_db()
    
    # Progresso do edital por matéria
    query = """
        SELECT materia,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos,
               SUM(horas_estudadas) as horas
        FROM edital WHERE 1=1
    """
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " GROUP BY materia ORDER BY materia"
    
    materias_edital = conn.execute(query, params).fetchall()
    
    # Acerto em questões por matéria
    questoes_por_mat = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
    """).fetchall()
    q_map = {r[0]: {"total": r[1], "acertos": r[2]} for r in questoes_por_mat}
    
    conn.close()
    
    # Montar dados do radar
    radar_data = []
    for m in materias_edital:
        materia = m[0]
        total = m[1]
        concluidos = m[2]
        horas = m[3] or 0
        
        # Score do edital (0-100)
        pct_edital = (concluidos / total * 100) if total > 0 else 0
        
        # Score de questões (0-100)
        q_data = q_map.get(materia, {"total": 0, "acertos": 0})
        pct_questoes = (q_data["acertos"] / q_data["total"] * 100) if q_data["total"] > 0 else 0
        
        # Score composto (média)
        score = (pct_edital + pct_questoes) / 2 if q_data["total"] > 0 else pct_edital
        
        radar_data.append({
            "materia": materia,
            "score": round(score, 1),
            "pct_edital": round(pct_edital, 1),
            "pct_questoes": round(pct_questoes, 1),
            "horas": round(horas, 1),
            "topicos_total": total,
            "topicos_concluidos": concluidos
        })
    
    return radar_data


# ============================================================
# NOTIFICAÇÕES DE REVISÃO
# ============================================================

@app.get("/api/notificacoes")
def get_notificacoes():
    """Retorna lembretes/notificações pendentes"""
    conn = get_db()
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
        if hoje[1] < config[0]:  # horas
            falta = config[0] - hoje[1]
            notifs.append({"tipo": "meta", "icon": "⏱", "msg": f"Faltam {falta:.1f}h para bater a meta de hoje", "prioridade": "media"})
        if hoje[2] < config[1]:  # questões
            falta = config[1] - hoje[2]
            notifs.append({"tipo": "meta", "icon": "❓", "msg": f"Faltam {falta} questões para a meta de hoje", "prioridade": "media"})
    elif config:
        notifs.append({"tipo": "meta", "icon": "📖", "msg": "Você ainda não estudou hoje! Que tal começar?", "prioridade": "alta"})
    
    # Streak em risco
    ontem = (date.today() - timedelta(days=1)).isoformat()
    streak_ontem = conn.execute("SELECT * FROM streaks WHERE data = ?", (ontem,)).fetchone()
    if not hoje and streak_ontem:
        notifs.append({"tipo": "streak", "icon": "🔥", "msg": "Seu streak está em risco! Estude hoje para não perder.", "prioridade": "alta"})
    
    conn.close()
    return notifs


# ============================================================
# CORREÇÃO DO MIME TYPE PARA .mjs / .js (PDF.js)
# ============================================================
from starlette.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope


class FixedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.endswith((".mjs", ".js")):
            response.headers["content-type"] = "application/javascript; charset=utf-8"
        return response


# Monta o frontend com a correção (DEVE SER O ÚLTIMO)
app.mount("/", FixedStaticFiles(directory="../frontend", html=True), name="frontend")
