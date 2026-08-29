"""Trilha de Estudo (roadmap por tópicos do edital).

Diferente da "trilha diária" (agenda do dia, em treinador/trilha.py), esta é a
trilha longitudinal: uma sequência ordenada de etapas (uma por tópico do edital)
com pré-requisitos e progresso persistente (bloqueada → atual → concluída).

Integrações:
- Ciclo de Estudos: define QUAIS matérias entram (filtra ciclo ativo).
- Knowledge Graph (topic_dependencies): define a ORDEM (topological sort) e os
  pré-requisitos entre etapas.
- Edital/Mastery: define CONCLUSÃO de cada etapa (status = 'Concluído').

Técnicas científicas aplicadas: Desirable Difficulty (ordem por pré-requisito),
Progress Milestones (progresso por etapa) e Interleaving (round-robin entre
matérias quando não há dependências explícitas).
"""

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException, Query

from constants import XP_PER_TOPIC
from database import get_db_session
from logger import log
from utils import today_str

from .tables import _ensure_tables

router = APIRouter(prefix="/api/trilha", tags=["Trilha"])

STATUS_CONCLUIDO = "Concluído"
XP_PER_TOPICO = XP_PER_TOPIC  # +25 XP por tópico concluído (via Ligas)
NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ============================================================
# ORDENAÇÃO DOS TÓPICOS (topological sort + interleaving)
# ============================================================


def _materias_do_ciclo(conn, user_id: int):
    """Retorna as matérias do ciclo ATIVO (skill rule #2). Vazio se não há ciclo."""
    rows = conn.execute(
        "SELECT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem, id",
        (user_id,),
    ).fetchall()
    # Preserva ordem e remove duplicatas
    seen = set()
    materias = []
    for r in rows:
        m = r["materia"]
        if m not in seen:
            seen.add(m)
            materias.append(m)
    return materias


