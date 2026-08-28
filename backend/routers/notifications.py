"""Router de Push Notifications para ConcurseiroOS."""
import json
import os
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from database import get_db_session
from deps import get_user_id
from logger import log
from notification_templates import (
    get_streak_notification,
    get_flashcard_notification,
    get_exam_notification,
    get_challenge_notification,
    get_inactivity_notification,
    get_study_suggestion,
)

# ============================================================
# CONDITIONAL IMPORT: pywebpush
# ============================================================

try:
    from pywebpush import webpush, WebPushException
    WEBPUSH_AVAILABLE = True
except ImportError:
    WEBPUSH_AVAILABLE = False
    log.warning("pywebpush not installed - push notifications will be disabled")

# ============================================================
# VAPID KEY MANAGEMENT
# ============================================================

_BACKEND_DIR = Path(__file__).parent.parent
_VAPID_PRIVATE_KEY_FILE = _BACKEND_DIR / ".vapid_private_key"
_VAPID_PUBLIC_KEY_FILE = _BACKEND_DIR / ".vapid_public_key"
_VAPID_SUBJECT = "mailto:admin@concurseiroos.app"


def _get_vapid_keys() -> tuple[str, str]:
    """Obtém VAPID keys de forma persistente.

    1. Se env vars VAPID_PRIVATE_KEY e VAPID_PUBLIC_KEY estão definidas, usa elas
    2. Se arquivos .vapid_private_key e .vapid_public_key existem, lê deles
    3. Senão, gera novas keys e salva nos arquivos
    """
    env_private = os.environ.get("VAPID_PRIVATE_KEY")
    env_public = os.environ.get("VAPID_PUBLIC_KEY")

    if env_private and env_public:
        return env_private, env_public

    if _VAPID_PRIVATE_KEY_FILE.exists() and _VAPID_PUBLIC_KEY_FILE.exists():
        private_key = _VAPID_PRIVATE_KEY_FILE.read_text().strip()
        public_key = _VAPID_PUBLIC_KEY_FILE.read_text().strip()
        return private_key, public_key

    # Generate new VAPID keys
    try:
        from py_vapid import Vapid
        vapid = Vapid()
        vapid.generate_keys()
        private_key = vapid.private_pem().decode("utf-8")
        public_key = vapid.public_key_urlsafe_base64()
    except ImportError:
        # Fallback: generate a placeholder - user must provide real keys
        log.warning("py_vapid not available - generating placeholder VAPID keys")
        private_key = secrets.token_urlsafe(32)
        public_key = secrets.token_urlsafe(65)

    try:
        _VAPID_PRIVATE_KEY_FILE.write_text(private_key)
        _VAPID_PUBLIC_KEY_FILE.write_text(public_key)
    except OSError:
        pass  # Em ambientes read-only, usa as keys em memória

    return private_key, public_key


VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY = _get_vapid_keys()

# ============================================================
# PYDANTIC MODELS
# ============================================================


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


class PushSendRequest(BaseModel):
    user_id: int
    title: str
    body: str
    url: str = ""
    tag: str = ""


