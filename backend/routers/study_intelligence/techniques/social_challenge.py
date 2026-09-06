"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Body, Depends

from database import get_db_session
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# PEER TEACHING — Webb (1991), Fiorella & Mayer (2013)
# Ensinar = processamento profundo + detecção de lacunas
# "Se não consegue explicar, não entendeu de verdade"
# ============================================================


@router.get(
    "/api/study-intelligence/peer-teaching",
    summary="Peer Teaching Suggestion",
    description="""Sugere tópicos para o user ENSINAR a outros (no chat, grupo ou Study Room).
Ensinar produz 'generative learning' — força reorganização do conhecimento.
Baseado em Webb (1991): quem explica retém 90% vs 10% de quem apenas lê.
Fiorella & Mayer (2013): 'learning by teaching' é uma das técnicas mais eficazes.""",
)
def peer_teaching_suggestion(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Sugere tópicos ideais para ensinar (domínio suficiente mas não perfeito)."""

    # Tópicos ideais para ensinar: acerto entre 70-90% (sabe o suficiente mas ensinar consolida)
    materias_para_ensinar = conn.execute(
        """
        SELECT q.materia,
               COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct_acerto
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        HAVING total >= 10 AND pct_acerto BETWEEN 70 AND 92
        ORDER BY pct_acerto DESC
    """,
        (user_id,),
    ).fetchall()

    sugestoes = []
    for m in materias_para_ensinar[:5]:
        # Buscar tópico específico dessa matéria que tem bom domínio
        topico = conn.execute(
            """
            SELECT topico FROM edital
            WHERE materia = ? AND user_id = ? AND status = 'Concluído' AND arquivado = 0
            ORDER BY RANDOM() LIMIT 1
        """,
            (m["materia"], user_id),
        ).fetchone()

        sugestoes.append(
            {
                "materia": m["materia"],
                "pct_acerto": m["pct_acerto"],
                "total_questoes": m["total"],
                "topico_sugerido": topico["topico"] if topico else None,
                "como_ensinar": _gerar_prompt_ensino(m["materia"], topico["topico"] if topico else ""),
            }
        )

    # Verificar se já ensinou recentemente (XP bonus tracking)
    xp_ensino = 0
    try:
        ensinos = conn.execute(
            """
            SELECT COUNT(*) as total FROM peer_teaching_log
            WHERE user_id = ? AND created_at >= date('now', '-7 days')
        """,
            (user_id,),
        ).fetchone()
        xp_ensino = (ensinos["total"] or 0) * 30  # 30 XP por ensino
    except Exception:
        pass

    return {
        "sugestoes": sugestoes,
        "total_sugestoes": len(sugestoes),
        "xp_ensino_semana": xp_ensino,
        "mensagem": "🎓 Ensinar é a forma mais eficaz de aprender! Escolha um tópico e explique para alguém (chat, grupo ou Study Room).",
        "beneficios": [
            "Retenção de 90% (vs 10% de leitura passiva)",
            "Identifica lacunas: se não consegue explicar, precisa revisar",
            "Reforça conexões neurais pelo processamento generativo",
            "Ganha 30 XP por cada sessão de ensino registrada",
        ],
        "tecnica": "Peer Teaching (Webb 1991, Fiorella & Mayer 2013): explicar para outros força reorganização do conhecimento e detecção de lacunas. Pirâmide de aprendizagem: ensinar = 90% retenção.",
    }


def _gerar_prompt_ensino(materia: str, topico: str) -> str:
    """Gera prompt/desafio para ensinar o tópico."""
    if topico:
        return f"Explique '{topico}' como se estivesse ensinando para um colega que nunca estudou {materia}. Use exemplos práticos."
    return f"Escolha um conceito de {materia} que você domina e explique em no máximo 3 parágrafos, como se fosse para alguém que está começando."


@router.post("/api/study-intelligence/peer-teaching/registrar", summary="Registrar sessão de ensino")
def peer_teaching_registrar(
    materia: str = Body(...),
    topico: str = Body(""),
    formato: str = Body("texto", description="texto, audio, video, chat, studyroom"),
    duracao_min: int = Body(5),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra que o user ensinou algo (dá XP bônus)."""
    from datetime import datetime

    conn.execute("""
        CREATE TABLE IF NOT EXISTS peer_teaching_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            materia TEXT NOT NULL,
            topico TEXT DEFAULT '',
            formato TEXT DEFAULT 'texto',
            duracao_min INTEGER DEFAULT 5,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_peer_teaching_user ON peer_teaching_log(user_id)")

    conn.execute(
        """
        INSERT INTO peer_teaching_log (user_id, materia, topico, formato, duracao_min, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (user_id, materia, topico, formato, duracao_min, datetime.now().isoformat()),
    )

    # Registrar como sessão de estudo (tipo 'ensino')
    horas = duracao_min / 60
    conn.execute(
        """
        INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at)
        VALUES (?, ?, ?, 'ensino', ?, ?)
    """,
        (materia, round(horas, 3), today_str(), user_id, datetime.now().isoformat()),
    )

    conn.commit()

    return {
        "ok": True,
        "xp_ganho": 30,
        "mensagem": f"🎓 +30 XP por ensinar {materia}! Ensinar é a forma mais eficaz de fixar conhecimento.",
    }


# ============================================================
# GAMIFIED SPACED REPETITION — Boss Battle Mode
# Flashcard review como RPG: Boss HP = difficulty, dano = rating
# Motivação via narrativa + mecânicas de jogo
# ============================================================


@router.get(
    "/api/study-intelligence/boss-battle",
    summary="Boss Battle — Gamified Flashcard Review",
    description="""Transforma revisão de flashcards em batalha contra um Boss.
Boss HP proporcional à dificuldade dos cards pendentes.
Cada card respondido = ataque. Rating determina dano.
Derrota o boss = XP + badge. Motivação via narrativa de jogo.""",
)
def boss_battle_start(
    materia: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera uma boss battle com flashcards pendentes."""
    hoje = today_str()

    # Buscar flashcards pendentes para revisão
    params = [hoje, user_id]
    filtro_mat = ""
    if materia:
        filtro_mat = "AND materia = ?"
        params.append(materia)

    cards = conn.execute(
        f"""
        SELECT id, pergunta, resposta, materia, difficulty, stability, fsrs_state
        FROM flashcards
        WHERE proxima_revisao <= ? AND user_id = ? {filtro_mat}
        ORDER BY difficulty DESC, stability ASC
        LIMIT 15
    """,
        params,
    ).fetchall()

    if not cards:
        return {
            "boss": None,
            "mensagem": "🎉 Sem flashcards pendentes! Todos os bosses foram derrotados hoje.",
            "cards": [],
        }

    cards_list = [dict(c) for c in cards]

    # Calcular Boss stats baseado nos cards
    avg_difficulty = sum(c.get("difficulty") or 3 for c in cards_list) / len(cards_list)
    total_cards = len(cards_list)

    # Boss HP calibrado para a nova escala de dano (base 10–25/ataque, média ~17).
    # HP por card = 10 + (difficulty média × 1.5) → ~15–20/card. Assim o boss é
    # derrotável com bom desempenho ao longo dos cards, sem depender de marcar
    # "Easy". Cards mais difíceis (maior difficulty) elevam levemente o HP.
    boss_hp = int(total_cards * (10 + avg_difficulty * 1.5))

    # Escolher boss baseado na dificuldade
    bosses = [
        {"nome": "Esquecimento Leve", "emoji": "👻", "tier": 1, "hp_range": (0, 100)},
        {"nome": "Confusão Mental", "emoji": "🌀", "tier": 2, "hp_range": (101, 200)},
        {"nome": "Bloqueio Cognitivo", "emoji": "🧱", "tier": 3, "hp_range": (201, 350)},
        {"nome": "Amnésia Profunda", "emoji": "🕳️", "tier": 4, "hp_range": (351, 500)},
        {"nome": "Dragão do Esquecimento", "emoji": "🐉", "tier": 5, "hp_range": (501, 9999)},
    ]

    boss = bosses[0]
    for b in bosses:
        if b["hp_range"][0] <= boss_hp <= b["hp_range"][1]:
            boss = b
            break
        boss = b  # Fallback para o último

    # Dano por rating — nova mecânica (não punir o esforço no card difícil):
    # Todo ataque causa dano base; a qualidade da recuperação modula moderadamente
    # (diferença de 2.5x entre errar e dominar, não 10x). Errar (Again) ainda causa
    # dano porque o esforço de enfrentar um card difícil é o que importa (desirable
    # difficulty). A consistência é premiada pelo bônus de combo (ver frontend/resultado).
    dano_map = {1: 10, 2: 15, 3: 20, 4: 25}
    # Bônus de combo: a partir do 3º acerto (>=Good) consecutivo, +5 de dano por
    # ataque, com teto de +15. Um "Again" reseta o combo (não pune, só recomeça).
    combo_bonus_por_acerto = 5
    combo_bonus_teto = 15
    combo_inicio = 3

    # ─── Fraquezas do boss por matéria (Fase D — incentiva INTERLEAVING) ───
    # O boss tem 1–2 matérias "fracas": acertar (>=Good) um card dessas matérias
    # causa dano CRÍTICO (×2). Escolhemos como fracas as matérias em que o
    # candidato tem PIOR desempenho entre as presentes na batalha — assim o
    # crítico recompensa revisar justamente o que ele mais precisa, e alternar
    # matérias (Rohrer, 2012: interleaving melhora discriminação e retenção).
    materias_na_batalha = [m for m in {c["materia"] for c in cards_list if c["materia"]}]
    fraquezas = []
    CRIT_MULT = 2
    if materias_na_batalha:
        # % de acerto por matéria (menor acerto = mais "fraco" no candidato)
        desempenho = {}
        for m in materias_na_batalha:
            row = conn.execute(
                """SELECT COUNT(*) total, COALESCE(SUM(qr.acertou),0) ac
                   FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
                   WHERE q.materia = ? AND qr.user_id = ?""",
                (m, user_id),
            ).fetchone()
            total_q = row["total"] or 0
            pct = (row["ac"] / total_q * 100) if total_q else None
            desempenho[m] = pct
        # Ordena: matérias com desempenho conhecido e menor % primeiro; depois as
        # sem histórico (None) por maior difficulty média dos cards; empate estável.
        dif_media = {}
        for m in materias_na_batalha:
            ds = [c.get("difficulty") or 3 for c in cards_list if c["materia"] == m]
            dif_media[m] = sum(ds) / len(ds) if ds else 3

        def _rank(m):
            pct = desempenho.get(m)
            # menor acerto → mais fraco (rank menor). Sem histórico usa 50 como neutro,
            # desempatando por maior dificuldade (negativo para vir antes).
            base = pct if pct is not None else 50.0
            return (base, -dif_media[m])

        ordenadas = sorted(materias_na_batalha, key=_rank)
        # 1 fraqueza para poucas matérias, 2 quando há variedade suficiente
        n_fraquezas = 2 if len(materias_na_batalha) >= 3 else 1
        fraquezas = ordenadas[:n_fraquezas]

    # Preparar cards para batalha (com resposta, para revelar sem novo fetch)
    battle_cards = [
        {
            "id": c["id"],
            "pergunta": c["pergunta"],
            "resposta": c["resposta"],
            "materia": c["materia"],
            "difficulty": round(c.get("difficulty") or 3, 1),
            "ponto_fraco": c["materia"] in fraquezas,
        }
        for c in cards_list
    ]

    return {
        "boss": {
            "nome": boss["nome"],
            "emoji": boss["emoji"],
            "tier": boss["tier"],
            "hp_total": boss_hp,
            "hp_atual": boss_hp,
            "fraquezas": fraquezas,
            "crit_mult": CRIT_MULT,
        },
        "cards": battle_cards,
        "total_cards": total_cards,
        "dano_map": dano_map,
        "combo": {
            "bonus_por_acerto": combo_bonus_por_acerto,
            "teto": combo_bonus_teto,
            "inicio": combo_inicio,
        },
        "fraquezas": fraquezas,
        "crit_mult": CRIT_MULT,
        "dano_descricao": {
            "again": "10 dano (Errou, mas atacou! 💨)",
            "hard": "15 dano (Lembrou com esforço ⚔️)",
            "good": "20 dano (Lembrou bem 🗡️)",
            "easy": "25 dano (Dominado 💥)",
        },
        "recompensas": {
            "derrotar_boss": f"+{boss['tier'] * 20} XP",
            "sem_erros": "+50 XP bônus (Precisão total!)",
            "combo_acertos": "+30 XP (Combo de 3+ acertos seguidos)",
        },
        "mensagem": (
            f"⚔️ {boss['emoji']} {boss['nome']} (Tier {boss['tier']}) apareceu! HP: {boss_hp}. "
            + (
                f"Ponto(s) fraco(s): {', '.join(fraquezas)} — acerte esses cards para dano CRÍTICO! "
                if fraquezas
                else ""
            )
            + "Revise os flashcards para atacar!"
        ),
        "instrucao": (
            "Cada flashcard = 1 ataque. Avalie com honestidade: Again(10), Hard(15), Good(20), Easy(25). "
            "Errar também ataca — o esforço conta! Acertos seguidos formam combo. "
            "Acertar cards das matérias fracas do boss causa dano CRÍTICO (×2) — alterne matérias (interleaving)!"
        ),
    }


@router.post("/api/study-intelligence/boss-battle/resultado", summary="Registrar resultado da Boss Battle")
def boss_battle_resultado(
    boss_tier: int = Body(1),
    boss_hp_total: int = Body(100),
    dano_total: int = Body(0),
    cards_revisados: int = Body(0),
    acertos_easy: int = Body(0),
    acertos_good: int = Body(0),
    acertos_hard: int = Body(0),
    erros_again: int = Body(0),
    combo_max: int = Body(0),
    derrotou: bool = Body(False),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra resultado da boss battle e calcula XP ganho.

    IMPORTANTE (evita dupla contagem nas Ligas): cada card revisado na batalha
    já concede +5 XP na liga via streaks.flashcards_revisados (o frontend chama
    /review-fsrs por card). Portanto, persistimos apenas o XP BÔNUS da batalha
    (derrotar boss + precisão + combo) na tabela boss_battles, que a liga soma
    separadamente. O XP por card NÃO é persistido aqui.

    Mecânica pedagógica (não punir o esforço): o bônus de combo premia a
    CONSISTÊNCIA (maior sequência de acertos ≥ Good), não o marcar "Easy". Errar
    um card difícil não zera XP — apenas quebra o combo em andamento.
    """
    import json as _json

    # XP BÔNUS (persistido para a liga)
    xp_bonus = 0
    if derrotou:
        xp_bonus += boss_tier * 20
    if erros_again == 0 and cards_revisados > 0:
        xp_bonus += 50  # Precisão total (sem "Again")
    # Combo de acertos: 3+ acertos consecutivos (Good/Easy/Hard). Fallback para
    # payloads antigos (sem combo_max): usa acertos_easy como aproximação.
    combo = combo_max if combo_max > 0 else acertos_easy
    if combo >= 3:
        xp_bonus += 30  # Combo de acertos ×3+

    # XP total exibido ao usuário (bônus + base por card, só para feedback visual)
    xp_total = xp_bonus + cards_revisados * 5

    # Persistir o resultado — a liga conta o xp_bonus da semana (categoria própria).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boss_battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            boss_tier INTEGER DEFAULT 1,
            derrotou INTEGER DEFAULT 0,
            xp_bonus INTEGER DEFAULT 0,
            cards_revisados INTEGER DEFAULT 0,
            stats TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)
    from datetime import datetime as _dt

    stats_obj = {
        "easy": acertos_easy,
        "good": acertos_good,
        "hard": acertos_hard,
        "again": erros_again,
        "dano_total": dano_total,
        "combo_max": combo,
    }
    conn.execute(
        """INSERT INTO boss_battles
           (user_id, data, boss_tier, derrotou, xp_bonus, cards_revisados, stats, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            today_str(),
            boss_tier,
            1 if derrotou else 0,
            xp_bonus,
            cards_revisados,
            _json.dumps(stats_obj),
            _dt.now().isoformat(),
        ),
    )
    conn.commit()

    # Feedback narrativo
    if derrotou and erros_again == 0:
        narrativa = f"🏆 PERFECT VICTORY! {boss_tier * '⭐'} {acertos_easy + acertos_good + acertos_hard} ataques, 0 falhas. Lendário!"
    elif derrotou:
        narrativa = f"⚔️ BOSS DERROTADO! Dano total: {dano_total}. Você venceu o esquecimento!"
    elif dano_total > boss_hp_total * 0.7:
        narrativa = f"😤 Quase! Boss com apenas {boss_hp_total - dano_total} HP restante. Volte amanhã para finalizar!"
    else:
        narrativa = f"💀 Boss sobreviveu com {boss_hp_total - dano_total} HP. Revise mais e tente novamente!"

    return {
        "xp_ganho": xp_total,
        "xp_bonus": xp_bonus,
        "derrotou": derrotou,
        "narrativa": narrativa,
        "stats": {
            "cards_revisados": cards_revisados,
            "dano_total": dano_total,
            "easy": acertos_easy,
            "good": acertos_good,
            "hard": acertos_hard,
            "again": erros_again,
        },
    }


# ============================================================
# TESTING BOUNDARIES — Bjork (2011) Zona Ótima de Aprendizado
# ============================================================


@router.get(
    "/api/study-intelligence/testing-boundaries",
    summary="Testing Boundaries — Zona Ótima de Aprendizado",
    description="""Identifica flashcards na zona ótima de aprendizado (quality médio 2-3 = quase acertou).
Evidência: Bjork (2011) — Testar nos limites do conhecimento (nem fácil demais, nem impossível)
produz o máximo de aprendizado. Cards com quality 2-3 são os que mais beneficiam de revisão.""",
)
def testing_boundaries(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna análise da zona ótima de aprendizado."""
    uma_semana = (date.today() - timedelta(days=7)).isoformat()

    # Buscar flashcards revisados na última semana com quality médio
    rows = conn.execute(
        """
        SELECT f.id, f.materia, f.pergunta, f.stability, f.difficulty,
               AVG(CASE WHEN fr.quality IS NOT NULL THEN fr.quality ELSE 3 END) as avg_quality,
               COUNT(fr.id) as revisoes_semana
        FROM flashcards f
        LEFT JOIN (
            SELECT flashcard_id, quality, id FROM flashcards_reviews
            WHERE user_id = ? AND created_at >= ?
        ) fr ON f.id = fr.flashcard_id
        WHERE f.user_id = ? AND f.stability > 0
        GROUP BY f.id
        HAVING revisoes_semana > 0
    """,
        (user_id, uma_semana, user_id),
    ).fetchall()

    # Se não tiver tabela flashcards_reviews, usar fallback com difficulty
    if not rows:
        rows = conn.execute(
            """
            SELECT id, materia, pergunta, stability, difficulty
            FROM flashcards
            WHERE user_id = ? AND stability > 0 AND difficulty > 0
        """,
            (user_id,),
        ).fetchall()
        # Classificar por difficulty (0.3-0.7 = zona ótima)
        zona_otima = [dict(r) for r in rows if 0.3 <= (r["difficulty"] or 0) <= 0.7]
        zona_facil = [dict(r) for r in rows if (r["difficulty"] or 0) < 0.3]
        zona_dificil = [dict(r) for r in rows if (r["difficulty"] or 0) > 0.7]
    else:
        items = [dict(r) for r in rows]
        zona_otima = [i for i in items if 2.0 <= (i.get("avg_quality") or 3) <= 3.5]
        zona_facil = [i for i in items if (i.get("avg_quality") or 3) > 3.5]
        zona_dificil = [i for i in items if (i.get("avg_quality") or 3) < 2.0]

    total = len(zona_otima) + len(zona_facil) + len(zona_dificil)
    pct_otima = round(len(zona_otima) / total * 100) if total > 0 else 0

    # Matérias na zona ótima
    materias_otima = {}
    for item in zona_otima:
        m = item.get("materia") or "Geral"
        materias_otima[m] = materias_otima.get(m, 0) + 1

    return {
        "zona_otima": len(zona_otima),
        "zona_facil": len(zona_facil),
        "zona_dificil": len(zona_dificil),
        "total_analisados": total,
        "pct_zona_otima": pct_otima,
        "materias_zona_otima": dict(sorted(materias_otima.items(), key=lambda x: -x[1])[:5]),
        "recomendacao": (
            "🎯 Ótimo! Maioria dos cards está na zona de máximo aprendizado."
            if pct_otima >= 40
            else "⚠️ Poucos cards na zona ótima. Ajuste a dificuldade ou adicione mais cards intermediários."
            if pct_otima < 20
            else "✅ Boa distribuição. Continue revisando os cards de dificuldade média."
        ),
        "explicacao": "Cards na 'zona ótima' (quality 2-3 / difficulty 0.3-0.7) são os que mais aprendem por sessão. Nem tão fáceis que desperdiçam tempo, nem tão difíceis que frustram.",
    }