def _topicos_ordenados(conn, user_id: int, materias, edital_nome: str = "", cargo: str = ""):
    """Ordena os tópicos do edital respeitando pré-requisitos (topic_dependencies).

    Considera SOMENTE as matérias do ciclo (parâmetro `materias`). Se `materias`
    estiver vazio, retorna [] — a trilha nunca inclui o edital inteiro.

    Filtros opcionais `edital_nome`/`cargo`: quando informados, restringem a
    trilha a um edital/cargo específico. Isso evita o problema de agregar o mesmo
    tópico de matérias comuns (ex: Língua Portuguesa) que se repetem em dezenas de
    cargos do mesmo concurso, inflando artificialmente o total de etapas.

    Fallback quando não há dependências: interleaving (round-robin) por matéria,
    preservando a ordem do edital dentro de cada matéria.
    """
    if not materias:
        return []
    placeholders = ",".join("?" * len(materias))
    query = (
        "SELECT id, materia, topico, status FROM edital "
        f"WHERE arquivado = 0 AND user_id = ? AND materia IN ({placeholders})"
    )
    params = [user_id, *materias]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " ORDER BY materia, id"

    topicos = [dict(t) for t in conn.execute(query, params).fetchall()]
    if not topicos:
        return []

    topicos_map = {t["id"]: t for t in topicos}
    ids = set(topicos_map.keys())

    # Dependências do tipo pré-requisito, restritas ao conjunto atual
    deps_rows = conn.execute(
        "SELECT topic_id, depends_on_id FROM topic_dependencies WHERE user_id = ? AND relationship = 'prerequisite'",
        (user_id,),
    ).fetchall()
    prereqs = {}  # topic_id -> [depends_on_ids]
    for d in deps_rows:
        tid, dep = d["topic_id"], d["depends_on_id"]
        if tid in ids and dep in ids:
            prereqs.setdefault(tid, []).append(dep)

    if not prereqs:
        # Sem dependências: interleaving por matéria (round-robin)
        return _interleave_por_materia(topicos, materias)

    # Topological sort (Kahn) com desempate por ordem do edital (id)
    in_degree = {tid: len(prereqs.get(tid, [])) for tid in ids}
    ordem_edital = {t["id"]: i for i, t in enumerate(topicos)}
    dependentes = {}
    for tid, deps in prereqs.items():
        for dep in deps:
            dependentes.setdefault(dep, []).append(tid)

    disponiveis = sorted([tid for tid in ids if in_degree[tid] == 0], key=lambda t: ordem_edital[t])
    resultado = []
    while disponiveis:
        tid = disponiveis.pop(0)
        resultado.append(topicos_map[tid])
        for dep in dependentes.get(tid, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                disponiveis.append(dep)
        disponiveis.sort(key=lambda t: ordem_edital[t])

    # Ciclo de dependências: anexa remanescentes na ordem do edital
    if len(resultado) < len(topicos):
        restantes = [t for t in topicos if t["id"] not in {r["id"] for r in resultado}]
        resultado.extend(restantes)

    return resultado


def _interleave_por_materia(topicos, materias):
    """Round-robin entre matérias (Interleaving), preservando ordem interna."""
    por_materia = {}
    for t in topicos:
        por_materia.setdefault(t["materia"], []).append(t)

    # Ordem das matérias: a do ciclo, depois quaisquer outras
    ordem_mats = [m for m in materias if m in por_materia]
    for m in por_materia:
        if m not in ordem_mats:
            ordem_mats.append(m)

    resultado = []
    idx = {m: 0 for m in ordem_mats}
    restantes = sum(len(v) for v in por_materia.values())
    while restantes > 0:
        for m in ordem_mats:
            fila = por_materia[m]
            if idx[m] < len(fila):
                resultado.append(fila[idx[m]])
                idx[m] += 1
                restantes -= 1
    return resultado


# ============================================================
# GERAÇÃO
# ============================================================


@router.post(
    "/gerar",
    summary="Gerar trilha de estudo",
    description="""Gera (ou regenera) a trilha de estudo do usuário como uma sequência
ordenada de etapas por tópico do edital.

Fonte das matérias: ciclo de estudos ativo (se houver); caso contrário, todos os
tópicos do edital do usuário. Ordem: topological sort pelos pré-requisitos do
Knowledge Graph; sem dependências, aplica interleaving por matéria.

Cada etapa nasce com estado: 'concluida' (tópico já Concluído no edital),
'atual' (primeira etapa não-concluída — desbloqueada) ou 'bloqueada' (as demais).""",
)
def gerar_trilha(
    nome: str = Query("Minha Trilha", description="Nome da trilha"),
    edital_nome: str = Query("", description="Filtro opcional por edital"),
    cargo: str = Query("", description="Filtro opcional por cargo"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)

    materias = _materias_do_ciclo(conn, user_id)

    # A trilha considera APENAS as matérias do ciclo de estudos (as que o usuário
    # selecionou/colocou no ciclo) — nunca o edital inteiro. Sem ciclo ativo,
    # não há o que ordenar.
    if not materias:
        raise HTTPException(
            status_code=400,
            detail="Monte seu ciclo de estudos primeiro. A trilha é gerada apenas com as matérias que você colocou no ciclo.",
        )

    topicos = _topicos_ordenados(conn, user_id, materias, edital_nome, cargo)

    if not topicos:
        raise HTTPException(
            status_code=400,
            detail="As matérias do seu ciclo não têm tópicos no edital. Adicione tópicos a essas matérias primeiro.",
        )

    agora = today_str()

    # Desativa trilhas anteriores e cria uma nova (mantém histórico)
    conn.execute("UPDATE trilha SET ativo = 0, updated_at = ? WHERE user_id = ? AND ativo = 1", (agora, user_id))
    cur = conn.execute(
        "INSERT INTO trilha (user_id, nome, edital_nome, cargo, ativo, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
        (user_id, nome, edital_nome, cargo, agora, agora),
    )
    trilha_id = cur.lastrowid

    # Cria etapas: define 'atual' na primeira não-concluída
    primeira_pendente_definida = False
    prev_etapa_id = None
    total = 0
    concluidas = 0

    for ordem, t in enumerate(topicos, start=1):
        concluido = t["status"] == STATUS_CONCLUIDO
        if concluido:
            status = "concluida"
            desbloqueada = 1
            concluidas += 1
        elif not primeira_pendente_definida:
            status = "atual"
            desbloqueada = 1
            primeira_pendente_definida = True
        else:
            status = "bloqueada"
            desbloqueada = 0

        razao = (
            "Já concluído no edital"
            if concluido
            else ("Pronto para estudar agora" if status == "atual" else "Aguardando etapa anterior")
        )

        cur = conn.execute(
            """INSERT INTO trilha_etapas
               (trilha_id, user_id, ordem, topico_id, materia, topico, status, desbloqueada, prerequisito_etapa_id, razao, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trilha_id,
                user_id,
                ordem,
                t["id"],
                t["materia"],
                t["topico"],
                status,
                desbloqueada,
                prev_etapa_id,
                razao,
                agora,
            ),
        )
        prev_etapa_id = cur.lastrowid
        total += 1

    conn.commit()
    log.info(f"Trilha gerada: id={trilha_id}, {total} etapas ({concluidas} concluídas), materias_ciclo={len(materias)}")

    return _montar_trilha(conn, trilha_id, user_id)


# ============================================================
# PROGRESSO (concluir etapa)
# ============================================================


@router.post(
    "/etapas/{etapa_id}/concluir",
    summary="Concluir etapa da trilha",
    description="""Marca uma etapa como concluída. Regras:

- A etapa precisa estar desbloqueada ('atual' ou já 'concluida'); etapas 'bloqueada' são rejeitadas (409).
- O tópico do edital correspondente é marcado como 'Concluído' (single source of truth):
  isso alimenta o XP semanal das Ligas (+25 XP/tópico) e o progresso do edital.
- A próxima etapa da sequência é desbloqueada e vira a 'atual'.

Retorna a trilha atualizada + o XP concedido pelo tópico.""",
)
def concluir_etapa(
    etapa_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)

    etapa = conn.execute(
        "SELECT id, trilha_id, ordem, topico_id, status, desbloqueada FROM trilha_etapas WHERE id = ? AND user_id = ?",
        (etapa_id, user_id),
    ).fetchone()
    if not etapa:
        raise HTTPException(status_code=404, detail="Etapa da trilha não encontrada.")

    if etapa["status"] == "bloqueada" or not etapa["desbloqueada"]:
        raise HTTPException(
            status_code=409,
            detail="Etapa bloqueada. Conclua a etapa anterior antes de avançar.",
        )

    trilha_id = etapa["trilha_id"]
    xp_topico = _aplicar_conclusao_etapa(conn, etapa, user_id)
    conn.commit()

    resultado = _montar_trilha(conn, trilha_id, user_id)
    resultado["xp_topico"] = xp_topico
    return resultado


def _aplicar_conclusao_etapa(conn, etapa, user_id: int) -> int:
    """Lógica central de conclusão de uma etapa (sem commit).

    Marca o tópico do edital como Concluído (fonte da verdade p/ XP nas Ligas),
    marca a etapa como 'concluida' e desbloqueia a próxima ('atual').
    Retorna o XP concedido (0 se já estava concluída).

    Reutilizada pelo endpoint POST /concluir e pela conclusão automática via
    calendário (marcar_etapa_por_topico).
    """
    agora = today_str()
    xp_topico = 0
    ja_concluida = etapa["status"] == "concluida"

    if etapa["topico_id"]:
        conn.execute(
            "UPDATE edital SET status = 'Concluído', mastery_updated_at = ? WHERE id = ? AND user_id = ?",
            (agora, etapa["topico_id"], user_id),
        )
        if not ja_concluida:
            xp_topico = XP_PER_TOPICO

    conn.execute(
        "UPDATE trilha_etapas SET status = 'concluida', desbloqueada = 1 WHERE id = ? AND user_id = ?",
        (etapa["id"], user_id),
    )

    proxima = conn.execute(
        """SELECT id FROM trilha_etapas
           WHERE trilha_id = ? AND user_id = ? AND ordem > ? AND status != 'concluida'
           ORDER BY ordem LIMIT 1""",
        (etapa["trilha_id"], user_id, etapa["ordem"]),
    ).fetchone()
    if proxima:
        conn.execute(
            "UPDATE trilha_etapas SET status = 'atual', desbloqueada = 1 WHERE id = ? AND user_id = ?",
            (proxima["id"], user_id),
        )

    conn.execute("UPDATE trilha SET updated_at = ? WHERE id = ? AND user_id = ?", (agora, etapa["trilha_id"], user_id))
    log.info(f"Trilha etapa concluída: etapa={etapa['id']}, trilha={etapa['trilha_id']}, xp={xp_topico}")
    return xp_topico


def marcar_etapa_por_topico(conn, user_id: int, materia: str, topico: str) -> bool:
    """Conclui automaticamente a etapa da trilha ativa que casa com (materia, topico).

    Usada quando o usuário marca uma atividade de tipo='trilha' como concluída no
    calendário. Idempotente e silenciosa (não levanta erro se não houver match).
    Retorna True se alguma etapa foi concluída agora.
    """
    if not topico:
        return False
    _ensure_tables(conn)
    etapa = conn.execute(
        """SELECT e.id, e.trilha_id, e.ordem, e.topico_id, e.status
           FROM trilha_etapas e
           JOIN trilha t ON t.id = e.trilha_id AND t.ativo = 1
           WHERE e.user_id = ? AND e.materia = ? AND e.topico = ? AND e.status != 'concluida'
           ORDER BY e.ordem LIMIT 1""",
        (user_id, materia, topico),
    ).fetchone()
    if not etapa:
        return False
    _aplicar_conclusao_etapa(conn, etapa, user_id)
    return True


# ============================================================
# SINCRONIZAÇÃO COM O CALENDÁRIO
# ============================================================


@router.post(
    "/sincronizar-calendario",
    summary="Agendar próximas etapas no calendário",
    description="""Distribui as próximas etapas pendentes da trilha (na ordem) pelos dias úteis
do calendário personalizado, como atividades do tipo 'trilha'.

- Idempotente: remove as atividades de tipo 'trilha' anteriores antes de recriar (não mexe nas
  demais atividades do calendário do usuário).
- `dias_semana`: quantos dias da semana usar (1..7, começando na segunda). Padrão 6 (seg-sáb).
- `tempo_min`: minutos alocados por etapa/atividade. Padrão 60.
- `max_etapas`: quantas etapas pendentes agendar. Padrão 12.

Retorna um resumo por dia.""",
)
def sincronizar_calendario(
    dias_semana: int = Query(6, ge=1, le=7),
    tempo_min: int = Query(60, ge=5, le=480),
    max_etapas: int = Query(12, ge=1, le=60),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)

    trilha = conn.execute(
        "SELECT id FROM trilha WHERE user_id = ? AND ativo = 1 ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not trilha:
        raise HTTPException(
            status_code=404,
            detail="Nenhuma trilha ativa. Gere a trilha antes de sincronizar com o calendário.",
        )

    # Próximas etapas pendentes (na ordem da trilha)
    etapas = conn.execute(
        """SELECT materia, topico FROM trilha_etapas
           WHERE trilha_id = ? AND user_id = ? AND status != 'concluida'
           ORDER BY ordem LIMIT ?""",
        (trilha["id"], user_id, max_etapas),
    ).fetchall()

    if not etapas:
        raise HTTPException(
            status_code=400,
            detail="Não há etapas pendentes na trilha para agendar.",
        )

    # Idempotência: remove só as atividades de trilha anteriores (preserva as demais)
    conn.execute(
        "DELETE FROM calendario_personalizado WHERE user_id = ? AND tipo = 'trilha'",
        (user_id,),
    )

    # Distribui as etapas em round-robin pelos dias úteis
    agendadas = 0
    ordem_por_dia = {d: 0 for d in range(dias_semana)}
    for i, e in enumerate(etapas):
        dia = i % dias_semana
        conn.execute(
            """INSERT INTO calendario_personalizado
               (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id)
               VALUES (?, ?, ?, ?, 'trilha', ?, ?)""",
            (dia, e["materia"], e["topico"], tempo_min, ordem_por_dia[dia], user_id),
        )
        ordem_por_dia[dia] += 1
        agendadas += 1

    conn.commit()
    log.info(f"Trilha sincronizada ao calendário: {agendadas} etapas em {dias_semana} dias (trilha={trilha['id']})")

    resumo = []
    for d in range(dias_semana):
        itens = [e["topico"] for i, e in enumerate(etapas) if i % dias_semana == d]
        resumo.append({"dia_semana": d, "nome": NOMES_DIAS[d], "atividades": len(itens), "topicos": itens})

    return {
        "ok": True,
        "agendadas": agendadas,
        "dias_semana": dias_semana,
        "tempo_min": tempo_min,
        "dias": resumo,
    }


# ============================================================
# LEITURA
# ============================================================


@router.get(
    "",
    summary="Obter trilha ativa",
    description="Retorna a trilha ativa do usuário com suas etapas e o progresso longitudinal.",
)
def get_trilha(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    _ensure_tables(conn)
    row = conn.execute(
        "SELECT id FROM trilha WHERE user_id = ? AND ativo = 1 ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row:
        return {
            "trilha": None,
            "etapas": [],
            "progresso": None,
            "mensagem": "Nenhuma trilha ativa. Use POST /api/trilha/gerar para criar.",
        }
    return _montar_trilha(conn, row["id"], user_id)


def _montar_trilha(conn, trilha_id: int, user_id: int) -> dict:
    """Monta o payload completo da trilha (cabeçalho + etapas + progresso)."""
    cab = conn.execute(
        "SELECT id, nome, edital_nome, cargo, ativo, created_at, updated_at FROM trilha WHERE id = ? AND user_id = ?",
        (trilha_id, user_id),
    ).fetchone()
    if not cab:
        raise HTTPException(status_code=404, detail="Trilha não encontrada.")

    etapas = [
        dict(e)
        for e in conn.execute(
            """SELECT id, ordem, topico_id, materia, topico, status, desbloqueada, prerequisito_etapa_id, razao
           FROM trilha_etapas WHERE trilha_id = ? AND user_id = ? ORDER BY ordem""",
            (trilha_id, user_id),
        ).fetchall()
    ]

    total = len(etapas)
    concluidas = sum(1 for e in etapas if e["status"] == "concluida")
    atual = next((e for e in etapas if e["status"] == "atual"), None)
    pct = round(concluidas / total * 100, 1) if total else 0.0

    progresso = {
        "total_etapas": total,
        "concluidas": concluidas,
        "bloqueadas": sum(1 for e in etapas if e["status"] == "bloqueada"),
        "pct_conclusao": pct,
        "etapa_atual": atual,
        "concluida": total > 0 and concluidas == total,
    }

    return {"trilha": dict(cab), "etapas": etapas, "progresso": progresso}
