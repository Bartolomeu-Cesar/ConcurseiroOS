"""
Leagues / Leaderboard System - Duolingo-style
Manages weekly competitive leagues with tier progression.
"""

import random
from datetime import date, timedelta, datetime
from fastapi import APIRouter, Depends, HTTPException
from database import get_db_session
from deps import get_user_id
from logger import log

router = APIRouter(prefix="", tags=["Ligas"])

# ─── Tier Configuration ───────────────────────────────────────────────────────

TIERS = ["bronze", "prata", "ouro", "diamante", "mestre"]

TIER_LABELS = {
    "bronze": "Bronze",
    "prata": "Prata",
    "ouro": "Ouro",
    "diamante": "Diamante",
    "mestre": "Mestre",
}

TIER_XP_RANGES = {
    "bronze": (50, 500),
    "prata": (200, 800),
    "ouro": (500, 1500),
    "diamante": (1000, 3000),
    "mestre": (2000, 5000),
}

PROMOTION_ZONE = 5  # Top 5 promote
DEMOTION_ZONE = 5   # Bottom 5 demote
MIN_LEAGUE_SIZE = 20
MAX_LEAGUE_SIZE = 25

# ─── Bot Names (realistic Brazilian names) ────────────────────────────────────

BOT_NAMES = [
    "Lucas S.", "Ana P.", "Carlos M.", "Fernanda R.", "João V.",
    "Mariana L.", "Pedro H.", "Juliana C.", "Rafael T.", "Beatriz A.",
    "Gabriel F.", "Camila O.", "Matheus D.", "Larissa N.", "Thiago B.",
    "Amanda G.", "Bruno K.", "Letícia W.", "Diego S.", "Isabela M.",
    "Vinícius R.", "Natália P.", "Gustavo L.", "Patrícia C.", "Felipe A.",
]

# ─── XP Constants (mirrored from constants.py) ────────────────────────────────

XP_PER_HOUR = 100
XP_PER_QUESTION = 10
XP_PER_FLASHCARD = 5


# ─── Helper Functions ─────────────────────────────────────────────────────────

def get_current_week_bounds() -> tuple[str, str]:
    """Get Monday 00:00 and Sunday 23:59 of the current week as ISO strings."""
    today = date.today()
    # Monday = isoweekday() == 1
    days_since_monday = today.isoweekday() - 1
    monday = today - timedelta(days=days_since_monday)
    sunday = monday + timedelta(days=6)
    week_start = monday.isoformat()
    week_end = sunday.isoformat()
    return week_start, week_end


def get_days_remaining() -> int:
    """Days remaining until end of current week (Sunday)."""
    today = date.today()
    days_since_monday = today.isoweekday() - 1
    return 6 - days_since_monday


def get_user_tier(db, user_id: int) -> str:
    """Determine user's current tier based on their history."""
    row = db.execute(
        """SELECT tier FROM league_history 
           WHERE user_id = ? 
           ORDER BY week_end DESC LIMIT 1""",
        (user_id,)
    ).fetchone()
    if row:
        last_tier = row[0]
        # Check if they were promoted or demoted last week
        last_history = db.execute(
            """SELECT tier, promoted, demoted FROM league_history
               WHERE user_id = ?
               ORDER BY week_end DESC LIMIT 1""",
            (user_id,)
        ).fetchone()
        if last_history:
            tier = last_history[0]
            promoted = last_history[1]
            demoted = last_history[2]
            tier_idx = TIERS.index(tier)
            if promoted and tier_idx < len(TIERS) - 1:
                return TIERS[tier_idx + 1]
            elif demoted and tier_idx > 0:
                return TIERS[tier_idx - 1]
            return tier
    return "bronze"


