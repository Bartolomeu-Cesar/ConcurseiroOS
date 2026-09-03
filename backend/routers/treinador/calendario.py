"""Endpoint do Calendário Semanal — GET /api/calendario-semanal."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from database import get_db_session
from deps import get_user_id
from logger import log

from .analise import (
    _get_last_session_by_subject,
    _get_pending_reviews,
    _get_performance_by_subject,
)

router = APIRouter(prefix="", tags=["Treinador Inteligente"])

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _planejador_desalinhado(conn, user_id: int) -> bool:
    """True se o planejador_semanal não corresponde mais ao ciclo ativo atual.

    Detecta o caso em que o usuário trocou de concurso/ciclo mas o calendário
    ficou preso a um planejamento antigo (de outro edital). Comparamos os
    conjuntos de matérias: se o planejador contém matérias que não estão no
    ciclo ativo, OU deixa de fora matérias do ciclo, consideramos desalinhado.

    Só avalia quando há ciclo ativo (senão não há referência para comparar).
    """
    ciclo_mats = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?",
            (user_id,),
        ).fetchall()
    }
    if not ciclo_mats:
        return False  # sem ciclo ativo, não há como (nem por que) realinhar

    plan_mats = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT materia FROM planejador_semanal WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    }
    if not plan_mats:
        return False  # vazio é tratado pelo fluxo de geração normal

    # Desalinhado se os conjuntos de matérias divergem em qualquer direção.
    return plan_mats != ciclo_mats


def _get_uncompleted_topics(conn, materia: str, user_id: int, edital_nome: str = "", cargo: str = "", limit: int = 3) -> list:
    """Tópicos pendentes de uma matéria, na ORDEM da trilha ativa (Opção B).

    Mantém a distribuição de matérias por dia do calendário, mas garante que o
    tópico exibido para cada matéria seja o próximo indicado pela trilha —
    eliminando o descompasso de tópico entre trilha e calendário. Sem trilha
    ativa, cai no fallback da ordem do edital.
    """
    from routers.trilha import topicos_pendentes_por_trilha

    return topicos_pendentes_por_trilha(
        conn, user_id, materia, limit=limit, edital_nome=edital_nome, cargo=cargo
    )


def _gerar_planejador_interno(conn, user_id: int, horas_dia: float = 3.0):
    """Gera planejador internamente (sem HTTP). Cascata: gera ciclo se necessário."""
    from routers.ciclo import _gerar_ciclo_automatico

    ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()
    if not ciclo:
        _gerar_ciclo_automatico(conn, user_id, horas_dia)
        ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()
    if not ciclo:
        return

    materias_scored = []
    for c in ciclo:
        mat = c["materia"]
        desemp = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id WHERE q.materia = ? AND qr.user_id = ?
        """, (mat, user_id)).fetchone()
        total_q = desemp[0] or 0
        pct_acerto = (desemp[1] / total_q * 100) if total_q > 0 else 0
        horas_estudadas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ? AND user_id = ?", (mat, user_id)).fetchone()[0]
        pendentes = conn.execute("SELECT COUNT(*) FROM edital WHERE materia = ? AND status != 'Concluído' AND arquivado = 0 AND user_id = ?", (mat, user_id)).fetchone()[0]
        ultima = conn.execute("SELECT MAX(data) FROM sessoes_estudo WHERE materia = ? AND user_id = ?", (mat, user_id)).fetchone()[0]
        try:
            dias_sem = (date.today() - date.fromisoformat(ultima)).days if ultima else 999
        except (ValueError, TypeError):
            dias_sem = 30

        score = (100 - pct_acerto) * 0.35 + min(pendentes * 2, 25) + c["horas_alvo"] * 5
        if horas_estudadas < c["horas_alvo"] * 2:
            score += 10
        if dias_sem >= 999:
            score += 15
        elif dias_sem >= 7:
            score += 8
        if total_q == 0:
            score += 8
        materias_scored.append({"materia": mat, "score": score, "horas_alvo": c["horas_alvo"], "pct_acerto": pct_acerto})

    materias_scored.sort(key=lambda x: -x["score"])
    total_mats = len(materias_scored)
    for i, m in enumerate(materias_scored):
        pos = i / max(total_mats, 1)
        m["freq"] = 3 if pos < 0.3 else 2 if pos < 0.65 else 1

    SLOTS_POR_DIA = [3, 2, 3, 2, 3, 2]
    dias = [[] for _ in range(7)]
    pool = []
    for m in materias_scored:
        pool.extend([m] * m["freq"])

    last_day_materias = set()
    pool_idx = 0
    for dia in range(6):
        target = SLOTS_POR_DIA[dia]
        used_today = set()
        attempts = 0
        search_idx = pool_idx
        while len(dias[dia]) < target and attempts < len(pool) * 3:
            if not pool:
                break
            candidate = pool[search_idx % len(pool)]
            if candidate["materia"] not in last_day_materias and candidate["materia"] not in used_today:
                horas_slot = round(horas_dia / target, 1)
                if candidate["score"] > 50:
                    horas_slot = round(horas_slot * 1.2, 1)
                horas_slot = min(2.0, max(0.5, horas_slot))
                dias[dia].append({"materia": candidate["materia"], "horas": horas_slot})
                used_today.add(candidate["materia"])
                pool_idx = (search_idx + 1) % len(pool)
            search_idx += 1
            attempts += 1
        if len(dias[dia]) < target:
            for m in materias_scored:
                if m["materia"] not in used_today:
                    dias[dia].append({"materia": m["materia"], "horas": round(horas_dia / target, 1)})
                    used_today.add(m["materia"])
                    if len(dias[dia]) >= target:
                        break
        last_day_materias = used_today

    for m in materias_scored[:2]:
        dias[6].append({"materia": m["materia"], "horas": 0.5})

    conn.execute("DELETE FROM planejador_semanal WHERE user_id = ?", (user_id,))
    for dia_idx, slots in enumerate(dias):
        for slot in slots:
            conn.execute("INSERT INTO planejador_semanal (dia_semana, materia, horas, user_id) VALUES (?, ?, ?, ?)",
                         (dia_idx, slot["materia"], slot["horas"], user_id))
    conn.commit()


