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
        "limites": {
            # Conteúdo — TUDO ILIMITADO
            "editais": -1,
            "flashcards": -1,
            "questoes_dia": -1,
            "questoes_banco": -1,
            "pdfs": -1,
            "simulados": -1,
            "ciclo_materias": -1,
            # Recursos — TUDO HABILITADO
            "treinador": True,         # todas as 14 técnicas
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
        }
    },
    "ilimitado": {
        "nome": "Vitalício",
        "descricao": "Pague uma vez — acesso permanente a tudo + atualizações",
        "preco": "R$97 (único)",
        "limites": {
            # Tudo do Premium sem expiração
            "editais": -1,
            "flashcards": -1,
            "questoes_dia": -1,
            "questoes_banco": -1,
            "pdfs": -1,
            "simulados": -1,
            "ciclo_materias": -1,
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
        }
    },
}


def get_plan(user):
    """Retorna o plano do usuário (ou 'guest' se não autenticado)."""
    if not user:
        return "guest"
    plano = user.get("plano", "free") if isinstance(user, dict) else (user["plano"] if user else "free")
    # Verificar expiração do plano premium
    if plano == "premium" and user.get("plano_expira"):
        try:
            expira = datetime.fromisoformat(user["plano_expira"])
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


def get_plan_info(user):
    """Retorna informações completas do plano para exibir no frontend."""
    plano_key = get_plan(user)
    plano = PLANS[plano_key]
    return {
        "plano": plano_key,
        "nome": plano["nome"],
        "descricao": plano["descricao"],
        "preco": plano["preco"],
        "limites": plano["limites"],
        "plano_expira": user.get("plano_expira", "") if user else "",
    }