def calculate_user_weekly_xp(db, user_id: int, week_start: str, week_end: str) -> int:
    """Calculate user's XP earned this week from all activities."""
    total_xp = 0

    # XP from study sessions (sessoes_estudo) - based on duration
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
            total_xp += int(float(sessions[0]) * XP_PER_HOUR)
    except Exception as e:
        log.warning(f"Error calculating session XP: {e}")

    # XP from questions answered (questoes_respostas)
    try:
        questions = db.execute(
            """SELECT COUNT(*) FROM questoes_respostas
            WHERE user_id = ?
            AND date(respondida_em) >= ? AND date(respondida_em) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if questions and questions[0]:
            total_xp += questions[0] * XP_PER_QUESTION
    except Exception as e:
        log.warning(f"Error calculating question XP: {e}")

    # XP from flashcard reviews
    try:
        flashcards = db.execute(
            """SELECT COUNT(*) FROM flashcard_reviews
            WHERE user_id = ?
            AND date(reviewed_at) >= ? AND date(reviewed_at) <= ?""",
            (user_id, week_start, week_end)
        ).fetchone()
        if flashcards and flashcards[0]:
            total_xp += flashcards[0] * XP_PER_FLASHCARD
    except Exception as e:
        log.warning(f"Error calculating flashcard XP: {e}")

    return total_xp


def populate_bots(db, league_id: int, tier: str):
    """Populate a league with simulated bot members."""
    num_bots = random.randint(MIN_LEAGUE_SIZE - 1, MAX_LEAGUE_SIZE - 1)
    xp_min, xp_max = TIER_XP_RANGES.get(tier, (50, 500))

    selected_names = random.sample(BOT_NAMES, min(num_bots, len(BOT_NAMES)))

    for i, name in enumerate(selected_names):
        bot_user_id = -(i + 1)  # -1 to -25
        # Generate realistic XP with some variance (bell curve-ish)
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
    current_xp = calculate_user_weekly_xp(db, user_id, week_start, week_end)
    db.execute(
        """INSERT OR IGNORE INTO league_members (league_id, user_id, weekly_xp, rank, promoted, demoted)
           VALUES (?, ?, ?, 0, 0, 0)""",
        (league_id, user_id, current_xp)
    )
    db.commit()

    # Recalculate rankings
    recalculate_rankings(db, league_id)

    return {"league_id": league_id, "tier": tier}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/leagues/current")
def get_current_league(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Get user's current league standings.
    If user has no league this week, auto-assign or create one.
    Returns: tier, rank, standings, days_remaining, promotion_zone, demotion_zone.
    """
    log.info(f"Getting current league for user {user_id}")

    league_info = ensure_user_league(db, user_id)
    league_id = league_info["league_id"]
    tier = league_info["tier"]

    # Get all members with rankings
    members = db.execute(
        """SELECT user_id, weekly_xp, rank FROM league_members
           WHERE league_id = ?
           ORDER BY rank ASC""",
        (league_id,)
    ).fetchall()

    total_members = len(members)

    # Build standings list
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

        # Determine zone
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
    """Get user's league history (past weeks)."""
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

        result_label = "Manteve"
        if row[5]:  # promoted
            next_tier = TIERS[tier_idx + 1] if tier_idx < len(TIERS) - 1 else tier
            result_label = f"Promovido para {TIER_LABELS.get(next_tier, next_tier)}"
        elif row[6]:  # demoted
            prev_tier = TIERS[tier_idx - 1] if tier_idx > 0 else tier
            result_label = f"Rebaixado para {TIER_LABELS.get(prev_tier, prev_tier)}"

        results.append({
            "week_start": row[0],
            "week_end": row[1],
            "tier": tier,
            "tier_label": TIER_LABELS.get(tier, tier.capitalize()),
            "final_rank": row[3],
            "final_xp": row[4],
            "promoted": bool(row[5]),
            "demoted": bool(row[6]),
            "result_label": result_label,
        })

    return {"history": results}


@router.post("/api/leagues/update-xp")
def update_league_xp(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Called when user earns XP - updates their weekly XP in current league.
    Recalculates rankings."""
    log.info(f"Updating league XP for user {user_id}")

    week_start, week_end = get_current_week_bounds()

    # Find user's current league membership
    membership = db.execute(
        """SELECT lm.id, lm.league_id FROM league_members lm
           JOIN leagues l ON l.id = lm.league_id
           WHERE lm.user_id = ? AND l.week_start = ? AND l.week_end = ?""",
        (user_id, week_start, week_end)
    ).fetchone()

    if not membership:
        # Auto-assign to league
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

    # Recalculate actual XP from activities
    new_xp = calculate_user_weekly_xp(db, user_id, week_start, week_end)

    db.execute(
        "UPDATE league_members SET weekly_xp = ? WHERE id = ?",
        (new_xp, member_id)
    )
    db.commit()

    # Simulate bot XP progression (small random increments)
    _progress_bots(db, league_id)

    # Recalculate rankings
    recalculate_rankings(db, league_id)

    # Get updated rank
    updated = db.execute(
        "SELECT rank, weekly_xp FROM league_members WHERE id = ?",
        (member_id,)
    ).fetchone()

    return {
        "weekly_xp": updated[1] if updated else new_xp,
        "rank": updated[0] if updated else 0,
        "league_id": league_id,
    }


@router.post("/api/leagues/process-week")
def process_week_end(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Process end-of-week: calculate promotions/demotions, archive to history,
    create new leagues for next week. Can be called by cron or manually."""
    log.info(f"Processing week end (triggered by user {user_id})")

    week_start, week_end = get_current_week_bounds()

    # Find all leagues for the current (or most recent completed) week
    # Process leagues that haven't been processed yet
    leagues = db.execute(
        """SELECT id, tier, week_start, week_end FROM leagues
           WHERE week_end <= ?
           AND id NOT IN (
               SELECT DISTINCT league_id FROM league_members WHERE promoted = 1 OR demoted = 1
           )""",
        (date.today().isoformat(),)
    ).fetchall()

    if not leagues:
        # Try to process current week's leagues if it's Sunday or past Sunday
        leagues = db.execute(
            """SELECT id, tier, week_start, week_end FROM leagues
               WHERE week_end = ?""",
            (week_end,)
        ).fetchall()

    processed_count = 0

    for league in leagues:
        league_id = league[0]
        tier = league[1]
        l_week_start = league[2]
        l_week_end = league[3]
        tier_idx = TIERS.index(tier) if tier in TIERS else 0

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

        # Assign final ranks and determine promotions/demotions
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

            # Archive to history (only real users, not bots)
            if member_user_id > 0:
                db.execute(
                    """INSERT INTO league_history 
                       (user_id, week_start, week_end, tier, final_rank, final_xp, promoted, demoted)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (member_user_id, l_week_start, l_week_end, tier, rank, member_xp, promoted, demoted)
                )

        db.commit()
        processed_count += 1
        log.info(f"Processed league {league_id} (tier: {tier}, members: {total})")

    return {
        "processed_leagues": processed_count,
        "message": f"{processed_count} liga(s) processada(s) com sucesso.",
    }


@router.get("/api/leagues/tier-info")
def get_tier_info(
    user_id: int = Depends(get_user_id),
    db=Depends(get_db_session)
):
    """Returns info about all tiers and their XP requirements."""
    log.info(f"Getting tier info for user {user_id}")

    # Get user's current tier
    current_tier = get_user_tier(db, user_id)

    tiers_info = []
    for i, tier in enumerate(TIERS):
        xp_min, xp_max = TIER_XP_RANGES[tier]
        tiers_info.append({
            "tier": tier,
            "label": TIER_LABELS[tier],
            "order": i + 1,
            "xp_range_min": xp_min,
            "xp_range_max": xp_max,
            "is_current": tier == current_tier,
            "is_unlocked": TIERS.index(tier) <= TIERS.index(current_tier),
        })

    return {
        "current_tier": current_tier,
        "current_tier_label": TIER_LABELS.get(current_tier, current_tier.capitalize()),
        "tiers": tiers_info,
        "promotion_top": PROMOTION_ZONE,
        "demotion_bottom": DEMOTION_ZONE,
        "league_size": f"{MIN_LEAGUE_SIZE}-{MAX_LEAGUE_SIZE}",
    }


# ─── Internal Helpers ─────────────────────────────────────────────────────────

def _progress_bots(db, league_id: int):
    """Simulate small XP gains for bots to make leaderboard feel alive."""
    # Get league tier for XP range context
    league = db.execute(
        "SELECT tier FROM leagues WHERE id = ?", (league_id,)
    ).fetchone()
    if not league:
        return

    tier = league[0]
    xp_min, xp_max = TIER_XP_RANGES.get(tier, (50, 500))

    # Small random increment for some bots (not all, to feel realistic)
    bots = db.execute(
        """SELECT id, weekly_xp FROM league_members
           WHERE league_id = ? AND user_id < 0""",
        (league_id,)
    ).fetchall()

    for bot in bots:
        # ~60% chance each bot gains some XP on each update
        if random.random() < 0.6:
            # Increment proportional to tier difficulty
            increment = random.randint(1, max(1, xp_max // 50))
            new_xp = bot[1] + increment
            db.execute(
                "UPDATE league_members SET weekly_xp = ? WHERE id = ?",
                (new_xp, bot[0])
            )

    db.commit()
