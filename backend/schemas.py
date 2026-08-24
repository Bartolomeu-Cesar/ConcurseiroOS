"""Pydantic schemas for request/response validation.

These schemas cover the common patterns used across routers (especially auth.py
which currently uses raw `dict = Body(...)` patterns). They are ready to be
plugged into the routers as typed replacements for the dict bodies.

Usage (when wiring up):
    from schemas import LoginRequest, VerifyCodeRequest, ...

    @router.post("/login")
    def login(body: LoginRequest, ...):
        ...
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


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
    email: Optional[EmailStr] = None
    nome: Optional[str] = None
    username: Optional[str] = None
    plano: Optional[str] = None
    plano_expira: Optional[str] = None
    avatar: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


class AdminBulkAction(BaseModel):
    """POST /api/admin/users/bulk body — bulk actions on users."""
    user_ids: list[int]
    action: str
    value: str = ""


class AdminChangePlan(BaseModel):
    """POST /api/admin/users/{id}/plano body — change user plan."""
    plano: str
    plano_expira: str = ""
