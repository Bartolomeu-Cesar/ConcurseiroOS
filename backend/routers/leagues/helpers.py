"""
Leagues / Liga Semanal - Duolingo-style Weekly Competition System.
Manages weekly competitive leagues with tier progression (Bronze → Prata → Ouro → Diamante).

Endpoints:
  GET  /api/liga          — Current week's league status
  GET  /api/liga/historico — Past weeks results
  POST /api/liga/processar — Process end-of-week (promote/demote)

  GET  /api/leagues/current    — (alias) Current league standings
  GET  /api/leagues/history    — (alias) League history
  POST /api/leagues/update-xp  — Update user XP in league
  POST /api/leagues/process-week — (alias) Process week end
  GET  /api/leagues/tier-info  — Tier metadata
"""

import random
from datetime import date, datetime, timedelta

from fastapi import APIRouter

from logger import log

router = APIRouter(prefix="", tags=["Ligas"])

# ─── Tier Configuration ───────────────────────────────────────────────────────

TIERS = ["bronze", "prata", "ouro", "diamante"]

TIER_LABELS = {
    "bronze": "Bronze",
    "prata": "Prata",
    "ouro": "Ouro",
    "diamante": "Diamante",
}

TIER_ICONS = {
    "bronze": "🥉",
    "prata": "🥈",
    "ouro": "🥇",
    "diamante": "💎",
}

TIER_XP_RANGES = {
    "bronze": (50, 500),
    "prata": (200, 800),
    "ouro": (500, 1500),
    "diamante": (1000, 3000),
}

PROMOTION_ZONE = 3   # Top 3 promote
DEMOTION_ZONE = 3    # Bottom 3 demote
MIN_LEAGUE_SIZE = 15
MAX_LEAGUE_SIZE = 20

# ─── XP Constants ─────────────────────────────────────────────────────────────

XP_PER_QUESTION = 10        # Questões respondidas corretamente
XP_PER_HOUR = 20            # Horas estudadas (per hour)
XP_PER_FLASHCARD = 5        # Flashcards revisados
XP_DESAFIO_DIARIO = 50      # Desafio diário completo
XP_BATALHA_VENCIDA = 100    # Batalha vencida
XP_STREAK_DAY = 15          # Cada dia de streak
XP_PER_SUMULA = 5           # Súmula revisada
XP_PER_TOPIC_COMPLETED = 25 # Tópico do edital concluído
XP_META_DIARIA = 30         # Meta diária 100% cumprida
XP_PER_ERRO_CORRIGIDO = 8   # Caderno de erros: acertou na revisão
XP_SIMULADO_COMPLETO = 50   # Simulado completado

# ─── Bot Names (realistic Brazilian names) ────────────────────────────────────

BOT_NAMES = [
    "Lucas S.", "Ana P.", "Carlos M.", "Fernanda R.", "João V.",
    "Mariana L.", "Pedro H.", "Juliana C.", "Rafael T.", "Beatriz A.",
    "Gabriel F.", "Camila O.", "Matheus D.", "Larissa N.", "Thiago B.",
    "Amanda G.", "Bruno K.", "Letícia W.", "Diego S.", "Isabela M.",
    "Vinícius R.", "Natália P.", "Gustavo L.", "Patrícia C.", "Felipe A.",
]


# ─── Migration: Add 'liga' column to users table ─────────────────────────────

def migrate_liga_column(db):
    """Add 'liga' column to users table and 'week_end' to leagues if they don't exist."""
    try:
        db.execute("SELECT liga FROM users LIMIT 1")
    except Exception:
        try:
            db.execute("ALTER TABLE users ADD COLUMN liga TEXT DEFAULT 'bronze'")
            db.commit()
            log.info("Migration: added column 'liga' to users table")
        except Exception as e:
            log.warning(f"Migration liga column failed (may already exist): {e}")

    # Ensure leagues table has week_end column
    try:
        db.execute("SELECT week_end FROM leagues LIMIT 1")
    except Exception:
        try:
            db.execute("ALTER TABLE leagues ADD COLUMN week_end TEXT DEFAULT ''")
            db.commit()
            log.info("Migration: added column 'week_end' to leagues table")
        except Exception as e:
            log.warning(f"Migration week_end failed: {e}")


# ─── Helper Functions ─────────────────────────────────────────────────────────

def get_current_week_bounds() -> tuple[str, str]:
    """Get Monday 00:00 and Sunday 23:59 of the current week as ISO strings."""
    today = date.today()
    days_since_monday = today.isoweekday() - 1
    monday = today - timedelta(days=days_since_monday)
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def get_days_remaining() -> int:
    """Days remaining until end of current week (Sunday)."""
    today = date.today()
    days_since_monday = today.isoweekday() - 1
    return 6 - days_since_monday


