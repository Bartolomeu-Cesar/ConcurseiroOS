"""Router do Calendário Personalizado e Atividades."""
import random
from datetime import date, datetime, timedelta
from typing import List

from fastapi import APIRouter, Body, Depends, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import CalendarioItem
from sanitize import sanitize_input
from schemas import (
    AtividadeConcluidaRequest,
    DesmarcarAtividadeRequest,
    RegistrarAutoavaliacaoRequest,
    ResetInteligenteRequest,
    SalvarQuestaoDissertativaRequest,
)
from utils import today_str

router = APIRouter(prefix="", tags=["Calendário"])

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ============================================================

# ============================================================
# MICRO-PLANNING: Agenda do dia com blocos de tempo
# ============================================================


def _ensure_study_prefs_table(conn):
    """Cria tabela de preferências de horário se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            hora_inicio TEXT DEFAULT '08:00',
            hora_fim TEXT DEFAULT '12:00',
            bloco_min INTEGER DEFAULT 25,
            pausa_min INTEGER DEFAULT 5,
            pausa_longa_min INTEGER DEFAULT 15,
            blocos_antes_pausa_longa INTEGER DEFAULT 4,
            dias_estudo TEXT DEFAULT '0,1,2,3,4,5',
            updated_at TEXT DEFAULT ''
        )
    """)
    conn.commit()


