"""Router do Planejador Semanal."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from models import OkResponse, PlanejadorItem

router = APIRouter(prefix="", tags=["Planejador"])


@router.get("/api/planejador")
def get_planejador(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT id, dia_semana, materia, horas FROM planejador_semanal WHERE user_id = ? ORDER BY dia_semana, id", (user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/planejador")
def add_planejador(body: PlanejadorItem, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("INSERT INTO planejador_semanal (dia_semana, materia, horas, user_id) VALUES (?, ?, ?, ?)",
                       (body.dia_semana, body.materia, body.horas, user_id))
    conn.commit()
    log.info(f"Planejador item added: {body.materia} dia {body.dia_semana}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/planejador/{id}", response_model=OkResponse)
def delete_planejador(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM planejador_semanal WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Planejador item deleted: {id}")
    return {"ok": True}


@router.post("/api/planejador/gerar", summary="Gerar planejador automaticamente",
             description="Distribui matérias do ciclo nos dias da semana com scoring inteligente")
def gerar_planejador(horas_dia: float = Query(default=3.0), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """
    Gera planejador semanal inteligente. Cascata:
    1. Verifica se há ciclo ativo → se não, gera automaticamente dos editais
    2. Distribui matérias nos dias otimizando aprendizado
    """
    # 1. Verificar ciclo ativo
    ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()

    ciclo_gerado = False
    if not ciclo:
        from routers.ciclo import _gerar_ciclo_automatico
        result = _gerar_ciclo_automatico(conn, horas_dia, user_id)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail="Não há matérias no edital para gerar o planejador")
        ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()
        ciclo_gerado = True

    # 2. Calcular scoring por matéria
    materias_scored = []
    for c in ciclo:
        mat = c["materia"]

        desemp = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE q.materia = ? AND qr.user_id = ?
        """, (mat, user_id)).fetchone()
        total_q = desemp[0] or 0
        pct_acerto = (desemp[1] / total_q * 100) if total_q > 0 else 0

        horas_estudadas = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ? AND user_id = ?", (mat, user_id)
        ).fetchone()[0]

        pendentes = conn.execute(
            "SELECT COUNT(*) FROM edital WHERE materia = ? AND status != 'Concluído' AND arquivado = 0 AND user_id = ?",
            (mat, user_id)
        ).fetchone()[0]

        ultima = conn.execute(
            "SELECT MAX(data) FROM sessoes_estudo WHERE materia = ? AND user_id = ?", (mat, user_id)
        ).fetchone()[0]
        if ultima:
            try:
                dias_sem = (date.today() - date.fromisoformat(ultima)).days
            except (ValueError, TypeError):
                dias_sem = 30
        else:
            dias_sem = 999

        score = 0.0
        score += (100 - pct_acerto) * 0.35
        score += min(pendentes * 2, 25)
        score += c["horas_alvo"] * 5
        if horas_estudadas < c["horas_alvo"] * 2:
            score += 10
        if dias_sem >= 999:
            score += 15
        elif dias_sem >= 7:
            score += 8
        elif dias_sem >= 3:
            score += 4
        if total_q == 0:
            score += 8

        materias_scored.append({
            "materia": mat,
            "score": round(score, 2),
            "horas_alvo": c["horas_alvo"],
            "pct_acerto": round(pct_acerto, 1),
            "horas_estudadas": round(horas_estudadas, 1),
            "pendentes": pendentes,
            "dias_sem": dias_sem if dias_sem < 999 else None,
        })

    # 3. Ordenar por score
    materias_scored.sort(key=lambda x: -x["score"])

    # 4. Determinar frequência semanal
    total_mats = len(materias_scored)
    for i, m in enumerate(materias_scored):
        pos_relativa = i / max(total_mats, 1)
        if pos_relativa < 0.3:
            m["freq"] = 3
        elif pos_relativa < 0.65:
            m["freq"] = 2
        else:
            m["freq"] = 1

    # 5. Distribuir nos 6 dias úteis
    DIAS_ESTUDO = 6
    SLOTS_POR_DIA = [3, 2, 3, 2, 3, 2]
    dias = [[] for _ in range(7)]

    pool = []
    for m in materias_scored:
        pool.extend([m] * m["freq"])

    last_day_materias = set()
    pool_idx = 0

    for dia in range(DIAS_ESTUDO):
        target_slots = SLOTS_POR_DIA[dia]
        used_today = set()
        attempts = 0
        search_idx = pool_idx

        while len(dias[dia]) < target_slots and attempts < len(pool) * 3:
            if not pool:
                break
            candidate = pool[search_idx % len(pool)]
            cand_name = candidate["materia"]

            if cand_name not in last_day_materias and cand_name not in used_today:
                horas_slot = round(horas_dia / target_slots, 1)
                if candidate["score"] > 50:
                    horas_slot = round(horas_slot * 1.2, 1)
                horas_slot = min(horas_slot, 2.0)
                horas_slot = max(horas_slot, 0.5)

                dias[dia].append({
                    "materia": cand_name,
                    "horas": horas_slot,
                    "score": candidate["score"],
                    "pct_acerto": candidate["pct_acerto"],
                })
                used_today.add(cand_name)
                pool_idx = (search_idx + 1) % len(pool)

            search_idx += 1
            attempts += 1

        if len(dias[dia]) < target_slots:
            for m in materias_scored:
                if m["materia"] not in used_today:
                    horas_slot = round(horas_dia / target_slots, 1)
                    dias[dia].append({
                        "materia": m["materia"],
                        "horas": horas_slot,
                        "score": m["score"],
                        "pct_acerto": m["pct_acerto"],
                    })
                    used_today.add(m["materia"])
                    if len(dias[dia]) >= target_slots:
                        break

        last_day_materias = used_today

    # Domingo: revisão leve
    weakest = materias_scored[:2] if len(materias_scored) >= 2 else materias_scored
    for m in weakest:
        dias[6].append({
            "materia": m["materia"],
            "horas": 0.5,
            "score": m["score"],
            "pct_acerto": m["pct_acerto"],
        })

    # 6. Salvar no banco
    conn.execute("DELETE FROM planejador_semanal WHERE user_id = ?", (user_id,))
    count = 0
    for dia_idx, slots in enumerate(dias):
        for slot in slots:
            conn.execute(
                "INSERT INTO planejador_semanal (dia_semana, materia, horas, user_id) VALUES (?, ?, ?, ?)",
                (dia_idx, slot["materia"], slot["horas"], user_id)
            )
            count += 1
    conn.commit()

    log.info(f"Planejador gerado: {count} slots em 7 dias (ciclo_gerado={ciclo_gerado})")

    nomes_dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    resumo_dias = []
    for i, slots in enumerate(dias):
        resumo_dias.append({
            "dia": nomes_dias[i],
            "dia_semana": i,
            "materias": [{"materia": s["materia"], "horas": s["horas"]} for s in slots],
            "horas_total": round(sum(s["horas"] for s in slots), 1),
        })

    return {
        "ok": True,
        "ciclo_gerado": ciclo_gerado,
        "total_slots": count,
        "horas_dia": horas_dia,
        "dias": resumo_dias,
        "scoring": materias_scored[:10],
    }
