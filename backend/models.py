from typing import List, Optional
from pydantic import BaseModel


# ============================================================
# PDF Progress
# ============================================================

class ProgressUpdate(BaseModel):
    current_page: int
    total_pages: int


# ============================================================
# Edital
# ============================================================

class EditalCreate(BaseModel):
    materia: str
    topico: str
    edital_nome: str = "Geral"
    cargo: str = ""


class EditalHoras(BaseModel):
    horas: float


class EditalPdfLink(BaseModel):
    pdf_link: str
    pdf_pagina: int = 1


# ============================================================
# Flashcards
# ============================================================

class FlashcardCreate(BaseModel):
    pergunta: str
    resposta: str


class FlashcardReview(BaseModel):
    acertou: bool


# ============================================================
# Questões
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


# ============================================================
# Simulados
# ============================================================

class SimuladoCreate(BaseModel):
    titulo: str
    tempo_limite_min: int = 60
    questao_ids: List[int]


class SimuladoResponder(BaseModel):
    questao_id: int
    resposta: str


class SimuladoFinalizar(BaseModel):
    tempo_gasto_seg: int = 0


# ============================================================
# Ciclo de Estudos
# ============================================================

class CicloCreate(BaseModel):
    materia: str
    horas_alvo: float = 1.0


class CicloUpdate(BaseModel):
    horas_alvo: Optional[float] = None
    ativo: Optional[int] = None
    ordem: Optional[int] = None


class CicloHoras(BaseModel):
    horas: float


# ============================================================
# Metas
# ============================================================

class MetasUpdate(BaseModel):
    meta_horas: float = 3.0
    meta_questoes: int = 30
    meta_flashcards: int = 10
    meta_paginas: int = 20


# ============================================================
# Notas
# ============================================================

class NotaCreate(BaseModel):
    pdf_path: str
    pagina: int = 1
    conteudo: str


class NotaTopicoCreate(BaseModel):
    edital_id: int
    conteudo: str


# ============================================================
# Planejador
# ============================================================

class PlanejadorItem(BaseModel):
    dia_semana: int  # 0=seg, 6=dom
    materia: str
    horas: float = 1.0


# ============================================================
# Cadernos
# ============================================================

class CadernoCreate(BaseModel):
    nome: str
    descricao: str = ""


class CadernoAddItem(BaseModel):
    tipo: str  # 'questao' ou 'topico'
    item_id: int


# ============================================================
# Bookmarks
# ============================================================

class BookmarkCreate(BaseModel):
    pdf_path: str
    pagina: int
    label: str = ""
    cor: str = "blue"


# ============================================================
# Feynman
# ============================================================

class FeynmanCreate(BaseModel):
    edital_id: int
    explicacao: str


# ============================================================
# Desafios
# ============================================================

class DesafioCreate(BaseModel):
    titulo: str
    meta_tipo: str  # 'questoes', 'horas', 'topicos'
    meta_valor: int
    materia: str = ""
    dias: int = 7