@router.get("/api/calendario/preferencias")
def get_study_preferences(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna preferências de horário de estudo do usuário."""
    _ensure_study_prefs_table(conn)
    prefs = conn.execute("SELECT * FROM study_preferences WHERE user_id = ?", (user_id,)).fetchone()
    if not prefs:
        return {
            "hora_inicio": "08:00", "hora_fim": "12:00",
            "bloco_min": 25, "pausa_min": 5,
            "pausa_longa_min": 15, "blocos_antes_pausa_longa": 4,
            "dias_estudo": [0, 1, 2, 3, 4, 5],
        }
    return {
        "hora_inicio": prefs["hora_inicio"],
        "hora_fim": prefs["hora_fim"],
        "bloco_min": prefs["bloco_min"],
        "pausa_min": prefs["pausa_min"],
        "pausa_longa_min": prefs["pausa_longa_min"],
        "blocos_antes_pausa_longa": prefs["blocos_antes_pausa_longa"],
        "dias_estudo": [int(d) for d in (prefs["dias_estudo"] or "0,1,2,3,4,5").split(",")],
    }


@router.post("/api/calendario/preferencias")
def save_study_preferences(
    hora_inicio: str = Body("08:00"),
    hora_fim: str = Body("12:00"),
    bloco_min: int = Body(25),
    pausa_min: int = Body(5),
    pausa_longa_min: int = Body(15),
    blocos_antes_pausa_longa: int = Body(4),
    dias_estudo: list = Body([0, 1, 2, 3, 4, 5]),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Salvar preferências de horário de estudo."""
    _ensure_study_prefs_table(conn)
    dias_str = ",".join(str(d) for d in dias_estudo)
    conn.execute("""
        INSERT INTO study_preferences (user_id, hora_inicio, hora_fim, bloco_min, pausa_min, 
                                       pausa_longa_min, blocos_antes_pausa_longa, dias_estudo, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            hora_inicio=?, hora_fim=?, bloco_min=?, pausa_min=?,
            pausa_longa_min=?, blocos_antes_pausa_longa=?, dias_estudo=?, updated_at=?
    """, (user_id, hora_inicio, hora_fim, bloco_min, pausa_min, pausa_longa_min, blocos_antes_pausa_longa, dias_str, today_str(),
          hora_inicio, hora_fim, bloco_min, pausa_min, pausa_longa_min, blocos_antes_pausa_longa, dias_str, today_str()))
    conn.commit()
    return {"ok": True}


@router.get("/api/calendario/hoje", summary="Agenda do dia com blocos de tempo",
            description="Gera micro-planning: blocos Pomodoro sequenciais com matérias priorizadas, revisões FSRS preditivas, e pausas. Matérias difíceis no início (curva de atenção).")
def calendario_hoje(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera agenda completa do dia com blocos de tempo, revisões preditivas e pausas."""
    from routers.ciclo import _calcular_score_materia

    _ensure_study_prefs_table(conn)
    hoje = date.today()
    hoje_str = hoje.isoformat()

    # === 1. Carregar preferências ===
    prefs = conn.execute("SELECT * FROM study_preferences WHERE user_id = ?", (user_id,)).fetchone()
    hora_inicio = prefs["hora_inicio"] if prefs else "08:00"
    hora_fim = prefs["hora_fim"] if prefs else "12:00"
    bloco_min = prefs["bloco_min"] if prefs else 25
    pausa_min = prefs["pausa_min"] if prefs else 5
    pausa_longa_min = prefs["pausa_longa_min"] if prefs else 15
    blocos_antes_pausa = prefs["blocos_antes_pausa_longa"] if prefs else 4

    # Calcular tempo disponível
    h_ini, m_ini = [int(x) for x in hora_inicio.split(":")]
    h_fim, m_fim = [int(x) for x in hora_fim.split(":")]
    inicio_min = h_ini * 60 + m_ini
    fim_min = h_fim * 60 + m_fim
    if fim_min <= inicio_min:
        fim_min += 24 * 60  # Passa da meia-noite
    tempo_total_min = fim_min - inicio_min

    # === 2. Buscar matérias do ciclo ativo com score ===
    ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem", (user_id,)).fetchall()
    if not ciclo:
        return {"blocos": [], "resumo": {"tempo_total_min": 0, "mensagem": "Adicione matérias ao ciclo primeiro."}}

    materias_scored = []
    for c in ciclo:
        info = _calcular_score_materia(c["materia"], conn, user_id)
        info["horas_alvo"] = c["horas_alvo"]
        materias_scored.append(info)
    materias_scored.sort(key=lambda x: -x["score"])

    # === 3. Revisão preditiva FSRS: tópicos que vão cair abaixo de 85% de recall ===
    revisoes_preditivas = []
    try:
        # Tópicos do edital com FSRS que precisam revisão nos próximos 2 dias
        topicos_urgentes = conn.execute("""
            SELECT id, materia, topico, stability_edital, mastery_updated_at, mastery_level
            FROM edital
            WHERE user_id = ? AND arquivado = 0 AND stability_edital > 0
            AND materia IN (SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?)
            AND proxima_revisao <= ?
            ORDER BY proxima_revisao ASC
            LIMIT 8
        """, (user_id, user_id, (hoje + timedelta(days=1)).isoformat())).fetchall()

        for t in topicos_urgentes:
            revisoes_preditivas.append({
                "tipo": "revisao_preditiva",
                "materia": t["materia"],
                "topico": t["topico"],
                "descricao": f"Revisar: {t['topico']}",
                "motivo": "FSRS prediz queda de recall abaixo de 85%",
                "mastery_level": t["mastery_level"] or 0,
            })
    except Exception:
        pass

    # Flashcards pendentes agrupados por matéria
    fc_pendentes = {}
    try:
        fcs = conn.execute("""
            SELECT materia, COUNT(*) as cnt FROM flashcards
            WHERE user_id = ? AND proxima_revisao <= ?
            AND materia IN (SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?)
            GROUP BY materia ORDER BY cnt DESC
        """, (user_id, hoje_str, user_id)).fetchall()
        for fc in fcs:
            fc_pendentes[fc["materia"]] = fc["cnt"]
    except Exception:
        pass

    # === 4. Gerar blocos sequenciais ===
    blocos = []
    cursor_min = inicio_min  # Minutos desde meia-noite
    bloco_count = 0
    materias_usadas = set()

    # Estratégia de curva de atenção:
    # Início (alta atenção): matérias difíceis + teoria nova
    # Meio: questões + prática ativa
    # Final (atenção baixa): revisão leve + flashcards

    # Fase 1: Revisões preditivas urgentes (máx 2 blocos no início = retrieval primeiro)
    for rev in revisoes_preditivas[:2]:
        if cursor_min + bloco_min > fim_min:
            break
        bloco_count += 1
        h, m = divmod(cursor_min % (24*60), 60)
        blocos.append({
            "id": bloco_count,
            "hora_inicio": f"{h:02d}:{m:02d}",
            "hora_fim": f"{(h + (m + bloco_min) // 60) % 24:02d}:{(m + bloco_min) % 60:02d}",
            "duracao_min": bloco_min,
            "tipo": "revisao_preditiva",
            "materia": rev["materia"],
            "descricao": rev["descricao"],
            "motivo": rev["motivo"],
            "tecnica": "Spaced Repetition — reforço antes do esquecimento",
            "cor": "#f9e2af",
        })
        cursor_min += bloco_min
        materias_usadas.add(rev["materia"])

        # Pausa curta
        if bloco_count % blocos_antes_pausa == 0:
            h, m = divmod(cursor_min % (24*60), 60)
            blocos.append({
                "id": bloco_count + 100,
                "hora_inicio": f"{h:02d}:{m:02d}",
                "hora_fim": f"{(h + (m + pausa_longa_min) // 60) % 24:02d}:{(m + pausa_longa_min) % 60:02d}",
                "duracao_min": pausa_longa_min,
                "tipo": "pausa_longa",
                "materia": None,
                "descricao": "☕ Pausa longa — descanso + micro-retrieval",
                "motivo": "Consolidação: descanso entre blocos melhora retenção (Bjork 2011)",
                "tecnica": "Mindfulness ou revisão rápida de flashcards",
                "cor": "#a6e3a1",
            })
            cursor_min += pausa_longa_min
        else:
            h, m = divmod(cursor_min % (24*60), 60)
            blocos.append({
                "id": bloco_count + 100,
                "hora_inicio": f"{h:02d}:{m:02d}",
                "hora_fim": f"{(h + (m + pausa_min) // 60) % 24:02d}:{(m + pausa_min) % 60:02d}",
                "duracao_min": pausa_min,
                "tipo": "pausa",
                "materia": None,
                "descricao": "⏸ Pausa — respire, alongue",
                "motivo": None,
                "tecnica": None,
                "cor": "#585b70",
            })
            cursor_min += pausa_min

    # Fase 2: Matérias prioritárias (teoria/questões) — curva de atenção alta
    for m in materias_scored:
        if cursor_min + bloco_min > fim_min:
            break
        if m["materia"] in materias_usadas and len(materias_usadas) < len(materias_scored):
            continue

        bloco_count += 1
        h, mi = divmod(cursor_min % (24*60), 60)

        # Decidir tipo de atividade
        if m["total_questoes"] == 0 or m["pendentes"] > m["total_topicos"] * 0.7:
            tipo_bloco = "teoria"
            # Buscar próximo tópico concreto
            topico = conn.execute("""
                SELECT topico FROM edital WHERE materia = ? AND status != 'Concluído'
                AND arquivado = 0 AND user_id = ? ORDER BY id LIMIT 1
            """, (m["materia"], user_id)).fetchone()
            descricao = f"Estudar: {topico['topico']}" if topico else f"Avançar teoria de {m['materia']}"
            tecnica = "Elaboração ativa — resuma, explique, conecte"
            cor = "#89b4fa"
        elif m["pct_acerto"] < 60:
            tipo_bloco = "questoes"
            descricao = f"Resolver questões de {m['materia']} (foco nos erros)"
            tecnica = "Retrieval Practice + análise de erros"
            cor = "#cba6f7"
        else:
            tipo_bloco = "questoes_avancadas"
            descricao = f"Questões avançadas de {m['materia']} (elevar nível)"
            tecnica = "Desirable Difficulty — questões acima do nível atual"
            cor = "#cba6f7"

        blocos.append({
            "id": bloco_count,
            "hora_inicio": f"{h:02d}:{mi:02d}",
            "hora_fim": f"{(h + (mi + bloco_min) // 60) % 24:02d}:{(mi + bloco_min) % 60:02d}",
            "duracao_min": bloco_min,
            "tipo": tipo_bloco,
            "materia": m["materia"],
            "descricao": descricao,
            "motivo": f"Score {m['score']:.0f} | {m['pct_acerto']:.0f}% acerto | {m['pendentes']} pendentes",
            "tecnica": tecnica,
            "cor": cor,
        })
        cursor_min += bloco_min
        materias_usadas.add(m["materia"])

        # Pausa
        if cursor_min + pausa_min > fim_min:
            break
        if bloco_count % blocos_antes_pausa == 0:
            h, mi = divmod(cursor_min % (24*60), 60)
            blocos.append({
                "id": bloco_count + 100,
                "hora_inicio": f"{h:02d}:{mi:02d}",
                "hora_fim": f"{(h + (mi + pausa_longa_min) // 60) % 24:02d}:{(mi + pausa_longa_min) % 60:02d}",
                "duracao_min": pausa_longa_min,
                "tipo": "pausa_longa",
                "materia": None,
                "descricao": "☕ Pausa longa — descanso + micro-retrieval",
                "motivo": "Consolidação neural (Bjork 2011)",
                "tecnica": "Caminhe, hidrate, revise 3 flashcards",
                "cor": "#a6e3a1",
            })
            cursor_min += pausa_longa_min
        else:
            h, mi = divmod(cursor_min % (24*60), 60)
            blocos.append({
                "id": bloco_count + 100,
                "hora_inicio": f"{h:02d}:{mi:02d}",
                "hora_fim": f"{(h + (mi + pausa_min) // 60) % 24:02d}:{(mi + pausa_min) % 60:02d}",
                "duracao_min": pausa_min,
                "tipo": "pausa",
                "materia": None,
                "descricao": "⏸ Pausa",
                "motivo": None,
                "tecnica": None,
                "cor": "#585b70",
            })
            cursor_min += pausa_min

    # Fase 3: Final — revisão leve (flashcards) se sobrar tempo
    for mat, cnt in fc_pendentes.items():
        if cursor_min + bloco_min > fim_min:
            break
        if cnt == 0:
            continue
        bloco_count += 1
        h, mi = divmod(cursor_min % (24*60), 60)
        blocos.append({
            "id": bloco_count,
            "hora_inicio": f"{h:02d}:{mi:02d}",
            "hora_fim": f"{(h + (mi + bloco_min) // 60) % 24:02d}:{(mi + bloco_min) % 60:02d}",
            "duracao_min": bloco_min,
            "tipo": "flashcards",
            "materia": mat,
            "descricao": f"Revisar {min(cnt, 15)} flashcards de {mat}",
            "motivo": f"{cnt} pendentes hoje",
            "tecnica": "Spaced Repetition — atenção baixa = revisão leve ideal",
            "cor": "#f5c2e7",
        })
        cursor_min += bloco_min

        # Pausa curta final
        if cursor_min + pausa_min <= fim_min:
            h, mi = divmod(cursor_min % (24*60), 60)
            blocos.append({
                "id": bloco_count + 100,
                "hora_inicio": f"{h:02d}:{mi:02d}",
                "hora_fim": f"{(h + (mi + pausa_min) // 60) % 24:02d}:{(mi + pausa_min) % 60:02d}",
                "duracao_min": pausa_min,
                "tipo": "pausa",
                "materia": None,
                "descricao": "⏸ Pausa",
                "motivo": None,
                "tecnica": None,
                "cor": "#585b70",
            })
            cursor_min += pausa_min

    # === 5. Resumo ===
    blocos_estudo = [b for b in blocos if b["tipo"] not in ("pausa", "pausa_longa")]
    tempo_estudo = sum(b["duracao_min"] for b in blocos_estudo)
    tempo_pausas = sum(b["duracao_min"] for b in blocos if b["tipo"] in ("pausa", "pausa_longa"))

    return {
        "data": hoje_str,
        "hora_inicio": hora_inicio,
        "hora_fim": hora_fim,
        "blocos": blocos,
        "resumo": {
            "tempo_total_min": tempo_estudo + tempo_pausas,
            "tempo_estudo_min": tempo_estudo,
            "tempo_pausas_min": tempo_pausas,
            "total_blocos": len(blocos_estudo),
            "revisoes_preditivas": len([b for b in blocos if b["tipo"] == "revisao_preditiva"]),
            "materias": list(materias_usadas),
        },
        "tecnicas_aplicadas": [
            "Curva de atenção: difícil → fácil",
            "Pomodoro: blocos focados + pausas",
            "Interleaving: matérias alternadas",
            "Spaced Repetition: revisões no momento ideal",
            "Retrieval Practice: questões antes de reler",
        ],
    }


# CALENDÁRIO PERSONALIZADO
