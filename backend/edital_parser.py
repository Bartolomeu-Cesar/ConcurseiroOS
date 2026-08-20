"""
Edital PDF Parser for ConcurseiroOS
====================================
Extracts verticalização (subjects and topics) from Brazilian public exam PDFs
(editais de concursos públicos).

Handles the standard format:
- CONHECIMENTOS GERAIS section (shared across cargos)
- CONHECIMENTOS ESPECÍFICOS per CARGO
- Subjects in ALL CAPS followed by colon and numbered topics
- Numbered topics: 1 Topic. 1.1 Subtopic. 2 Another topic...
- EXCETO markers for excluding certain cargos from a subject
- Roman numeral sub-sections (I, II, III) within a subject
"""

import re
import unicodedata
from typing import Optional

from pypdf import PdfReader


# ============================================================
# Regex patterns
# ============================================================

# Matches "CARGO N:" or "CARGO N " followed by cargo name
RE_CARGO = re.compile(
    r"^CARGO\s+(\d+)\s*[:\s]\s*(.+)",
    re.IGNORECASE
)

# Matches the EXCETO clause in subject names
RE_EXCETO = re.compile(
    r"\(EXCETO\s+PARA\s+O\s+(.+?)\)",
    re.IGNORECASE
)

# Matches section markers
RE_CONHECIMENTOS_GERAIS = re.compile(
    r"(?:14\.\d+(?:\.\d+)?\s+)?CONHECIMENTOS\s+GERAIS",
    re.IGNORECASE
)

RE_CONHECIMENTOS_ESPECIFICOS = re.compile(
    r"(?:14\.\d+(?:\.\d+)?\s+)?CONHECIMENTOS\s+ESPEC[ÍI]FICOS",
    re.IGNORECASE
)

# Character class for Brazilian Portuguese uppercase letters
_UPPER = r"A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ"
# Character class for subject name content (uppercase + allowed chars)
_SUBJ_CHARS = _UPPER + r"\s,/\-–—()0-9º°ª"


# Preposições e artigos que ficam em minúscula no Title Case português
_LOWERCASE_WORDS = {
    "de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos",
    "a", "o", "as", "os", "ao", "aos", "à", "às", "com", "por", "para",
    "pelo", "pela", "pelos", "pelas", "sem", "sob", "sobre", "entre",
}


def _smart_title_case(text: str) -> str:
    """Converte ALL CAPS para Title Case respeitando preposições portuguesas."""
    if not text:
        return text
    words = text.lower().split()
    result = []
    for i, word in enumerate(words):
        if i == 0:
            result.append(word.capitalize())
        elif word in _LOWERCASE_WORDS:
            result.append(word)
        else:
            result.append(word.capitalize())
    return " ".join(result)


def extract_text_from_pdf(pdf_path: str, start_page: int = 0) -> str:
    """Extract all text from a PDF file starting at a given page."""
    reader = PdfReader(pdf_path)
    text_parts = []
    for i in range(start_page, len(reader.pages)):
        page_text = reader.pages[i].extract_text()
        if page_text:
            # Normalize Unicode: convert decomposed chars (C + combining cedilla) to composed (Ç)
            page_text = unicodedata.normalize("NFC", page_text)
            text_parts.append(page_text)
    return "\n".join(text_parts)


def extract_edital_name(pdf_path: str) -> str:
    """
    Extract the edital name from the first page.
    Looks for patterns like 'TCE/MA', abbreviations in parentheses, and year.
    """
    reader = PdfReader(pdf_path)
    if not reader.pages:
        return "Edital Desconhecido"

    first_page = reader.pages[0].extract_text()
    if not first_page:
        return "Edital Desconhecido"

    first_page = unicodedata.normalize("NFC", first_page)

    # Try to find the abbreviated name in parentheses (e.g., TCE/MA)
    sigla_match = re.search(r"\(([A-Z]{2,}[/\-][A-Z]{2,})\)", first_page)
    sigla = sigla_match.group(1) if sigla_match else ""

    # Try to find the year
    year_match = re.search(r"EDITAL\s+N[ºo°]\s*\d+.*?(\d{4})", first_page, re.IGNORECASE)
    if not year_match:
        year_match = re.search(r"DE\s+\d+\s+DE\s+\w+\s+DE\s+(\d{4})", first_page)
    year = year_match.group(1) if year_match else ""

    if sigla and year:
        return f"{sigla.replace('/', '-')} {year}"
    elif sigla:
        return sigla.replace('/', '-')

    # Fallback: try to get organization name from first lines
    lines = first_page.split('\n')
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) > 10 and line.isupper():
            words = line.split()
            if len(words) > 4:
                return " ".join(words[:5]) + f" {year}" if year else " ".join(words[:5])
            return f"{line} {year}" if year else line

    return f"Edital {year}" if year else "Edital Desconhecido"