def get_user_tier(db, user_id: int) -> str:
    """Determine user's current tier based on their history or users table."""
    # First try users table
    try:
        user_row = db.execute(
            "SELECT liga FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user_row and user_row[0]:
            return user_row[0]
    except Exception:
        pass

    # Fallback: check league history
    row = db.execute(
        """SELECT tier, promoted, demoted FROM league_history
           WHERE user_id = ?
           ORDER BY week_end DESC LIMIT 1""",
        (user_id,)
    ).fetchone()
    if row:
        tier = row[0]
        promoted = row[1]
        demoted = row[2]
        tier_idx = TIERS.index(tier) if tier in TIERS else 0
        if promoted and tier_idx < len(TIERS) - 1:
            return TIERS[tier_idx + 1]
        elif demoted and tier_idx > 0:
            return TIERS[tier_idx - 1]
        return tier

    return "bronze"


def calculate_user_weekly_xp(db, user_id: int, week_start: str, week_end: str) -> dict:
    """Calculate user's XP earned this week from all activities.
    Returns dict with total and breakdown."""
    breakdown = {
        "questoes": 0,
        "horas_estudo": 0,
        "flashcards": 0,
        "desafios": 0,
        "batalhas": 0,
        "streak": 0,
        "sumulas": 0,
        "topicos": 0,
        "metas": 0,
        "erros_corrigidos": 0,
        "simulados": 0,
        "boss_battles": 0,
    }

    # 1. XP from questions answered correctly: +10 XP each
    try:
        questions = db.execute(
            """SELECT COUNT(*) FROM questoes_respostas
            WHERE user_id = ?
            AND data >= ? AND data <= ?
            AND acertou = 1""",
            (user_id, week_start, week_end)
        ).fetchone()
        if questions and questions[0]:
            breakdown["questoes"] = questions[0] * XP_PER_QUESTION
    except Exception as e:
        log.warning(f"Error calculating question XP: {e}")

    # 2. XP from study sessions: +20 XP per hour
    try:
        sessions = db.execute(
            """SELECT COALESCE(SUM(horas), 0) as hours
            FROM sessoes_estudo
            WHERE user_id = ?
            AND data >= ? AND data <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if sessions and sessions[0]:
            breakdown["horas_estudo"] = int(float(sessions[0]) * XP_PER_HOUR)
    except Exception as e:
        log.warning(f"Error calculating session XP: {e}")

    # 3. XP from flashcard reviews: +5 XP each
    try:
        flashcards = db.execute(
            """SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks
            WHERE user_id = ?
            AND data >= ? AND data <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if flashcards and flashcards[0]:
            breakdown["flashcards"] = int(flashcards[0]) * XP_PER_FLASHCARD
    except Exception as e:
        log.warning(f"Error calculating flashcard XP: {e}")

    # 4. XP from completed daily challenges: +50 XP each
    try:
        desafios = db.execute(
            """SELECT COUNT(*) FROM desafio_diario
            WHERE user_id = ?
            AND completado = 1
            AND data >= ? AND data <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if desafios and desafios[0]:
            breakdown["desafios"] = desafios[0] * XP_DESAFIO_DIARIO
    except Exception as e:
        log.warning(f"Error calculating desafio XP: {e}")

    # 5. XP from battles won: +100 XP each
    try:
        battles_won = db.execute(
            """SELECT COUNT(*) FROM battle_players bp
            JOIN battles b ON b.id = bp.battle_id
            WHERE bp.user_id = ?
            AND bp.posicao = 1
            AND b.status = 'finalizada'
            AND date(b.created_at) >= ? AND date(b.created_at) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if battles_won and battles_won[0]:
            breakdown["batalhas"] = battles_won[0] * XP_BATALHA_VENCIDA
    except Exception as e:
        log.warning(f"Error calculating batalha XP: {e}")

    # 6. XP from streak days: +15 XP per day with streak this week
    try:
        streak_days = db.execute(
            """SELECT COUNT(*) FROM streaks
            WHERE user_id = ?
            AND date(data) >= ? AND date(data) <= ?
            AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)""",
            (user_id, week_start, week_end)
        ).fetchone()
        if streak_days and streak_days[0]:
            breakdown["streak"] = streak_days[0] * XP_STREAK_DAY
    except Exception:
        # streaks table may not have user_id column in older schemas
        try:
            streak_days = db.execute(
                """SELECT COUNT(*) FROM streaks
                WHERE date(data) >= ? AND date(data) <= ?
                AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)""",
                (week_start, week_end)
            ).fetchone()
            if streak_days and streak_days[0]:
                breakdown["streak"] = streak_days[0] * XP_STREAK_DAY
        except Exception as e2:
            log.warning(f"Error calculating streak XP: {e2}")

    # 7. XP from súmulas reviewed: +5 XP each
    try:
        sumulas_count = db.execute(
            """SELECT COALESCE(SUM(sumulas_revisadas), 0) FROM streaks
            WHERE user_id = ?
            AND date(data) >= ? AND date(data) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if sumulas_count and sumulas_count[0]:
            breakdown["sumulas"] = int(sumulas_count[0]) * XP_PER_SUMULA
    except Exception as e:
        log.warning(f"Error calculating sumula XP: {e}")

    # 8. XP from edital topics completed: +25 XP each
    try:
        topicos = db.execute(
            """SELECT COUNT(*) FROM edital
            WHERE user_id = ? AND status = 'concluido'
            AND date(mastery_updated_at) >= ? AND date(mastery_updated_at) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if topicos and topicos[0]:
            breakdown["topicos"] = topicos[0] * XP_PER_TOPIC_COMPLETED
    except Exception as e:
        log.warning(f"Error calculating topic XP: {e}")

    # 9. XP from daily meta achieved (100%): +30 XP per day
    try:
        # Dias onde todas as metas foram cumpridas
        meta_config = db.execute(
            "SELECT meta_horas, meta_questoes, meta_flashcards FROM metas_config WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if meta_config:
            mh = meta_config[0] or 3.0
            mq = meta_config[1] or 30
            mf = meta_config[2] or 10
            meta_days = db.execute(
                """SELECT COUNT(*) FROM streaks
                WHERE user_id = ?
                AND date(data) >= ? AND date(data) <= ?
                AND horas_estudadas >= ?
                AND questoes_resolvidas >= ?
                AND flashcards_revisados >= ?""",
                (user_id, week_start, week_end, mh, mq, mf)
            ).fetchone()
            if meta_days and meta_days[0]:
                breakdown["metas"] = meta_days[0] * XP_META_DIARIA
    except Exception as e:
        log.warning(f"Error calculating meta XP: {e}")

    # 10. XP from caderno de erros: correct on review: +8 XP each
    try:
        erros_corrigidos = db.execute(
            """SELECT COUNT(*) FROM erros_revisao
            WHERE user_id = ?
            AND date(updated_at) >= ? AND date(updated_at) <= ?
            AND fsrs_state > 0 AND reps > 0""",
            (user_id, week_start, week_end)
        ).fetchone()
        if erros_corrigidos and erros_corrigidos[0]:
            breakdown["erros_corrigidos"] = erros_corrigidos[0] * XP_PER_ERRO_CORRIGIDO
    except Exception as e:
        log.warning(f"Error calculating erro XP: {e}")

    # 11. XP from simulados completed: +50 XP each
    try:
        simulados = db.execute(
            """SELECT COUNT(*) FROM simulados
            WHERE user_id = ? AND status = 'finalizado'
            AND date(finalizado_at) >= ? AND date(finalizado_at) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if simulados and simulados[0]:
            breakdown["simulados"] = simulados[0] * XP_SIMULADO_COMPLETO
    except Exception as e:
        log.warning(f"Error calculating simulado XP: {e}")

    # 12. XP bônus de Boss Battles (flashcards gamificados): soma o xp_bonus da semana.
    # O XP por card revisado já entra em "flashcards" (via streaks) — aqui é só o bônus
    # (derrotar boss + perfect + combo), evitando dupla contagem.
    try:
        boss_bonus = db.execute(
            """SELECT COALESCE(SUM(xp_bonus), 0) FROM boss_battles
            WHERE user_id = ?
            AND date(data) >= ? AND date(data) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if boss_bonus and boss_bonus[0]:
            breakdown["boss_battles"] = int(boss_bonus[0])
    except Exception as e:
        # tabela pode não existir ainda (nenhuma batalha registrada)
        log.warning(f"Error calculating boss battle XP: {e}")

    total = sum(breakdown.values())
    return {"total": total, "breakdown": breakdown}


def populate_bots(db, league_id: int, tier: str):
    """Populate a league with simulated bot members."""
    num_bots = random.randint(MIN_LEAGUE_SIZE - 1, MAX_LEAGUE_SIZE - 1)
    xp_min, xp_max = TIER_XP_RANGES.get(tier, (50, 500))

    selected_names = random.sample(BOT_NAMES, min(num_bots, len(BOT_NAMES)))

    for i, _name in enumerate(selected_names):
        bot_user_id = -(i + 1)
        bot_xp = int(random.triangular(xp_min, xp_max, (xp_min + xp_max) // 2))

        db.execute(
            """INSERT OR IGNORE INTO league_members (league_id, user_id, weekly_xp, rank, promoted, demoted)
               VALUES (?, ?, ?, 0, 0, 0)""",
            (league_id, bot_user_id, bot_xp)
        )

    db.commit()
    log.info(f"Populated league {league_id} with {len(selected_names)} bots (tier: {tier})")


def get_bot_display_name(user_id: int) -> str:
    """Get display name for a bot user_id."""
    idx = abs(user_id) - 1
    if 0 <= idx < len(BOT_NAMES):
        return BOT_NAMES[idx]
    return f"Jogador {abs(user_id)}"


def recalculate_rankings(db, league_id: int):
    """Recalculate rankings for all members in a league based on XP."""
    members = db.execute(
        """SELECT id, user_id, weekly_xp FROM league_members
           WHERE league_id = ?
           ORDER BY weekly_xp DESC""",
        (league_id,)
    ).fetchall()

    for rank, member in enumerate(members, 1):
        db.execute(
            "UPDATE league_members SET rank = ? WHERE id = ?",
            (rank, member[0])
        )

    db.commit()


def ensure_user_league(db, user_id: int) -> dict:
    """Ensure user has a league for the current week. Create one if needed."""
    # Run migration on first access
    migrate_liga_column(db)

    week_start, week_end = get_current_week_bounds()

    # Check if user already has a league this week
    membership = db.execute(
        """SELECT lm.league_id, l.tier FROM league_members lm
           JOIN leagues l ON l.id = lm.league_id
           WHERE lm.user_id = ? AND l.week_start = ? AND l.week_end = ?""",
        (user_id, week_start, week_end)
    ).fetchone()

    if membership:
        league_id = membership[0]
        tier = membership[1]
        # Always recalculate and update XP on access
        xp_data = calculate_user_weekly_xp(db, user_id, week_start, week_end)
        db.execute(
            "UPDATE league_members SET weekly_xp = ? WHERE league_id = ? AND user_id = ?",
            (xp_data["total"], league_id, user_id)
        )
        db.commit()
        # Recalculate rankings after XP update
        recalculate_rankings(db, league_id)
        # Progress bots slightly each time
        _progress_bots(db, league_id)
        return {"league_id": league_id, "tier": tier}

    # Determine user's tier
    tier = get_user_tier(db, user_id)

    # Try to find an existing league with space this week
    existing_league = db.execute(
        """SELECT l.id FROM leagues l
           WHERE l.week_start = ? AND l.week_end = ? AND l.tier = ?
           AND (SELECT COUNT(*) FROM league_members WHERE league_id = l.id) < ?""",
        (week_start, week_end, tier, MAX_LEAGUE_SIZE)
    ).fetchone()

    if existing_league:
        league_id = existing_league[0]
    else:
        # Create a new league
        now = datetime.now().isoformat()
        db.execute(
            """INSERT INTO leagues (week_start, week_end, tier, created_at)
               VALUES (?, ?, ?, ?)""",
            (week_start, week_end, tier, now)
        )
        db.commit()
        league_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        log.info(f"Created new league {league_id} for tier {tier}, week {week_start}")

        # Populate with bots
        populate_bots(db, league_id, tier)

    # Add user to league (or update XP if already member)
    xp_data = calculate_user_weekly_xp(db, user_id, week_start, week_end)
    db.execute(
        """INSERT OR IGNORE INTO league_members (league_id, user_id, weekly_xp, rank, promoted, demoted)
           VALUES (?, ?, ?, 0, 0, 0)""",
        (league_id, user_id, xp_data["total"])
    )
    # Always update XP to reflect current activity
    db.execute(
        "UPDATE league_members SET weekly_xp = ? WHERE league_id = ? AND user_id = ?",
        (xp_data["total"], league_id, user_id)
    )
    db.commit()

    # Update users table with current tier
    try:
        db.execute("UPDATE users SET liga = ? WHERE id = ?", (tier, user_id))
        db.commit()
    except Exception:
        pass

    # Recalculate rankings
    recalculate_rankings(db, league_id)

    return {"league_id": league_id, "tier": tier}


def _progress_bots(db, league_id: int):
    """Simulate small XP gains for bots to make leaderboard feel alive."""
    league = db.execute(
        "SELECT tier FROM leagues WHERE id = ?", (league_id,)
    ).fetchone()
    if not league:
        return

    tier = league[0]
    xp_min, xp_max = TIER_XP_RANGES.get(tier, (50, 500))

    bots = db.execute(
        """SELECT id, weekly_xp FROM league_members
           WHERE league_id = ? AND user_id < 0""",
        (league_id,)
    ).fetchall()

    for bot in bots:
        if random.random() < 0.6:
            increment = random.randint(1, max(1, xp_max // 50))
            new_xp = bot[1] + increment
            db.execute(
                "UPDATE league_members SET weekly_xp = ? WHERE id = ?",
                (new_xp, bot[0])
            )

    db.commit()


# ─── NEW: /api/liga Endpoints (as specified) ──────────────────────────────────