@router.get("/api/calendario-semanal", summary="Calendário Semanal",
            description="Gera calendário semanal de estudos distribuindo matérias ao longo dos dias. Considera progresso no edital, desempenho e configuração de horas por dia.")
def calendario_semanal(edital_nome: str = "", cargo: str = "", horas_dia: float = Query(default=3.0), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera calendário semanal de estudos."""
    tempo_dia_min = int(horas_dia * 60)

    planejador = conn.execute("SELECT * FROM planejador_semanal WHERE user_id = ? ORDER BY dia_semana, id", (user_id,)).fetchall()
    planejador_gerado = False
    # Regenera se estiver vazio OU desalinhado do ciclo ativo (ex.: usuário trocou
    # de concurso e o planejador ficou preso ao edital antigo).
    if not planejador or _planejador_desalinhado(conn, user_id):
        _gerar_planejador_interno(conn, user_id, horas_dia)
        planejador = conn.execute("SELECT * FROM planejador_semanal WHERE user_id = ? ORDER BY dia_semana, id", (user_id,)).fetchall()
        planejador_gerado = True

    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())

    if not planejador:
        return {
            "semana_inicio": inicio_semana.isoformat(),
            "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
            "horas_dia": horas_dia, "planejador_gerado": False,
            "dias": [{"dia_semana": i, "nome": NOMES_DIAS[i],
                      "data": (inicio_semana + timedelta(days=i)).isoformat(),
                      "atividades": [{"tipo": "revisao", "descricao": "Adicione matérias ao edital para gerar o calendário", "tempo_min": 0, "materia": None}],
                      "tempo_total_min": 0, "materias": []} for i in range(7)],
            "resumo": {"total_materias": 0, "horas_semana": 0, "distribuicao": []}
        }

    plan_por_dia = {i: [] for i in range(7)}
    for p in planejador:
        plan_por_dia[p["dia_semana"]].append({"materia": p["materia"], "horas": p["horas"]})

    desempenho = _get_performance_by_subject(conn, user_id)
    pending = _get_pending_reviews(conn, user_id)

    dias = []
    distribuicao_map = {}

    for day_idx in range(7):
        data_dia = inicio_semana + timedelta(days=day_idx)
        atividades = []
        tempo_restante = tempo_dia_min
        materias_do_dia = []
        is_domingo = day_idx == 6

        if pending["flashcards"] > 0:
            tempo_flash = min(10, tempo_restante)
            atividades.append({"tipo": "revisao", "descricao": f"Revisar {pending['flashcards']} flashcards pendentes", "tempo_min": tempo_flash, "materia": None})
            tempo_restante -= tempo_flash

        day_plan = plan_por_dia.get(day_idx, [])

        if is_domingo and not day_plan:
            if pending["topicos"] > 0:
                tempo_top = min(15, tempo_restante)
                atividades.append({"tipo": "revisao", "descricao": f"Revisar {pending['topicos']} tópicos com baixa retenção", "tempo_min": tempo_top, "materia": None})
                tempo_restante -= tempo_top
            if tempo_restante >= 10:
                atividades.append({"tipo": "revisao", "descricao": "Revisão geral da semana", "tempo_min": min(15, tempo_restante), "materia": None})
        elif day_plan:
            tempo_revisao_final = 10
            tempo_para_materias = tempo_restante - tempo_revisao_final

            for slot in day_plan:
                if tempo_para_materias <= 0:
                    break
                materia_nome = slot["materia"]
                materias_do_dia.append(materia_nome)
                if materia_nome not in distribuicao_map:
                    distribuicao_map[materia_nome] = {"dias": [], "tempo_total": 0}
                distribuicao_map[materia_nome]["dias"].append(day_idx)

                total_horas_dia = sum(s["horas"] for s in day_plan) or 1
                proporcao = slot["horas"] / total_horas_dia
                tempo_materia = int(tempo_para_materias * proporcao)

                topicos = _get_uncompleted_topics(conn, materia_nome, user_id, edital_nome, cargo, limit=3)
                if not topicos:
                    topicos = ["Revisão geral"]

                perf = desempenho.get(materia_nome, {})
                pct = perf.get("pct", 0)
                if pct < 50 and perf.get("total", 0) > 0:
                    tempo_estudo = int(tempo_materia * 0.45)
                    tempo_questoes = int(tempo_materia * 0.45)
                elif pct > 80:
                    tempo_estudo = int(tempo_materia * 0.7)
                    tempo_questoes = int(tempo_materia * 0.2)
                else:
                    tempo_estudo = int(tempo_materia * 0.6)
                    tempo_questoes = int(tempo_materia * 0.3)

                if tempo_estudo >= 15:
                    atividades.append({"tipo": "estudo", "materia": materia_nome, "topicos": topicos, "tempo_min": tempo_estudo})
                if tempo_questoes >= 10:
                    qtd_questoes = max(5, tempo_questoes // 2)
                    atividades.append({"tipo": "questoes", "materia": materia_nome, "qtd": qtd_questoes, "tempo_min": tempo_questoes})

                distribuicao_map[materia_nome]["tempo_total"] += tempo_estudo + tempo_questoes
                tempo_para_materias -= (tempo_estudo + tempo_questoes)

            if tempo_revisao_final > 0:
                atividades.append({"tipo": "revisao", "descricao": "Resumo do dia (Técnica Feynman)", "tempo_min": tempo_revisao_final, "materia": None})

        tempo_total_dia = sum(a["tempo_min"] for a in atividades)
        dias.append({"dia_semana": day_idx, "nome": NOMES_DIAS[day_idx], "data": data_dia.isoformat(),
                     "atividades": atividades, "tempo_total_min": tempo_total_dia, "materias": materias_do_dia})

    distribuicao = []
    for materia, info in distribuicao_map.items():
        tempo_total_materia = sum(a["tempo_min"] for d in dias for a in d["atividades"] if a.get("materia") == materia)
        distribuicao.append({"materia": materia, "dias": sorted(set(info["dias"])), "horas_semana": round(tempo_total_materia / 60, 1)})
    distribuicao.sort(key=lambda x: -x["horas_semana"])

    horas_semana_total = round(sum(d["tempo_total_min"] for d in dias) / 60, 1)
    total_materias = len(set(m for d in dias for m in d["materias"]))

    log.info(f"Calendário semanal gerado: {total_materias} matérias, {horas_semana_total}h/semana")
    return {
        "semana_inicio": inicio_semana.isoformat(),
        "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
        "horas_dia": horas_dia, "planejador_gerado": planejador_gerado,
        "dias": dias,
        "resumo": {"total_materias": total_materias, "horas_semana": horas_semana_total, "distribuicao": distribuicao}
    }