class NotificationPreferences(BaseModel):
    streak_reminders: bool = True
    flashcard_reminders: bool = True
    exam_reminders: bool = True
    challenge_reminders: bool = True
    quiet_hours_start: int = Field(default=22, ge=0, le=23)
    quiet_hours_end: int = Field(default=7, ge=0, le=23)


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def _ensure_tables(conn):
    """Cria tabelas de push notifications se não existirem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id INTEGER PRIMARY KEY,
            streak_reminders INTEGER DEFAULT 1,
            flashcard_reminders INTEGER DEFAULT 1,
            exam_reminders INTEGER DEFAULT 1,
            challenge_reminders INTEGER DEFAULT 1,
            quiet_hours_start INTEGER DEFAULT 22,
            quiet_hours_end INTEGER DEFAULT 7
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            titulo TEXT NOT NULL,
            corpo TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _is_quiet_hours(conn, user_id: int) -> bool:
    """Verifica se estamos no horário silencioso do usuário."""
    prefs = conn.execute(
        "SELECT quiet_hours_start, quiet_hours_end FROM notification_preferences WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if not prefs:
        start, end = 22, 7
    else:
        start, end = prefs["quiet_hours_start"], prefs["quiet_hours_end"]

    now_hour = datetime.now().hour

    if start > end:
        # Crosses midnight, e.g., 22:00 to 07:00
        return now_hour >= start or now_hour < end
    else:
        # Same day, e.g., 01:00 to 06:00
        return start <= now_hour < end


def _already_sent_today(conn, user_id: int, tipo: str) -> bool:
    """Verifica se já enviou notificação deste tipo hoje (rate limiting)."""
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM notification_log WHERE user_id = ? AND tipo = ? AND sent_at >= ?",
        (user_id, tipo, today)
    ).fetchone()
    return row["cnt"] > 0 if row else False


def _log_notification(conn, user_id: int, tipo: str, titulo: str, corpo: str):
    """Registra notificação enviada no log."""
    conn.execute(
        "INSERT INTO notification_log (user_id, tipo, titulo, corpo, sent_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, tipo, titulo, corpo, datetime.now().isoformat())
    )
    conn.commit()


def _send_push_to_user(conn, user_id: int, title: str, body: str, url: str = "", tag: str = "") -> int:
    """Envia push notification para todas as subscriptions de um usuário.

    Returns: número de envios bem-sucedidos.
    """
    if not WEBPUSH_AVAILABLE:
        log.warning("Push notification skipped - pywebpush not available")
        return 0

    subscriptions = conn.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
        (user_id,)
    ).fetchall()

    if not subscriptions:
        return 0

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag,
    })

    vapid_claims = {
        "sub": _VAPID_SUBJECT,
    }

    sent_count = 0
    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"],
            }
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims,
            )
            sent_count += 1
        except WebPushException as e:
            log.warning(f"Push failed for endpoint {sub['endpoint'][:50]}...: {e}")
            # Se o endpoint retornou 410 Gone, remover subscription
            if hasattr(e, 'response') and e.response is not None and e.response.status_code == 410:
                conn.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?",
                    (sub["endpoint"], user_id)
                )
                conn.commit()
                log.info(f"Removed expired subscription for user {user_id}")
        except Exception as e:
            log.warning(f"Unexpected push error: {e}")

    return sent_count


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(prefix="", tags=["Push Notifications"])


# ============================================================
# SUBSCRIPTION MANAGEMENT
# ============================================================


@router.post("/api/push/subscribe", summary="Registrar push subscription")
def subscribe(body: PushSubscribeRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Armazena uma push subscription para o usuário autenticado."""
    _ensure_tables(conn)

    # Upsert: se endpoint já existe, atualiza keys e user_id
    conn.execute("""
        INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(endpoint) DO UPDATE SET
            user_id = excluded.user_id,
            p256dh = excluded.p256dh,
            auth = excluded.auth,
            created_at = excluded.created_at
    """, (user_id, body.endpoint, body.keys.p256dh, body.keys.auth, datetime.now().isoformat()))
    conn.commit()

    log.info(f"Push subscription registered for user {user_id}")
    return {"ok": True, "vapid_public_key": VAPID_PUBLIC_KEY}


