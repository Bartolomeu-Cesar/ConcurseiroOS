"""League/Liga endpoints: liga semanal, histórico, processar semana, XP."""
from datetime import date, datetime

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from logger import log

from .helpers import (
    DEMOTION_ZONE,
    MAX_LEAGUE_SIZE,
    MIN_LEAGUE_SIZE,
    PROMOTION_ZONE,
    TIER_ICONS,
    TIER_LABELS,
    TIER_XP_RANGES,
    TIERS,
    _progress_bots,
    calculate_user_weekly_xp,
    ensure_user_league,
    get_bot_display_name,
    get_current_week_bounds,
    get_days_remaining,
    get_user_tier,
    migrate_liga_column,
    recalculate_rankings,
)

router = APIRouter(prefix="", tags=["Ligas"])

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
        ensure_user_league(db, user_id)
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
