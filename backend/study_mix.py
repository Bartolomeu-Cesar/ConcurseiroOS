"""Distribuição adaptativa NOVO vs. REVISÃO para flashcards, questões e desafio.

Objetivo (pedido do usuário): distribuir a sessão entre conteúdo NOVO e REVISÃO
espaçada numa proporção ÓTIMA para o candidato absorver o máximo, sem ficar
"respondendo sempre as mesmas questões ou o mesmo assunto".

Como funciona
=============
A proporção não é fixa: é calculada por `compute_mix()` a partir de três fatores,
nesta ordem de prioridade:

1. FASE (dias até a prova) — métrica "ótimo" automática:
   - LONGE da prova  -> mais NOVO (priorizar cobertura do edital).
   - PERTO da prova  -> mais REVISÃO/consolidação (blindar o que já sabe).
   Zonas (dias): >120 = expansão | 60-120 = equilíbrio | 21-60 = consolidação
   | <21 = reta final (quase só revisão). Sem data -> zona equilíbrio.

2. BACKLOG de revisão (freio de segurança). Se a fila de itens vencidos já
   consome a carga do dia, corta os novos: não adianta empilhar conteúdo novo
   sobre uma dívida de revisão crescente (é o que faz o candidato "afogar" e
   acabar revendo sempre as mesmas coisas atrasadas). Regras:
   - backlog >= carga           -> 100% revisão (0 novos).
   - backlog >= 70% da carga    -> no máx. 10% de novos.

3. OVERRIDE do usuário (preferências). Se o usuário fixou uma proporção-alvo
   de novos (`mix_pct_novos > 0`) e/ou uma carga diária (`mix_carga_diaria > 0`),
   esses valores substituem o default automático da fase — mas o freio de
   backlog (fator 2) continua valendo (segurança acima de preferência).

Base científica (mesmas fontes já citadas em study_ordering.py):
- SRS maduro sustenta-se com ~1/3 novo : 2/3 revisão; teto dinâmico de novos evita
  o "backlog explosivo" (prática consolidada de SRS — Anki/SuperMemo).
- Perto da avaliação, deslocar peso para revisão maximiza retenção no dia D
  (Spacing/Lag Effect exam-aware — Cepeda et al. 2006).

Este módulo é PURO em `compute_mix()` (sem I/O) para ser trivial de testar; as
funções `*_from_conn`/`mix_for_*` leem carga/backlog/dias do banco reutilizando
helpers canônicos do projeto (services.get_dias_ate_prova).
"""

from __future__ import annotations

from dataclasses import dataclass

# Defaults canônicos (bom default sem configuração do usuário) ---------------
DEFAULT_CARGA_DIARIA = 40          # itens/dia por modalidade quando nada configurado
MIN_CARGA_DIARIA = 5
MAX_CARGA_DIARIA = 500

# Proporção-alvo de NOVOS por zona de fase (fração 0..1). O restante é revisão.
FASE_EXPANSAO_PCT_NOVOS = 0.50     # >120 dias: metade novo, metade revisão
FASE_EQUILIBRIO_PCT_NOVOS = 0.35   # 60-120 dias (default global sem data)
FASE_CONSOLIDACAO_PCT_NOVOS = 0.20  # 21-60 dias
FASE_RETA_FINAL_PCT_NOVOS = 0.05   # <21 dias: quase só revisão

# Limites das zonas (dias até a prova)
ZONA_EXPANSAO_MIN_DIAS = 120
ZONA_EQUILIBRIO_MIN_DIAS = 60
ZONA_CONSOLIDACAO_MIN_DIAS = 21

# Freio por backlog de revisão
BACKLOG_TRAVA_TOTAL = 1.0          # backlog >= 100% da carga -> 0 novos
BACKLOG_TRAVA_PARCIAL = 0.70       # backlog >= 70% da carga -> teto de novos
BACKLOG_TETO_NOVOS_PARCIAL = 0.10  # ...no máx. 10% de novos


@dataclass
class MixConfig:
    """Configuração efetiva do mix (após aplicar defaults/override do usuário)."""

    carga_diaria: int = DEFAULT_CARGA_DIARIA
    pct_novos_override: float = 0.0   # 0 = automático por fase; >0 = fixo pelo usuário
    auto_por_prova: bool = True       # se True, usa dias_ate_prova para a fase


