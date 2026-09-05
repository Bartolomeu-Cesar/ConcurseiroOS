"""Knowledge Graph — Mapa de dependências entre tópicos do edital.

Permite modelar relações de pré-requisito, temas relacionados e progressão
entre tópicos. Oferece sugestões automáticas baseadas em heurísticas.
"""
from datetime import datetime

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from database import get_db_session

router = APIRouter(prefix="/api/knowledge-graph", tags=["Knowledge Graph"])

RELATIONSHIP_TYPES = ["prerequisite", "related", "builds_on"]


def _ensure_table(conn):
    """Garante que a tabela existe (compat com DBs sem migration)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topic_dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            depends_on_id INTEGER NOT NULL,
            relationship TEXT NOT NULL DEFAULT 'prerequisite',
            user_id INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (topic_id) REFERENCES edital(id),
            FOREIGN KEY (depends_on_id) REFERENCES edital(id)
        )
    """)


# ============================================================
# CRUD
# ============================================================

@router.get("", summary="Grafo completo de dependências",
            description="Retorna nodes (tópicos) e edges (dependências) para visualização.")
def get_graph(
    materia: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna o grafo de dependências do usuário."""
    _ensure_table(conn)

    # Nodes: tópicos do edital
    query_nodes = "SELECT id, materia, topico, status FROM edital WHERE arquivado = 0 AND user_id = ?"
    params_nodes = [user_id]
    if materia:
        query_nodes += " AND materia = ?"
        params_nodes.append(materia)

    nodes = [dict(r) for r in conn.execute(query_nodes, params_nodes).fetchall()]

    # Edges: dependências
    node_ids = [n["id"] for n in nodes]
    if not node_ids:
        return {"nodes": [], "edges": [], "stats": {"total_nodes": 0, "total_edges": 0}}

    placeholders = ",".join("?" * len(node_ids))
    edges_rows = conn.execute(f"""
        SELECT id, topic_id, depends_on_id, relationship
        FROM topic_dependencies
        WHERE user_id = ? AND (topic_id IN ({placeholders}) OR depends_on_id IN ({placeholders}))
    """, [user_id] + node_ids + node_ids).fetchall()

    edges = [dict(r) for r in edges_rows]

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
    }


@router.post("/edges", summary="Criar dependência entre tópicos")
def create_edge(
    topic_id: int = Body(..., embed=True),
    depends_on_id: int = Body(..., embed=True),
    relationship: str = Body("prerequisite", embed=True),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Cria uma relação de dependência entre dois tópicos."""
    _ensure_table(conn)

    if relationship not in RELATIONSHIP_TYPES:
        raise HTTPException(400, f"Tipo inválido. Válidos: {', '.join(RELATIONSHIP_TYPES)}")

    if topic_id == depends_on_id:
        raise HTTPException(400, "Um tópico não pode depender de si mesmo")

    # Verificar que ambos existem e pertencem ao user
    t1 = conn.execute("SELECT id FROM edital WHERE id = ? AND user_id = ?", (topic_id, user_id)).fetchone()
    t2 = conn.execute("SELECT id FROM edital WHERE id = ? AND user_id = ?", (depends_on_id, user_id)).fetchone()
    if not t1 or not t2:
        raise HTTPException(404, "Tópico não encontrado")

    # Verificar duplicata
    existing = conn.execute(
        "SELECT id FROM topic_dependencies WHERE topic_id = ? AND depends_on_id = ? AND user_id = ?",
        (topic_id, depends_on_id, user_id)
    ).fetchone()
    if existing:
        # Atualizar tipo
        conn.execute("UPDATE topic_dependencies SET relationship = ? WHERE id = ?", (relationship, existing["id"]))
        conn.commit()
        return {"ok": True, "id": existing["id"], "updated": True}

    # Verificar ciclo (A→B e B→A)
    reverse = conn.execute(
        "SELECT id FROM topic_dependencies WHERE topic_id = ? AND depends_on_id = ? AND user_id = ?",
        (depends_on_id, topic_id, user_id)
    ).fetchone()
    if reverse and relationship == "prerequisite":
        raise HTTPException(400, "Dependência circular: o tópico-alvo já é pré-requisito deste")

    cur = conn.execute(
        "INSERT INTO topic_dependencies (topic_id, depends_on_id, relationship, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (topic_id, depends_on_id, relationship, user_id, datetime.now().isoformat())
    )
    conn.commit()
    return {"ok": True, "id": cur.lastrowid, "updated": False}


@router.delete("/edges/{edge_id}", summary="Remover dependência")
def delete_edge(
    edge_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Remove uma relação de dependência."""
    _ensure_table(conn)
    conn.execute("DELETE FROM topic_dependencies WHERE id = ? AND user_id = ?", (edge_id, user_id))
    conn.commit()
    return {"ok": True}


@router.get("/prerequisites/{topic_id}", summary="Pré-requisitos de um tópico")
def get_prerequisites(
    topic_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna a cadeia de pré-requisitos de um tópico (recursivo até 3 níveis)."""
    _ensure_table(conn)

    prerequisites = []
    visited = set()

    def _walk(tid, depth=0):
        if depth > 3 or tid in visited:
            return
        visited.add(tid)
        rows = conn.execute("""
            SELECT td.depends_on_id, td.relationship, e.materia, e.topico, e.status
            FROM topic_dependencies td
            JOIN edital e ON e.id = td.depends_on_id
            WHERE td.topic_id = ? AND td.user_id = ?
        """, (tid, user_id)).fetchall()
        for r in rows:
            prerequisites.append({
                "id": r["depends_on_id"],
                "materia": r["materia"],
                "topico": r["topico"],
                "status": r["status"],
                "relationship": r["relationship"],
                "depth": depth,
            })
            if r["relationship"] == "prerequisite":
                _walk(r["depends_on_id"], depth + 1)

    _walk(topic_id)

    # Status geral
    all_done = all(p["status"] == "Concluído" for p in prerequisites) if prerequisites else True

    return {
        "topic_id": topic_id,
        "prerequisites": prerequisites,
        "total": len(prerequisites),
        "all_completed": all_done,
    }


# ============================================================
# SUGESTÃO AUTOMÁTICA
# ============================================================

@router.get("/suggest", summary="Sugerir dependências automaticamente",
            description="Usa heurísticas para sugerir relações entre tópicos da mesma matéria.")
def suggest_dependencies(
    materia: str = Query("", description="Filtrar por matéria"),
    limit: int = Query(10, ge=1, le=50),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Sugere dependências baseado em heurísticas:
    1. Ordem no edital (tópico N depende de N-1 na mesma matéria)
    2. Padrões no nome (ex: "Avançado" depende de "Básico" na mesma matéria)
    3. Sequência numérica (Art. 1 → Art. 2)
    """
    _ensure_table(conn)

    query = "SELECT id, materia, topico FROM edital WHERE arquivado = 0 AND user_id = ?"
    params = [user_id]
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    query += " ORDER BY materia, id"

    topicos = conn.execute(query, params).fetchall()

    # Dependências já existentes
    existing = set()
    rows = conn.execute("SELECT topic_id, depends_on_id FROM topic_dependencies WHERE user_id = ?", (user_id,)).fetchall()
    for r in rows:
        existing.add((r["topic_id"], r["depends_on_id"]))

    suggestions = []

    # Heurística 1: Sequência na mesma matéria (tópico i depende de i-1)
    by_materia = {}
    for t in topicos:
        mat = t["materia"]
        if mat not in by_materia:
            by_materia[mat] = []
        by_materia[mat].append(dict(t))

    for mat, items in by_materia.items():
        if len(items) < 2:
            continue
        for i in range(1, len(items)):
            pair = (items[i]["id"], items[i - 1]["id"])
            if pair not in existing:
                suggestions.append({
                    "topic_id": items[i]["id"],
                    "topic_name": items[i]["topico"],
                    "depends_on_id": items[i - 1]["id"],
                    "depends_on_name": items[i - 1]["topico"],
                    "materia": mat,
                    "relationship": "prerequisite",
                    "reason": "Sequência no edital",
                    "confidence": 0.6,
                })

    # Heurística 2: Padrões de nome (Básico/Avançado, Parte I/II, Introdução/Aprofundamento)
    advanced_keywords = ["avançad", "aprofundament", "especial", "parte ii", "parte 2", "complementar"]
    basic_keywords = ["básic", "introdução", "noções", "fundament", "princípio", "parte i", "parte 1", "geral"]

    for mat, items in by_materia.items():
        basics = [t for t in items if any(kw in t["topico"].lower() for kw in basic_keywords)]
        advanceds = [t for t in items if any(kw in t["topico"].lower() for kw in advanced_keywords)]

        for adv in advanceds:
            for bas in basics:
                pair = (adv["id"], bas["id"])
                if pair not in existing and adv["id"] != bas["id"]:
                    suggestions.append({
                        "topic_id": adv["id"],
                        "topic_name": adv["topico"],
                        "depends_on_id": bas["id"],
                        "depends_on_name": bas["topico"],
                        "materia": mat,
                        "relationship": "prerequisite",
                        "reason": "Padrão nome (avançado → básico)",
                        "confidence": 0.8,
                    })

    # Ordenar por confiança e limitar
    suggestions.sort(key=lambda s: -s["confidence"])
    return {"suggestions": suggestions[:limit], "total_available": len(suggestions)}


# ============================================================
# ORDEM ÓTIMA DE ESTUDO (Topological Sort + Scoring)
# ============================================================

@router.get("/optimal-order", summary="Ordem ótima de estudo",
            description="""Calcula a ordem ideal para estudar os tópicos baseado em:
1. Pré-requisitos (topological sort): não estude X antes de dominar Y
2. Urgência (dias sem estudar, flashcards pendentes)
3. Impacto (peso da matéria no edital, questões disponíveis)
4. Status atual (priorizar não-iniciados com pré-requisitos satisfeitos)

Retorna lista ordenada de tópicos com razão da priorização.""")
def optimal_study_order(
    materia: str = Query("", description="Filtrar por matéria (vazio = todas)"),
    limit: int = Query(20, ge=5, le=50),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Calcula ordem ótima de estudo considerando dependências e performance."""
    _ensure_table(conn)

    # Buscar tópicos
    query = "SELECT id, materia, topico, status, horas_estudadas FROM edital WHERE arquivado = 0 AND user_id = ?"
    params = [user_id]
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    query += " ORDER BY materia, id"

    topicos = conn.execute(query, params).fetchall()
    if not topicos:
        return {"ordem": [], "mensagem": "Nenhum tópico no edital."}

    topicos_map = {t["id"]: dict(t) for t in topicos}
    topico_ids = set(topicos_map.keys())

    # Buscar dependências (prerequisite)
    deps = conn.execute("""
        SELECT topic_id, depends_on_id FROM topic_dependencies
        WHERE user_id = ? AND relationship = 'prerequisite'
    """, (user_id,)).fetchall()

    # Construir grafo de dependências
    dependencias = {}  # topic_id → [depends_on_ids]
    dependentes = {}   # depends_on_id → [topic_ids que dependem dele]
    for d in deps:
        tid = d["topic_id"]
        dep_id = d["depends_on_id"]
        if tid in topico_ids and dep_id in topico_ids:
            dependencias.setdefault(tid, []).append(dep_id)
            dependentes.setdefault(dep_id, []).append(tid)

    # Topological sort (Kahn's algorithm)
    in_degree = {tid: 0 for tid in topico_ids}
    for tid, deps_list in dependencias.items():
        in_degree[tid] = len(deps_list)

    # Queue: tópicos sem pré-requisitos pendentes (in_degree = 0)
    # Mas só se os pré-requisitos estão concluídos
    queue = []
    blocked = []

    for tid in topico_ids:
        if in_degree[tid] == 0:
            queue.append(tid)
        else:
            # Verificar se pré-requisitos estão concluídos
            prereqs = dependencias.get(tid, [])
            all_done = all(topicos_map.get(p, {}).get("status") == "Concluído" for p in prereqs)
            if all_done:
                queue.append(tid)
            else:
                blocked.append(tid)

    # Scoring para priorização dentro de cada nível do grafo
    def _score_topico(tid):
        t = topicos_map[tid]
        score = 0

        # Status: não iniciado > em andamento > concluído
        if t["status"] == "Não iniciado":
            score += 30
        elif t["status"] == "Em andamento":
            score += 20
        elif t["status"] == "Concluído":
            score += 0

        # Quantos tópicos dependem deste (impacto de desbloqueio)
        desbloqueios = len(dependentes.get(tid, []))
        score += desbloqueios * 15  # Cada tópico desbloqueado = +15

        # Horas estudadas (menos estudo = mais prioridade)
        horas = t.get("horas_estudadas") or 0
        if horas == 0:
            score += 10
        elif horas < 1:
            score += 5

        return score

    # Ordenar queue por score (maior primeiro)
    queue.sort(key=lambda tid: -_score_topico(tid))

    # Gerar lista ordenada
    ordem = []
    visited = set()

    for tid in queue:
        if tid in visited:
            continue
        visited.add(tid)
        t = topicos_map[tid]
        prereqs = dependencias.get(tid, [])
        prereqs_status = [
            {"topico": topicos_map[p]["topico"], "status": topicos_map[p]["status"]}
            for p in prereqs if p in topicos_map
        ]

        # Razão da priorização
        razoes = []
        if not prereqs:
            razoes.append("Sem pré-requisitos (pode começar agora)")
        elif all(topicos_map.get(p, {}).get("status") == "Concluído" for p in prereqs):
            razoes.append("Pré-requisitos satisfeitos ✅")

        desbloqueios = len(dependentes.get(tid, []))
        if desbloqueios > 0:
            razoes.append(f"Desbloqueia {desbloqueios} tópico(s) ao concluir")

        if t["status"] == "Não iniciado":
            razoes.append("Ainda não iniciado")
        elif t["status"] == "Em andamento":
            razoes.append("Em andamento — continue")

        ordem.append({
            "posicao": len(ordem) + 1,
            "id": tid,
            "materia": t["materia"],
            "topico": t["topico"],
            "status": t["status"],
            "horas_estudadas": t.get("horas_estudadas") or 0,
            "score": _score_topico(tid),
            "prerequisites": prereqs_status,
            "desbloqueios": desbloqueios,
            "razao": " · ".join(razoes),
        })

    # Adicionar bloqueados no final (com aviso)
    for tid in blocked:
        if tid in visited:
            continue
        t = topicos_map[tid]
        prereqs = dependencias.get(tid, [])
        prereqs_nao_concluidos = [
            topicos_map[p]["topico"]
            for p in prereqs
            if p in topicos_map and topicos_map[p]["status"] != "Concluído"
        ]

        ordem.append({
            "posicao": len(ordem) + 1,
            "id": tid,
            "materia": t["materia"],
            "topico": t["topico"],
            "status": t["status"],
            "horas_estudadas": t.get("horas_estudadas") or 0,
            "score": 0,
            "prerequisites": [{"topico": topicos_map[p]["topico"], "status": topicos_map[p]["status"]} for p in prereqs if p in topicos_map],
            "desbloqueios": len(dependentes.get(tid, [])),
            "razao": f"⚠️ BLOQUEADO: conclua primeiro: {', '.join(prereqs_nao_concluidos[:3])}",
            "bloqueado": True,
        })

    return {
        "ordem": ordem[:limit],
        "total_topicos": len(topicos_map),
        "total_desbloqueados": len(queue),
        "total_bloqueados": len(blocked),
        "mensagem": f"📊 {len(queue)} tópicos prontos para estudar, {len(blocked)} aguardando pré-requisitos.",
        "dica": "Comece pelos tópicos no topo — eles desbloqueiam outros e não têm pré-requisitos pendentes.",
        "tecnica": "Knowledge Graph + Topological Sort: estudar na ordem certa evita frustração (estudar algo que depende de conceito não dominado) e maximiza desbloqueio de conteúdo.",
    }
