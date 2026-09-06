"""Pydantic schemas — canonical request/response models for ConcurseiroOS.

All Pydantic models live here. Routers import from this single module.

Usage:
    from schemas import LoginRequest, EditalCreate, FlashcardCreate, ...
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

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
    materia: str = ""
    reverso: bool = False  # se True, cria também o card invertido (R->P)


class FlashcardUpdate(BaseModel):
    pergunta: str | None = None
    resposta: str | None = None
    materia: str | None = None


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
    confianca: int | None = None  # 1=chutei, 2=acho que sei, 3=certeza
    # Se True, a questão foi servida com alternativas EMBARALHADAS (mesma semente
    # determinística por user+questão). O backend reaplica o embaralhamento para
    # comparar a resposta com o gabarito NA ORDEM QUE O USUÁRIO VIU. Default False
    # preserva o comportamento de todos os fluxos que servem na ordem original.
    embaralhada: bool = False
    # Semente do embaralhamento NÃO-determinístico. Se o frontend serviu com
    # ?embaralhar=true&seed=N, envia a MESMA seed aqui para o backend reconstruir a
    # permutação exibida e validar. None = usa a semente determinística (legado).
    seed: int | None = None


# ============================================================
# Simulados
# ============================================================


class SimuladoCreate(BaseModel):
    titulo: str
    tempo_limite_min: int = 60
    questao_ids: list[int]


class SimuladoEditar(BaseModel):
    titulo: str | None = None
    tempo_limite_min: int | None = None


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


class DificuldadeMix(BaseModel):
    facil: int = 20
    medio: int = 40
    dificil: int = 20


class SimuladoCronometradoCreate(BaseModel):
    titulo: str = "Simulado Cronometrado"
    tempo_total_min: int = 240
    questoes_total: int = 80
    materias: list[str] = []
    dificuldade_mix: DificuldadeMix = DificuldadeMix()


class RespostaCronometrada(BaseModel):
    questao_id: int
    resposta: str
    tempo_seg: int = 0


class SimuladoCronometradoFinalizar(BaseModel):
    respostas: list[RespostaCronometrada]
    tempo_total_seg: int = 0


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
    meta_sumulas: int = 0  # 0 = desativado, 5 = padrão para jurídicos


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
# Response Models (Core)
# ============================================================


class HealthDbStatus(BaseModel):
    status: str
    size_mb: float


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    db: HealthDbStatus
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
    texto_base: str = ""
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
    # Quando a questão é servida com ?embaralhar=true (alternativas reordenadas):
    embaralhada: bool = False
    mapeamento: dict = {}  # nova_letra -> letra_original (para o cliente, se precisar)
    seed: int | None = None  # semente usada (o cliente reenvia no /responder)


class QuestaoRespostaResponse(BaseModel):
    acertou: bool | None = None
    resposta_correta: str = ""
    sem_gabarito: bool = False
    mensagem: str | None = None
    alerta: dict | None = None


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
    horas_estudo: float = 0
    horas_questoes: float = 0
    edital: dict
    questoes: dict
    acertos_por_dia: list
    horas_por_materia: list
    flashcards: dict


# ============================================================
# Auth — Requests
# ============================================================


class LoginRequest(BaseModel):
    """POST /api/auth/login body."""

    email: EmailStr


class RegisterRequest(BaseModel):
    """POST /api/auth/register body."""

    email: EmailStr
    nome: str = ""


class VerifyCodeRequest(BaseModel):
    """POST /api/auth/verify-code body."""

    email: EmailStr
    code: str = Field(..., min_length=1)


class ProfileUpdateRequest(BaseModel):
    """PUT /api/auth/profile body."""

    nome: str | None = None
    avatar: str | None = None


class UpgradePlanRequest(BaseModel):
    """POST /api/auth/upgrade body."""

    plano: str = Field(default="premium", pattern=r"^(free|premium|ilimitado)$")
    vitalicio: bool = False  # Se True, pagamento único sem expiração


class RefreshTokenRequest(BaseModel):
    """POST /api/auth/refresh body."""

    refresh_token: str = Field(..., min_length=1)


# ============================================================
# Auth — Responses
# ============================================================


class UserResponse(BaseModel):
    """User data returned after login/verify or GET /api/auth/me."""

    id: int
    email: str
    nome: str
    avatar: str | None = None
    plano: str = "free"
    role: str = "user"


class AuthTokenResponse(BaseModel):
    """Response from POST /api/auth/verify-code (success)."""

    ok: bool = True
    token: str
    user: UserResponse


class AuthStatusResponse(BaseModel):
    """GET /api/auth/status response."""

    auth_enabled: bool
    smtp_configured: bool


# ============================================================
# Questões — Requests
# ============================================================


class QuestionCreate(BaseModel):
    """POST /api/questoes body — create a new question.

    Note: the existing `models.QuestaoCreate` already handles this in the router.
    This schema provides an alternative with slightly different field naming for
    external API consumers or future refactors.
    """

    materia: str
    enunciado: str
    alternativas: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of letter -> text, e.g. {'A': '...', 'B': '...'}",
    )
    # Individual alternativa fields (backwards-compatible with existing model)
    alternativa_a: str = ""
    alternativa_b: str = ""
    alternativa_c: str = ""
    alternativa_d: str = ""
    alternativa_e: str = ""
    gabarito: str = Field("", description="Correct answer letter (A-E)")
    banca: str = ""
    ano: str = ""
    topico: str = ""
    dificuldade: str = "Médio"
    explicacao: str = ""


class QuestionAnswer(BaseModel):
    """POST /api/questoes/{id}/responder body."""

    questao_id: int | None = None  # Optional — usually comes from path param
    resposta: str = Field(..., min_length=1, max_length=1, description="Answer letter (A-E)")
    tempo_segundos: int = 0


class QuestionBatchUpdate(BaseModel):
    """PUT /api/questoes/vincular-lote body (legacy untyped version)."""

    filtro: dict = Field(default_factory=dict)
    atualizar: dict = Field(default_factory=dict)


class QuestionLinkBatchFiltro(BaseModel):
    """Filter criteria for batch-linking questions."""

    created_at: str | None = None
    materia_atual: str | None = None
    banca: str | None = None
    sem_materia: bool | None = None
    prova_origem: str | None = None


class QuestionLinkBatchAtualizar(BaseModel):
    """Fields to update in batch-link operation."""

    materia: str | None = None
    topico: str | None = None
    banca: str | None = None
    dificuldade: str | None = None


class QuestionLinkBatch(BaseModel):
    """PUT /api/questoes/vincular-lote body — typed version."""

    filtro: QuestionLinkBatchFiltro = Field(default_factory=QuestionLinkBatchFiltro)
    atualizar: QuestionLinkBatchAtualizar = Field(default_factory=QuestionLinkBatchAtualizar)


class QuestionUpdate(BaseModel):
    """PUT /api/questoes/{id} body — all fields optional."""

    materia: str | None = None
    topico: str | None = None
    enunciado: str | None = None
    alternativa_a: str | None = None
    alternativa_b: str | None = None
    alternativa_c: str | None = None
    alternativa_d: str | None = None
    alternativa_e: str | None = None
    resposta_correta: str | None = None
    explicacao: str | None = None
    dificuldade: str | None = None
    banca: str | None = None


# ============================================================
# Generic Responses
# ============================================================


class GenericResponse(BaseModel):
    """Generic OK/error response used across many endpoints."""

    ok: bool = True
    message: str = ""


class GenericOkIdResponse(BaseModel):
    """Response with ok + created id."""

    ok: bool = True
    id: int


class PaginatedResponse(BaseModel):
    """Wrapper for paginated list endpoints."""

    items: list
    total: int
    page: int | None = None
    limit: int | None = None


# ============================================================
# Dashboard — Responses
# ============================================================


class DashboardEditalStats(BaseModel):
    total: int
    concluido: int


class DashboardQuestoesStats(BaseModel):
    total: int
    acertos: int
    percentual: float


class DashboardFlashcardsStats(BaseModel):
    pendentes: int
    total: int
    revisados_total: int = 0


class DashboardSummaryResponse(BaseModel):
    """GET /api/dashboard response (typed version)."""

    horas_por_dia: list
    total_horas: float
    horas_estudo: float = 0.0
    horas_questoes: float = 0.0
    edital: DashboardEditalStats
    questoes: DashboardQuestoesStats
    acertos_por_dia: list
    horas_por_materia: list
    flashcards: DashboardFlashcardsStats


# ============================================================
# Treinador — Responses (partial typing for key structures)
# ============================================================


class TreinadorMetaHoje(BaseModel):
    horas: float
    questoes: int
    cumprido_horas: float
    cumprido_questoes: int


class TreinadorRevisoesPendentes(BaseModel):
    flashcards: int
    topicos: int


class TreinadorRecommendation(BaseModel):
    tipo: str
    msg: str
    materia: str | None = None
    topico: str | None = None
    acao: str | None = None
    qtd: int | None = None
    destaque: bool = False


# ============================================================
# Admin — Requests
# ============================================================


class AdminCreateUser(BaseModel):
    """POST /api/admin/users body — admin creates a new user."""

    email: EmailStr
    nome: str = ""
    username: str = ""
    plano: str = "free"
    plano_expira: str = ""
    avatar: str = ""
    role: str = "user"
    password: str = ""


class AdminUpdateUser(BaseModel):
    """PUT /api/admin/users/{id} body — all fields optional."""

    email: EmailStr | None = None
    nome: str | None = None
    username: str | None = None
    plano: str | None = None
    plano_expira: str | None = None
    avatar: str | None = None
    role: str | None = None
    password: str | None = None


class AdminBulkAction(BaseModel):
    """POST /api/admin/users/bulk body — bulk actions on users."""

    user_ids: list[int]
    action: str
    value: str = ""


class AdminChangePlan(BaseModel):
    """POST /api/admin/users/{id}/plano body — change user plan."""

    plano: str
    plano_expira: str = ""


# ============================================================
# Batalha — Requests (P2-13)
# ============================================================


class CriarBatalhaRequest(BaseModel):
    """POST /api/batalha/criar body."""

    titulo: str = "Batalha de Questões"
    materias: list[str] = Field(default_factory=list)
    total_rodadas: int = 5
    tempo_por_questao: int = 30
    max_jogadores: int = 5


class EntrarBatalhaRequest(BaseModel):
    """POST /api/batalha/entrar body."""

    codigo: str
    nome: str | None = None


class ReconfigurarBatalhaRequest(BaseModel):
    """POST /api/batalha/reconfigurar/{codigo} body."""

    materias: list[str] | None = None
    total_rodadas: int | None = None
    tempo_por_questao: int | None = None
    max_jogadores: int | None = None


class IniciarBatalhaRequest(BaseModel):
    """POST /api/batalha/iniciar/{codigo} body."""

    questao_ids: list[int] = Field(default_factory=list)


class ResponderRodadaRequest(BaseModel):
    """POST /api/batalha/responder/{codigo} body."""

    resposta: str = ""
    tempo_seg: int = 0


# ============================================================
# Calendário — Requests (P2-13)
# ============================================================


class AtividadeConcluidaRequest(BaseModel):
    """POST /api/calendario/atividade-concluida body."""

    data: str | None = None
    dia_semana: int = 0
    materia: str = ""
    tipo: str = "estudo"
    tempo_min: int = 0
    total_atividades: int = 0
    topico: str = ""  # usado para casar com a etapa da trilha (tipo='trilha')


class DesmarcarAtividadeRequest(BaseModel):
    """DELETE /api/calendario/atividade-concluida body."""

    data: str | None = None
    materia: str = ""
    tipo: str = "estudo"
    total_atividades: int = 0


class SalvarQuestaoDissertativaRequest(BaseModel):
    """POST /api/questao-dissertativa/salvar body."""

    edital_id: int | None = None
    resposta: str = ""
    confianca: int = 3
    materia: str = ""


class RegistrarAutoavaliacaoRequest(BaseModel):
    """POST /api/autoavaliacao/registrar body."""

    resultados: list[dict] = Field(default_factory=list)


class ResetInteligenteRequest(BaseModel):
    """POST /api/planejador/reset-inteligente body."""

    edital_nome: str = ""
    cargo: str = ""
    horas_dia: float | None = None


# ============================================================
# Edital — Requests (P2-13)
# ============================================================


class UpdateEditalInfoRequest(BaseModel):
    """PUT /api/edital/info/{id} body."""

    edital_nome: str | None = None
    cargo: str | None = None
    orgao: str | None = None
    banca: str | None = None
    vagas: str | None = None
    subsidio: str | None = None
    inscricoes: str | None = None
    data_prova_objetiva: str | None = None
    data_prova_discursiva: str | None = None
    horario: str | None = None
    local_prova: str | None = None
    taxa_inscricao: str | None = None
    link_edital: str | None = None
    observacoes: str | None = None


class CreateEditalInfoRequest(BaseModel):
    """POST /api/edital/info body."""

    edital_nome: str = ""
    cargo: str = ""
    orgao: str = ""
    banca: str = ""
    vagas: str = ""
    subsidio: str = ""
    inscricoes: str = ""
    data_prova_objetiva: str = ""
    data_prova_discursiva: str = ""
    horario: str = ""
    local_prova: str = ""
    taxa_inscricao: str = ""
    link_edital: str = ""
    observacoes: str = ""


class RenomearEditalRequest(BaseModel):
    """PUT /api/edital/renomear body."""

    antigo: str = ""
    novo: str = ""
    cargo_antigo: str = ""
    cargo_novo: str = ""


# ============================================================
# Questões — Requests (P2-13)
# ============================================================


class RevisarErroRequest(BaseModel):
    """POST /api/questoes/erros/revisar/{id} body."""

    acertou: bool = False
    facilidade: int | None = None  # 1-4 mapping para FSRS ratings (opcional)
    tempo_segundos: int | None = None  # Tempo real gasto na revisão (se frontend enviar)


# ============================================================
# Social — Requests (P2-13)
# ============================================================


class AddMemberRequest(BaseModel):
    """POST /api/social/groups/{id}/add-member body."""

    email: str = ""
    user_id: int | None = None
    username: str = ""


class ChangeMemberRoleRequest(BaseModel):
    """PUT /api/social/groups/{id}/members/{member_id}/role body."""

    role: str = "member"


# ============================================================
# Fatigue Detection — Requests (B3)
# ============================================================


class HeartbeatRequest(BaseModel):
    """POST /api/sessao/heartbeat body."""

    session_id: str
    questao_num: int
    tempo_ms: int
    acertou: bool


class StartSessionRequest(BaseModel):
    """POST /api/sessao/iniciar body."""

    materia: str | None = None
    tipo: str = "questoes"


# ============================================================
# Generation Mode — Requests/Responses (C2)
# ============================================================


class ResponderGeracaoRequest(BaseModel):
    """POST /api/questoes/{id}/responder-geracao body."""

    resposta_digitada: str
    tempo_ms: int = 0


# ============================================================
# Sessão Adaptativa / CAT — Requests (C1)
# ============================================================


class IniciarAdaptativaRequest(BaseModel):
    """POST /api/sessao-adaptativa/iniciar body."""

    materia: str | None = None
    total_questoes: int = 20


class ResponderAdaptativaRequest(BaseModel):
    """POST /api/sessao-adaptativa/{session_id}/responder body."""

    questao_id: int
    resposta: str
    tempo_ms: int = 0


# ============================================================
# Caderno de Revisão por PDF
# ============================================================

# Limite do payload base64 de um recorte de imagem (~2 MB de imagem).
# base64 adiciona ~33% de overhead, então ~2 MB de PNG ≈ ~2.7 MB de string.
_MAX_IMAGEM_DATA_CHARS = 2_800_000


class RevisaoBlocoCreate(BaseModel):
    pdf_path: str
    tipo: str = Field(default="recorte")  # recorte | resumo_ia | texto | nota
    titulo: str = Field(default="", max_length=300)
    conteudo: str = Field(default="", max_length=20000)
    imagem_data: str = Field(default="", max_length=_MAX_IMAGEM_DATA_CHARS)
    pagina: int = 1
    # JSON de retângulos de oclusão (image occlusion), coords relativas 0-1.
    oclusoes: str = Field(default="", max_length=10000)
    # Tag/categoria: decorar | entender | pegadinha | revisar | '' (sem tag).
    tag: str = Field(default="", max_length=20)


class RevisaoBlocoUpdate(BaseModel):
    titulo: str | None = Field(default=None, max_length=300)
    conteudo: str | None = Field(default=None, max_length=20000)
    ordem: int | None = None
    oclusoes: str | None = Field(default=None, max_length=10000)
    tag: str | None = Field(default=None, max_length=20)


class DestaqueCreate(BaseModel):
    pdf_path: str
    pagina: int = 1
    cor: str = Field(default="yellow", max_length=20)
    texto: str = Field(default="", max_length=5000)
    # JSON com a lista de retângulos da seleção, coords relativas 0-1 à página.
    rects: str = Field(default="[]", max_length=20000)
    # Estilo: highlight | underline | strike | box
    estilo: str = Field(default="highlight", max_length=20)
    comentario: str = Field(default="", max_length=5000)


class DestaqueUpdate(BaseModel):
    cor: str | None = Field(default=None, max_length=20)
    estilo: str | None = Field(default=None, max_length=20)
    comentario: str | None = Field(default=None, max_length=5000)