@router.delete("/api/push/unsubscribe", summary="Remover push subscription")
def unsubscribe(body: PushUnsubscribeRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Remove uma push subscription pelo endpoint."""
    _ensure_tables(conn)

    result = conn.execute(
        "DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?",
        (body.endpoint, user_id)
    )
    conn.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Subscription não encontrada")

    log.info(f"Push subscription removed for user {user_id}")
    return {"ok": True}


@router.get("/api/push/status", summary="Status da subscription")
def get_push_status(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Verifica se o usuário tem uma subscription ativa."""
    _ensure_tables(conn)

    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM push_subscriptions WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    has_subscription = row["cnt"] > 0 if row else False

    return {
        "subscribed": has_subscription,
        "vapid_public_key": VAPID_PUBLIC_KEY,
    }


# ============================================================
# SEND NOTIFICATION (internal/admin)
# ============================================================


@router.post("/api/push/send", summary="Enviar notificação para usuário")
def send_notification(body: PushSendRequest, conn=Depends(get_db_session)):
    """Envia uma push notification para um usuário específico.

    Endpoint para uso interno/admin. Não requer autenticação do destinatário.
    """
    _ensure_tables(conn)

    # Check quiet hours
    if _is_quiet_hours(conn, body.user_id):
        return {"ok": False, "reason": "quiet_hours", "sent": 0}

    # Rate limiting by tag
    if body.tag and _already_sent_today(conn, body.user_id, body.tag):
        return {"ok": False, "reason": "rate_limited", "sent": 0}

    sent = _send_push_to_user(conn, body.user_id, body.title, body.body, body.url, body.tag)

    if sent > 0 and body.tag:
        _log_notification(conn, body.user_id, body.tag, body.title, body.body)

    return {"ok": True, "sent": sent}


# ============================================================
# SCHEDULED TRIGGER CHECKS
# ============================================================


@router.post("/api/push/check-triggers", summary="Verificar e disparar notificações agendadas")
def check_triggers(conn=Depends(get_db_session)):
    """Verifica todas as condições de notificação e envia para usuários elegíveis.

    Chamado pelo background scheduler. Verifica:
    - Streak em risco: sem atividade hoje, com urgência escalável (gentle/urgent/critical)
    - Flashcards atrasados: >10 flashcards pendentes
    - Prova se aproximando: data da prova dentro de 30 dias
    - Desafio prestes a expirar: <1 dia restante em desafio ativo
    - Inatividade: sem estudo há 2+ dias
    """
    _ensure_tables(conn)

    results = {
        "streak_at_risk": 0,
        "flashcards_overdue": 0,
        "exam_approaching": 0,
        "challenge_expiring": 0,
        "inactivity": 0,
    }

    # Get all users with active subscriptions
    users = conn.execute(
        "SELECT DISTINCT user_id FROM push_subscriptions"
    ).fetchall()

    if not users:
        return {"ok": True, "notifications_sent": results}

    hoje = date.today().isoformat()
    now = datetime.now()

    for user_row in users:
        uid = user_row["user_id"]

        # Load preferences
        prefs = conn.execute(
            "SELECT * FROM notification_preferences WHERE user_id = ?", (uid,)
        ).fetchone()

        streak_enabled = prefs["streak_reminders"] if prefs else 1
        flashcard_enabled = prefs["flashcard_reminders"] if prefs else 1
        exam_enabled = prefs["exam_reminders"] if prefs else 1
        challenge_enabled = prefs["challenge_reminders"] if prefs else 1

        # Skip if in quiet hours
        if _is_quiet_hours(conn, uid):
            continue

        # --- 1. STREAK AT RISK (escalating urgency) ---
        if streak_enabled and now.hour >= 18:
            # Determine urgency level based on time of day
            if now.hour >= 22:
                urgency = "critical"
                tag_suffix = "critical"
            elif now.hour >= 20:
                urgency = "urgent"
                tag_suffix = "urgent"
            else:
                urgency = "gentle"
                tag_suffix = "gentle"

            streak_tag = f"streak_{tag_suffix}"
            if not _already_sent_today(conn, uid, streak_tag):
                # Check if user has any activity today
                activity = conn.execute(
                    "SELECT * FROM streaks WHERE data = ? AND user_id = ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)",
                    (hoje, uid)
                ).fetchone()

                if not activity:
                    # Get current streak count
                    streak_row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM streaks WHERE user_id = ? AND data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)",
                        (uid, (date.today() - timedelta(days=90)).isoformat())
                    ).fetchone()
                    streak_count = streak_row["cnt"] if streak_row else 0

                    # Get personalized study suggestion
                    suggestion = get_study_suggestion(conn, uid)

                    notif = get_streak_notification(streak=streak_count, urgency=urgency, suggestion=suggestion)
                    sent = _send_push_to_user(conn, uid, notif["title"], notif["body"], notif["url"], notif["tag"])
                    if sent > 0:
                        _log_notification(conn, uid, streak_tag, notif["title"], notif["body"])
                        results["streak_at_risk"] += 1

        # --- 2. FLASHCARDS OVERDUE ---
        if flashcard_enabled:
            if not _already_sent_today(conn, uid, "flashcards_overdue"):
                overdue = conn.execute(
                    "SELECT COUNT(*) as cnt FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
                    (hoje, uid)
                ).fetchone()

                if overdue and overdue["cnt"] > 10:
                    notif = get_flashcard_notification(count=overdue["cnt"])
                    sent = _send_push_to_user(conn, uid, notif["title"], notif["body"], notif["url"], notif["tag"])
                    if sent > 0:
                        _log_notification(conn, uid, "flashcards_overdue", notif["title"], notif["body"])
                        results["flashcards_overdue"] += 1

        # --- 3. EXAM APPROACHING ---
        if exam_enabled:
            if not _already_sent_today(conn, uid, "exam_approaching"):
                # Check calendario_eventos for upcoming exams
                threshold = (date.today() + timedelta(days=30)).isoformat()
                exams = conn.execute(
                    """SELECT titulo, data_inicio, banca FROM calendario_eventos
                       WHERE user_id = ? AND tipo = 'prova' AND data_inicio >= ? AND data_inicio <= ?
                       ORDER BY data_inicio ASC LIMIT 1""",
                    (uid, hoje, threshold)
                ).fetchone()

                if exams:
                    exam_date = exams["data_inicio"][:10]
                    days_left = (date.fromisoformat(exam_date) - date.today()).days
                    banca = exams["banca"] if "banca" in exams.keys() else ""
                    notif = get_exam_notification(
                        exam_name=exams["titulo"],
                        days_until=days_left,
                        banca=banca or ""
                    )
                    sent = _send_push_to_user(conn, uid, notif["title"], notif["body"], notif["url"], notif["tag"])
                    if sent > 0:
                        _log_notification(conn, uid, "exam_approaching", notif["title"], notif["body"])
                        results["exam_approaching"] += 1

        # --- 4. CHALLENGE ABOUT TO EXPIRE ---
        if challenge_enabled:
            if not _already_sent_today(conn, uid, "challenge_expiring"):
                # Active challenges with <1 day remaining
                desafios = conn.execute(
                    "SELECT id, titulo, dias, created_at, progresso, meta FROM desafios WHERE user_id = ? AND finalizado = 0",
                    (uid,)
                ).fetchall()

                for desafio in desafios:
                    try:
                        created = datetime.fromisoformat(desafio["created_at"])
                        expires = created + timedelta(days=desafio["dias"])
                        remaining = expires - now
                        if timedelta(0) < remaining < timedelta(days=1):
                            progresso = desafio["progresso"] if "progresso" in desafio.keys() else 0
                            meta = desafio["meta"] if "meta" in desafio.keys() else 1
                            pct = int((progresso / meta) * 100) if meta > 0 else 0
                            notif = get_challenge_notification(
                                titulo=desafio["titulo"],
                                progresso=progresso,
                                meta=meta,
                                pct=pct
                            )
                            sent = _send_push_to_user(conn, uid, notif["title"], notif["body"], notif["url"], notif["tag"])
                            if sent > 0:
                                _log_notification(conn, uid, "challenge_expiring", notif["title"], notif["body"])
                                results["challenge_expiring"] += 1
                            break  # Only one challenge notification per day
                    except (ValueError, TypeError):
                        continue

        # --- 5. INACTIVITY DETECTION ---
        if streak_enabled:
            if not _already_sent_today(conn, uid, "inactivity"):
                # Check last activity date
                last_activity = conn.execute(
                    """SELECT MAX(data) as last_date FROM streaks
                       WHERE user_id = ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)""",
                    (uid,)
                ).fetchone()

                if last_activity and last_activity["last_date"]:
                    last_date = date.fromisoformat(last_activity["last_date"])
                    days_inactive = (date.today() - last_date).days
                    if days_inactive >= 2:
                        notif = get_inactivity_notification(days_inactive=days_inactive)
                        sent = _send_push_to_user(conn, uid, notif["title"], notif["body"], notif["url"], notif["tag"])
                        if sent > 0:
                            _log_notification(conn, uid, "inactivity", notif["title"], notif["body"])
                            results["inactivity"] += 1

        # --- 6. SLEEP CONSOLIDATION REMINDER (21h-22h) ---
        if flashcard_enabled and 21 <= now.hour <= 22:
            if not _already_sent_today(conn, uid, "sleep_consolidation"):
                # Check if user has errors today that need consolidation
                erros_hoje = conn.execute(
                    "SELECT COUNT(*) as cnt FROM questoes_respostas WHERE user_id = ? AND data = ? AND acertou = 0",
                    (uid, hoje)
                ).fetchone()
                fc_frageis = conn.execute(
                    "SELECT COUNT(*) as cnt FROM flashcards WHERE user_id = ? AND stability > 0 AND stability <= 3",
                    (uid,)
                ).fetchone()
                total_itens = (erros_hoje["cnt"] or 0) + (fc_frageis["cnt"] or 0)

                if total_itens > 0:
                    sent = _send_push_to_user(
                        conn, uid,
                        "🌙 Revisão Pré-Sono",
                        f"Revise {total_itens} itens antes de dormir para +20% retenção amanhã. Seu cérebro consolida memórias durante o sono!",
                        "/",
                        "sleep_consolidation"
                    )
                    if sent > 0:
                        _log_notification(conn, uid, "sleep_consolidation", "🌙 Revisão Pré-Sono", f"{total_itens} itens")
                        results["sleep_consolidation"] = results.get("sleep_consolidation", 0) + 1

        # --- 7. DAILY META NOT REACHED (20h-21h) ---
        if streak_enabled and 20 <= now.hour <= 21:
            if not _already_sent_today(conn, uid, "meta_diaria"):
                try:
                    meta = conn.execute("SELECT meta_horas, meta_questoes FROM metas_config WHERE user_id = ?", (uid,)).fetchone()
                    if meta:
                        streak_hoje = conn.execute("SELECT horas_estudadas, questoes_resolvidas FROM streaks WHERE data = ? AND user_id = ?", (hoje, uid)).fetchone()
                        horas_hoje = streak_hoje["horas_estudadas"] if streak_hoje else 0
                        quest_hoje = streak_hoje["questoes_resolvidas"] if streak_hoje else 0
                        meta_horas = meta["meta_horas"] or 3
                        meta_quest = meta["meta_questoes"] or 30
                        pct_horas = horas_hoje / meta_horas * 100 if meta_horas > 0 else 100
                        pct_quest = quest_hoje / meta_quest * 100 if meta_quest > 0 else 100

                        if pct_horas < 50 or pct_quest < 50:
                            falta_horas = max(0, meta_horas - horas_hoje)
                            falta_quest = max(0, meta_quest - quest_hoje)
                            msg = f"Faltam {falta_horas:.1f}h e {falta_quest} questões para bater a meta. Ainda dá tempo!"
                            sent = _send_push_to_user(conn, uid, "⚠️ Meta Diária", msg, "/", "meta_diaria")
                            if sent > 0:
                                _log_notification(conn, uid, "meta_diaria", "⚠️ Meta Diária", msg)
                                results["meta_diaria"] = results.get("meta_diaria", 0) + 1
                except Exception:
                    pass

    return {"ok": True, "notifications_sent": results}


