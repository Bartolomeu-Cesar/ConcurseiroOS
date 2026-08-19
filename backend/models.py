

from pydantic import BaseModel, Field

from constants import SM2_INITIAL_EF

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


class FlashcardReviewSM2(BaseModel):
    quality: int = Field(ge=0, le=5, description="Quality grade: 0=forgot, 5=perfect")


class EditalReviewSM2(BaseModel):
    quality: int = Field(ge=0, le=5, description="Quality grade: 0=forgot, 5=perfect")


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
    banca: str = ""


class QuestaoResposta(BaseModel):
    resposta: str
    tempo_segundos: int = 0


# ============================================================
# Simulados
# ============================================================

class SimuladoCreate(BaseModel):
    titulo: str
    tempo_limite_min: int = 60
    questao_ids: list[int]


class SimuladoResponder(BaseModel):
    questao_id: int
    resposta: str


class SimuladoFinalizar(BaseModel):
    tempo_gasto_seg: int = 0


class SimuladoProvaReal(BaseModel):
    titulo: str = "Simulado Prova Real"
    edital_nome: str = ""
    cargo: str = ""
    tempo_limite_min: int = 180


# ============================================================
# Ciclo de Estudos
# ============================================================

class CicloCreate(BaseModel):
    materia: str
    horas_alvo: float = 1.0


class CicloUpdate(BaseModel):
    horas_alvo: float | None = None
    ativo: int | None = None
    ordem: int | None = None


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
# Calendário Personalizado
# ============================================================

class CalendarioItem(BaseModel):
    dia_semana: int  # 0=Seg, 6=Dom
    materia: str
    topicos: str = ""
    tempo_min: int = 60
    tipo: str = "estudo"  # estudo, questoes, revisao
    ordem: int = 0


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


# ============================================================
# Resumos (Elaboration Strategy)
# ============================================================

class ResumoCreate(BaseModel):
    resumo: str
    tipo: str = "livre"  # '3frases', 'mapa', 'livre'


# ============================================================
# Response Models
# ============================================================

class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    database: str
    version: str
    tables_count: int
    edital_count: int
    timestamp: str


class FlashcardResponse(BaseModel):
    id: int
    pergunta: str
    resposta: str
    proxima_revisao: str
    intervalo_dias: int
    easiness_factor: float = SM2_INITIAL_EF
    repetitions: int = 0


class FlashcardReviewResponse(BaseModel):
    id: int
    intervalo_dias: int
    proxima_revisao: str


class FlashcardReviewSM2Response(BaseModel):
    id: int
    intervalo_dias: int
    proxima_revisao: str
    easiness_factor: float
    repetitions: int
    quality: int


class EditalItemResponse(BaseModel):
    id: int
    edital_nome: str
    cargo: str
    materia: str
    topico: str
    status: str
    horas_estudadas: float
    pdf_link: str = ""
    pdf_pagina: int = 0


class QuestaoResponse(BaseModel):
    id: int
    materia: str
    topico: str
    enunciado: str
    alternativa_a: str
    alternativa_b: str
    alternativa_c: str
    alternativa_d: str
    alternativa_e: str = ""
    resposta_correta: str
    explicacao: str = ""
    dificuldade: str = "Médio"
    banca: str = ""
    created_at: str


class QuestaoRespostaResponse(BaseModel):
    acertou: bool
    resposta_correta: str


class OkResponse(BaseModel):
    ok: bool = True


class OkIdResponse(BaseModel):
    ok: bool = True
    id: int


class StreakResponse(BaseModel):
    streak_atual: int
    melhor_streak: int
    hoje: dict


class DashboardResponse(BaseModel):
    horas_por_dia: list
    total_horas: float
    edital: dict
    questoes: dict
    acertos_por_dia: list
    horas_por_materia: list
    flashcards: dict
