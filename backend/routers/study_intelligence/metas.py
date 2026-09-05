"""Metas adaptativas e detecção de platô."""
from datetime import date

from deps import get_user_id
from fastapi import APIRouter, Body, Depends

from database import get_db_session

router = APIRouter(prefix="", tags=["Study Intelligence"])

# ============================================================
# #3 META ADAPTATIVA POR SEMANA
# ============================================================


@router.get("/api/metas/adaptativa", summary="Meta adaptativa baseada no ritmo real",
            description="Calcula meta semanal progressiva baseada no desempenho real. Inclui projeção de cobertura do edital e contagem regressiva até a prova.")
def meta_adaptativa(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Meta que se adapta ao ritmo real do aluno.

    Lógica:
    - Semana passada: média real de horas/questões/flashcards
    - Meta desta semana: +15% (progressão gradual)
    - Projeção: no ritmo atual, cobrirá X% do edital até a prova
    - Sugestão: para 100%, precisa aumentar para Y
    """
    import re
    from datetime import timedelta

    hoje = date.today()
    inicio_semana_passada = (hoje - timedelta(days=hoje.weekday() + 7)).isoformat()
    fim_semana_passada = (hoje - timedelta(days=hoje.weekday() + 1)).isoformat()
    inicio_esta_semana = (hoje - timedelta(days=hoje.weekday())).isoformat()

    # === Ritmo da semana passada ===
    horas_semana_passada = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ? AND data >= ? AND data <= ?",
        (user_id, inicio_semana_passada, fim_semana_passada)
    ).fetchone()[0]

    questoes_semana_passada = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ? AND data >= ? AND data <= ?",
        (user_id, inicio_semana_passada, fim_semana_passada)
    ).fetchone()[0]

    flashcards_semana_passada = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ? AND data >= ? AND data <= ?",
        (user_id, inicio_semana_passada, fim_semana_passada)
    ).fetchone()[0]

    # === Progresso desta semana (até agora) ===
    dias_passados_semana = hoje.weekday() + 1  # 1=seg, 7=dom
    horas_esta_semana = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ? AND data >= ?",
        (user_id, inicio_esta_semana)
    ).fetchone()[0]
    questoes_esta_semana = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ? AND data >= ?",
        (user_id, inicio_esta_semana)
    ).fetchone()[0]
    flashcards_esta_semana = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ? AND data >= ?",
        (user_id, inicio_esta_semana)
    ).fetchone()[0]

    # === Detectar burnout para ajustar fator de progressão ===
    burnout_risk = None
    try:
        from routers.treinador.analise import _detect_burnout
        burnout_info = _detect_burnout(conn, user_id)
        burnout_risk = burnout_info.get("risk")
    except Exception:
        pass

    # === Calcular meta adaptativa (ajustada por burnout) ===
    # Normal: +15% | Burnout moderado: -10% | Burnout alto: -25%
    if burnout_risk == "alto":
        FATOR_PROGRESSAO = 0.75  # Reduz 25% — forçar descanso
    elif burnout_risk == "moderado":
        FATOR_PROGRESSAO = 0.90  # Reduz 10% — suavizar carga
    else:
        FATOR_PROGRESSAO = 1.15  # Normal: progressão gradual

    MIN_HORAS_SEMANA = 5.0
    MIN_QUESTOES_SEMANA = 20
    MIN_FLASHCARDS_SEMANA = 10

    meta_horas = max(MIN_HORAS_SEMANA, round(horas_semana_passada * FATOR_PROGRESSAO, 1))
    meta_questoes = max(MIN_QUESTOES_SEMANA, int(questoes_semana_passada * FATOR_PROGRESSAO))
    meta_flashcards = max(MIN_FLASHCARDS_SEMANA, int(flashcards_semana_passada * FATOR_PROGRESSAO))

    # === Override manual (opcional) ===
    # Se o usuário definiu metas semanais fixas (> 0) em metas_config, elas têm
    # prioridade sobre o cálculo automático. Valor 0/ausente = mantém automático.
    origem = {"horas": "automatico", "questoes": "automatico", "flashcards": "automatico"}
    try:
        cfg = conn.execute(
            "SELECT meta_semanal_horas, meta_semanal_questoes, meta_semanal_flashcards "
            "FROM metas_config WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    except Exception:
        cfg = None  # colunas ainda não migradas
    if cfg:
        keys = cfg.keys() if hasattr(cfg, "keys") else []
        mh = cfg["meta_semanal_horas"] if "meta_semanal_horas" in keys else 0
        mq = cfg["meta_semanal_questoes"] if "meta_semanal_questoes" in keys else 0
        mf = cfg["meta_semanal_flashcards"] if "meta_semanal_flashcards" in keys else 0
        if mh and mh > 0:
            meta_horas = round(float(mh), 1)
            origem["horas"] = "manual"
        if mq and mq > 0:
            meta_questoes = int(mq)
            origem["questoes"] = "manual"
        if mf and mf > 0:
            meta_flashcards = int(mf)
            origem["flashcards"] = "manual"
    manual_ativo = any(v == "manual" for v in origem.values())

    # === Projeção até a prova ===
    dias_prova = None
    semanas_restantes = None
    try:
        prova = conn.execute("""
            SELECT data_prova_objetiva FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?
            ORDER BY data_prova_objetiva LIMIT 1
        """, (user_id,)).fetchone()
        if prova and prova[0]:
            parts = re.match(r'(\d+)[/\-](\d+)[/\-](\d+)', prova[0])
            if parts:
                if len(parts.group(3)) == 4:
                    d = date(int(parts.group(3)), int(parts.group(2)), int(parts.group(1)))
                else:
                    d = date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
                dias_prova = max(0, (d - hoje).days)
                semanas_restantes = dias_prova // 7
    except Exception:
        pass

    # Cobertura do edital
    total_topicos = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE user_id = ? AND arquivado = 0 AND materia IN (SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?)",
        (user_id, user_id)
    ).fetchone()[0] or 1
    topicos_concluidos = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE user_id = ? AND arquivado = 0 AND status = 'Concluído' AND materia IN (SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?)",
        (user_id, user_id)
    ).fetchone()[0]
    pct_cobertura = round(topicos_concluidos / total_topicos * 100, 1)

    # Projeção: no ritmo atual, quantos tópicos cobrirá por semana?
    # Estimar: ~1 tópico por hora de estudo (simplificado)
    topicos_por_semana = max(1, round(horas_semana_passada * 1.0))
    topicos_restantes = total_topicos - topicos_concluidos

    if semanas_restantes and semanas_restantes > 0:
        topicos_projetados = topicos_por_semana * semanas_restantes
        cobertura_projetada = min(100, round((topicos_concluidos + topicos_projetados) / total_topicos * 100, 1))
        # Para 100%: horas necessárias por semana
        horas_para_100 = round(topicos_restantes / max(semanas_restantes, 1), 1) if topicos_restantes > 0 else 0
    else:
        cobertura_projetada = None
        horas_para_100 = None

    # === Motivação: comparar com meta ===
    pct_horas = round(horas_esta_semana / meta_horas * 100) if meta_horas > 0 else 0
    pct_questoes = round(questoes_esta_semana / meta_questoes * 100) if meta_questoes > 0 else 0
    pct_flashcards = round(flashcards_esta_semana / meta_flashcards * 100) if meta_flashcards > 0 else 0

    # Status motivacional
    if burnout_risk == "alto":
        status = "burnout_alto"
        mensagem = "🛑 Burnout detectado! Metas REDUZIDAS em 25%. Descanse hoje — seu cérebro precisa consolidar."
    elif burnout_risk == "moderado":
        status = "burnout_moderado"
        mensagem = "⚠️ Carga elevada detectada. Metas reduzidas em 10%. Intercale dias leves para melhor retenção."
    elif pct_horas >= 100 and pct_questoes >= 100:
        status = "acima"
        mensagem = "🚀 Acima da meta! Você está evoluindo rápido."
    elif pct_horas >= 70 or pct_questoes >= 70:
        status = "no_ritmo"
        mensagem = "👍 No ritmo! Continue assim até o final da semana."
    elif dias_passados_semana <= 2:
        status = "inicio"
        mensagem = "📅 Semana começando. Foco nas prioridades do dia!"
    else:
        status = "atras"
        mensagem = "⚠️ Abaixo do ritmo. Tente encaixar mais 30min hoje."

    return {
        "meta_semana": {
            "horas": meta_horas,
            "questoes": meta_questoes,
            "flashcards": meta_flashcards,
            "origem": origem,
            "manual_ativo": manual_ativo,
        },
        "progresso_semana": {
            "horas": round(horas_esta_semana, 2),
            "questoes": questoes_esta_semana,
            "flashcards": flashcards_esta_semana,
            "pct_horas": min(pct_horas, 100),
            "pct_questoes": min(pct_questoes, 100),
            "pct_flashcards": min(pct_flashcards, 100),
            "dias_passados": dias_passados_semana,
        },
        "semana_passada": {
            "horas": round(horas_semana_passada, 2),
            "questoes": questoes_semana_passada,
            "flashcards": flashcards_semana_passada,
        },
        "projecao": {
            "dias_prova": dias_prova,
            "semanas_restantes": semanas_restantes,
            "pct_cobertura_atual": pct_cobertura,
            "cobertura_projetada": cobertura_projetada,
            "horas_semana_para_100": horas_para_100,
            "topicos_restantes": topicos_restantes,
        },
        "status": status,
        "mensagem": mensagem,
        "fator_progressao": FATOR_PROGRESSAO,
        "burnout_risk": burnout_risk,
    }


@router.get("/api/metas/adaptativa/override", summary="Ler override manual da meta semanal",
            description="Retorna os valores fixos definidos manualmente para a meta da semana (0 = automático).")
def get_meta_override(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Valores manuais da meta semanal. 0/ausente significa cálculo automático."""
    horas = questoes = flashcards = 0
    try:
        row = conn.execute(
            "SELECT meta_semanal_horas, meta_semanal_questoes, meta_semanal_flashcards "
            "FROM metas_config WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            keys = row.keys()
            horas = row["meta_semanal_horas"] if "meta_semanal_horas" in keys else 0
            questoes = row["meta_semanal_questoes"] if "meta_semanal_questoes" in keys else 0
            flashcards = row["meta_semanal_flashcards"] if "meta_semanal_flashcards" in keys else 0
    except Exception:
        pass  # colunas ainda não migradas
    manual_ativo = bool((horas or 0) > 0 or (questoes or 0) > 0 or (flashcards or 0) > 0)
    return {
        "horas": round(float(horas or 0), 1),
        "questoes": int(questoes or 0),
        "flashcards": int(flashcards or 0),
        "manual_ativo": manual_ativo,
    }


@router.put("/api/metas/adaptativa/override", summary="Definir/limpar override manual da meta semanal",
            description="Define metas semanais fixas (horas/questões/flashcards). Enviar 0 em um campo volta esse campo ao automático. Body: {horas, questoes, flashcards}.")
def set_meta_override(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Salva o override manual. Cada campo com 0 (ou ausente) volta ao automático.

    Validação: horas 0-168 (máx. horas numa semana), questões 0-10000,
    flashcards 0-10000. Valores negativos são rejeitados.
    """
    def _num(v, default=0):
        try:
            return max(0, float(v))
        except (TypeError, ValueError):
            return default

    horas = round(_num(body.get("horas", 0)), 1)
    questoes = int(_num(body.get("questoes", 0)))
    flashcards = int(_num(body.get("flashcards", 0)))

    from fastapi import HTTPException
    if horas > 168:
        raise HTTPException(status_code=400, detail="Horas semanais não podem exceder 168")
    if questoes > 10000 or flashcards > 10000:
        raise HTTPException(status_code=400, detail="Valor muito alto para questões/flashcards")

    # Garante que existe uma linha de config para o usuário
    existing = conn.execute("SELECT id FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO metas_config (meta_horas, meta_questoes, meta_flashcards, meta_paginas, user_id) "
            "VALUES (3.0, 30, 10, 20, ?)",
            (user_id,),
        )

    conn.execute(
        "UPDATE metas_config SET meta_semanal_horas = ?, meta_semanal_questoes = ?, "
        "meta_semanal_flashcards = ? WHERE user_id = ?",
        (horas, questoes, flashcards, user_id),
    )
    conn.commit()

    manual_ativo = bool(horas > 0 or questoes > 0 or flashcards > 0)
    return {
        "ok": True,
        "horas": horas,
        "questoes": questoes,
        "flashcards": flashcards,
        "manual_ativo": manual_ativo,
    }


# ============================================================
# #4 DETECÇÃO DE PLATÔ E MUDANÇA DE ESTRATÉGIA
# ============================================================


@router.get("/api/inteligencia/plato", summary="Detectar platô e sugerir mudança",
            description="Analisa 3+ semanas de dados para detectar estagnação em matérias e sugere mudanças de abordagem (Bjork: desirable difficulties).")
def detectar_plato(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Detecta matérias estagnadas e sugere mudanças de estratégia.

    Platô = 2+ semanas sem melhora significativa (±3%) na taxa de acerto.
    Baseado em Bjork (2011): quando blocked practice para de funcionar,
    variar abordagem (interleaving, elaboration, generation) desbloqueio.
    """
    from datetime import timedelta

    hoje = date.today()
    platos = []

    # Buscar matérias do ciclo ativo
    ciclo_materias = conn.execute(
        "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
    ).fetchall()

    for mat_row in ciclo_materias:
        materia = mat_row["materia"]

        # Calcular % acerto por semana (últimas 4 semanas)
        semanas_data = []
        for weeks_ago in range(4):
            inicio = (hoje - timedelta(days=hoje.weekday() + 7 * weeks_ago + 7)).isoformat()
            fim = (hoje - timedelta(days=hoje.weekday() + 7 * weeks_ago + 1)).isoformat()

            stats = conn.execute("""
                SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
                FROM questoes_respostas qr
                JOIN questoes q ON q.id = qr.questao_id
                WHERE q.materia = ? AND qr.user_id = ? AND qr.data >= ? AND qr.data <= ?
            """, (materia, user_id, inicio, fim)).fetchone()

            total = stats["total"] or 0
            acertos = stats["acertos"] or 0
            pct = round((acertos / total * 100), 1) if total >= 3 else None  # Mínimo 3 questões para ser válido
            semanas_data.append({"semana": weeks_ago, "total": total, "pct": pct})

        # Detectar platô: 2+ semanas consecutivas com variação <= 3%
        semanas_validas = [s for s in semanas_data if s["pct"] is not None]
        if len(semanas_validas) < 2:
            continue

        # Comparar semanas mais recentes
        pcts = [s["pct"] for s in semanas_validas]
        variacao_max = max(pcts[:3]) - min(pcts[:3]) if len(pcts) >= 3 else max(pcts) - min(pcts)
        media_pct = round(sum(pcts) / len(pcts), 1)
        semanas_estagnado = 0

        for i in range(len(pcts) - 1):
            if abs(pcts[i] - pcts[i+1]) <= 3:
                semanas_estagnado += 1
            else:
                break

        is_plato = semanas_estagnado >= 2 and media_pct < 85

        if not is_plato:
            continue

        # Gerar sugestões de mudança de estratégia
        sugestoes = []

        # Analisar padrão de erros para sugestões específicas
        erros_topicos = conn.execute("""
            SELECT q.topico, COUNT(*) as erros FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE q.materia = ? AND qr.user_id = ? AND qr.acertou = 0
            AND qr.data >= ?
            GROUP BY q.topico ORDER BY erros DESC LIMIT 3
        """, (materia, user_id, (hoje - timedelta(days=21)).isoformat())).fetchall()

        topicos_fracos = [t["topico"] for t in erros_topicos if t["topico"]]

        if media_pct < 50:
            sugestoes.append({
                "tipo": "voltar_teoria",
                "titulo": "📖 Voltar à teoria",
                "descricao": f"Pare questões por 3 dias e estude os fundamentos. Seus erros concentram em: {', '.join(topicos_fracos[:2]) or 'tópicos básicos'}.",
                "prioridade": "alta",
            })
            sugestoes.append({
                "tipo": "elaboration",
                "titulo": "✍️ Técnica de Elaboração",
                "descricao": "Reescreva os conceitos com suas palavras. Ensine para alguém (ou escreva como se fosse ensinar).",
                "prioridade": "media",
            })
        elif media_pct < 70:
            sugestoes.append({
                "tipo": "interleaving",
                "titulo": "🔄 Mudar para Interleaving",
                "descricao": "Em vez de resolver só questões dessa matéria, misture com outras. O cérebro discrimina melhor assim.",
                "prioridade": "alta",
            })
            sugestoes.append({
                "tipo": "generation",
                "titulo": "🧠 Modo Generation",
                "descricao": "Tente responder questões SEM ver as alternativas primeiro. Gere a resposta mentalmente, depois confira.",
                "prioridade": "media",
            })
        else:
            sugestoes.append({
                "tipo": "desirable_difficulty",
                "titulo": "⬆️ Aumentar Dificuldade",
                "descricao": "Você domina o básico mas estagnou. Resolva questões de nível DIFÍCIL ou de bancas diferentes.",
                "prioridade": "alta",
            })
            sugestoes.append({
                "tipo": "simulado_parcial",
                "titulo": "📝 Simulado Cronometrado",
                "descricao": "Faça 20 questões dessa matéria em tempo de prova (30min). Pressão temporal revela gaps ocultos.",
                "prioridade": "media",
            })

        # Sempre sugerir análise de erros
        if topicos_fracos:
            sugestoes.append({
                "tipo": "foco_erros",
                "titulo": "🎯 Foco nos Erros",
                "descricao": f"Seus 3 tópicos mais errados: {', '.join(topicos_fracos)}. Estude APENAS eles por 2 dias.",
                "prioridade": "alta",
            })

        platos.append({
            "materia": materia,
            "media_pct": media_pct,
            "semanas_estagnado": semanas_estagnado + 1,
            "variacao": round(variacao_max, 1),
            "historico_semanas": semanas_validas,
            "topicos_fracos": topicos_fracos,
            "sugestoes": sugestoes,
        })

    # Ordenar: platô mais longo primeiro
    platos.sort(key=lambda x: (-x["semanas_estagnado"], x["media_pct"]))

    return {
        "platos_detectados": len(platos),
        "platos": platos,
        "mensagem": f"⚠️ {len(platos)} matéria{'s' if len(platos) != 1 else ''} em platô — hora de mudar a estratégia!" if platos else "✅ Nenhum platô detectado. Você está progredindo!",
    }
