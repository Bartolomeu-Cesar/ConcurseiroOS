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


def _topicos_ordenados(conn, user_id: int, materias):
    """Ordena os tópicos do edital respeitando pré-requisitos (topic_dependencies).

    Fallback quando não há dependências: interleaving (round-robin) por matéria,
    preservando a ordem do edital dentro de cada matéria.
    """
    query = "SELECT id, materia, topico, status FROM edital WHERE arquivado = 0 AND user_id = ?"
    params = [user_id]
    if materias:
        placeholders = ",".join("?" * len(materias))
        query += f" AND materia IN ({placeholders})"
        params.extend(materias)
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
    topicos = _topicos_ordenados(conn, user_id, materias)

    if not topicos:
        raise HTTPException(
            status_code=400,
            detail="Nenhum tópico no edital para gerar a trilha. Adicione tópicos ao edital primeiro.",
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
    agora = today_str()
    xp_topico = 0

    # Só concede XP se ainda não estava concluída (evita XP duplicado ao reconcluir)
    ja_concluida = etapa["status"] == "concluida"

    # 1. Marca o tópico do edital como Concluído (fonte da verdade p/ XP e progresso)
    if etapa["topico_id"]:
        conn.execute(
            "UPDATE edital SET status = 'Concluído', mastery_updated_at = ? WHERE id = ? AND user_id = ?",
            (agora, etapa["topico_id"], user_id),
        )
        if not ja_concluida:
            xp_topico = XP_PER_TOPICO

    # 2. Marca a etapa como concluída
    conn.execute(
        "UPDATE trilha_etapas SET status = 'concluida', desbloqueada = 1 WHERE id = ? AND user_id = ?",
        (etapa_id, user_id),
    )

    # 3. Desbloqueia a próxima etapa não-concluída da sequência → vira 'atual'
    proxima = conn.execute(
        """SELECT id FROM trilha_etapas
           WHERE trilha_id = ? AND user_id = ? AND ordem > ? AND status != 'concluida'
           ORDER BY ordem LIMIT 1""",
        (trilha_id, user_id, etapa["ordem"]),
    ).fetchone()
    if proxima:
        conn.execute(
            "UPDATE trilha_etapas SET status = 'atual', desbloqueada = 1 WHERE id = ? AND user_id = ?",
            (proxima["id"], user_id),
        )

    conn.execute("UPDATE trilha SET updated_at = ? WHERE id = ? AND user_id = ?", (agora, trilha_id, user_id))
    conn.commit()
    log.info(f"Trilha etapa concluída: etapa={etapa_id}, trilha={trilha_id}, xp={xp_topico}")

    resultado = _montar_trilha(conn, trilha_id, user_id)
    resultado["xp_topico"] = xp_topico
    return resultado


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
