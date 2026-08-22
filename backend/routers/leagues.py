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
from datetime import date, timedelta, datetime
from fastapi import APIRouter, Depends, HTTPException
from database import get_db_session
from deps import get_user_id
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
    }

    # 1. XP from questions answered correctly: +10 XP each
    try:
        questions = db.execute(
            """SELECT COUNT(*) FROM questoes_respostas
            WHERE user_id = ?
            AND date(respondida_em) >= ? AND date(respondida_em) <= ?
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
            """SELECT COALESCE(SUM(
                CAST((julianday(fim) - julianday(inicio)) * 24 AS REAL)
            ), 0) as hours
            FROM sessoes_estudo
            WHERE user_id = ?
            AND date(inicio) >= ? AND date(inicio) <= ?
            AND fim IS NOT NULL""",
            (user_id, week_start, week_end)
        ).fetchone()
        if sessions and sessions[0]:
            breakdown["horas_estudo"] = int(float(sessions[0]) * XP_PER_HOUR)
    except Exception as e:
        log.warning(f"Error calculating session XP: {e}")

    # 3. XP from flashcard reviews: +5 XP each
    try:
        flashcards = db.execute(
            """SELECT COUNT(*) FROM flashcard_reviews
            WHERE user_id = ?
            AND date(reviewed_at) >= ? AND date(reviewed_at) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if flashcards and flashcards[0]:
            breakdown["flashcards"] = flashcards[0] * XP_PER_FLASHCARD
    except Exception as e:
        log.warning(f"Error calculating flashcard XP: {e}")

    # 4. XP from completed daily challenges: +50 XP each
    try:
        desafios = db.execute(
            """SELECT COUNT(*) FROM desafios
            WHERE user_id = ?
            AND finalizado = 1
            AND date(created_at) >= ? AND date(created_at) <= ?""",
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
    except Exception as e:
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

    total = sum(breakdown.values())
    return {"total": total, "breakdown": breakdown}


def populate_bots(db, league_id: int, tier: str):
    """Populate a league with simulated bot members."""
    num_bots = random.randint(MIN_LEAGUE_SIZE - 1, MAX_LEAGUE_SIZE - 1)
    xp_min, xp_max = TIER_XP_RANGES.get(tier, (50, 500))

    selected_names = random.sample(BOT_NAMES, min(num_bots, len(BOT_NAMES)))

    for i, name in enumerate(selected_names):
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
        return {"league_id": membership[0], "tier": membership[1]}

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

    # Add user to league
    xp_data = calculate_user_weekly_xp(db, user_id, week_start, week_end)
    db.execute(
        """INSERT OR IGNORE INTO league_members (league_id, user_id, weekly_xp, rank, promoted, demoted)
           VALUES (?, ?, ?, 0, 0, 0)""",
        (league_id, user_id, xp_data["total"])
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

@router.get("/api/liga")
def get_liga_semanal(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """GET /api/liga — Current week's league status.
    Returns: {liga_atual, posicao, total_jogadores, ranking, semana_inicio, semana_fim,
              zona_promocao, zona_rebaixamento, xp_semana, xp_breakdown, xp_para_promocao}
    """
    log.info(f"GET /api/liga for user {user_id}")

    league_info = ensure_user_league(db, user_id)
    league_id = league_info["league_id"]
    tier = league_info["tier"]
    week_start, week_end = get_current_week_bounds()

    # Get all members with rankings
    members = db.execute(
        """SELECT user_id, weekly_xp, rank FROM league_members
           WHERE league_id = ?
           ORDER BY rank ASC""",
        (league_id,)
    ).fetchall()

    total_members = len(members)

    # Build ranking list
    ranking = []
    user_rank = 0
    user_xp = 0
    promo_threshold_xp = 0

    for member in members:
        member_user_id = member[0]
        member_xp = member[1]
        member_rank = member[2]

        if member_user_id == user_id:
            user_rank = member_rank
            user_xp = member_xp

        # Get name
        if member_user_id == user_id:
            # Get user's real name
            try:
                user_row = db.execute(
                    "SELECT nome, avatar FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                nome = user_row[0] if user_row and user_row[0] else "Você"
                avatar = user_row[1] if user_row else ""
            except Exception:
                nome = "Você"
                avatar = ""
        elif member_user_id < 0:
            nome = get_bot_display_name(member_user_id)
            avatar = ""
        else:
            try:
                other_user = db.execute(
                    "SELECT nome, avatar FROM users WHERE id = ?", (member_user_id,)
                ).fetchone()
                nome = other_user[0] if other_user and other_user[0] else f"Usuário {member_user_id}"
                avatar = other_user[1] if other_user else ""
            except Exception:
                nome = f"Usuário {member_user_id}"
                avatar = ""

        # Track promotion zone XP threshold (the XP of the person at position PROMOTION_ZONE)
        if member_rank == PROMOTION_ZONE:
            promo_threshold_xp = member_xp

        ranking.append({
            "user_id": member_user_id,
            "nome": nome,
            "xp_semana": member_xp,
            "avatar": avatar,
            "posicao": member_rank,
            "is_current_user": member_user_id == user_id,
            "zona": "promocao" if member_rank <= PROMOTION_ZONE else
                    "rebaixamento" if member_rank > total_members - DEMOTION_ZONE else
                    "segura",
        })

    # Calculate XP needed for promotion
    xp_para_promocao = max(0, promo_threshold_xp - user_xp + 1) if user_rank > PROMOTION_ZONE else 0

    # Get XP breakdown
    xp_data = calculate_user_weekly_xp(db, user_id, week_start, week_end)

    return {
        "liga_atual": tier,
        "liga_label": TIER_LABELS.get(tier, tier.capitalize()),
        "liga_icon": TIER_ICONS.get(tier, "🏆"),
        "posicao": user_rank,
        "total_jogadores": total_members,
        "ranking": ranking,
        "semana_inicio": week_start,
        "semana_fim": week_end,
        "zona_promocao": PROMOTION_ZONE,
        "zona_rebaixamento": DEMOTION_ZONE,
        "dias_restantes": get_days_remaining(),
        "xp_semana": user_xp,
        "xp_breakdown": xp_data["breakdown"],
        "xp_para_promocao": xp_para_promocao,
    }


@router.get("/api/liga/historico")
def get_liga_historico(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """GET /api/liga/historico — Past weeks results."""
    log.info(f"GET /api/liga/historico for user {user_id}")

    history = db.execute(
        """SELECT week_start, week_end, tier, final_rank, final_xp, promoted, demoted
           FROM league_history
           WHERE user_id = ?
           ORDER BY week_end DESC
           LIMIT 20""",
        (user_id,)
    ).fetchall()

    results = []
    for row in history:
        tier = row[2]
        tier_idx = TIERS.index(tier) if tier in TIERS else 0

        if row[5]:  # promoted
            next_tier = TIERS[tier_idx + 1] if tier_idx < len(TIERS) - 1 else tier
            resultado = "promoted"
            resultado_label = f"Promovido para {TIER_LABELS.get(next_tier, next_tier)}"
        elif row[6]:  # demoted
            prev_tier = TIERS[tier_idx - 1] if tier_idx > 0 else tier
            resultado = "demoted"
            resultado_label = f"Rebaixado para {TIER_LABELS.get(prev_tier, prev_tier)}"
        else:
            resultado = "maintained"
            resultado_label = "Manteve posição"

        results.append({
            "semana_inicio": row[0],
            "semana_fim": row[1],
            "liga": tier,
            "liga_label": TIER_LABELS.get(tier, tier.capitalize()),
            "liga_icon": TIER_ICONS.get(tier, "🏆"),
            "posicao_final": row[3],
            "xp_final": row[4],
            "promovido": bool(row[5]),
            "rebaixado": bool(row[6]),
            "resultado": resultado,
            "resultado_label": resultado_label,
        })

    return {"historico": results}


@router.post("/api/liga/processar")
def processar_semana(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """POST /api/liga/processar — Process end-of-week (promote/demote).
    Top 3 → promote to next league.
    Bottom 3 → demote to previous league.
    Run via cron or manually at week end.
    """
    log.info(f"POST /api/liga/processar (triggered by user {user_id})")

    # Run migration
    migrate_liga_column(db)

    week_start, week_end = get_current_week_bounds()

    # Find all leagues for weeks that have ended (or current if it's Sunday)
    today_iso = date.today().isoformat()
    leagues_to_process = db.execute(
        """SELECT id, tier, week_start, week_end FROM leagues
           WHERE week_end <= ?
           AND id NOT IN (
               SELECT DISTINCT league_id FROM league_history lh
               JOIN league_members lm ON lm.league_id = leagues.id
               WHERE lm.user_id > 0
           )""",
        (today_iso,)
    ).fetchall()

    # Fallback: process current week if it's the end
    if not leagues_to_process:
        leagues_to_process = db.execute(
            """SELECT id, tier, week_start, week_end FROM leagues
               WHERE week_end <= ?""",
            (today_iso,)
        ).fetchall()

    processed_count = 0
    promotions = []
    demotions = []

    for league in leagues_to_process:
        league_id = league[0]
        tier = league[1]
        l_week_start = league[2]
        l_week_end = league[3]
        tier_idx = TIERS.index(tier) if tier in TIERS else 0

        # Check if already processed
        already_processed = db.execute(
            """SELECT COUNT(*) FROM league_history
               WHERE user_id > 0 AND week_start = ? AND week_end = ?""",
            (l_week_start, l_week_end)
        ).fetchone()
        if already_processed and already_processed[0] > 0:
            continue

        # Get final rankings
        members = db.execute(
            """SELECT id, user_id, weekly_xp, rank FROM league_members
               WHERE league_id = ?
               ORDER BY weekly_xp DESC""",
            (league_id,)
        ).fetchall()

        total = len(members)
        if total == 0:
            continue

        for rank, member in enumerate(members, 1):
            member_id = member[0]
            member_user_id = member[1]
            member_xp = member[2]

            promoted = 1 if rank <= PROMOTION_ZONE and tier_idx < len(TIERS) - 1 else 0
            demoted = 1 if rank > total - DEMOTION_ZONE and tier_idx > 0 else 0

            # Update member record
            db.execute(
                """UPDATE league_members
                   SET rank = ?, promoted = ?, demoted = ?
                   WHERE id = ?""",
                (rank, promoted, demoted, member_id)
            )

            # Archive to history and update users table (only real users)
            if member_user_id > 0:
                db.execute(
                    """INSERT INTO league_history
                       (user_id, week_start, week_end, tier, final_rank, final_xp, promoted, demoted, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (member_user_id, l_week_start, l_week_end, tier, rank, member_xp,
                     promoted, demoted, datetime.now().isoformat())
                )

                # Update user's liga in users table
                new_tier = tier
                if promoted and tier_idx < len(TIERS) - 1:
                    new_tier = TIERS[tier_idx + 1]
                    promotions.append(member_user_id)
                elif demoted and tier_idx > 0:
                    new_tier = TIERS[tier_idx - 1]
                    demotions.append(member_user_id)

                try:
                    db.execute(
                        "UPDATE users SET liga = ? WHERE id = ?",
                        (new_tier, member_user_id)
                    )
                except Exception:
                    pass

        db.commit()
        processed_count += 1
        log.info(f"Processed league {league_id} (tier: {tier}, members: {total})")

    return {
        "processed_leagues": processed_count,
        "promotions": len(promotions),
        "demotions": len(demotions),
        "message": f"{processed_count} liga(s) processada(s). "
                   f"{len(promotions)} promoção(ões), {len(demotions)} rebaixamento(s).",
    }


# ─── Original /api/leagues/* Endpoints (backward compatible) ──────────────────

@router.get("/api/leagues/current")
def get_current_league(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Get user's current league standings (backward compatible)."""
    log.info(f"Getting current league for user {user_id}")

    league_info = ensure_user_league(db, user_id)
    league_id = league_info["league_id"]
    tier = league_info["tier"]

    members = db.execute(
        """SELECT user_id, weekly_xp, rank FROM league_members
           WHERE league_id = ?
           ORDER BY rank ASC""",
        (league_id,)
    ).fetchall()

    total_members = len(members)
    standings = []
    user_rank = 0

    for member in members:
        member_user_id = member[0]
        member_xp = member[1]
        member_rank = member[2]

        if member_user_id == user_id:
            display_name = "Você"
            is_current_user = True
            user_rank = member_rank
        elif member_user_id < 0:
            display_name = get_bot_display_name(member_user_id)
            is_current_user = False
        else:
            display_name = f"Usuário {member_user_id}"
            is_current_user = False

        zone = "safe"
        if member_rank <= PROMOTION_ZONE:
            zone = "promotion"
        elif member_rank > total_members - DEMOTION_ZONE:
            zone = "demotion"

        standings.append({
            "rank": member_rank,
            "name": display_name,
            "xp": member_xp,
            "is_current_user": is_current_user,
            "is_me": is_current_user,
            "zone": zone,
        })

    return {
        "league_id": league_id,
        "tier": tier,
        "tier_label": TIER_LABELS.get(tier, tier.capitalize()),
        "user_rank": user_rank,
        "total_members": total_members,
        "standings": standings,
        "days_remaining": get_days_remaining(),
        "promotion_zone": PROMOTION_ZONE,
        "demotion_zone": DEMOTION_ZONE,
        "week_start": get_current_week_bounds()[0],
        "week_end": get_current_week_bounds()[1],
    }


@router.get("/api/leagues/history")
def get_league_history(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Get user's league history (backward compatible for frontend)."""
    log.info(f"Getting league history for user {user_id}")

    history = db.execute(
        """SELECT week_start, week_end, tier, final_rank, final_xp, promoted, demoted
           FROM league_history
           WHERE user_id = ?
           ORDER BY week_end DESC
           LIMIT 20""",
        (user_id,)
    ).fetchall()

    results = []
    for row in history:
        tier = row[2]
        tier_idx = TIERS.index(tier) if tier in TIERS else 0

        result = "maintained"
        if row[5]:
            result = "promoted"
        elif row[6]:
            result = "demoted"

        results.append({
            "week_start": row[0],
            "week_end": row[1],
            "tier": tier,
            "tier_label": TIER_LABELS.get(tier, tier.capitalize()),
            "final_rank": row[3],
            "final_xp": row[4],
            "position": row[3],
            "promoted": bool(row[5]),
            "demoted": bool(row[6]),
            "result": result,
        })

    return {"history": results}


@router.post("/api/leagues/update-xp")
def update_league_xp(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Update user's weekly XP in current league. Recalculates rankings."""
    log.info(f"Updating league XP for user {user_id}")

    week_start, week_end = get_current_week_bounds()

    membership = db.execute(
        """SELECT lm.id, lm.league_id FROM league_members lm
           JOIN leagues l ON l.id = lm.league_id
           WHERE lm.user_id = ? AND l.week_start = ? AND l.week_end = ?""",
        (user_id, week_start, week_end)
    ).fetchone()

    if not membership:
        league_info = ensure_user_league(db, user_id)
        membership = db.execute(
            """SELECT lm.id, lm.league_id FROM league_members lm
               JOIN leagues l ON l.id = lm.league_id
               WHERE lm.user_id = ? AND l.week_start = ? AND l.week_end = ?""",
            (user_id, week_start, week_end)
        ).fetchone()

    if not membership:
        raise HTTPException(status_code=404, detail="Não foi possível encontrar liga do usuário")

    member_id = membership[0]
    league_id = membership[1]

    # Recalculate actual XP from all activities
    xp_data = calculate_user_weekly_xp(db, user_id, week_start, week_end)
    new_xp = xp_data["total"]

    db.execute(
        "UPDATE league_members SET weekly_xp = ? WHERE id = ?",
        (new_xp, member_id)
    )
    db.commit()

    # Simulate bot XP progression
    _progress_bots(db, league_id)

    # Recalculate rankings
    recalculate_rankings(db, league_id)

    updated = db.execute(
        "SELECT rank, weekly_xp FROM league_members WHERE id = ?",
        (member_id,)
    ).fetchone()

    return {
        "weekly_xp": updated[1] if updated else new_xp,
        "rank": updated[0] if updated else 0,
        "league_id": league_id,
        "xp_breakdown": xp_data["breakdown"],
    }


@router.post("/api/leagues/process-week")
def process_week_end(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Process end-of-week (backward compatible alias)."""
    return processar_semana(user_id=user_id, db=db)


@router.get("/api/leagues/tier-info")
def get_tier_info(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Returns info about all tiers."""
    log.info(f"Getting tier info for user {user_id}")

    current_tier = get_user_tier(db, user_id)

    tiers_info = []
    for i, tier in enumerate(TIERS):
        xp_min, xp_max = TIER_XP_RANGES[tier]
        tiers_info.append({
            "tier": tier,
            "label": TIER_LABELS[tier],
            "icon": TIER_ICONS[tier],
            "order": i + 1,
            "xp_range_min": xp_min,
            "xp_range_max": xp_max,
            "is_current": tier == current_tier,
            "is_unlocked": TIERS.index(tier) <= TIERS.index(current_tier),
        })

    return {
        "current_tier": current_tier,
        "current_tier_label": TIER_LABELS.get(current_tier, current_tier.capitalize()),
        "current_tier_icon": TIER_ICONS.get(current_tier, "🏆"),
        "tiers": tiers_info,
        "promotion_top": PROMOTION_ZONE,
        "demotion_bottom": DEMOTION_ZONE,
        "league_size": f"{MIN_LEAGUE_SIZE}-{MAX_LEAGUE_SIZE}",
    }