def find_content_start(text: str) -> int:
    """
    Find where the evaluation content section begins.
    Looks for 'OBJETOS DE AVALIAÇÃO', 'CONHECIMENTOS GERAIS', etc.
    """
    patterns = [
        r"(?:14|15|16)\s+DOS\s+OBJETOS\s+DE\s+AVALIA[ÇC][AÃ]O",
        r"OBJETOS?\s+DE\s+AVALIA[ÇC][ÃA]O\s*\(",
        r"(?:14|15|16)\.\d+\s+CONHECIMENTOS",
        r"CONHECIMENTOS\s+GERAIS",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.start()
    return 0


def split_topics(topic_text: str) -> list[str]:
    """
    Split a topic string into individual numbered topics.
    Input: "1 Compreensão e interpretação de textos. 2 Reconhecimento de tipos. 2.1 Subtipo."
    Output: ["1 Compreensão e interpretação de textos", "2 Reconhecimento de tipos", "2.1 Subtipo"]
    """
    if not topic_text or not topic_text.strip():
        return []

    topic_text = topic_text.strip()

    # Strategy: find all numbered items using their positions
    # A topic number is: digits possibly with dots (1, 1.1, 2.3.1)
    # followed by a space and then a word starting with an uppercase letter
    # We need to avoid matching things like "Lei nº 14.133/2021"
    # Key insight: topic numbers appear after sentence-ending punctuation or at start

    # Find all potential topic starts
    # Pattern: beginning of text or after ". " or after "; " -> number(s) + space + Uppercase
    topic_starts = []
    for match in re.finditer(
        r"(?:^|(?<=\.\s)|(?<=;\s)|(?<=\s))(\d+(?:\.\d+)*)\s+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ])",
        topic_text
    ):
        num = match.group(1)
        # Validate: the number should look like a topic number, not a year or law number
        # Topic numbers: 1, 1.1, 2.3.1 (max 3 levels)
        parts = num.split('.')
        if len(parts) <= 4 and all(len(p) <= 3 for p in parts):
            # Additional check: first number shouldn't be unreasonably large
            # unless it follows the sequence (topics rarely go above 30 at top level)
            first_num = int(parts[0])
            if first_num <= 50:
                topic_starts.append(match.start())

    # If we found no topic starts, try a more lenient approach
    if not topic_starts:
        for match in re.finditer(r"(\d+(?:\.\d+)*)\s+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ])", topic_text):
            num = match.group(1)
            parts = num.split('.')
            if len(parts) <= 4 and all(len(p) <= 3 for p in parts):
                first_num = int(parts[0])
                if first_num <= 50:
                    topic_starts.append(match.start())

    # Extract topics between positions
    topics = []
    for i, start in enumerate(topic_starts):
        end = topic_starts[i + 1] if i + 1 < len(topic_starts) else len(topic_text)
        item = topic_text[start:end].strip()
        # Clean trailing punctuation
        item = item.rstrip('.').rstrip(';').strip()
        if item:
            topics.append(item)

    return topics


def _extract_subjects_from_block(text_block: str) -> list[dict]:
    """
    Extract subjects and their topics from a text block.
    Returns list of {disciplina, topicos: [...], exceto_cargos: [...]}
    """
    subjects = []

    # Normalize text: join wrapped lines into continuous text
    continuous_text = re.sub(r"\s*\n\s*", " ", text_block).strip()
    # Normalize Unicode
    continuous_text = unicodedata.normalize("NFC", continuous_text)

    # Find all subject headers: ALL CAPS text followed by colon, then "1 " or "I "
    header_positions = []
    for match in re.finditer(
        r"([" + _UPPER + r"][" + _SUBJ_CHARS + r"]{3,}?)"
        r"\s*:\s*"
        r"(?=(?:I{1,3}\s+[" + _UPPER + r"]|1\s))",
        continuous_text
    ):
        name = match.group(1).strip()
        # Remove parenthetical for the caps check
        name_check = re.sub(r"\([^)]*\)", "", name).strip()
        # Must be all uppercase and at least 3 meaningful chars
        if name_check and name_check == name_check.upper() and len(name_check) >= 3:
            header_positions.append((match.start(), match.end(), name))

    # Post-process: merge Roman numeral sub-sections into parent subject
    # Pattern: "HISTÓRIA E GEOGRAFIA DO MARANHÃO : I HISTÓRIA: 1 ... II GEOGRAFIA: 1 ..."
    # When a parent header's content immediately leads to a Roman-numeral sub-header,
    # we merge them into one subject.
    merged_entries = []  # (start, end_of_header, name, content_text)
    skip_indices = set()

    for i, (start, end, name) in enumerate(header_positions):
        if i in skip_indices:
            continue

        # Determine where this header's content ends
        if i + 1 < len(header_positions):
            next_start = header_positions[i + 1][0]
        else:
            next_start = len(continuous_text)

        # Check if content between this header and next is very small (< 5 chars)
        # AND the next header starts with a Roman numeral prefix
        # This indicates the current header is a parent with Roman sub-sections
        gap_content = continuous_text[end:next_start].strip()

        if (i + 1 < len(header_positions)
            and len(gap_content) < 5
            and re.match(r"^(?:I{1,3}|IV|V|VI{0,3})\s+[" + _UPPER + r"]",
                         header_positions[i + 1][2].strip())):
            # This is a parent subject — collect all Roman numeral sub-sections
            combined_end = next_start
            for j in range(i + 1, len(header_positions)):
                sub_name = header_positions[j][2].strip()
                if re.match(r"^(?:I{1,3}|IV|V|VI{0,3})\s+[" + _UPPER + r"]", sub_name):
                    skip_indices.add(j)
                    # Update combined_end to include this sub-section's content
                    if j + 1 < len(header_positions):
                        combined_end = header_positions[j + 1][0]
                    else:
                        combined_end = len(continuous_text)
                else:
                    break

            content = continuous_text[end:combined_end].strip()
            # Remove the Roman numeral sub-headers from content
            content = re.sub(
                r"(?:I{1,3}|IV|V|VI{0,3})\s+[" + _UPPER + r"][" + _SUBJ_CHARS + r"]*?\s*:\s*",
                " ",
                content
            )
            merged_entries.append((start, end, name, content))
        else:
            # Normal case
            content = continuous_text[end:next_start].strip()
            merged_entries.append((start, end, name, content))

    # Now process each entry
    for start, end, name, content in merged_entries:
        name_clean = name.strip()

        # Check for EXCETO clause
        exceto_cargos = []
        exceto_match = RE_EXCETO.search(name_clean)
        if exceto_match:
            exceto_text = exceto_match.group(1)
            exceto_cargos = re.findall(r"CARGO\s+(\d+)", exceto_text, re.IGNORECASE)
            name_clean = RE_EXCETO.sub("", name_clean).strip()

        # Normalize whitespace in name
        name_clean = re.sub(r"\s+", " ", name_clean).strip()

        # Convert to proper Title Case (lowercase prepositions/articles)
        name_clean = _smart_title_case(name_clean)

        # Split content into topics
        topics = split_topics(content)

        if topics:
            subjects.append({
                "disciplina": name_clean,
                "topicos": topics,
                "exceto_cargos": exceto_cargos
            })

    return subjects


def _parse_cargo_name(cargo_line: str) -> tuple[str, str]:
    """
    Parse a cargo line to extract cargo number and a CLEAN short name.
    
    Exemplos:
    - 'CARGO 1: ANALISTA ... – ESPECIALIDADE: ADMINISTRAÇÃO' → ('1', 'Analista - Administração')
    - 'CARGO 12: AUDITOR ... – ESPECIALIDADE: CONTROLE EXTERNO' → ('12', 'Auditor - Controle Externo')
    - 'CARGO 16: TÉCNICO ... – ESPECIALIDADE: TÉCNICO-ADMINISTRATIVA' → ('16', 'Técnico - Técnico-Administrativa')
    """
    match = RE_CARGO.match(cargo_line.strip())
    if match:
        num = match.group(1)
        name = match.group(2).strip()
        name = re.sub(r"\s*[\n\r]+\s*", " ", name).strip()
        name = re.sub(r"\s+", " ", name)
        name = re.sub(r"\s*-\s*$", "", name)

        # Extract short name: cargo type + especialidade
        short_name = _simplify_cargo_name(name)
        return num, short_name
    return "", _smart_title_case(cargo_line.strip())


def _simplify_cargo_name(full_name: str) -> str:
    """Simplifica nome do cargo para formato curto."""
    # Fix common PDF extraction issues (broken words)
    full_name = re.sub(r"ANA\s+LISTA", "ANALISTA", full_name, flags=re.IGNORECASE)
    full_name = re.sub(r"AN\s+ALISTA", "ANALISTA", full_name, flags=re.IGNORECASE)

    # Try to extract ESPECIALIDADE
    esp_match = re.search(r"ESPECIALIDADE\s*:\s*(.+?)(?:\s*$|\s*–)", full_name, re.IGNORECASE)
    if esp_match:
        especialidade = esp_match.group(1).strip().rstrip("–").rstrip("-").strip()
    else:
        especialidade = ""

    # Extract cargo type
    tipo_match = re.match(r"(ANALISTA|AUDITOR|T[ÉE]CNICO|PROCURADOR|DEFENSOR|DELEGADO|INVESTIGADOR|AGENTE|ESCRIV[ÃA]O|PERITO)", full_name, re.IGNORECASE)
    tipo = tipo_match.group(1) if tipo_match else ""

    if tipo and especialidade:
        return f"{_smart_title_case(tipo)} - {_smart_title_case(especialidade)}"
    elif tipo:
        return _smart_title_case(tipo)
    else:
        clean = _smart_title_case(full_name)
        return clean[:60] if len(clean) > 60 else clean


def _extract_metadados(pdf_path: str) -> dict:
    """Extrai metadados completos do concurso: órgão, banca, remuneração, jornada, vagas, inscrições, datas, taxa."""
    reader = PdfReader(pdf_path)
    # Read first 25 pages for general metadata
    text_inicio = ""
    for i in range(min(25, len(reader.pages))):
        page_text = reader.pages[i].extract_text() or ""
        text_inicio += unicodedata.normalize("NFC", page_text) + "\n"

    # Read last 15 pages for cronograma/anexo
    text_final = ""
    for i in range(max(0, len(reader.pages) - 15), len(reader.pages)):
        page_text = reader.pages[i].extract_text() or ""
        text_final += unicodedata.normalize("NFC", page_text) + "\n"

    metadados = {
        "orgao": "",
        "banca": "",
        "remuneracao": "",
        "jornada": "",
        "vagas": {},
        "escolaridade": "",
        "inscricoes": "",
        "data_prova_objetiva": "",
        "data_prova_discursiva": "",
        "local_prova": "",
        "taxa_inscricao": "",
        "link_edital": "",
    }

    # === ÓRGÃO ===
    orgao_match = re.search(
        r"(TRIBUNAL\s+DE\s+CONTAS[^(\n]{0,60}|POL[ÍI]CIA\s+CIVIL[^(\n]{0,60}|"
        r"MINIST[ÉE]RIO\s+P[ÚU]BLICO[^(\n]{0,60}|DEFENSORIA\s+P[ÚU]BLICA[^(\n]{0,60}|"
        r"PROCURADORIA[^(\n]{0,40}|PREFEITURA[^(\n]{0,60})",
        text_inicio, re.IGNORECASE
    )
    if orgao_match:
        orgao = orgao_match.group(1).strip()
        # Limpar e formatar
        orgao = re.sub(r"\s+", " ", orgao).strip()
        metadados["orgao"] = _smart_title_case(orgao) if orgao == orgao.upper() else orgao

    # === BANCA ===
    banca_match = re.search(
        r"(Cebraspe|CEBRASPE|CESPE|FCC|FGV|VUNESP|IBFC|AOCP|IADES|IDECAN|FUNDEP|CONSULPLAN|INSTITUTO\s+AOCP)",
        text_inicio, re.IGNORECASE
    )
    if banca_match:
        metadados["banca"] = banca_match.group(1).strip().upper()

    # === REMUNERAÇÃO ===
    remuneracao_match = re.search(r"REMUNERA[ÇC][ÃA]O\s*:?\s*R?\$?\s*([\d.,]+)", text_inicio, re.IGNORECASE)
    if remuneracao_match:
        metadados["remuneracao"] = f"R$ {remuneracao_match.group(1).rstrip('.')}"

    # === JORNADA ===
    jornada_match = re.search(r"JORNADA\s+DE\s+TRABALHO\s*:?\s*(\d+\s*horas?\s*semanais?)", text_inicio, re.IGNORECASE)
    if jornada_match:
        metadados["jornada"] = jornada_match.group(1).strip()

    # === VAGAS POR CARGO (tabela) ===
    # Pattern: "Cargo N: ... Total X" ou linhas com números de vagas
    for match in re.finditer(
        r"Cargo\s+(\d+)\s*:.*?(?:Total|total)\s*(\d+)",
        text_inicio, re.DOTALL
    ):
        metadados["vagas"][match.group(1)] = match.group(2)

    # Fallback: pattern "Cargo N: ... <numeros>" em linhas da tabela
    if not metadados["vagas"]:
        for match in re.finditer(r"Cargo\s+(\d+).*?(\d+)\s*$", text_inicio, re.MULTILINE):
            metadados["vagas"][match.group(1)] = match.group(2)

    # === INSCRIÇÕES (período) ===
    # Buscar no cronograma primeiro
    inscr_match = re.search(
        r"(?:per[íi]odo\s+de\s+(?:solicita[çc][ãa]o\s+de\s+)?inscri[çc][õo]es?).*?(\d{1,2}/\d{1,2})\s*(?:a|até)\s*(\d{1,2}/\d{1,2}/\d{4})",
        text_inicio + text_final, re.IGNORECASE | re.DOTALL
    )
    if inscr_match:
        inicio_inscr = inscr_match.group(1)
        fim_inscr = inscr_match.group(2)
        # Extrair ano do fim
        ano = fim_inscr.split("/")[-1]
        if "/" not in inicio_inscr or len(inicio_inscr.split("/")) < 3:
            inicio_inscr = inicio_inscr + "/" + ano
        metadados["inscricoes"] = f"{inicio_inscr} a {fim_inscr}"

    # === DATA DA PROVA ===
    # Buscar "Aplicação das provas" no cronograma
    prova_match = re.search(
        r"(?:Aplica[çc][ãa]o\s+das\s+provas?\s+objetivas?).*?(\d{1,2}/\d{1,2}/\d{4})",
        text_final, re.IGNORECASE | re.DOTALL
    )
    if prova_match:
        data_prova = prova_match.group(1)
        metadados["data_prova_objetiva"] = data_prova
        metadados["data_prova_discursiva"] = data_prova  # Geralmente mesmo dia

    # Buscar segunda data de prova (se tiver Auditor/Técnico em outra data)
    prova_matches = re.findall(
        r"Aplica[çc][ãa]o\s+das\s+provas?.*?(\d{1,2}/\d{1,2}/\d{4})",
        text_final, re.IGNORECASE | re.DOTALL
    )
    if len(prova_matches) > 1:
        # Guardar todas as datas encontradas (será distribuída por cargo no endpoint)
        metadados["datas_provas"] = list(set(prova_matches))

    # === TAXA DE INSCRIÇÃO ===
    taxa_match = re.search(r"(?:taxa.*?inscri|inscri.*?taxa).*?R\$\s*([\d.,]+)", text_inicio, re.IGNORECASE | re.DOTALL)
    if not taxa_match:
        # Buscar padrão "para os cargos de ...: R$ X"
        taxa_match = re.search(r"R\$\s*([\d.,]+)\s*[;.]", text_inicio)
    if taxa_match:
        metadados["taxa_inscricao"] = f"R$ {taxa_match.group(1)}"

    # Múltiplas taxas por nível
    taxas_multi = re.findall(
        r"(?:para\s+o[s]?\s+cargo[s]?\s+de\s+)(.+?):\s*R\$\s*([\d.,]+)",
        text_inicio, re.IGNORECASE
    )
    if taxas_multi:
        partes = [f"{cargo.strip()}: R$ {valor}" for cargo, valor in taxas_multi]
        metadados["taxa_inscricao"] = " | ".join(partes)

    # === LOCAL DA PROVA ===
    local_match = re.search(
        r"(?:provas?\s+ser[ãa]o?\s+(?:realizad|aplicad)).*?(?:em|na\s+cidade\s+de)\s+([A-Za-zÀ-ÿ\s]+?)(?:\.|,|\s*e\s+em)",
        text_inicio, re.IGNORECASE
    )
    if local_match:
        metadados["local_prova"] = local_match.group(1).strip()
    else:
        # Fallback: buscar capital do estado
        estado_match = re.search(r"ESTADO\s+D[OE]\s+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ]+)", text_inicio)
        if estado_match:
            metadados["local_prova"] = f"Capital do Estado ({estado_match.group(1).title()})"

    # === LINK DO EDITAL ===
    link_match = re.search(r"(https?://www\.cebraspe\.org\.br/concursos/[^\s\"]{3,})", text_inicio)
    if not link_match:
        link_match = re.search(r"(https?://[^\s\"]{20,80}concurso[^\s\"]*)", text_inicio, re.IGNORECASE)
    if link_match:
        link = link_match.group(1).rstrip(".,;")
        # Fix PDF line breaks in URL (e.g., "tce_ma_2 6" → "tce_ma_26")
        link = re.sub(r"\s+", "", link)
        metadados["link_edital"] = link

    # === ESCOLARIDADE ===
    if "NÍVEL SUPERIOR" in text_inicio.upper() and "NÍVEL MÉDIO" in text_inicio.upper():
        metadados["escolaridade"] = "Nível Superior e Médio"
    elif "NÍVEL SUPERIOR" in text_inicio.upper():
        metadados["escolaridade"] = "Nível Superior"
    elif "NÍVEL MÉDIO" in text_inicio.upper():
        metadados["escolaridade"] = "Nível Médio"

    return metadados


def parse_edital_pdf(pdf_path: str) -> dict:
    """
    Main parser function. Reads a PDF edital and extracts structured
    verticalização data (subjects and topics per cargo).

    Returns:
    {
        "edital_nome": "TCE-MA 2026",
        "total_cargos": 16,
        "total_materias": ...,
        "total_topicos": ...,
        "conhecimentos_gerais": [...],
        "cargos": [
            {
                "cargo_numero": "1",
                "cargo_nome": "...",
                "materias": [{"materia": "...", "topicos": [...]}]
            }, ...
        ]
    }
    """
    # Step 1: Extract edital name from first page
    edital_nome = extract_edital_name(pdf_path)

    # Step 2: Extract full text
    full_text = extract_text_from_pdf(pdf_path)

    # Step 3: Find where the content section begins
    content_start = find_content_start(full_text)
    content_text = full_text[content_start:]

    # Step 4: Split into lines for section detection
    lines = content_text.split('\n')

    # Step 5: Find CONHECIMENTOS GERAIS and CONHECIMENTOS ESPECÍFICOS boundaries
    gerais_start = None
    especificos_start = None

    for i, line in enumerate(lines):
        if RE_CONHECIMENTOS_GERAIS.search(line) and gerais_start is None:
            gerais_start = i
        if RE_CONHECIMENTOS_ESPECIFICOS.search(line):
            especificos_start = i
            break

    # Step 6: Extract CONHECIMENTOS GERAIS
    conhecimentos_gerais = []
    if gerais_start is not None:
        end_idx = especificos_start if especificos_start else len(lines)
        start_idx = gerais_start + 1
        # Skip preamble lines (14.2.1, 14.2.2, etc.)
        while start_idx < end_idx:
            line = lines[start_idx].strip()
            if line and not re.match(r"^14\.\d+", line) and not line.startswith("CONHECIMENTOS"):
                break
            start_idx += 1

        gerais_block = "\n".join(lines[start_idx:end_idx])
        conhecimentos_gerais = _extract_subjects_from_block(gerais_block)

    # Step 7: Extract CONHECIMENTOS ESPECÍFICOS per CARGO
    cargos = []
    if especificos_start is not None:
        especificos_text = "\n".join(lines[especificos_start + 1:])

        # Detect end of content section (ANEXO, signatures, etc.)
        # Common end markers in Brazilian editais
        end_markers = [
            r"^\s*ANEXO\s",
            r"^\s*CRONOGRAMA\s+PREVISTO",
            r"^\s*DAS\s+DISPOSIÇÕES\s+FINAIS",
            r"^\s*(?:15|16|17|18)\s+DAS\s+DISPOSIÇÕES",
        ]
        content_end = len(especificos_text)
        for marker_pattern in end_markers:
            marker_match = re.search(marker_pattern, especificos_text, re.MULTILINE | re.IGNORECASE)
            if marker_match and marker_match.start() < content_end:
                content_end = marker_match.start()

        # Also detect signature lines (name in CAPS at end of section, typically short)
        # Pattern: isolated short ALL-CAPS line that's NOT a subject header
        sig_pattern = re.search(
            r"\n\s*([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s]{5,50})\s*\n\s*(?:Presidente|Diretor|Secret[áa]rio)",
            especificos_text,
            re.IGNORECASE
        )
        if sig_pattern and sig_pattern.start() < content_end:
            content_end = sig_pattern.start()

        especificos_text = especificos_text[:content_end]

        # Find all CARGO markers
        cargo_positions = []
        for match in re.finditer(
            r"^(CARGO\s+\d+\s*[:\s].+?)$",
            especificos_text,
            re.MULTILINE
        ):
            cargo_positions.append((match.start(), match.group(1)))

        # Fallback: more lenient pattern
        if not cargo_positions:
            for match in re.finditer(
                r"(CARGO\s+\d+\s*[:\s].+?)(?=CARGO\s+\d+|$)",
                especificos_text,
                re.DOTALL
            ):
                cargo_positions.append((match.start(), match.group(1).split('\n')[0]))

        # Extract content for each cargo
        for i, (pos, cargo_line) in enumerate(cargo_positions):
            content_start_pos = pos + len(cargo_line)
            if i + 1 < len(cargo_positions):
                content_end_pos = cargo_positions[i + 1][0]
            else:
                content_end_pos = len(especificos_text)

            cargo_content = especificos_text[content_start_pos:content_end_pos].strip()

            # Check if cargo name continues on next line(s)
            cargo_full_line = cargo_line
            content_lines = cargo_content.split('\n')
            while content_lines:
                first_line = content_lines[0].strip()
                # If line is ALL CAPS continuation of name (not a subject header)
                if (first_line
                    and first_line == first_line.upper()
                    and not re.match(r"^\d+", first_line)
                    and not re.search(r":\s*(?:I\s|1\s)", first_line)
                    and len(first_line) < 100
                    and not re.match(r"^[A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s]{5,}:", first_line)):
                    cargo_full_line += " " + first_line
                    content_lines.pop(0)
                else:
                    break
            cargo_content = "\n".join(content_lines)

            cargo_num, cargo_name = _parse_cargo_name(cargo_full_line)

            # Extract subjects from cargo content
            materias = _extract_subjects_from_block(cargo_content)

            cargos.append({
                "cargo_numero": cargo_num,
                "cargo_nome": cargo_name,
                "materias": [
                    {"materia": m["disciplina"], "topicos": m["topicos"]}
                    for m in materias
                ]
            })

    # Step 8: Build combined result with CONHECIMENTOS GERAIS applied per cargo
    total_topicos = 0
    total_materias_set = set()

    for cargo in cargos:
        # Add CONHECIMENTOS GERAIS subjects (respecting EXCETO)
        gerais_for_cargo = []
        for subj in conhecimentos_gerais:
            if cargo["cargo_numero"] not in subj.get("exceto_cargos", []):
                gerais_for_cargo.append({
                    "materia": subj["disciplina"],
                    "topicos": subj["topicos"]
                })

        # Prepend gerais before específicos
        cargo["materias"] = gerais_for_cargo + cargo["materias"]

        for m in cargo["materias"]:
            total_topicos += len(m["topicos"])
            total_materias_set.add(m["materia"])

    result = {
        "edital_nome": edital_nome,
        "total_cargos": len(cargos),
        "total_materias": len(total_materias_set),
        "total_topicos": total_topicos,
        "metadados": _extract_metadados(pdf_path),
        "conhecimentos_gerais": [
            {"disciplina": s["disciplina"], "topicos": s["topicos"], "exceto_cargos": s["exceto_cargos"]}
            for s in conhecimentos_gerais
        ],
        "cargos": cargos
    }

    return result


def format_preview(result: dict) -> str:
    """Format parser results as a human-readable preview."""
    lines = []
    lines.append(f"📋 EDITAL: {result['edital_nome']}")
    lines.append(f"   Total: {result['total_cargos']} cargos | {result['total_materias']} matérias | {result['total_topicos']} tópicos")
    lines.append("")

    # Conhecimentos Gerais summary
    if result["conhecimentos_gerais"]:
        lines.append("📚 CONHECIMENTOS GERAIS:")
        for subj in result["conhecimentos_gerais"]:
            exceto = f" (exceto cargos {', '.join(subj['exceto_cargos'])})" if subj["exceto_cargos"] else ""
            lines.append(f"   • {subj['disciplina']}: {len(subj['topicos'])} tópicos{exceto}")
        lines.append("")

    # Per-cargo summary
    lines.append("🎯 CARGOS (com CONHECIMENTOS ESPECÍFICOS):")
    for cargo in result["cargos"]:
        total = sum(len(m["topicos"]) for m in cargo["materias"])
        n_materias = len(cargo["materias"])
        lines.append(f"\n   CARGO {cargo['cargo_numero']}: {cargo['cargo_nome']}")
        lines.append(f"   ({n_materias} matérias, {total} tópicos total)")
        # Show only specific subjects (not gerais)
        gerais_names = {g["disciplina"] for g in result["conhecimentos_gerais"]}
        especificos = [m for m in cargo["materias"] if m["materia"] not in gerais_names]
        for m in especificos[:5]:
            lines.append(f"      • {m['materia']}: {len(m['topicos'])} tópicos")
        if len(especificos) > 5:
            lines.append(f"      ... e mais {len(especificos) - 5} matérias")

    return "\n".join(lines)


# ============================================================
# CLI test entry point
# ============================================================

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        pdf_path = "pdfs/5FADC380CB030A07F557A9C5EEA6D063017A2CA675E683F39C50B65E6D70F57B.pdf"
    else:
        pdf_path = sys.argv[1]

    print(f"Parsing: {pdf_path}")
    print("=" * 60)

    result = parse_edital_pdf(pdf_path)

    # Print preview
    print(format_preview(result))
    print("\n" + "=" * 60)

    # Print detailed first cargo
    if result["cargos"]:
        cargo = result["cargos"][0]
        print(f"\n📝 DETALHES - CARGO {cargo['cargo_numero']}: {cargo['cargo_nome']}")
        for m in cargo["materias"][:3]:
            print(f"\n   📖 {m['materia']}:")
            for t in m["topicos"][:5]:
                print(f"      - {t}")
            if len(m["topicos"]) > 5:
                print(f"      ... ({len(m['topicos'])} tópicos total)")

    # Save full JSON output
    output_path = pdf_path.replace(".pdf", "_parsed.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Full JSON saved to: {output_path}")
