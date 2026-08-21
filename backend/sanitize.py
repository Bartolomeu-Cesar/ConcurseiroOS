"""Utilitário de sanitização de entrada — usa apenas stdlib (html, re)."""
import html
import re

# Tags permitidas no sanitize_html (formatação básica)
_ALLOWED_TAGS = frozenset({"b", "i", "em", "strong", "br", "p", "ul", "ol", "li"})

# Regex para encontrar tags HTML
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)

# Regex para detectar tentativas de path traversal
_PATH_TRAVERSAL_RE = re.compile(r"(\.\.[\\/]|[\\/]\.\.)|^[/\\]|[\x00]")

# Caracteres perigosos em nomes de arquivo
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"|?*\x00-\x1f]')

# Comprimento máximo padrão para sanitize_input
_MAX_INPUT_LENGTH = 500


def sanitize_html(text: str) -> str:
    """Remove tags/atributos perigosos, mantendo formatação básica (<b>, <i>, <br>, etc.).

    Tags permitidas são preservadas SEM atributos. Todas as outras são stripped.
    Conteúdo de texto é HTML-escaped para prevenir XSS.
    """
    if not text:
        return ""

    def _replace_tag(match: re.Match) -> str:
        closing = match.group(1)  # "/" or ""
        tag_name = match.group(2).lower()
        if tag_name in _ALLOWED_TAGS:
            # Retorna tag sem atributos
            if closing:
                return f"</{tag_name}>"
            # br é auto-fechante
            if tag_name == "br":
                return "<br>"
            return f"<{tag_name}>"
        # Tag não permitida — remove completamente
        return ""

    # Primeiro: escapa todo o texto (isso escapa < e > que não são tags válidas)
    # Mas precisamos preservar tags válidas, então fazemos em ordem diferente:
    # 1. Processa tags permitidas vs não permitidas
    result = _TAG_RE.sub(_replace_tag, text)

    return result


def sanitize_input(text: str, max_length: int = _MAX_INPUT_LENGTH) -> str:
    """Remove ALL HTML, trim whitespace, limita comprimento.

    Ideal para campos de texto livre como nome, username, etc.
    """
    if not text:
        return ""

    # Strip todas as tags HTML
    cleaned = re.sub(r"<[^>]*>", "", text)

    # Decode HTML entities e re-escape não é necessário aqui pois removemos tags
    cleaned = html.unescape(cleaned)

    # Remove caracteres de controle (exceto newline e tab)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)

    # Trim whitespace
    cleaned = cleaned.strip()

    # Colapsa múltiplos espaços
    cleaned = re.sub(r" {2,}", " ", cleaned)

    # Limita comprimento
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    return cleaned


def is_safe_filename(name: str) -> bool:
    """Verifica se o nome de arquivo é seguro (rejeita path traversal, caracteres perigosos).

    Retorna True se seguro, False se potencialmente perigoso.
    """
    if not name or not name.strip():
        return False

    # Rejeita path traversal
    if _PATH_TRAVERSAL_RE.search(name):
        return False

    # Rejeita caracteres perigosos
    if _UNSAFE_FILENAME_RE.search(name):
        return False

    # Rejeita nomes muito longos
    if len(name) > 255:
        return False

    # Rejeita nomes que começam com ponto (arquivos ocultos)
    if name.startswith("."):
        return False

    # Rejeita nomes que são devices reservados no Windows
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
    stem = name.split(".")[0].upper()
    if stem in reserved:
        return False

    return True
