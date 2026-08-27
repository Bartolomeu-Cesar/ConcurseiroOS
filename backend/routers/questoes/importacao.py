"""Importação de questões: CSV, PDF (OCR) e URL. Inclui parsers para QConcursos, Gran, CESPE/Cebraspe."""
import codecs
import csv
import io
import os
import re
import tempfile

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile

from database import get_db_session
from deps import get_user_id
from logger import log
from utils import today_str

router = APIRouter()


# ============================================================
# HELPER FUNCTIONS — CSV
# ============================================================

def _detect_csv_format(headers: list[str]) -> str:
    """Detecta o formato do CSV baseado nos cabeçalhos das colunas."""
    headers_lower = [h.lower().strip() for h in headers]

    qconcursos_markers = {"disciplina", "enunciado", "gabarito"}
    if qconcursos_markers.issubset(set(headers_lower)):
        return "qconcursos"

    gran_markers = {"questão", "alternativa a", "resposta"}
    if gran_markers.issubset(set(headers_lower)):
        return "gran"
    gran_markers_no_accent = {"questao", "alternativa a", "resposta"}
    if gran_markers_no_accent.issubset(set(headers_lower)):
        return "gran"

    return "unknown"


def _normalize_header(h: str) -> str:
    return h.strip().lower()


def _parse_csv_qconcursos(row: dict) -> dict:
    norm = {_normalize_header(k): v for k, v in row.items()}
    enunciado = norm.get("enunciado", "").strip()
    if not enunciado:
        return None
    return {
        "materia": norm.get("disciplina", "").strip(),
        "topico": norm.get("assunto", "").strip(),
        "enunciado": enunciado,
        "alternativa_a": norm.get("a", "").strip(),
        "alternativa_b": norm.get("b", "").strip(),
        "alternativa_c": norm.get("c", "").strip(),
        "alternativa_d": norm.get("d", "").strip(),
        "alternativa_e": norm.get("e", "").strip(),
        "resposta_correta": norm.get("gabarito", "").strip().upper(),
        "explicacao": norm.get("explicacao", norm.get("explicação", "")).strip(),
        "dificuldade": norm.get("dificuldade", "Médio").strip() or "Médio",
        "banca": norm.get("banca", "").strip(),
        "ano": norm.get("ano", "").strip(),
    }


def _parse_csv_gran(row: dict) -> dict:
    norm = {_normalize_header(k): v for k, v in row.items()}
    enunciado = norm.get("questão", norm.get("questao", "")).strip()
    if not enunciado:
        return None
    return {
        "materia": norm.get("matéria", norm.get("materia", "")).strip(),
        "topico": norm.get("tópico", norm.get("topico", "")).strip(),
        "enunciado": enunciado,
        "alternativa_a": norm.get("alternativa a", "").strip(),
        "alternativa_b": norm.get("alternativa b", "").strip(),
        "alternativa_c": norm.get("alternativa c", "").strip(),
        "alternativa_d": norm.get("alternativa d", "").strip(),
        "alternativa_e": norm.get("alternativa e", "").strip(),
        "resposta_correta": norm.get("resposta", "").strip().upper(),
        "explicacao": norm.get("explicacao", norm.get("explicação", "")).strip(),
        "dificuldade": norm.get("dificuldade", "Médio").strip() or "Médio",
        "banca": norm.get("banca", "").strip(),
        "ano": norm.get("ano", "").strip(),
    }


def _decode_csv_content(raw_bytes: bytes) -> str:
    try:
        if raw_bytes.startswith(codecs.BOM_UTF8):
            return raw_bytes.decode("utf-8-sig")
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw_bytes.decode("latin-1")
    except UnicodeDecodeError:
        return raw_bytes.decode("utf-8", errors="replace")


# ============================================================
# HELPER FUNCTIONS — PDF EXTRACTION
# ============================================================

def _extrair_texto_pdf(file_path: str) -> str:
    """Extrai texto do PDF: pdfplumber → pypdf → OCR."""
    texto = ""

    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                texto += page_text + "\n"
        if len(texto.strip()) > 100:
            return texto
    except ImportError:
        pass
    except Exception:
        pass

    from pypdf import PdfReader
    reader = PdfReader(file_path)
    texto = ""
    for page in reader.pages:
        page_text = page.extract_text() or ""
        texto += page_text + "\n"

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
            log.warning("pytesseract/pdf2image não instalados.")
            raise
        except Exception as e:
            log.error(f"Erro no OCR: {e}")
            raise

    return texto


def _parse_gabarito(texto: str) -> dict:
    """Extrai gabarito do texto (grid CESPE, padrões tradicionais, etc)."""
    gabarito = {}

    lines = [l.strip() for l in texto.split('\n') if l.strip()]
    for i in range(len(lines) - 1):
        nums = lines[i].split()
        answers = lines[i + 1].split()
        if len(nums) >= 3 and len(nums) == len(answers):
            all_nums = all(n.isdigit() for n in nums)
            all_answers = all(a.upper() in ('A', 'B', 'C', 'D', 'E', 'X', '0') for a in answers)
            if all_nums and all_answers:
                for num_str, ans in zip(nums, answers):
                    num = int(num_str)
                    a = ans.upper()
                    if num == 0 or a in ('0', 'X'):
                        continue
                    gabarito[num] = a

    if len(gabarito) >= 3:
        return gabarito

    patterns = [
        r'(\d+)\s*[-–.):]\s*([A-Ea-e])',
        r'[Qq](?:uestão)?\s*(\d+)\s*[-–.):]\s*([A-Ea-e])',
        r'(\d+)\s*\|\s*([A-Ea-e])',
        r'(\d+)\s+([A-Ea-e])\s',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, texto)
        if matches:
            for num, letra in matches:
                gabarito[int(num)] = letra.upper()
            if len(gabarito) >= 3:
                break

    if len(gabarito) < 3:
        short_lines = [l.strip() for l in texto.split('\n') if 3 <= len(l.strip()) <= 15]
        for line in short_lines:
            m = re.match(r'^(\d{1,3})\s+([A-EaCcEe])$', line)
            if m:
                gabarito[int(m.group(1))] = m.group(2).upper()

    return gabarito


