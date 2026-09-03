"""Router de Fatigue Detection intra-sessão (B3).

Detecta queda de performance DURANTE uma sessão de estudo e sugere ações.
"""
import uuid
from datetime import datetime
from statistics import median

from deps import get_user_id
from fastapi import APIRouter, Depends
from schemas import HeartbeatRequest, StartSessionRequest

from database import get_db_session

router = APIRouter(tags=["Fatigue Detection"])


@router.post("/api/sessao/iniciar", summary="Iniciar sessão de estudo",
             description="Gera um session_id único para rastrear performance intra-sessão.")
def start_session(body: StartSessionRequest, conn=Depends(get_db_session),
                  user_id: int = Depends(get_user_id)):
    session_id = str(uuid.uuid4())
    return {
        "ok": True,
        "session_id": session_id,
        "materia": body.materia,
        "tipo": body.tipo,
    }


@router.post("/api/sessao/heartbeat", summary="Heartbeat de sessão",
             description="Registra métrica de uma questão respondida e retorna análise de fadiga em tempo real.")
def session_heartbeat(body: HeartbeatRequest, conn=Depends(get_db_session),
                      user_id: int = Depends(get_user_id)):
    now = datetime.now().isoformat()

    # Gravar na session_metrics
    conn.execute(
        """INSERT INTO session_metrics (user_id, session_id, questao_num, tempo_ms, acertou, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, body.session_id, body.questao_num, body.tempo_ms, int(body.acertou), now),
    )
    conn.commit()

    # Buscar todas as metrics dessa session_id
    rows = conn.execute(
        """SELECT questao_num, tempo_ms, acertou, created_at
           FROM session_metrics
           WHERE user_id = ? AND session_id = ?
           ORDER BY questao_num ASC""",
        (user_id, body.session_id),
    ).fetchall()

    total_questoes = len(rows)
    tempos = [r[1] for r in rows]
    acertos = [r[2] for r in rows]

    # Métricas básicas
    tempo_medio_ms = sum(tempos) / total_questoes if total_questoes > 0 else 0

    # Duração total da sessão (diferença entre primeiro e último registro)
    duracao_sessao_min = 0.0
    if total_questoes >= 2:
        try:
            t_inicio = datetime.fromisoformat(rows[0][3])
            t_fim = datetime.fromisoformat(rows[-1][3])
            duracao_sessao_min = (t_fim - t_inicio).total_seconds() / 60.0
        except (ValueError, TypeError):
            pass

    # Calcular fadiga baseada em janelas
    status = "flow"
    sugestao = "Continue!"

    # Precisamos de pelo menos 8 questões para análise confiável
    if total_questoes >= 8:
        # Janela de início: primeiras 5-10 questões (usar min(10, metade))
        janela_inicio = min(10, total_questoes // 2)
        janela_fim = 5  # últimas 5

        tempos_inicio = tempos[:janela_inicio]
        tempos_recentes = tempos[-janela_fim:]
        acertos_inicio = acertos[:janela_inicio]
        acertos_recentes = acertos[-janela_fim:]

        # Usar MEDIANA de tempo (robusta a outliers): uma única questão muito
        # lenta no fim — ex.: enunciado longo, distração pontual — não deve
        # dominar a média e disparar falso positivo de fadiga.
        med_tempo_inicio = median(tempos_inicio) if tempos_inicio else 0
        med_tempo_recente = median(tempos_recentes) if tempos_recentes else 0
        # Média mantida apenas para exibição/retorno de métricas.
        avg_tempo_inicio = sum(tempos_inicio) / len(tempos_inicio)
        avg_tempo_recente = sum(tempos_recentes) / len(tempos_recentes)

        pct_acerto_inicio = (sum(acertos_inicio) / len(acertos_inicio)) * 100 if acertos_inicio else 0
        pct_acerto_recente = (sum(acertos_recentes) / len(acertos_recentes)) * 100 if acertos_recentes else 0

        # Fadiga por tempo só é confiável com amostra e duração suficientes.
        # Fadiga cognitiva real não aparece em 3 min / 8 questões. Exigimos
        # >= 12 questões E >= 10 min de sessão para considerar o sinal de tempo.
        # Além disso, aplicamos um PISO ABSOLUTO: só conta aumento de tempo se a
        # mediana recente ultrapassar 45s/questão (abaixo disso, variações são ruído).
        TEMPO_MIN_QUESTOES = 12
        TEMPO_MIN_DURACAO_MIN = 10.0
        TEMPO_PISO_ABSOLUTO_MS = 45_000

        fadiga_tempo = "ok"
        tempo_confiavel = (
            total_questoes >= TEMPO_MIN_QUESTOES
            and duracao_sessao_min >= TEMPO_MIN_DURACAO_MIN
            and med_tempo_recente >= TEMPO_PISO_ABSOLUTO_MS
        )
        if tempo_confiavel and med_tempo_inicio > 0:
            aumento_tempo = (med_tempo_recente - med_tempo_inicio) / med_tempo_inicio
            if aumento_tempo > 0.50:
                fadiga_tempo = "alta"
            elif aumento_tempo > 0.30:
                fadiga_tempo = "leve"

        # Análise de acerto (queda = fadiga)
        fadiga_acerto = "ok"
        if pct_acerto_inicio > 0:
            queda_acerto = (pct_acerto_inicio - pct_acerto_recente) / pct_acerto_inicio
            if queda_acerto > 0.35:
                fadiga_acerto = "alta"
            elif queda_acerto > 0.20:
                fadiga_acerto = "leve"

        # Determinar status final.
        # fadiga_ALTA exige CONCORDÂNCIA dos dois sinais (tempo alto E queda de
        # acerto), OU uma queda de acerto forte e isolada. O sinal de tempo
        # sozinho gera no máximo fadiga_leve — assim, acertar 80% num ritmo
        # rápido não manda o usuário "parar".
        if fadiga_acerto == "alta" and fadiga_tempo in ("alta", "leve"):
            status = "fadiga_alta"
            sugestao = "Encerre e descanse"
        elif fadiga_acerto == "alta":
            # Queda de acerto forte isolada → alerta alto (sinal mais fiável de fadiga)
            status = "fadiga_alta"
            sugestao = "Encerre e descanse"
        elif fadiga_tempo == "alta" or fadiga_acerto == "leve" or fadiga_tempo == "leve":
            status = "fadiga_leve"
            sugestao = "Pause 5min"
    else:
        # Valores placeholder quando ainda não há dados suficientes
        janela_inicio = min(total_questoes, 5)
        tempos_inicio = tempos[:janela_inicio] if janela_inicio > 0 else tempos
        acertos_inicio = acertos[:janela_inicio] if janela_inicio > 0 else acertos
        tempos_recentes = tempos[-5:] if total_questoes >= 5 else tempos
        acertos_recentes = acertos[-5:] if total_questoes >= 5 else acertos

        avg_tempo_inicio = sum(tempos_inicio) / len(tempos_inicio) if tempos_inicio else 0
        avg_tempo_recente = sum(tempos_recentes) / len(tempos_recentes) if tempos_recentes else 0
        pct_acerto_inicio = (sum(acertos_inicio) / len(acertos_inicio)) * 100 if acertos_inicio else 0
        pct_acerto_recente = (sum(acertos_recentes) / len(acertos_recentes)) * 100 if acertos_recentes else 0

    # Tempo total > 60min sem pausa → fadiga moderada (somente se não já detectou alta)
    if duracao_sessao_min > 60 and status == "flow" or duracao_sessao_min > 60 and status == "fadiga_leve":
        status = "fadiga_moderada"
        sugestao = "Troque de matéria"

    return {
        "status": status,
        "metricas": {
            "questoes_respondidas": total_questoes,
            "tempo_medio_ms": round(tempo_medio_ms, 1),
            "tempo_medio_inicio_ms": round(avg_tempo_inicio, 1),
            "tempo_medio_recente_ms": round(avg_tempo_recente, 1),
            "pct_acerto_recente": round(pct_acerto_recente, 1),
            "pct_acerto_inicio": round(pct_acerto_inicio, 1),
            "duracao_sessao_min": round(duracao_sessao_min, 1),
        },
        "sugestao": sugestao,
    }


@router.get("/api/sessao/{session_id}/resumo", summary="Resumo da sessão",
            description="Retorna resumo completo de uma sessão: total, acertos, tempos, pico e queda de performance.")
def session_summary(session_id: str, conn=Depends(get_db_session),
                    user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        """SELECT questao_num, tempo_ms, acertou, created_at
           FROM session_metrics
           WHERE user_id = ? AND session_id = ?
           ORDER BY questao_num ASC""",
        (user_id, session_id),
    ).fetchall()

    if not rows:
        return {"ok": False, "message": "Sessão não encontrada"}

    total_questoes = len(rows)
    acertos = sum(1 for r in rows if r[2] == 1)
    tempos = [r[1] for r in rows]
    tempo_medio = sum(tempos) / total_questoes

    # Duração total
    duracao_total_min = 0.0
    if total_questoes >= 2:
        try:
            t_inicio = datetime.fromisoformat(rows[0][3])
            t_fim = datetime.fromisoformat(rows[-1][3])
            duracao_total_min = (t_fim - t_inicio).total_seconds() / 60.0
        except (ValueError, TypeError):
            pass

    # Pico de performance: questão com menor tempo E acerto
    pico_performance = None
    melhor_tempo = float("inf")
    for r in rows:
        if r[2] == 1 and r[1] < melhor_tempo:
            melhor_tempo = r[1]
            pico_performance = r[0]

    # Detecção de queda: primeira questão onde moving avg(5) > 150% da avg das primeiras 5
    queda_detectada_em = None
    if total_questoes >= 8:
        avg_inicio = sum(tempos[:5]) / 5
        for i in range(5, total_questoes):
            window_start = max(0, i - 4)
            moving_avg = sum(tempos[window_start:i + 1]) / (i + 1 - window_start)
            if avg_inicio > 0 and moving_avg > avg_inicio * 1.5:
                queda_detectada_em = rows[i][0]
                break

    return {
        "ok": True,
        "session_id": session_id,
        "total_questoes": total_questoes,
        "acertos": acertos,
        "percentual_acerto": round((acertos / total_questoes) * 100, 1) if total_questoes > 0 else 0,
        "tempo_medio_ms": round(tempo_medio, 1),
        "pico_performance": pico_performance,
        "queda_detectada_em": queda_detectada_em,
        "duracao_total_min": round(duracao_total_min, 1),
    }