@dataclass
class MixResult:
    """Resultado da distribuição para uma sessão."""

    carga: int            # total de itens-alvo do dia (para esta modalidade)
    novos: int            # quantos NOVOS incluir
    revisao: int          # quantos de REVISÃO incluir
    pct_novos: float      # fração efetiva de novos (0..1)
    zona: str             # 'expansao'|'equilibrio'|'consolidacao'|'reta_final'|'manual'
    motivo: str           # explicação legível (para UI/telemetria)
    dias_ate_prova: int | None = None
    backlog: int = 0

    def as_dict(self) -> dict:
        return {
            "carga": self.carga,
            "novos": self.novos,
            "revisao": self.revisao,
            "pct_novos": round(self.pct_novos, 4),
            "zona": self.zona,
            "motivo": self.motivo,
            "dias_ate_prova": self.dias_ate_prova,
            "backlog": self.backlog,
        }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def zona_por_dias(dias_ate_prova: int | None) -> tuple[str, float]:
    """Mapeia dias até a prova -> (zona, pct_novos automático).

    Sem data (None) -> equilíbrio (default global seguro).
    """
    if dias_ate_prova is None:
        return "equilibrio", FASE_EQUILIBRIO_PCT_NOVOS
    if dias_ate_prova >= ZONA_EXPANSAO_MIN_DIAS:
        return "expansao", FASE_EXPANSAO_PCT_NOVOS
    if dias_ate_prova >= ZONA_EQUILIBRIO_MIN_DIAS:
        return "equilibrio", FASE_EQUILIBRIO_PCT_NOVOS
    if dias_ate_prova >= ZONA_CONSOLIDACAO_MIN_DIAS:
        return "consolidacao", FASE_CONSOLIDACAO_PCT_NOVOS
    return "reta_final", FASE_RETA_FINAL_PCT_NOVOS


def compute_mix(
    *,
    backlog_revisao: int,
    dias_ate_prova: int | None = None,
    config: MixConfig | None = None,
    carga_override: int | None = None,
) -> MixResult:
    """Calcula a distribuição NOVO vs. REVISÃO (função pura, sem I/O).

    Args:
        backlog_revisao: nº de itens de revisão VENCIDOS (proxima_revisao <= hoje).
        dias_ate_prova: dias até a próxima prova futura (None = desconhecido).
        config: MixConfig com carga/override do usuário (None = defaults).
        carga_override: força a carga total desta sessão (ex.: `qtd` pedido pelo
            endpoint). Tem precedência sobre config.carga_diaria.

    Returns:
        MixResult com novos/revisão inteiros que somam a carga efetiva.
    """
    cfg = config or MixConfig()

    # 1. Carga efetiva
    carga = carga_override if carga_override is not None else cfg.carga_diaria
    carga_min = 1 if carga_override is not None else MIN_CARGA_DIARIA
    carga = int(_clamp(int(carga or 0), carga_min, MAX_CARGA_DIARIA))

    # 2. Proporção-alvo de novos: override do usuário OU automático por fase
    if cfg.pct_novos_override and cfg.pct_novos_override > 0:
        pct_novos = _clamp(cfg.pct_novos_override, 0.0, 1.0)
        zona = "manual"
        motivo = f"Proporção fixa do usuário: {round(pct_novos * 100)}% novos."
    else:
        zona, pct_novos = zona_por_dias(dias_ate_prova if cfg.auto_por_prova else None)
        if zona == "expansao":
            motivo = f"Longe da prova ({dias_ate_prova}d): priorizando conteúdo novo (cobertura)."
        elif zona == "equilibrio":
            base = f"({dias_ate_prova}d)" if dias_ate_prova is not None else "(sem data de prova)"
            motivo = f"Fase de equilíbrio {base}: novo e revisão balanceados."
        elif zona == "consolidacao":
            motivo = f"Aproximando da prova ({dias_ate_prova}d): mais revisão, consolidando."
        else:  # reta_final
            motivo = f"Reta final ({dias_ate_prova}d): quase só revisão (blindar o que já sabe)."

    # 3. Freio de segurança por backlog de revisão (sempre aplica)
    backlog = max(0, int(backlog_revisao or 0))
    if carga > 0:
        ratio = backlog / carga
        if ratio >= BACKLOG_TRAVA_TOTAL:
            pct_novos = 0.0
            zona = f"{zona}+backlog_total"
            motivo = (
                f"Fila de revisão vencida ({backlog}) atingiu a carga do dia ({carga}): "
                "0% novos até você quitar as revisões atrasadas."
            )
        elif ratio >= BACKLOG_TRAVA_PARCIAL and pct_novos > BACKLOG_TETO_NOVOS_PARCIAL:
            pct_novos = BACKLOG_TETO_NOVOS_PARCIAL
            zona = f"{zona}+backlog_alto"
            motivo = (
                f"Fila de revisão alta ({backlog}/{carga}): limitando novos a "
                f"{round(BACKLOG_TETO_NOVOS_PARCIAL * 100)}% para não acumular dívida."
            )

    # 4. Converter em inteiros que somam a carga
    novos = int(round(carga * pct_novos))
    novos = int(_clamp(novos, 0, carga))
    revisao = carga - novos

    return MixResult(
        carga=carga,
        novos=novos,
        revisao=revisao,
        pct_novos=(novos / carga if carga else 0.0),
        zona=zona,
        motivo=motivo,
        dias_ate_prova=dias_ate_prova,
        backlog=backlog,
    )


