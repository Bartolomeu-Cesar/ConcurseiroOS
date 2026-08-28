"""Sistema de planos e controle de acesso por nível.

Referência de mercado:
- QConcursos: Gratuito (10 questões/dia) → Básico R$19,90/mês → Avançado → Elite
- Quizlet: Free (limitado) → Plus R$35,99/ano
- Anki: Grátis (desktop) / $24,99 one-time (iOS)

ConcurseiroOS é uma ferramenta pessoal/offline-first, então os planos
focam em volume de conteúdo e recursos avançados.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

# ==================== DEFINIÇÃO DOS PLANOS ====================

PLANS = {
    "guest": {
        "nome": "Visitante",
        "descricao": "Sem conta — explore a plataforma",
        "preco": "Grátis",
        "limites": {
            # Conteúdo
            "editais": 1,              # 1 concurso
            "flashcards": 30,          # total de cards
            "questoes_dia": 5,         # questões por dia
            "questoes_banco": 50,      # total no banco
            "pdfs": 3,                 # arquivos PDF
            "simulados": 1,            # simulados criados
            "ciclo_materias": 3,       # matérias no ciclo
            # Batalha
            "batalha": False,          # sem acesso
            "batalha_max_jogadores": 0,
            "batalha_max_rodadas": 0,
            # Recursos
            "treinador": False,        # técnicas de estudo
            "dashboard_completo": False,# analytics completo
            "export_import": False,    # exportar/importar dados
            "calendario": False,       # planejador semanal
            "modo_foco": True,         # modo foco básico
            "revisao_espacada": True,  # SM-2 básico
            "gamification": False,     # XP, níveis, conquistas
            "notas_topico": False,     # anotações por tópico
            "vinculo_pdf": False,      # vincular PDF a disciplina
            "countdown": True,         # contador de provas
            "streak": True,            # streak de estudo
            "relatorios": False,       # relatórios avançados
            "backup_auto": False,      # backup automático
        }
    },
    "free": {
        "nome": "Estudante",
        "descricao": "Conta gratuita — recursos essenciais para começar",
        "preco": "Grátis",
        "limites": {
            # Conteúdo
            "editais": 2,              # 2 concursos
            "flashcards": 150,         # cards no total
            "questoes_dia": 15,        # questões por dia
            "questoes_banco": 200,     # total no banco
            "pdfs": 10,                # arquivos PDF
            "simulados": 3,            # simulados
            "ciclo_materias": 8,       # matérias no ciclo
            # Batalha
            "batalha": True,           # acesso à batalha
            "batalha_max_jogadores": 3,# máx 3 jogadores
            "batalha_max_rodadas": 5,  # máx 5 rodadas
            # Recursos
            "treinador": True,         # 3 técnicas básicas
            "dashboard_completo": True,# dashboard principal
            "export_import": False,    # sem export/import
            "calendario": True,        # planejador semanal
            "modo_foco": True,         # modo foco
            "revisao_espacada": True,  # SM-2 completo
            "gamification": True,      # XP e níveis
            "notas_topico": True,      # anotações
            "vinculo_pdf": True,       # vincular PDF
            "countdown": True,         # countdown
            "streak": True,            # streaks
            "relatorios": False,       # sem relatórios avançados
            "backup_auto": False,      # sem backup auto
        }
    },
    "premium": {
        "nome": "Premium",
        "descricao": "Sem limites de conteúdo + recursos avançados",
        "preco": "R$14,90/mês",
        "preco_vitalicio": "R$97 (único)",
        "limites": {
            # Conteúdo — TUDO ILIMITADO
            "editais": -1,
            "flashcards": -1,
            "questoes_dia": -1,
            "questoes_banco": -1,
            "pdfs": -1,
            "simulados": -1,
            "ciclo_materias": -1,
            # Batalha
            "batalha": True,           # acesso completo
            "batalha_max_jogadores": 5,# máx 5 jogadores
            "batalha_max_rodadas": 20, # máx 20 rodadas
            # Recursos — TUDO HABILITADO
            "treinador": True,         # todas as técnicas
            "dashboard_completo": True,
            "export_import": True,     # exportar/importar tudo
            "calendario": True,
            "modo_foco": True,
            "revisao_espacada": True,
            "gamification": True,
            "notas_topico": True,
            "vinculo_pdf": True,
            "countdown": True,
            "streak": True,
            "relatorios": True,        # relatórios de desempenho
            "backup_auto": True,       # backup automático
            # IA — com limite diário
            "ai_tutor_ilimitado": False,
            "ai_tokens_dia": 50000,    # 50k tokens/dia (~30 perguntas)
            # Sem exclusivos vitalícios
            "importacao_prioritaria": False,
            "suporte_prioritario": False,
            "beta_features": False,
            "temas_exclusivos": False,
            "study_room_privada": False,
            "relatorios_pdf": False,
        }
    },
    "ilimitado": {
        "nome": "Vitalício",
        "descricao": "Pague uma vez — acesso permanente a tudo + exclusivos + atualizações vitalícias",
        "preco": "R$97 (único)",
        "limites": {
            # Tudo do Premium sem expiração + EXCLUSIVOS
            "editais": -1,
            "flashcards": -1,
            "questoes_dia": -1,
            "questoes_banco": -1,
            "pdfs": -1,
            "simulados": -1,
            "ciclo_materias": -1,
            # Batalha — SUPERIOR ao premium
            "batalha": True,
            "batalha_max_jogadores": 10,  # Premium = 5
            "batalha_max_rodadas": 50,    # Premium = 20
            # Recursos — TUDO + EXCLUSIVOS
            "treinador": True,
            "dashboard_completo": True,
            "export_import": True,
            "calendario": True,
            "modo_foco": True,
            "revisao_espacada": True,
            "gamification": True,
            "notas_topico": True,
            "vinculo_pdf": True,
            "countdown": True,
            "streak": True,
            "relatorios": True,
            "backup_auto": True,
            # === EXCLUSIVOS VITALÍCIO ===
            "ai_tutor_ilimitado": True,   # Sem limite diário de tokens IA
            "ai_tokens_dia": -1,          # Premium = 50.000/dia
            "importacao_prioritaria": True,# Parser com OCR avançado
            "suporte_prioritario": True,  # Suporte direto
            "beta_features": True,        # Acesso antecipado a novas features
            "temas_exclusivos": True,     # Temas visuais extras
            "study_room_privada": True,   # Sala de estudo privada
            "relatorios_pdf": True,       # Exportar relatórios em PDF
        }
    },
}


def get_plan(user):
    """Retorna o plano do usuário (ou DEFAULT_PLAN das settings se não autenticado).

    Lógica de expiração:
    - plano_expira vazio ou "vitalicio" = acesso permanente (pagou vitalício)
    - plano_expira com data = verifica se expirou (assinatura mensal)
    """
    from settings import settings

    if not user:
        return settings.DEFAULT_PLAN if settings.DEFAULT_PLAN in PLANS else "guest"
    plano = user.get("plano", "free") if isinstance(user, dict) else (user["plano"] if user else "free")
    # Verificar expiração do plano premium (mensal)
    # Se plano_expira está vazio ou é "vitalicio", é acesso permanente
    if plano == "premium" and user.get("plano_expira"):
        plano_expira = user["plano_expira"]
        if plano_expira.lower() in ("vitalicio", "vitalício", "lifetime", ""):
            return plano  # Vitalício, não expira
        try:
            expira = datetime.fromisoformat(plano_expira)
            if expira < datetime.now(timezone.utc):
                return "free"  # Expirou, volta para free
        except (ValueError, TypeError):
            pass
    return plano if plano in PLANS else "free"


def get_limits(user):
    """Retorna os limites do plano do usuário."""
    plano = get_plan(user)
    return PLANS[plano]["limites"]


def check_limit(user, recurso, quantidade_atual=0):
    """Verifica se o usuário pode usar mais de um recurso.
    Retorna True se pode, False se atingiu o limite.
    """
    limites = get_limits(user)
    limite = limites.get(recurso)
    if limite is None:
        return True
    if isinstance(limite, bool):
        return limite
    if limite == -1:
        return True  # Ilimitado
    return quantidade_atual < limite


def check_feature(user, feature):
    """Verifica se uma feature está disponível para o plano do usuário."""
    limites = get_limits(user)
    return limites.get(feature, False)


def require_feature(feature):
    """Dependency que bloqueia se a feature não está disponível no plano."""
    def check(user):
        if not check_feature(user, feature):
            plano = get_plan(user)
            raise HTTPException(
                status_code=403,
                detail=f"Recurso não disponível no plano {PLANS[plano]['nome']}. Faça upgrade para Premium!"
            )
    return check


def enforce_plan_limit(conn, user_id: int, recurso: str):
    """Verifica se o usuário pode criar mais do recurso dado.

    Lança HTTPException 403 se o limite do plano foi atingido.
    Deve ser chamado em endpoints POST de criação de recursos limitados.

    Recursos suportados: flashcards, pdfs, simulados, ciclo_materias, editais.
    Para questoes_dia usa contagem diária.
    """
    from utils import today_str as _today

    user = conn.execute(
        "SELECT id, plano, plano_expira FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    user_dict = dict(user) if user else {"id": user_id, "plano": "free", "plano_expira": ""}

    limites = get_limits(user_dict)
    limite = limites.get(recurso)

    # Sem limite definido ou ilimitado (-1) → permitir
    if limite is None or limite == -1:
        return
    if isinstance(limite, bool):
        if not limite:
            plano = get_plan(user_dict)
            raise HTTPException(
                status_code=403,
                detail=f"'{recurso}' não disponível no plano {PLANS[plano]['nome']}. Faça upgrade para Premium!"
            )
        return

    # Contar uso atual
    if recurso == "flashcards":
        count = conn.execute("SELECT COUNT(*) FROM flashcards WHERE user_id = ?", (user_id,)).fetchone()[0]
    elif recurso == "pdfs":
        count = conn.execute("SELECT COUNT(*) FROM progress WHERE user_id = ?", (user_id,)).fetchone()[0]
    elif recurso == "simulados":
        count = conn.execute("SELECT COUNT(*) FROM simulados WHERE user_id = ?", (user_id,)).fetchone()[0]
    elif recurso == "ciclo_materias":
        count = conn.execute("SELECT COUNT(*) FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    elif recurso == "editais":
        count = conn.execute("SELECT COUNT(DISTINCT edital_nome) FROM edital WHERE arquivado = 0 AND user_id = ?", (user_id,)).fetchone()[0]
    elif recurso == "questoes_dia":
        today = _today()
        count = conn.execute(
            "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ? AND data = ?",
            (user_id, today)
        ).fetchone()[0]
    elif recurso == "questoes_banco":
        count = conn.execute("SELECT COUNT(*) FROM questoes WHERE user_id = ?", (user_id,)).fetchone()[0]
    else:
        return  # Recurso desconhecido → permitir

    if count >= limite:
        plano = get_plan(user_dict)
        raise HTTPException(
            status_code=403,
            detail=f"Limite de {recurso} atingido ({count}/{limite}) no plano {PLANS[plano]['nome']}. Faça upgrade para Premium!"
        )


def get_plan_info(user):
    """Retorna informações completas do plano para exibir no frontend."""
    plano_key = get_plan(user)
    plano = PLANS[plano_key]
    plano_expira = user.get("plano_expira", "") if user else ""
    is_vitalicio = plano_key in ("ilimitado",) or (plano_expira and plano_expira.lower() in ("vitalicio", "vitalício", "lifetime")) or (plano_key == "premium" and not plano_expira)
    return {
        "plano": plano_key,
        "nome": plano["nome"],
        "descricao": plano["descricao"],
        "preco": plano["preco"],
        "preco_vitalicio": plano.get("preco_vitalicio", ""),
        "limites": plano["limites"],
        "plano_expira": plano_expira,
        "vitalicio": is_vitalicio,
    }


# ==================== SISTEMA DE CRÉDITOS ====================
# 1 crédito = 3 dias de acesso Premium
# 10 créditos = 30 dias (1 mês)
# Créditos residuais (< 1 dia) ficam no saldo sem expirar por padrão

CREDIT_CONFIG = {
    "dias_por_credito": 3,           # 1 crédito = 3 dias de premium
    "creditos_por_mes": 10,          # 10 créditos = 1 mês
    "minimo_ativacao": 1,            # Mínimo 1 crédito para ativar (3 dias)
    "expiracao_padrao_dias": None,   # None = sem expiração (créditos não expiram)
    "precos": {
        1: 4.90,      # 1 crédito = R$4,90 (3 dias)
        5: 19.90,     # 5 créditos = R$19,90 (15 dias) — economia 19%
        10: 34.90,    # 10 créditos = R$34,90 (30 dias) — economia 29%
        20: 59.90,    # 20 créditos = R$59,90 (60 dias) — economia 39%
        50: 119.90,   # 50 créditos = R$119,90 (150 dias) — economia 51%
    },
}


def calcular_dias_creditos(creditos: int) -> int:
    """Converte créditos em dias de acesso. Mínimo 1 dia se creditos >= 1."""
    dias = creditos * CREDIT_CONFIG["dias_por_credito"]
    return dias


def creditos_para_mes() -> int:
    """Quantos créditos para 1 mês completo."""
    return CREDIT_CONFIG["creditos_por_mes"]