@router.get("/api/push/auto-check", summary="Auto-check triggers (chamado pelo frontend no login)")
def auto_check_triggers(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Verifica triggers para o user atual e retorna alertas pendentes (sem enviar push).
    Chamado pelo frontend ao abrir o app para mostrar alertas inline."""
    _ensure_tables(conn)
    hoje = date.today().isoformat()
    now = datetime.now()
    alertas = []

    # Flashcards pendentes
    fc = conn.execute("SELECT COUNT(*) as cnt FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (hoje, user_id)).fetchone()
    if fc and fc["cnt"] > 5:
        alertas.append({"tipo": "flashcards", "icone": "🧠", "msg": f"{fc['cnt']} flashcards pendentes para revisão", "acao": "/#flashcards"})

    # Erros pendentes de revisão
    try:
        erros = conn.execute("SELECT COUNT(*) as cnt FROM erros_revisao WHERE user_id = ? AND proxima_revisao <= ?", (user_id, hoje)).fetchone()
        if erros and erros["cnt"] > 3:
            alertas.append({"tipo": "erros", "icone": "📝", "msg": f"{erros['cnt']} questões erradas agendadas para revisão", "acao": "/caderno-erros.html"})
    except Exception:
        pass

    # Sleep consolidation (se 21h-1h)
    if 21 <= now.hour or now.hour <= 1:
        alertas.append({"tipo": "sleep", "icone": "🌙", "msg": "Hora da revisão pré-sono! Revise erros do dia antes de dormir.", "acao": "/"})

    # Meta diária
    try:
        meta = conn.execute("SELECT meta_horas, meta_questoes FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
        streak_hoje = conn.execute("SELECT horas_estudadas, questoes_resolvidas FROM streaks WHERE data = ? AND user_id = ?", (hoje, user_id)).fetchone()
        if meta and streak_hoje:
            pct = (streak_hoje["horas_estudadas"] or 0) / (meta["meta_horas"] or 3) * 100
            if pct < 30 and now.hour >= 18:
                alertas.append({"tipo": "meta", "icone": "⚠️", "msg": f"Meta diária em {pct:.0f}%. Ainda dá tempo!", "acao": "/"})
    except Exception:
        pass

    return {"alertas": alertas, "total": len(alertas)}


# ============================================================
# NOTIFICATION PREFERENCES
# ============================================================


@router.get("/api/push/preferences", summary="Obter preferências de notificação")
def get_preferences(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna as preferências de notificação do usuário."""
    _ensure_tables(conn)

    row = conn.execute(
        "SELECT * FROM notification_preferences WHERE user_id = ?", (user_id,)
    ).fetchone()

    if not row:
        # Return defaults
        return {
            "streak_reminders": True,
            "flashcard_reminders": True,
            "exam_reminders": True,
            "challenge_reminders": True,
            "quiet_hours_start": 22,
            "quiet_hours_end": 7,
        }

    return {
        "streak_reminders": bool(row["streak_reminders"]),
        "flashcard_reminders": bool(row["flashcard_reminders"]),
        "exam_reminders": bool(row["exam_reminders"]),
        "challenge_reminders": bool(row["challenge_reminders"]),
        "quiet_hours_start": row["quiet_hours_start"],
        "quiet_hours_end": row["quiet_hours_end"],
    }


@router.put("/api/push/preferences", summary="Atualizar preferências de notificação")
def update_preferences(body: NotificationPreferences, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Atualiza as preferências de notificação do usuário."""
    _ensure_tables(conn)

    conn.execute("""
        INSERT INTO notification_preferences (user_id, streak_reminders, flashcard_reminders, exam_reminders, challenge_reminders, quiet_hours_start, quiet_hours_end)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            streak_reminders = excluded.streak_reminders,
            flashcard_reminders = excluded.flashcard_reminders,
            exam_reminders = excluded.exam_reminders,
            challenge_reminders = excluded.challenge_reminders,
            quiet_hours_start = excluded.quiet_hours_start,
            quiet_hours_end = excluded.quiet_hours_end
    """, (
        user_id,
        int(body.streak_reminders),
        int(body.flashcard_reminders),
        int(body.exam_reminders),
        int(body.challenge_reminders),
        body.quiet_hours_start,
        body.quiet_hours_end,
    ))
    conn.commit()

    log.info(f"Notification preferences updated for user {user_id}")
    return {"ok": True}


# ============================================================
# VAPID PUBLIC KEY ENDPOINT
# ============================================================


@router.get("/api/push/vapid-key", summary="Obter VAPID public key")
def get_vapid_key():
    """Retorna a VAPID public key para o frontend configurar o service worker."""
    # Re-read from file to ensure freshness after key regeneration
    if _VAPID_PUBLIC_KEY_FILE.exists():
        fresh_key = _VAPID_PUBLIC_KEY_FILE.read_text().strip()
        if fresh_key:
            return {"vapid_public_key": fresh_key}
    return {"vapid_public_key": VAPID_PUBLIC_KEY}