def allocate(mix: MixResult, *, disponiveis_novos: int, disponiveis_revisao: int) -> tuple[int, int]:
    """Ajusta o alvo (novos, revisão) ao que REALMENTE existe nos pools.

    Preserva a carga total sempre que possível: se falta item de um tipo, tenta
    completar com o outro (ex.: em dia com a revisão, "sobra" da revisão vira
    novo; com backlog e sem novos disponíveis, a revisão absorve tudo).

    Returns:
        (n_novos, n_revisao) — nunca excede os disponíveis; soma <= mix.carga.
    """
    disponiveis_novos = max(0, int(disponiveis_novos or 0))
    disponiveis_revisao = max(0, int(disponiveis_revisao or 0))

    n_novos = min(mix.novos, disponiveis_novos)
    n_rev = min(mix.revisao, disponiveis_revisao)

    faltam = mix.carga - (n_novos + n_rev)
    if faltam > 0:
        # Completar com revisão remanescente (prioridade: consolidar > avançar)
        extra_rev = min(faltam, disponiveis_revisao - n_rev)
        n_rev += max(0, extra_rev)
        faltam = mix.carga - (n_novos + n_rev)
    if faltam > 0:
        # Ainda falta -> completar com novos remanescentes
        extra_novos = min(faltam, disponiveis_novos - n_novos)
        n_novos += max(0, extra_novos)

    return n_novos, n_rev


# --- Integração com o banco (config do usuário + backlog + dias até prova) ---

def load_config_from_conn(conn, user_id: int) -> MixConfig:
    """Lê a config do usuário de metas_config (migration 98). Tolerante a schema
    antigo: se as colunas não existirem, retorna defaults."""
    cfg = MixConfig()
    try:
        row = conn.execute(
            "SELECT mix_carga_diaria, mix_pct_novos, mix_auto_prova "
            "FROM metas_config WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    except Exception:
        return cfg  # colunas ainda não migradas -> defaults
    if not row:
        return cfg
    keys = row.keys()
    carga = row["mix_carga_diaria"] if "mix_carga_diaria" in keys else 0
    pct = row["mix_pct_novos"] if "mix_pct_novos" in keys else 0
    auto = row["mix_auto_prova"] if "mix_auto_prova" in keys else 1
    if carga and carga > 0:
        cfg.carga_diaria = int(_clamp(int(carga), MIN_CARGA_DIARIA, MAX_CARGA_DIARIA))
    # pct do usuário é armazenado como inteiro 0..100; 0 = automático
    if pct and pct > 0:
        cfg.pct_novos_override = _clamp(float(pct) / 100.0, 0.0, 1.0)
    cfg.auto_por_prova = bool(auto if auto is not None else 1)
    return cfg


def dias_ate_prova_from_conn(conn, user_id: int) -> int | None:
    """Reutiliza o helper canônico do projeto (services.get_dias_ate_prova)."""
    try:
        from services import get_dias_ate_prova
        return get_dias_ate_prova(conn, user_id)
    except Exception:
        return None


def backlog_flashcards(conn, user_id: int) -> int:
    """Flashcards com revisão VENCIDA (proxima_revisao <= hoje), não suspensos."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM flashcards "
            "WHERE user_id = ? AND COALESCE(suspenso,0) = 0 "
            "AND proxima_revisao <= date('now')",
            (user_id,),
        ).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def backlog_questoes(conn, user_id: int, materias: list[str] | None = None) -> int:
    """Questões agendadas para revisão hoje/atrasadas (erros_revisao vencidos)."""
    try:
        params: list = [user_id]
        mat_join = ""
        mat_clause = ""
        if materias:
            ph = ",".join("?" * len(materias))
            mat_join = "JOIN questoes q ON q.id = er.questao_id AND q.user_id = er.user_id"
            mat_clause = f" AND q.materia IN ({ph})"
            params += list(materias)
        row = conn.execute(
            f"SELECT COUNT(*) FROM erros_revisao er {mat_join} "
            f"WHERE er.user_id = ? AND er.proxima_revisao <= date('now'){mat_clause}",
            params,
        ).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def mix_for_flashcards(conn, user_id: int, carga_override: int | None = None) -> MixResult:
    """Mix pronto para a fila de flashcards do dia."""
    cfg = load_config_from_conn(conn, user_id)
    return compute_mix(
        backlog_revisao=backlog_flashcards(conn, user_id),
        dias_ate_prova=dias_ate_prova_from_conn(conn, user_id),
        config=cfg,
        carga_override=carga_override,
    )


def mix_for_questoes(
    conn, user_id: int, carga_override: int | None = None, materias: list[str] | None = None
) -> MixResult:
    """Mix pronto para seleção de questões / desafio diário."""
    cfg = load_config_from_conn(conn, user_id)
    return compute_mix(
        backlog_revisao=backlog_questoes(conn, user_id, materias),
        dias_ate_prova=dias_ate_prova_from_conn(conn, user_id),
        config=cfg,
        carga_override=carga_override,
    )