# ============================================================
# HELPER FUNCTIONS — QUESTION PARSERS
# ============================================================

def _parse_qconcursos(texto: str, materia_override: str = "") -> list:
    """Parser para formato QConcursos (Ano: XXXX Banca: XXX)."""
    questoes = []

    gabarito = {}
    gab_match = re.search(r'(?:Respostas|Gabarito|GABARITO)\s*[:\n](.+?)(?:www\.|$)', texto, re.DOTALL | re.IGNORECASE)
    if gab_match:
        gab_text = gab_match.group(1)
        gab_entries = re.findall(r'(\d+)\s*:\s*([A-Ea-e])', gab_text)
        if gab_entries:
            for num, letra in gab_entries:
                gabarito[int(num)] = letra.upper()
        else:
            gab_entries = re.findall(r'(\d+)\s+([A-Ea-e])', gab_text)
            for num, letra in gab_entries:
                gabarito[int(num)] = letra.upper()

    if len(gabarito) < 3:
        last_chunk = texto[-3000:]
        gab_entries = re.findall(r'(\d+)\s+([A-Ea-e])(?:\s|$)', last_chunk)
        if len(gab_entries) >= 10:
            for num, letra in gab_entries:
                gabarito[int(num)] = letra.upper()

    texto_limpo = texto
    texto_limpo = re.sub(r'\d+\s+Q\d+\s+>.*?(?=Ano:\s*\d{4}|Respostas|$)', '', texto_limpo, flags=re.DOTALL)
    texto_limpo = re.sub(r'(?:Respostas|Gabarito)\s*\n.*$', '', texto_limpo, flags=re.DOTALL | re.IGNORECASE)
    texto_limpo = re.sub(r'www\.qconcursos\.com\s*\n?', '', texto_limpo)

    header_pattern = r'Ano:\s*(\d{4})\s*Banca:\s*(.+?)(?:Órgão|Orgão|Prova):\s*(.+?)(?=\n|$)'
    splits = re.split(r'(?=Ano:\s*\d{4}\s*Banca:)', texto_limpo)

    gab_start = min(gabarito.keys()) if gabarito else 1
    quest_num = gab_start - 1
    for bloco in splits:
        bloco = bloco.strip()
        if not bloco or len(bloco) < 30:
            continue

        header_match = re.match(header_pattern, bloco, re.IGNORECASE)
        if not header_match:
            continue

        quest_num += 1
        ano = header_match.group(1)
        banca_q = header_match.group(2).strip().rstrip('Óó')
        banca_q = re.sub(r'[ÓO]rg[ãa]o.*$', '', banca_q, flags=re.IGNORECASE).strip()

        corpo = bloco[header_match.end():].strip()
        if len(corpo) < 20:
            continue

        alt_pattern = r'(?:^|\n)\s*([A-E])\s+(.+?)(?=(?:^|\n)\s*[A-E]\s+|\Z)'
        alt_matches = re.findall(alt_pattern, corpo, re.DOTALL)

        if len(alt_matches) < 4:
            alt_pattern2 = r'(?:^|\n)([A-E])\s{1,3}(.+?)(?=(?:^|\n)[A-E]\s{1,3}|\Z)'
            alt_matches = re.findall(alt_pattern2, corpo, re.DOTALL)

        if len(alt_matches) < 4:
            continue

        first_alt_re = re.search(r'(?:^|\n)\s*A\s+', corpo, re.MULTILINE)
        if first_alt_re:
            enunciado = corpo[:first_alt_re.start()].strip()
        else:
            enunciado = corpo.split('\n')[0].strip()

        enunciado = re.sub(r'\s*\n\s*', ' ', enunciado).strip()
        if len(enunciado) < 15:
            continue

        alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
        for letra, texto_alt in alt_matches[:5]:
            clean_text = re.sub(r'\s*\n\s*', ' ', texto_alt).strip()
            alts[letra.upper()] = clean_text

        resposta = gabarito.get(quest_num, '')

        questoes.append({
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
        })

    return questoes


def _is_cespe_format(texto: str) -> bool:
    """Detecta se o PDF é formato CESPE/Cebraspe."""
    indicators = [
        r'(?i)cebraspe',
        r'(?i)cespe',
        r'(?i)julgue\s+o[s]?\s+(?:seguinte|próximo|item|iten)',
        r'(?i)marque.*?campo.*?(?:C|CERTO).*?(?:E|ERRADO)',
        r'(?i)item.*?CERTO.*?ERRADO',
    ]
    score = sum(1 for p in indicators if re.search(p, texto[:3000]))
    items_numbered = len(re.findall(r'\n\s*\d{1,3}\s+[A-Z]', texto[:5000]))
    alternatives = len(re.findall(r'\n\s*\(?[A-E]\)', texto[:5000]))
    if score >= 2 or (items_numbered > 5 and alternatives < 3):
        return True
    return False


