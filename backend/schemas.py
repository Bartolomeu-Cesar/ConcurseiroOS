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
    """PUT /api/questoes/vincular-lote body."""
    filtro: dict = Field(default_factory=dict)
    atualizar: dict = Field(default_factory=dict)


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
