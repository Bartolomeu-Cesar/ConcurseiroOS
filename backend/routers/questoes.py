import random
import re
import tempfile

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile

from constants import DEFAULT_EXAM_DURATION_MIN, DEFAULT_EXAM_QUESTIONS, DEFAULT_TIME_PER_QUESTION_SEC
from database import get_db_session
from deps import get_user_id
from logger import log
from models import QuestaoCreate, QuestaoResponse, QuestaoResposta, QuestaoRespostaResponse
from utils import paginate, today_str, update_streak

router = APIRouter(prefix="", tags=["Questões"])


@router.get("/api/questoes", summary="Listar questões", description="Lista todas as questões do banco, com filtros por matéria/tópico e paginação opcional")
def list_questoes(
    materia: str = "",
    topico: str = "",
    dificuldade: str = "",
    banca: str = "",
    acertou: int | None = Query(None),
    respondidas: int | None = Query(None),
    data_inicio: str = "",
    data_fim: str = "",
    page: int | None = Query(None),
    limit: int = 50,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    params = []

    # Determinar tipo de query baseado nos filtros
    needs_join = acertou is not None or data_inicio or data_fim
    needs_not_in = respondidas == 0

    if needs_not_in:
        # Questões NÃO respondidas
        query = "SELECT q.* FROM questoes q WHERE q.user_id = ? AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)"
        params = [user_id, user_id]
        if materia:
            query += " AND q.materia = ?"
            params.append(materia)
        if topico:
            query += " AND q.topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND q.dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND q.banca = ?"
            params.append(banca)
    elif needs_join or respondidas == 1:
        # Questões com filtro por respostas (acertou/errou, datas)
        query = "SELECT DISTINCT q.* FROM questoes q JOIN questoes_respostas qr ON qr.questao_id = q.id WHERE q.user_id = ? AND qr.user_id = ?"
        params = [user_id, user_id]
        if materia:
            query += " AND q.materia = ?"
            params.append(materia)
        if topico:
            query += " AND q.topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND q.dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND q.banca = ?"
            params.append(banca)
        if acertou is not None:
            query += " AND qr.acertou = ?"
            params.append(acertou)
        if data_inicio:
            query += " AND qr.data >= ?"
            params.append(data_inicio)
        if data_fim:
            query += " AND qr.data <= ?"
            params.append(data_fim)
    else:
        # Query simples sem filtros de resposta
        query = "SELECT * FROM questoes WHERE user_id = ?"
        params = [user_id]
        if materia:
            query += " AND materia = ?"
            params.append(materia)
        if topico:
            query += " AND topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND banca = ?"
            params.append(banca)

    query += " ORDER BY q.id DESC" if (needs_join or needs_not_in or respondidas == 1) else " ORDER BY id DESC"
    rows = conn.execute(query, params).fetchall()

    items = [dict(r) for r in rows]
    return paginate(items, page, limit)


@router.get("/api/questoes/materias")
def list_questoes_materias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT DISTINCT materia FROM questoes WHERE user_id = ? ORDER BY materia", (user_id,)).fetchall()
    return [r[0] for r in rows]


# Caderno de Erros (DEVE ficar antes de /api/questoes/{id})
@router.get("/api/questoes/erros/caderno")
def caderno_erros(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("""
        SELECT q.id, q.materia, q.topico, q.enunciado, q.resposta_correta, qr.resposta_usuario, qr.data
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0 AND qr.user_id = ?
        ORDER BY qr.data DESC
    """, (user_id,)).fetchall()
    return [dict(r) for r in rows]


# Estatísticas de questões (DEVE ficar antes de /api/questoes/{id})
@router.get("/api/questoes/stats/geral")
def questoes_stats(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    total = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    por_materia = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        ORDER BY q.materia
    """, (user_id,)).fetchall()
    return {
        "total_resolvidas": total,
        "total_acertos": acertos,
        "percentual": round((acertos / total * 100) if total > 0 else 0, 1),
        "por_materia": [dict(r) for r in por_materia]
    }


@router.get("/api/questoes/stats/por-banca")
def questoes_stats_por_banca(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna estatísticas de acerto agrupadas por banca examinadora"""
    log.info("GET /api/questoes/stats/por-banca")
    rows = conn.execute("""
        SELECT q.banca,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE q.banca != '' AND q.banca IS NOT NULL AND qr.user_id = ?
        GROUP BY q.banca
        ORDER BY total DESC
    """, (user_id,)).fetchall()
    return [
        {
            "banca": r[0],
            "total": r[1],
            "acertos": r[2] or 0,
            "pct_acerto": round(((r[2] or 0) / r[1] * 100) if r[1] > 0 else 0, 1)
        }
        for r in rows
    ]


@router.get("/api/questoes/stats/tempo")
def questoes_stats_tempo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna tempo médio por questão com análise por matéria e dificuldade"""
    log.info("GET /api/questoes/stats/tempo")
    # Tempo médio geral (excluindo tempo_segundos = 0)
    geral = conn.execute("""
        SELECT AVG(tempo_segundos) as media, COUNT(*) as total
        FROM questoes_respostas
        WHERE tempo_segundos > 0 AND user_id = ?
    """, (user_id,)).fetchone()
    tempo_medio = int(geral[0]) if geral[0] else 0

    # Por matéria
    por_materia = conn.execute("""
        SELECT q.materia, AVG(qr.tempo_segundos) as media, COUNT(*) as questoes
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.tempo_segundos > 0 AND qr.user_id = ?
        GROUP BY q.materia
        ORDER BY media DESC
    """, (user_id,)).fetchall()

    # Por dificuldade
    por_dificuldade = conn.execute("""
        SELECT q.dificuldade, AVG(qr.tempo_segundos) as media
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.tempo_segundos > 0 AND qr.user_id = ?
        GROUP BY q.dificuldade
        ORDER BY media ASC
    """, (user_id,)).fetchall()

    tempo_prova_min = DEFAULT_EXAM_DURATION_MIN
    questoes_prova = DEFAULT_EXAM_QUESTIONS
    tempo_por_questao_prova = DEFAULT_TIME_PER_QUESTION_SEC

    # Análise
    if tempo_medio > 0 and tempo_medio <= tempo_por_questao_prova:
        status = "dentro_do_limite"
        mensagem = f"Seu tempo médio ({tempo_medio}s/questão) está dentro do limite da prova ({tempo_por_questao_prova}s/questão). Bom ritmo!"
    elif tempo_medio > tempo_por_questao_prova:
        status = "acima_do_limite"
        mensagem = f"Seu tempo médio ({tempo_medio}s/questão) está acima do limite da prova ({tempo_por_questao_prova}s/questão). Tente ser mais objetivo!"
    else:
        status = "sem_dados"
        mensagem = "Responda mais questões registrando o tempo para obter análise."

    # Formatar tempo
    minutos = tempo_medio // 60
    segundos = tempo_medio % 60
    tempo_formatado = f"{minutos}:{segundos:02d}"

    return {
        "tempo_medio_seg": tempo_medio,
        "tempo_medio_formatado": tempo_formatado,
        "por_materia": [
            {"materia": r[0], "tempo_medio_seg": int(r[1]), "questoes": r[2]}
            for r in por_materia
        ],
        "por_dificuldade": [
            {"dificuldade": r[0], "tempo_medio_seg": int(r[1])}
            for r in por_dificuldade
        ],
        "analise": {
            "tempo_prova_estimado_min": tempo_prova_min,
            "questoes_estimadas_prova": questoes_prova,
            "tempo_por_questao_prova_seg": tempo_por_questao_prova,
            "seu_tempo_vs_prova": status,
            "mensagem": mensagem
        }
    }


@router.get("/api/questoes/bancas")
def list_questoes_bancas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista bancas disponíveis no banco de questões"""
    log.info("GET /api/questoes/bancas")
    rows = conn.execute("SELECT DISTINCT banca FROM questoes WHERE banca != '' AND banca IS NOT NULL AND user_id = ? ORDER BY banca", (user_id,)).fetchall()
    return [r[0] for r in rows]


@router.get("/api/questoes/datas-importacao", summary="Listar datas de importação")
def list_datas_importacao(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna datas de importação com contagem de questões."""
    rows = conn.execute("""
        SELECT created_at, COUNT(*) as total,
               GROUP_CONCAT(DISTINCT materia) as materias,
               GROUP_CONCAT(DISTINCT banca) as bancas
        FROM questoes WHERE user_id = ? GROUP BY created_at ORDER BY created_at DESC
    """, (user_id,)).fetchall()
    return [{"data": r[0], "total": r[1], "materias": r[2] or "", "bancas": r[3] or ""} for r in rows]


@router.get("/api/questoes/{id}", response_model=QuestaoResponse)
def get_questao(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    return dict(row)


@router.post("/api/questoes", summary="Criar questão", description="Adiciona uma nova questão ao banco de questões")
def create_questao(body: QuestaoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("""
        INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
            alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, created_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (body.materia, body.topico, body.enunciado, body.alternativa_a, body.alternativa_b,
          body.alternativa_c, body.alternativa_d, body.alternativa_e, body.resposta_correta,
          body.explicacao, body.dificuldade, body.banca, today_str(), user_id))
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Questão created: id={new_id} materia={body.materia}")
    return {"id": new_id, "ok": True}


@router.post("/api/questoes/{id}/responder", response_model=QuestaoRespostaResponse, summary="Responder questão", description="Registra a resposta do usuário e retorna se acertou ou errou")
def responder_questao(id: int, body: QuestaoResposta, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    questao = conn.execute("SELECT resposta_correta, materia FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
    conn.execute("""
        INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (id, body.resposta, acertou, body.tempo_segundos, today_str(), user_id))
    update_streak(conn, "questoes_resolvidas", user_id=user_id)

    # Registrar tempo como sessão de estudo (se > 10 segundos)
    if body.tempo_segundos > 10:
        horas = body.tempo_segundos / 3600
        materia = questao["materia"] or "Questões"
        # Acumular na sessão do dia (evitar muitas linhas)
        existing = conn.execute(
            "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'questoes' AND user_id = ?",
            (today_str(), materia, user_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                (horas, existing["id"], user_id)
            )
        else:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'questoes', ?)",
                (materia, horas, today_str(), user_id)
            )
        # Atualizar streak de horas do dia (meta diária)
        update_streak(conn, "horas_estudadas", horas, user_id=user_id)

    conn.commit()
    return {"acertou": bool(acertou), "resposta_correta": questao[0]}


@router.put("/api/questoes/vincular-lote", summary="Vincular disciplina em lote",
            description="Atualiza matéria/tópico/banca de todas as questões que correspondem ao filtro")
def vincular_questoes_lote(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """
    Body: {
        filtro: {created_at?, materia_atual?, banca?},
        atualizar: {materia?, topico?, banca?, dificuldade?}
    }
    """
    filtro = body.get("filtro", {})
    atualizar = body.get("atualizar", {})

    if not atualizar:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # Construir WHERE
    where = "WHERE user_id = ?"
    params = [user_id]
    if filtro.get("created_at"):
        where += " AND created_at = ?"
        params.append(filtro["created_at"])
    if filtro.get("materia_atual"):
        where += " AND materia = ?"
        params.append(filtro["materia_atual"])
    elif filtro.get("materia_atual") == "":
        where += " AND (materia IS NULL OR materia = '')"
    if filtro.get("banca"):
        where += " AND banca = ?"
        params.append(filtro["banca"])

    # Construir SET
    campos_permitidos = ["materia", "topico", "banca", "dificuldade"]
    sets = []
    for campo in campos_permitidos:
        if campo in atualizar:
            sets.append(f"{campo} = ?")
            params.append(atualizar[campo])

    if not sets:
        raise HTTPException(status_code=400, detail="Nenhum campo válido para atualizar")

    query = f"UPDATE questoes SET {', '.join(sets)} {where}"
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    log.info(f"Questões atualizadas em lote: {count} (filtro={filtro}, atualizar={atualizar})")
    return {"ok": True, "atualizadas": count}


@router.put("/api/questoes/{id}", summary="Editar questão")
def update_questao(id: int, body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Atualiza campos de uma questão (materia, topico, enunciado, alternativas, resposta, explicacao, dificuldade, banca)."""
    row = conn.execute("SELECT id FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    
    campos_permitidos = ["materia", "topico", "enunciado", "alternativa_a", "alternativa_b",
                         "alternativa_c", "alternativa_d", "alternativa_e", "resposta_correta",
                         "explicacao", "dificuldade", "banca"]
    updates = []
    params = []
    for campo in campos_permitidos:
        if campo in body:
            updates.append(f"{campo} = ?")
            params.append(body[campo])
    
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    params.append(id)
    params.append(user_id)
    conn.execute(f"UPDATE questoes SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
    conn.commit()
    
    updated = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    log.info(f"Questão atualizada: id={id}")
    return dict(updated)


@router.delete("/api/questoes/{id}")
def delete_questao(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM questoes_respostas WHERE questao_id = ? AND user_id = ?", (id, user_id))
    conn.execute("DELETE FROM questoes WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Questão deleted: id={id}")
    return {"ok": True}


@router.get("/api/daily-challenge")
def daily_challenge(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a questão do dia (uma aleatória não respondida hoje)"""
    # Buscar questões não respondidas hoje
    respondidas_hoje = conn.execute(
        "SELECT questao_id FROM questoes_respostas WHERE data = ? AND user_id = ?", (today_str(), user_id)
    ).fetchall()
    ids_hoje = [r[0] for r in respondidas_hoje]

    if ids_hoje:
        placeholders = ','.join('?' * len(ids_hoje))
        rows = conn.execute(f"SELECT * FROM questoes WHERE user_id = ? AND id NOT IN ({placeholders})", [user_id] + ids_hoje).fetchall()
    else:
        rows = conn.execute("SELECT * FROM questoes WHERE user_id = ?", (user_id,)).fetchall()

    if not rows:
        return {"message": "Parabéns! Você já respondeu todas as questões disponíveis hoje.", "questao": None}

    chosen = random.choice(rows)
    return {"questao": dict(chosen)}


@router.get("/api/active-recall/{materia}")
def active_recall_session(materia: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera uma sessão de active recall: questões aleatórias de uma matéria"""
    rows = conn.execute("SELECT * FROM questoes WHERE materia = ? AND user_id = ?", (materia, user_id)).fetchall()
    if not rows:
        return {"questoes": [], "message": "Nenhuma questão disponível para esta matéria."}
    sample = random.sample([dict(r) for r in rows], min(5, len(rows)))
    return {"questoes": sample, "materia": materia, "total": len(sample)}


@router.get("/api/intercalacao")
def intercalacao_forcada(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Sorteia tópicos de matérias DIFERENTES para estudo intercalado"""
    materias = conn.execute("SELECT DISTINCT materia FROM edital WHERE status != 'Concluído' AND user_id = ?", (user_id,)).fetchall()
    if len(materias) < 2:
        return {"topicos": [], "message": "Precisa de pelo menos 2 matérias não concluídas."}

    selected_mats = random.sample([r[0] for r in materias], min(3, len(materias)))
    topicos = []
    for mat in selected_mats:
        rows = conn.execute(
            "SELECT id, materia, topico FROM edital WHERE materia = ? AND status != 'Concluído' AND user_id = ? ORDER BY RANDOM() LIMIT 2",
            (mat, user_id)
        ).fetchall()
        topicos.extend([dict(r) for r in rows])
    random.shuffle(topicos)
    return {"topicos": topicos, "materias": selected_mats}


@router.get("/api/questoes-vinculadas/{edital_id}")
def questoes_vinculadas(edital_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Busca questões que correspondem ao tópico de um item do edital"""
    topico = conn.execute("SELECT materia, topico FROM edital WHERE id = ? AND user_id = ?", (edital_id, user_id)).fetchone()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    rows = conn.execute("SELECT id, enunciado, resposta_correta FROM questoes WHERE materia = ? AND user_id = ? LIMIT 10",
                        (topico[0], user_id)).fetchall()
    return {"materia": topico[0], "topico": topico[1], "questoes": [dict(r) for r in rows]}


@router.get("/api/gerar-questao/{edital_id}")
def gerar_questao_template(edital_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera um template de questão baseado no tópico do edital"""
    topico = conn.execute("SELECT materia, topico FROM edital WHERE id = ? AND user_id = ?", (edital_id, user_id)).fetchone()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    return {
        "materia": topico[0],
        "topico": topico[1],
        "template": {
            "enunciado": f"Sobre {topico[1].lower()}, assinale a alternativa correta:",
            "alternativa_a": "",
            "alternativa_b": "",
            "alternativa_c": "",
            "alternativa_d": "",
            "alternativa_e": "",
            "resposta_correta": "",
            "explicacao": "",
            "dificuldade": "Médio"
        }
    }


# ==================== IMPORTAÇÃO VIA PDF (OCR) ====================

def _extrair_texto_pdf(file_path: str) -> str:
    """Extrai texto do PDF: primeiro tenta pypdf (texto digital), depois OCR se necessário."""
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    texto = ""
    for page in reader.pages:
        page_text = page.extract_text() or ""
        texto += page_text + "\n"

    # Se o texto extraído é muito curto, provavelmente é PDF escaneado — usar OCR
    if len(texto.strip()) < 100:
        try:
            from pdf2image import convert_from_path
            import pytesseract

            log.info("PDF sem texto selecionável, usando OCR...")
            images = convert_from_path(file_path, dpi=300)
            texto = ""
            for img in images:
                texto += pytesseract.image_to_string(img, lang='por') + "\n"
        except ImportError:
            log.warning("pytesseract/pdf2image não instalados. Instale com: pip install pytesseract pdf2image")
            raise
        except Exception as e:
            log.error(f"Erro no OCR: {e}")
            raise

    return texto


def _parse_gabarito(texto: str) -> dict:
    """Extrai gabarito do texto. Busca padrões como '1-A', '1.A', '1) A', 'Q1: A', etc."""
    gabarito = {}

    # Padrões comuns de gabarito
    patterns = [
        r'(\d+)\s*[-–.):]\s*([A-Ea-e])',           # 1-A, 1.A, 1)A, 1: A
        r'[Qq](?:uestão)?\s*(\d+)\s*[-–.):]\s*([A-Ea-e])',  # Q1: A, Questão 1: A
        r'(\d+)\s*\|\s*([A-Ea-e])',                 # 1 | A
    ]

    for pattern in patterns:
        matches = re.findall(pattern, texto)
        if matches:
            for num, letra in matches:
                gabarito[int(num)] = letra.upper()
            if len(gabarito) >= 3:
                break

    return gabarito


def _parse_qconcursos(texto: str, materia_override: str = "") -> list:
    """
    Parser para formato QConcursos:
    Ano: 2026Banca: FUNDATECÓrgão: Polícia Penal - RS
    [enunciado]
    A [texto alternativa A]
    B [texto alternativa B]
    ...
    
    Gabarito no final: "Respostas\n1:B 2:D 3:B..."
    """
    questoes = []

    # 1. Extrair gabarito do final (formato "1:B 2:D 3:B" ou "1:B\n2:D\n3:B")
    gabarito = {}
    gab_match = re.search(r'(?:Respostas|Gabarito|GABARITO)\s*\n(.+?)(?:www\.|$)', texto, re.DOTALL | re.IGNORECASE)
    if gab_match:
        gab_text = gab_match.group(1)
        # Padrão "1:B" ou "1: B"
        gab_entries = re.findall(r'(\d+)\s*:\s*([A-Ea-e])', gab_text)
        for num, letra in gab_entries:
            gabarito[int(num)] = letra.upper()
    
    # Remover seção de gabarito e metadados finais do texto de questões
    texto_limpo = texto
    # Remover bloco "18 Q4228074 >Direito..." (índice de questões no final)
    texto_limpo = re.sub(r'\d+\s+Q\d+\s+>.*?(?=Ano:\s*\d{4}|Respostas|$)', '', texto_limpo, flags=re.DOTALL)
    # Remover seção de respostas
    texto_limpo = re.sub(r'(?:Respostas|Gabarito)\s*\n.*$', '', texto_limpo, flags=re.DOTALL | re.IGNORECASE)
    # Remover header do site
    texto_limpo = re.sub(r'www\.qconcursos\.com\s*\n?', '', texto_limpo)

    # 2. Separar questões pelo padrão "Ano: XXXX"
    header_pattern = r'Ano:\s*(\d{4})\s*Banca:\s*(.+?)(?:Órgão|Orgão|Prova):\s*(.+?)(?=\n|$)'
    
    # Dividir o texto em blocos de questões usando o header como separador
    splits = re.split(r'(?=Ano:\s*\d{4}\s*Banca:)', texto_limpo)
    
    # Determinar numeração base do gabarito (ex: se começa em 21, offset = 21)
    gab_start = min(gabarito.keys()) if gabarito else 1
    quest_num = gab_start - 1  # será incrementado para gab_start na primeira questão
    for bloco in splits:
        bloco = bloco.strip()
        if not bloco or len(bloco) < 30:
            continue
        
        # Extrair metadados do header
        header_match = re.match(header_pattern, bloco, re.IGNORECASE)
        if not header_match:
            continue
        
        quest_num += 1
        ano = header_match.group(1)
        banca_q = header_match.group(2).strip().rstrip('Óó')
        orgao = header_match.group(3).strip()
        
        # Limpar banca (pode ter "Órgão" colado)
        banca_q = re.sub(r'[ÓO]rg[ãa]o.*$', '', banca_q, flags=re.IGNORECASE).strip()
        
        # Texto após o header = enunciado + alternativas
        corpo = bloco[header_match.end():].strip()
        
        if len(corpo) < 20:
            continue
        
        # Encontrar alternativas
        # Formato QConcursos: letra seguida de espaço no início de linha
        alt_pattern = r'(?:^|\n)\s*([A-E])\s+(.+?)(?=(?:^|\n)\s*[A-E]\s+|\Z)'
        alt_matches = re.findall(alt_pattern, corpo, re.DOTALL)
        
        if len(alt_matches) < 4:
            # Tentar variação: letra seguida de espaço (mais agressivo)
            alt_pattern2 = r'(?:^|\n)([A-E])\s{1,3}(.+?)(?=(?:^|\n)[A-E]\s{1,3}|\Z)'
            alt_matches = re.findall(alt_pattern2, corpo, re.DOTALL)
        
        if len(alt_matches) < 4:
            continue
        
        # Encontrar onde começa a primeira alternativa para separar o enunciado
        first_alt_re = re.search(r'(?:^|\n)\s*A\s+', corpo, re.MULTILINE)
        if first_alt_re:
            enunciado = corpo[:first_alt_re.start()].strip()
        else:
            enunciado = corpo.split('\n')[0].strip()
        
        # Limpar enunciado (remover quebras de linha internas)
        enunciado = re.sub(r'\s*\n\s*', ' ', enunciado).strip()
        
        if len(enunciado) < 15:
            continue
        
        # Montar alternativas
        alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
        for letra, texto_alt in alt_matches[:5]:
            # Limpar texto da alternativa (remover quebras internas)
            clean_text = re.sub(r'\s*\n\s*', ' ', texto_alt).strip()
            alts[letra.upper()] = clean_text
        
        # Buscar resposta no gabarito
        resposta = gabarito.get(quest_num, '')
        
        questao = {
            "numero": quest_num,
            "materia": materia_override or "",
            "topico": "",
            "enunciado": enunciado,
            "alternativa_a": alts['A'],
            "alternativa_b": alts['B'],
            "alternativa_c": alts['C'],
            "alternativa_d": alts['D'],
            "alternativa_e": alts['E'],
            "resposta_correta": resposta,
            "explicacao": "",
            "dificuldade": "Médio",
            "banca": banca_q,
        }
        questoes.append(questao)
    
    return questoes


def _parse_questoes_texto(texto: str, materia: str = "", banca: str = "") -> list:
    """Analisa texto extraído e separa em questões individuais."""
    questoes = []

    # Detectar formato QConcursos (Ano: XXXX Banca: XXX Órgão: XXX)
    if re.search(r'Ano:\s*\d{4}\s*Banca:', texto):
        return _parse_qconcursos(texto, materia_override=materia)

    # Separar seção de questões da seção de gabarito
    # Identificar onde começa o gabarito
    gab_markers = ['GABARITO', 'Gabarito', 'RESPOSTAS', 'Respostas', 'CARTÃO RESPOSTA']
    texto_questoes = texto
    texto_gabarito = ""

    for marker in gab_markers:
        pos = texto.rfind(marker)
        if pos > 0:
            texto_questoes = texto[:pos]
            texto_gabarito = texto[pos:]
            break

    # Extrair gabarito
    gabarito = _parse_gabarito(texto_gabarito if texto_gabarito else texto)

    # Padrões para identificar início de questão
    quest_patterns = [
        r'(?:^|\n)\s*(?:QUESTÃO|Questão|questão)\s+(\d+)',
        r'(?:^|\n)\s*(\d+)\s*[.)]\s+(?=[A-Z])',      # "1. " ou "1) " seguido de letra maiúscula
        r'(?:^|\n)\s*(\d+)\s*[-–]\s+',                # "1 - "
    ]

    # Encontrar posições de início de cada questão
    quest_positions = []
    for pattern in quest_patterns:
        for m in re.finditer(pattern, texto_questoes):
            quest_positions.append((m.start(), int(m.group(1)), m.end()))
        if quest_positions:
            break

    # Ordenar por posição
    quest_positions.sort(key=lambda x: x[0])

    # Extrair texto de cada questão
    for i, (start, num, text_start) in enumerate(quest_positions):
        # Fim é o início da próxima questão ou fim do texto
        end = quest_positions[i + 1][0] if i + 1 < len(quest_positions) else len(texto_questoes)
        bloco = texto_questoes[text_start:end].strip()

        if len(bloco) < 20:
            continue

        # Separar enunciado e alternativas
        alt_pattern = r'\n\s*\(?([A-Ea-e])\)?\s*[-–.]?\s*(.+?)(?=\n\s*\(?[A-Ea-e]\)|\Z)'
        alternativas_matches = re.findall(alt_pattern, bloco, re.DOTALL)

        if len(alternativas_matches) < 4:
            # Tentar outro padrão
            alt_pattern2 = r'(?:^|\n)\s*([A-Ea-e])\s*[).\-–]\s*(.+?)(?=(?:^|\n)\s*[A-Ea-e]\s*[).\-–]|\Z)'
            alternativas_matches = re.findall(alt_pattern2, bloco, re.DOTALL)

        if len(alternativas_matches) < 4:
            continue

        # Encontrar onde começa a primeira alternativa para separar enunciado
        first_alt_pos = bloco.find(alternativas_matches[0][1].strip()[:20])
        if first_alt_pos > 0:
            # Voltar até a letra da alternativa
            search_back = bloco[:first_alt_pos].rfind(alternativas_matches[0][0])
            enunciado = bloco[:search_back].strip() if search_back > 0 else bloco[:first_alt_pos].strip()
        else:
            enunciado = bloco.split('\n')[0].strip()

        # Limpar enunciado
        enunciado = re.sub(r'^\d+\s*[.):\-–]\s*', '', enunciado).strip()

        # Montar alternativas
        alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
        for letra, texto_alt in alternativas_matches[:5]:
            alts[letra.upper()] = texto_alt.strip()

        # Buscar resposta no gabarito
        resposta = gabarito.get(num, '')

        questao = {
            "numero": num,
            "materia": materia,
            "topico": "",
            "enunciado": enunciado,
            "alternativa_a": alts['A'],
            "alternativa_b": alts['B'],
            "alternativa_c": alts['C'],
            "alternativa_d": alts['D'],
            "alternativa_e": alts['E'],
            "resposta_correta": resposta,
            "explicacao": "",
            "dificuldade": "Médio",
            "banca": banca,
        }
        questoes.append(questao)

    return questoes


@router.post("/api/questoes/importar-pdf",
             summary="Importar questões de PDF",
             description="Extrai questões de um PDF (com texto ou escaneado via OCR) e cadastra no banco")
async def importar_questoes_pdf(
    file: UploadFile = File(...),
    materia: str = "",
    banca: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """
    Aceita PDF com questões de múltipla escolha e gabarito.
    - Extrai texto via pypdf (PDF digital) ou pytesseract (PDF escaneado/OCR)
    - Identifica questões numeradas com alternativas A-E
    - Busca gabarito no mesmo PDF (seção 'GABARITO' ou padrão '1-A, 2-B...')
    """
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    # Salvar arquivo temporário
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Extrair texto
        texto = _extrair_texto_pdf(tmp_path)

        if len(texto.strip()) < 50:
            raise HTTPException(status_code=400, detail="Não foi possível extrair texto do PDF. Verifique se o arquivo contém questões legíveis.")

        # Parsear questões
        questoes = _parse_questoes_texto(texto, materia=materia, banca=banca)

        if not questoes:
            # Retornar o texto extraído para debug
            return {
                "ok": False,
                "importadas": 0,
                "erro": "Não foi possível identificar questões no formato esperado.",
                "texto_extraido_preview": texto[:2000],
                "dica": "O PDF deve conter questões numeradas (1, 2, 3...) com alternativas (A, B, C, D, E) e preferencialmente uma seção de GABARITO."
            }

        # Inserir no banco
        count = 0
        sem_gabarito = 0
        for q in questoes:
            if not q["enunciado"] or len(q["enunciado"]) < 10:
                continue
            if not q["resposta_correta"]:
                sem_gabarito += 1
            conn.execute("""
                INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                    alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (q["materia"], q["topico"], q["enunciado"], q["alternativa_a"], q["alternativa_b"],
                  q["alternativa_c"], q["alternativa_d"], q["alternativa_e"], q["resposta_correta"],
                  q["explicacao"], q["dificuldade"], q["banca"], today_str(), user_id))
            count += 1

        conn.commit()
        log.info(f"PDF import: {count} questões importadas de {file.filename}")

        return {
            "ok": True,
            "importadas": count,
            "sem_gabarito": sem_gabarito,
            "total_detectadas": len(questoes),
            "mensagem": f"{count} questões importadas com sucesso!" + (f" ({sem_gabarito} sem gabarito identificado)" if sem_gabarito else "")
        }

    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="OCR não disponível. Instale: pip install pytesseract pdf2image. E instale o Tesseract: sudo apt install tesseract-ocr tesseract-ocr-por"
        ) from None
    except Exception as e:
        log.error(f"Erro ao importar PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar PDF: {str(e)}") from None
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