def _parse_cespe_cebraspe(texto: str, materia: str = "", banca: str = "CESPE") -> list:
    """Parser para provas CESPE/Cebraspe (Certo/Errado)."""
    questoes = []

    tema_patterns = re.findall(
        r'(?i)(?:julgue|considere|com\s+base|a\s+respeito|acerca).*?(?:referentes?\s+a[o]?|sobre|relativos?\s+a[o]?|de\s+acordo\s+com\s+o\s+disposto\s+n[ao]?)\s+(.+?)(?:\.|,\s*julgue)',
        texto
    )
    tema_acerca = re.findall(
        r'(?i)(?:acerca\s+d[eoa]s?|(?:no|com)\s+(?:que|base).*?(?:refere|concerne).*?a[o]?)\s+(.+?)(?:,\s*julgue|\.\s*\n)',
        texto
    )
    materias_blocos = [(texto.find(t), t.strip()[:80]) for t in tema_patterns + tema_acerca if len(t.strip()) > 5]
    materias_blocos.sort(key=lambda x: x[0])

    gabarito = {}
    gab_section = ""
    for marker in ['GABARITO', 'Gabarito Oficial', 'GABARITO OFICIAL']:
        pos = texto.rfind(marker)
        if pos > 0:
            gab_section = texto[pos:]
            break

    if gab_section:
        gab_matches = re.findall(r'(\d{1,3})\s*[.\-–):]?\s*([CEce])', gab_section)
        for num, resp in gab_matches:
            gabarito[int(num)] = resp.upper()

    item_pattern = r'(?:^|\n)\s*(\d{1,3})\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][^\n]{15,})'
    items = list(re.finditer(item_pattern, texto))

    if not items:
        item_pattern = r'(?:^|\n)\s*(\d{1,3})\.\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][^\n]{15,})'
        items = list(re.finditer(item_pattern, texto))

    for i, match in enumerate(items):
        num = int(match.group(1))
        start = match.start()
        end = items[i + 1].start() if i + 1 < len(items) else len(texto)

        bloco = texto[match.start():end].strip()
        enunciado = re.sub(r'^\d{1,3}\s+', '', bloco).strip()
        enunciado = re.sub(r'\s*\n\s*', ' ', enunciado).strip()

        alt_match = re.findall(r'\(?([A-E])\)?\s*(.+?)(?=\(?[A-E]\)|$)', enunciado)

        if len(alt_match) >= 4:
            first_alt = re.search(r'\(?A\)?\s', enunciado)
            if first_alt:
                texto_enunciado = enunciado[:first_alt.start()].strip()
                alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
                for letra, txt in alt_match[:5]:
                    alts[letra] = txt.strip()

                resposta = gabarito.get(num, "")
                questoes.append({
                    "numero": num,
                    "enunciado": texto_enunciado,
                    "alternativa_a": alts['A'],
                    "alternativa_b": alts['B'],
                    "alternativa_c": alts['C'],
                    "alternativa_d": alts['D'],
                    "alternativa_e": alts['E'],
                    "resposta_correta": resposta,
                    "materia": materia,
                    "topico": "",
                    "explicacao": "",
                    "dificuldade": "Médio",
                    "banca": banca,
                    "tipo": "multipla_escolha",
                })
        else:
            if len(enunciado) > 800:
                enunciado = enunciado[:800].strip()
            if len(enunciado) < 30:
                continue
            if re.match(r'(?i)^(julgue|considere|com base|acerca|espaço livre|provas objetivas)', enunciado):
                continue

            resposta = gabarito.get(num, "")
            item_materia = materia
            if not item_materia and materias_blocos:
                for pos, tema in reversed(materias_blocos):
                    if pos < match.start():
                        item_materia = tema
                        break

            questoes.append({
                "numero": num,
                "enunciado": enunciado,
                "alternativa_a": "CERTO",
                "alternativa_b": "ERRADO",
                "alternativa_c": "",
                "alternativa_d": "",
                "alternativa_e": "",
                "resposta_correta": resposta if resposta in ('C', 'E') else "",
                "materia": item_materia or "Conhecimentos Gerais",
                "topico": "",
                "explicacao": "",
                "dificuldade": "Médio",
                "banca": banca,
                "tipo": "certo_errado",
            })

    for q in questoes:
        if q.get("tipo") == "certo_errado":
            if q["resposta_correta"] == "C":
                q["resposta_correta"] = "A"
            elif q["resposta_correta"] == "E":
                q["resposta_correta"] = "B"

    return questoes


