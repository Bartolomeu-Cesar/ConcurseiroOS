"""Retrieval-Induced Forgetting (RIF) — alerta de scheduling.

Evidência: Anderson, Bjork & Bjork (1994) — recuperar seletivamente um subconjunto
de itens de uma categoria pode SUPRIMIR temporariamente a lembrança dos itens
"irmãos" relacionados que não foram praticados. Aplicação prática (não uma técnica
de treino, mas um ALERTA): dentro de uma mesma matéria, tópicos muito menos
praticados que os "irmãos" dominantes podem estar sendo prejudicados.

Endpoint READ-ONLY: aponta, por matéria do ciclo ATIVO, os tópicos negligenciados
relativamente aos mais praticados, sugerindo reequilibrar a prática.
Regra do projeto: recomendações filtram por ciclo_estudos WHERE ativo = 1.
"""

from deps import get_user_id
from fastapi import APIRouter, Depends

from database import get_db_session

router = APIRouter(prefix="", tags=["Study Intelligence"])


@router.get(
    "/api/study-intelligence/retrieval-induced-forgetting",
    summary="Alerta de Retrieval-Induced Forgetting",
    description="""Detecta tópicos negligenciados dentro de matérias do ciclo ATIVO: quando alguns
tópicos são muito praticados e seus "irmãos" (mesma matéria) quase não, os últimos
podem sofrer supressão por recuperação seletiva (RIF). Sugere reequilibrar a prática.
Read-only — não altera dados.""",
)
def retrieval_induced_forgetting(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    # Prática por matéria+tópico (nº de respostas) — só matérias do ciclo ATIVO.
    rows = conn.execute(
        """
        SELECT q.materia AS materia, COALESCE(NULLIF(q.topico, ''), '(sem tópico)') AS topico,
               COUNT(*) AS praticas
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id AND q.user_id = qr.user_id
        WHERE qr.user_id = ?
          AND q.materia IN (SELECT materia FROM ciclo_estudos WHERE user_id = ? AND ativo = 1)
        GROUP BY q.materia, topico
        """,
        (user_id, user_id),
    ).fetchall()

    # Agrupar por matéria.
    por_materia: dict[str, list] = {}
    for r in rows:
        por_materia.setdefault(r["materia"], []).append({"topico": r["topico"], "praticas": r["praticas"]})

    alertas = []
    for materia, topicos in por_materia.items():
        if len(topicos) < 2:
            continue  # precisa de "irmãos" para haver supressão relativa
        max_praticas = max(t["praticas"] for t in topicos)
        if max_praticas < 3:
            continue  # prática dominante ainda incipiente — sem sinal confiável
        for t in topicos:
            # Negligenciado = praticado <= 25% do irmão mais praticado.
            if t["praticas"] <= max(1, max_praticas * 0.25):
                alertas.append(
                    {
                        "materia": materia,
                        "topico": t["topico"],
                        "praticas": t["praticas"],
                        "praticas_dominante": max_praticas,
                        "sugestao": f"Pratique '{t['topico']}' — está sendo ofuscado por tópicos irmãos muito mais treinados.",
                    }
                )

    # Ordenar pelos mais desbalanceados (maior gap relativo primeiro).
    alertas.sort(key=lambda a: a["praticas"] / max(1, a["praticas_dominante"]))

    return {
        "total_alertas": len(alertas),
        "alertas": alertas[:15],
        "tecnica": "Retrieval-Induced Forgetting (Anderson 1994): praticar seletivamente parte de uma "
        "matéria pode suprimir os tópicos irmãos não praticados. Reequilibre para proteger a memória deles.",
        "mensagem": "✅ Prática equilibrada entre os tópicos das matérias ativas."
        if not alertas
        else f"⚠️ {len(alertas)} tópico(s) podem estar sofrendo supressão por falta de prática relativa.",
    }