def _parse_questoes_texto(texto: str, materia: str = "", banca: str = "") -> list:
    """Analisa texto extraído e separa em questões individuais."""
    if re.search(r'Ano:\s*\d{4}\s*Banca:', texto):
        return _parse_qconcursos(texto, materia_override=materia)

    if _is_cespe_format(texto):
        return _parse_cespe_cebraspe(texto, materia=materia, banca=banca or "CESPE")

    questoes = []
    gab_markers = ['GABARITO', 'Gabarito', 'RESPOSTAS', 'Respostas', 'CARTÃO RESPOSTA']
    texto_questoes = texto
    texto_gabarito = ""

    for marker in gab_markers:
        pos = texto.rfind(marker)
        if pos > 0:
            texto_questoes = texto[:pos]
            texto_gabarito = texto[pos:]
            break

    gabarito = _parse_gabarito(texto_gabarito if texto_gabarito else texto)

    quest_patterns = [
        r'(?:^|\n)\s*(?:QUESTÃO|Questão|questão)\s+(\d+)',
        r'(?:^|\n)\s*(\d+)\s*[.)]\s+(?=[A-Z])',
        r'(?:^|\n)\s*(\d+)\s*[-–]\s+',
    ]

    quest_positions = []
    for pattern in quest_patterns:
        for m in re.finditer(pattern, texto_questoes):
            quest_positions.append((m.start(), int(m.group(1)), m.end()))
        if quest_positions:
            break

    quest_positions.sort(key=lambda x: x[0])

    for i, (start, num, text_start) in enumerate(quest_positions):
        end = quest_positions[i + 1][0] if i + 1 < len(quest_positions) else len(texto_questoes)
        bloco = texto_questoes[text_start:end].strip()

        if len(bloco) < 20:
            continue

        alt_pattern = r'\n\s*\(?([A-Ea-e])\)?\s*[-–.]?\s*(.+?)(?=\n\s*\(?[A-Ea-e]\)|\Z)'
        alternativas_matches = re.findall(alt_pattern, bloco, re.DOTALL)

        if len(alternativas_matches) < 4:
            alt_pattern2 = r'(?:^|\n)\s*([A-Ea-e])\s*[).\-–]\s*(.+?)(?=(?:^|\n)\s*[A-Ea-e]\s*[).\-–]|\Z)'
            alternativas_matches = re.findall(alt_pattern2, bloco, re.DOTALL)

        if len(alternativas_matches) < 4:
            alt_pattern3 = r'\n([A-E]) (.+?)(?=\n[A-E] |\nEssa quest|\Z)'
            alternativas_matches = re.findall(alt_pattern3, bloco, re.DOTALL)

        if len(alternativas_matches) < 4:
            continue

        first_alt_pos = bloco.find(alternativas_matches[0][1].strip()[:20])
        if first_alt_pos > 0:
            search_back = bloco[:first_alt_pos].rfind(alternativas_matches[0][0])
            enunciado = bloco[:search_back].strip() if search_back > 0 else bloco[:first_alt_pos].strip()
        else:
            enunciado = bloco.split('\n')[0].strip()

        enunciado = re.sub(r'^\d+\s*[.):\-–]\s*', '', enunciado).strip()
        enunciado = re.sub(
            r'^(\d{4}\s+.*?(?:FCC|CESPE|CEBRASPE|VUNESP|FGV|FUNDATEC|IADES|IBFC|QUADRIX).*?\n(?:.*?\n){0,3})',
            '', enunciado, count=1, flags=re.DOTALL | re.IGNORECASE
        ).strip()
        while enunciado and re.match(r'^[^\n]{3,80}\s+\d{5,}\s*$', enunciado.split('\n')[0]):
            enunciado = '\n'.join(enunciado.split('\n')[1:]).strip()
        enunciado = re.sub(r'^Quest.es oficiais.*?\n', '', enunciado).strip()
        enunciado = re.sub(r'Essa quest.o possui coment.rio.*$', '', enunciado, flags=re.MULTILINE).strip()
        enunciado = re.sub(r'\s*\n\s*', ' ', enunciado).strip()

        alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
        for letra, texto_alt in alternativas_matches[:5]:
            clean = re.sub(r'\s*\n\s*', ' ', texto_alt).strip()
            clean = re.sub(r'Essa quest.o possui coment.rio.*$', '', clean).strip()
            alts[letra.upper()] = clean

        resposta = gabarito.get(num, '')

        questoes.append({
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
        })

    return questoes


# ============================================================
# ENDPOINTS — IMPORTAÇÃO CSV
# ============================================================

@router.post("/api/questoes/importar-csv", summary="Importar questões via CSV",
             description="Importa questões de CSVs exportados do QConcursos ou Gran Cursos")
async def importar_csv(
    file: UploadFile = File(...),
    formato: str = Query("auto", description="Formato: auto, qconcursos, gran"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Apenas arquivos CSV são aceitos.")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    text_content = _decode_csv_content(raw_bytes)

    first_line = text_content.split('\n', 1)[0]
    delimiter = ';' if first_line.count(';') > first_line.count(',') else ','

    reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV sem cabeçalho válido.")

    detected_format = formato
    if formato == "auto":
        detected_format = _detect_csv_format(reader.fieldnames)
        if detected_format == "unknown":
            raise HTTPException(
                status_code=400,
                detail=f"Formato não reconhecido. Cabeçalhos encontrados: {', '.join(reader.fieldnames)}. "
                       f"Use formato=qconcursos ou formato=gran explicitamente."
            )

    if detected_format == "qconcursos":
        parse_row = _parse_csv_qconcursos
    elif detected_format == "gran":
        parse_row = _parse_csv_gran
    else:
        raise HTTPException(status_code=400, detail=f"Formato inválido: {formato}. Use: auto, qconcursos, gran.")

    imported = 0
    duplicates = 0
    errors = []
    row_num = 0
    MAX_ROWS = 5000

    for row in reader:
        row_num += 1
        if row_num > MAX_ROWS:
            errors.append(f"Limite de {MAX_ROWS} linhas atingido. Linhas restantes ignoradas.")
            break

        try:
            questao = parse_row(row)
            if questao is None:
                errors.append(f"Linha {row_num + 1}: enunciado vazio, ignorada.")
                continue

            if len(questao["enunciado"]) < 10:
                errors.append(f"Linha {row_num + 1}: enunciado muito curto ({len(questao['enunciado'])} chars).")
                continue

            existing = conn.execute(
                "SELECT id FROM questoes WHERE user_id = ? AND enunciado = ? AND banca = ? AND created_at LIKE ?",
                (user_id, questao["enunciado"], questao["banca"],
                 f"%{questao.get('ano', '')}%" if questao.get("ano") else "%")
            ).fetchone()

            if existing:
                duplicates += 1
                continue

            conn.execute("""
                INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                    alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao,
                    dificuldade, banca, ano, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                questao["materia"], questao["topico"], questao["enunciado"],
                questao["alternativa_a"], questao["alternativa_b"],
                questao["alternativa_c"], questao["alternativa_d"], questao["alternativa_e"],
                questao["resposta_correta"], questao.get("explicacao", ""),
                questao["dificuldade"], questao["banca"], questao.get("ano", ""),
                today_str(), user_id,
            ))
            imported += 1

        except Exception as e:
            errors.append(f"Linha {row_num + 1}: {str(e)}")

    conn.commit()
    log.info(f"CSV import: {imported} questões importadas de {file.filename} (formato={detected_format}, duplicatas={duplicates})")

    return {
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors[:50],
        "format_detected": detected_format,
        "total_rows": row_num,
    }


# ============================================================
# ENDPOINTS — IMPORTAÇÃO PDF
# ============================================================

@router.post("/api/questoes/importar-pdf",
             summary="Importar questões de PDF",
             description="Extrai questões de um PDF (com texto ou escaneado via OCR) e cadastra no banco")
async def importar_questoes_pdf(
    file: UploadFile = File(...),
    gabarito_file: UploadFile = File(None),
    materia: str = "",
    banca: str = "",
    prova_nome: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    gabarito_externo = {}
    if gabarito_file and gabarito_file.filename:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_gab:
            gab_content = await gabarito_file.read()
            tmp_gab.write(gab_content)
            tmp_gab_path = tmp_gab.name
        try:
            gab_texto = _extrair_texto_pdf(tmp_gab_path)
            gabarito_externo = _parse_gabarito(gab_texto)
            if not gabarito_externo:
                matches = re.findall(r'(\d{1,3})\s*[.\-–):]?\s*([A-Ea-eCcEeXx])', gab_texto)
                for num, resp in matches:
                    r = resp.upper()
                    if r == 'X':
                        continue
                    gabarito_externo[int(num)] = r
        except Exception:
            pass
        finally:
            os.unlink(tmp_gab_path)

    try:
        texto = _extrair_texto_pdf(tmp_path)

        if len(texto.strip()) < 50:
            raise HTTPException(status_code=400, detail="Não foi possível extrair texto do PDF.")

        questoes = _parse_questoes_texto(texto, materia=materia, banca=banca)

        if gabarito_externo and questoes:
            for q in questoes:
                num = q.get("numero", 0)
                if num in gabarito_externo and not q.get("resposta_correta"):
                    gab = gabarito_externo[num]
                    if gab in ('C', 'E') and q.get("tipo") == "certo_errado":
                        q["resposta_correta"] = "A" if gab == "C" else "B"
                    elif gab in ('A', 'B', 'C', 'D', 'E'):
                        q["resposta_correta"] = gab

        if not questoes:
            return {
                "ok": False,
                "importadas": 0,
                "erro": "Não foi possível identificar questões no formato esperado.",
                "texto_extraido_preview": texto[:2000],
                "dica": "O PDF deve conter questões numeradas (1, 2, 3...) com alternativas (A, B, C, D, E)."
            }

        existing_enunciados = set()
        rows_existing = conn.execute(
            "SELECT enunciado FROM questoes WHERE user_id = ?", (user_id,)
        ).fetchall()
        for row in rows_existing:
            normalized = ' '.join(row[0].split()).strip()[:200]
            existing_enunciados.add(normalized)

        nome_prova = prova_nome or file.filename.replace('.pdf', '').replace('-', ' ').replace('_', ' ')

        count = 0
        sem_gabarito = 0
        duplicates = 0
        for q in questoes:
            if not q["enunciado"] or len(q["enunciado"]) < 10:
                continue

            normalized = ' '.join(q["enunciado"].split()).strip()[:200]
            if normalized in existing_enunciados:
                duplicates += 1
                continue

            existing_enunciados.add(normalized)
            if not q["resposta_correta"]:
                sem_gabarito += 1

            conn.execute("""
                INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                    alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, prova_origem, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (q["materia"], q["topico"], q["enunciado"], q["alternativa_a"], q["alternativa_b"],
                  q["alternativa_c"], q["alternativa_d"], q["alternativa_e"], q["resposta_correta"],
                  q["explicacao"], q["dificuldade"], q["banca"], nome_prova, today_str(), user_id))
            count += 1

        conn.commit()
        log.info(f"PDF import: {count} questões importadas de {file.filename} (prova: {nome_prova}, duplicatas: {duplicates})")

        return {
            "ok": True,
            "importadas": count,
            "duplicatas": duplicates,
            "sem_gabarito": sem_gabarito,
            "total_detectadas": len(questoes),
            "mensagem": f"{count} questões importadas com sucesso!"
                + (f" ({sem_gabarito} sem gabarito identificado)" if sem_gabarito else "")
                + (f" ({duplicates} duplicata(s) ignorada(s))" if duplicates else "")
        }

    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="OCR não disponível. Instale: pip install pytesseract pdf2image."
        ) from None
    except Exception as e:
        log.error(f"Erro ao importar PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar PDF: {str(e)}") from None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ============================================================
# ENDPOINTS — APLICAR GABARITO
# ============================================================

@router.post("/api/questoes/aplicar-gabarito", summary="Aplicar gabarito PDF em questões já importadas",
             description="Envia apenas o PDF do gabarito para associar respostas às questões de uma prova específica.")
async def aplicar_gabarito_pdf(
    file: UploadFile = File(...),
    prova_origem: str = "",
    banca: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        texto = _extrair_texto_pdf(tmp_path)
        gabarito = _parse_gabarito(texto)
        if not gabarito:
            matches = re.findall(r'(\d{1,3})\s*[.\-–):]?\s*([A-Ea-eCcEeXx])', texto)
            for num, resp in matches:
                r = resp.upper()
                if r != 'X':
                    gabarito[int(num)] = r

        if not gabarito:
            return {
                "ok": False,
                "erro": "Não foi possível extrair gabarito do PDF.",
                "texto_preview": texto[:1000],
            }

        if prova_origem:
            questoes_prova = conn.execute("""
                SELECT id, enunciado FROM questoes
                WHERE user_id = ? AND prova_origem = ?
                ORDER BY id
            """, (user_id, prova_origem)).fetchall()
        else:
            ultima_prova = conn.execute("""
                SELECT prova_origem FROM questoes
                WHERE user_id = ? AND prova_origem != '' AND (resposta_correta = '' OR resposta_correta IS NULL)
                GROUP BY prova_origem
                ORDER BY MAX(id) DESC LIMIT 1
            """, (user_id,)).fetchone()
            if ultima_prova:
                prova_origem = ultima_prova[0]
                questoes_prova = conn.execute("""
                    SELECT id, enunciado FROM questoes
                    WHERE user_id = ? AND prova_origem = ?
                    ORDER BY id
                """, (user_id, prova_origem)).fetchall()
            else:
                return {"ok": False, "erro": "Nenhuma prova sem gabarito encontrada."}

        if not questoes_prova:
            return {"ok": False, "erro": f"Nenhuma questão encontrada para a prova '{prova_origem}'."}

        aplicadas = 0
        anuladas = 0
        for i, (qid, enunciado) in enumerate(questoes_prova):
            num = i + 1
            if num in gabarito:
                gab = gabarito[num]
                if gab == 'X':
                    conn.execute("UPDATE questoes SET explicacao = '⚠️ QUESTÃO ANULADA', resposta_correta = '' WHERE id = ?", (qid,))
                    anuladas += 1
                elif gab in ('C', 'E'):
                    resposta = 'A' if gab == 'C' else 'B'
                    conn.execute("UPDATE questoes SET resposta_correta = ? WHERE id = ?", (resposta, qid))
                    aplicadas += 1
                elif gab in ('A', 'B', 'C', 'D', 'E'):
                    conn.execute("UPDATE questoes SET resposta_correta = ? WHERE id = ?", (gab, qid))
                    aplicadas += 1

        conn.commit()

        return {
            "ok": True,
            "prova": prova_origem,
            "aplicadas": aplicadas,
            "anuladas": anuladas,
            "total_gabarito": len(gabarito),
            "total_questoes_prova": len(questoes_prova),
            "mensagem": f"Gabarito aplicado em '{prova_origem}'! {aplicadas} respostas." + (f" {anuladas} anuladas." if anuladas else ""),
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao processar gabarito: {e}") from e
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ============================================================
# ENDPOINTS — IMPORTAÇÃO POR URL
# ============================================================

@router.post("/api/questoes/importar-url",
             summary="Importar questões de prova via URL",
             description="Baixa PDF de prova + gabarito de URLs externas e importa as questões automaticamente.")
async def importar_questoes_url(
    prova_url: str = Body("", embed=True),
    gabarito_url: str = Body("", embed=True),
    materia: str = Body("", embed=True),
    banca: str = Body("CESPE", embed=True),
    prova_nome: str = Body("", embed=True),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    import httpx

    if not prova_url:
        raise HTTPException(status_code=400, detail="Informe a URL da prova (prova_url).")

    allowed_domains = ["gabarite.com.br", "pciconcursos.com.br", "cebraspe.org.br", "cdn.cebraspe.org.br",
                       "qconcursos.com", "estrategiaconcursos.com.br", "grancursos.com.br"]
    from urllib.parse import urlparse
    parsed = urlparse(prova_url)
    domain = parsed.netloc.replace("www.", "")

    is_pdf_direct = prova_url.lower().endswith('.pdf')
    is_allowed_domain = any(d in domain for d in allowed_domains)

    if not is_pdf_direct and not is_allowed_domain:
        raise HTTPException(
            status_code=400,
            detail=f"Domínio não permitido: {domain}. Use URLs de sites de concursos conhecidos ou links diretos para PDF."
        )

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            log.info(f"Downloading prova from: {prova_url}")
            resp = await client.get(prova_url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Erro ao baixar prova: HTTP {resp.status_code}")
            prova_content = resp.content

            if not prova_content[:5] == b'%PDF-':
                raise HTTPException(
                    status_code=400,
                    detail="O link não retornou um PDF direto. Use o link direto de download (geralmente termina em .pdf)."
                )

            gabarito_content = None
            if gabarito_url:
                log.info(f"Downloading gabarito from: {gabarito_url}")
                resp_gab = await client.get(gabarito_url, headers={"User-Agent": "Mozilla/5.0"})
                if resp_gab.status_code == 200 and resp_gab.content[:5] == b'%PDF-':
                    gabarito_content = resp_gab.content

    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="Timeout ao baixar. Tente novamente ou use um link mais rápido.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao baixar: {str(e)}")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(prova_content)
        tmp_path = tmp.name

    gabarito_externo = {}
    tmp_gab_path = None
    if gabarito_content:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_gab:
            tmp_gab.write(gabarito_content)
            tmp_gab_path = tmp_gab.name
        try:
            gab_texto = _extrair_texto_pdf(tmp_gab_path)
            gabarito_externo = _parse_gabarito(gab_texto)
        except Exception:
            pass

    try:
        texto = _extrair_texto_pdf(tmp_path)
        if not texto or len(texto) < 100:
            raise HTTPException(status_code=400, detail="Não foi possível extrair texto do PDF. Pode ser escaneado (sem OCR).")

        questoes_raw = _parse_questoes_texto(texto, materia=materia, banca=banca)

        if gabarito_externo and questoes_raw:
            for q in questoes_raw:
                num = q.get("numero", 0)
                if num in gabarito_externo and not q.get("resposta_correta"):
                    gab = gabarito_externo[num]
                    if gab in ('C', 'E') and q.get("tipo") == "certo_errado":
                        q["resposta_correta"] = "A" if gab == "C" else "B"
                    elif gab in ('A', 'B', 'C', 'D', 'E'):
                        q["resposta_correta"] = gab

        if not questoes_raw:
            raise HTTPException(status_code=400, detail="Nenhuma questão encontrada no PDF. Verifique se o formato é suportado.")

        count = 0
        duplicates = 0
        nome_prova = prova_nome or f"{banca} - {domain}"

        for q in questoes_raw:
            enunciado = q.get("enunciado", "").strip()
            if not enunciado or len(enunciado) < 20:
                continue

            existing = conn.execute(
                "SELECT id FROM questoes WHERE enunciado = ? AND user_id = ?",
                (enunciado[:200], user_id)
            ).fetchone()
            if existing:
                duplicates += 1
                continue

            mat = q.get("materia") or materia or "Geral"
            resp_correta = q.get("resposta_correta", "")

            conn.execute("""
                INSERT INTO questoes (enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e,
                                     resposta_correta, materia, banca, dificuldade, prova_origem, user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                enunciado,
                q.get("alternativa_a", ""), q.get("alternativa_b", ""),
                q.get("alternativa_c", ""), q.get("alternativa_d", ""), q.get("alternativa_e", ""),
                resp_correta, mat, banca, q.get("dificuldade", "Médio"),
                nome_prova, user_id, today_str()
            ))
            count += 1

        conn.commit()
        log.info(f"URL import: {count} questões de {prova_url} (duplicatas: {duplicates})")

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        if tmp_gab_path:
            try:
                os.unlink(tmp_gab_path)
            except OSError:
                pass

    return {
        "ok": True,
        "questoes_importadas": count,
        "duplicatas_ignoradas": duplicates,
        "total_encontradas": len(questoes_raw),
        "prova_nome": nome_prova,
        "url": prova_url,
        "mensagem": f"✅ {count} questões importadas de {nome_prova}. {duplicates} duplicatas ignoradas.",
    }


# ============================================================
# PARSER CESPE/CEBRASPE — Questões Certo/Errado
# ============================================================

def _parse_cespe_certo_errado(texto: str, materia_override: str = "", gabarito: dict = None) -> list:
    """Parser específico para provas CESPE/CEBRASPE formato Certo/Errado.

    Detecta itens numerados onde a resposta é C (Certo) ou E (Errado).
    Formato típico: número do item + enunciado + julgamento C/E no gabarito.
    """
    questoes = []
    if gabarito is None:
        gabarito = {}

    # Detectar padrão CESPE: itens numerados sequenciais
    # Padrão 1: "XX  texto do item" (2 espaços entre número e texto)
    # Padrão 2: "Item XX. texto"
    # Padrão 3: "XX) texto" ou "XX. texto"
    patterns = [
        r'(?:^|\n)\s*(\d{1,3})\s{2,}(.+?)(?=\n\s*\d{1,3}\s{2,}|\Z)',
        r'(?:^|\n)\s*(?:Item\s+)?(\d{1,3})\s*[.)]\s*(.+?)(?=\n\s*(?:Item\s+)?\d{1,3}\s*[.)]|\Z)',
    ]

    itens = []
    for pattern in patterns:
        matches = re.findall(pattern, texto, re.DOTALL)
        if len(matches) >= 5:  # Mínimo 5 itens para considerar prova CESPE
            itens = matches
            break

    if not itens:
        return []

    # Se não tem gabarito, tentar extrair do final do texto
    if not gabarito:
        # Padrão gabarito CESPE: "1-C 2-E 3-C" ou grid
        gab_patterns = [
            r'(\d+)\s*[-–]\s*([CEce])',
            r'(\d+)\s+([CEce])(?:\s|$)',
        ]
        last_chunk = texto[-2000:]
        for gp in gab_patterns:
            gab_matches = re.findall(gp, last_chunk)
            if len(gab_matches) >= 5:
                for num, resp in gab_matches:
                    gabarito[int(num)] = "A" if resp.upper() == "C" else "B"
                break

    for num_str, enunciado in itens:
        num = int(num_str)
        enunciado = enunciado.strip()
        enunciado = re.sub(r'\s+', ' ', enunciado)  # Normalizar espaços

        if len(enunciado) < 15:
            continue

        # Resposta: A = CERTO, B = ERRADO (convenção interna)
        resposta = gabarito.get(num, "")

        questoes.append({
            "materia": materia_override,
            "topico": "",
            "enunciado": enunciado,
            "alternativa_a": "CERTO",
            "alternativa_b": "ERRADO",
            "alternativa_c": "",
            "alternativa_d": "",
            "alternativa_e": "",
            "resposta_correta": resposta,
            "explicacao": "",
            "dificuldade": "Médio",
            "banca": "CESPE",
            "ano": "",
        })

    return questoes


# ============================================================
# ENDPOINT: Preview antes de importar (pré-visualização)
# ============================================================

@router.post("/api/questoes/importar/preview", summary="Pré-visualizar importação de prova",
             description="Analisa o PDF/arquivo e retorna preview das questões detectadas sem importar. Permite revisar antes de confirmar.")
def preview_importacao(
    file: UploadFile = File(...),
    materia: str = Query("", description="Matéria padrão"),
    banca: str = Query("", description="Banca (CESPE, FCC, FGV, VUNESP)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Pré-visualiza questões do arquivo sem importar. Retorna preview para confirmação."""
    content = file.file.read()
    filename = file.filename or ""

    questoes_preview = []

    if filename.lower().endswith('.pdf'):
        # Salvar temporariamente para processar
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        tmp.write(content)
        tmp.close()

        try:
            texto = _extrair_texto_pdf(tmp.name)
        except Exception as e:
            os.unlink(tmp.name)
            raise HTTPException(400, f"Erro ao ler PDF: {e}")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        # Detectar formato automaticamente
        formato_detectado = "generico"
        banca_detectada = banca.upper() if banca else ""

        # Detectar banca pelo conteúdo
        texto_upper = texto.upper()
        if "CEBRASPE" in texto_upper or "CESPE" in texto_upper:
            banca_detectada = "CESPE"
        elif "FCC" in texto_upper or "FUNDAÇÃO CARLOS CHAGAS" in texto_upper:
            banca_detectada = "FCC"
        elif "FGV" in texto_upper or "FUNDAÇÃO GETÚLIO VARGAS" in texto_upper or "GETULIO VARGAS" in texto_upper:
            banca_detectada = "FGV"
        elif "VUNESP" in texto_upper:
            banca_detectada = "VUNESP"

        # Extrair gabarito
        gabarito = _parse_gabarito(texto)

        # Tentar parser CESPE primeiro (se detectado ou se itens C/E no gabarito)
        ce_values = [v for v in gabarito.values() if v in ('A', 'B', 'C', 'E')]
        is_cespe = banca_detectada == "CESPE" or (len(ce_values) > 10 and all(v in ('A', 'B') for v in gabarito.values()))

        if is_cespe:
            questoes_preview = _parse_cespe_certo_errado(texto, materia, gabarito)
            formato_detectado = "cespe_ce"

        # Se CESPE não encontrou suficiente, tentar genérico
        if len(questoes_preview) < 5:
            questoes_preview = _parse_generic(texto, materia)
            formato_detectado = "multipla_escolha"

        # Aplicar gabarito se disponível
        if gabarito:
            for i, q in enumerate(questoes_preview):
                num = i + 1
                if num in gabarito and not q.get("resposta_correta"):
                    q["resposta_correta"] = gabarito[num]

        # Aplicar banca detectada
        for q in questoes_preview:
            if not q.get("banca"):
                q["banca"] = banca_detectada
            if materia and not q.get("materia"):
                q["materia"] = materia

    elif filename.lower().endswith('.csv'):
        text = content.decode('utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(text))
        fmt = _detect_csv_format(reader.fieldnames or [])
        for row in reader:
            if fmt == "qconcursos":
                q = _parse_csv_qconcursos(row)
            elif fmt == "gran":
                q = _parse_csv_gran(row)
            else:
                q = _parse_csv_generic(row)
            if q:
                questoes_preview.append(q)
        formato_detectado = f"csv_{fmt}"

    # Stats do preview
    com_gabarito = sum(1 for q in questoes_preview if q.get("resposta_correta"))
    sem_gabarito = len(questoes_preview) - com_gabarito
    materias_detectadas = list(set(q.get("materia", "") for q in questoes_preview if q.get("materia")))

    return {
        "total_detectadas": len(questoes_preview),
        "com_gabarito": com_gabarito,
        "sem_gabarito": sem_gabarito,
        "formato_detectado": formato_detectado,
        "banca_detectada": banca_detectada if 'banca_detectada' in dir() else banca,
        "materias_detectadas": materias_detectadas,
        "preview": questoes_preview[:20],  # Primeiras 20 para preview
        "mensagem": f"Detectadas {len(questoes_preview)} questões ({formato_detectado}). {com_gabarito} com gabarito, {sem_gabarito} sem.",
    }
