"""Router de Push Notifications para ConcurseiroOS."""
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException
from notification_templates import (
    get_challenge_notification,
    get_exam_notification,
    get_flashcard_notification,
    get_inactivity_notification,
    get_streak_notification,
    get_study_suggestion,
)
from pydantic import BaseModel, Field

from database import get_db_session
from logger import log

# ============================================================
# CONDITIONAL IMPORT: pywebpush
# ============================================================

try:
    from pywebpush import WebPushException, webpush
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
        import base64 as b64

        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from py_vapid import Vapid

        vapid = Vapid()
        vapid.generate_keys()
        # Public key: uncompressed EC P-256 point (65 bytes) in base64url
        pub_raw = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        public_key = b64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()
        # Private key: raw 32 bytes in base64url
        priv_numbers = vapid.private_key.private_numbers()
        priv_raw = priv_numbers.private_value.to_bytes(32, "big")
        private_key = b64.urlsafe_b64encode(priv_raw).rstrip(b"=").decode()
    except ImportError:
        # Fallback: generate placeholder - push won't work without real keys
        log.warning("py_vapid/cryptography not available - push notifications disabled")
        private_key = ""
        public_key = ""

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
    # Novas preferências anti-relaxamento
    study_time_reminder: bool = True
    study_time_hour: int = Field(default=19, ge=0, le=23)
    edital_review_reminders: bool = True
    pace_drop_alerts: bool = True
    milestone_celebrations: bool = True
    # Alerta de DEFASAGEM/desequilíbrio: sugere focar no pilar negligenciado
    # (teoria, questões ou flashcards) para não perder o foco nos estudos.
    balance_alerts: bool = True


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
    # Novas preferências anti-relaxamento (idempotente — ALTER se faltar a coluna).
    for _col, _ddl in (
        ("study_time_reminder", "ALTER TABLE notification_preferences ADD COLUMN study_time_reminder INTEGER DEFAULT 1"),
        ("study_time_hour", "ALTER TABLE notification_preferences ADD COLUMN study_time_hour INTEGER DEFAULT 19"),
        ("edital_review_reminders", "ALTER TABLE notification_preferences ADD COLUMN edital_review_reminders INTEGER DEFAULT 1"),
        ("pace_drop_alerts", "ALTER TABLE notification_preferences ADD COLUMN pace_drop_alerts INTEGER DEFAULT 1"),
        ("milestone_celebrations", "ALTER TABLE notification_preferences ADD COLUMN milestone_celebrations INTEGER DEFAULT 1"),
        ("balance_alerts", "ALTER TABLE notification_preferences ADD COLUMN balance_alerts INTEGER DEFAULT 1"),
    ):
        try:
            conn.execute(_ddl)
        except Exception:
            pass  # coluna já existe
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            title TEXT DEFAULT '',
            body TEXT DEFAULT '',
            sent_at TEXT NOT NULL,
            success INTEGER DEFAULT 1
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
    """Verifica se já enviou notificação deste tipo hoje (rate limiting).

    A coluna canônica é `tag` (migração 30). O parâmetro mantém o nome `tipo`
    por retrocompatibilidade dos chamadores.
    """
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM notification_log WHERE user_id = ? AND tag = ? AND sent_at >= ?",
        (user_id, tipo, today)
    ).fetchone()
    return row["cnt"] > 0 if row else False


def _log_notification(conn, user_id: int, tipo: str, titulo: str, corpo: str):
    """Registra notificação enviada no log (colunas canônicas tag/title/body)."""
    conn.execute(
        "INSERT INTO notification_log (user_id, tag, title, body, sent_at, success) VALUES (?, ?, ?, ?, ?, 1)",
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


def _detectar_defasagem(conn, user_id: int) -> dict | None:
    """Detecta DESEQUILÍBRIO entre os pilares de estudo nos últimos 7 dias e sugere
    focar no que está sendo negligenciado, para o estudante não perder o foco.

    Pilares e sinais (janela de 7 dias):
      - Teoria: horas em sessoes_estudo de tipos de estudo (edital/ciclo/leitura/
        timer/studyroom/video/revisao_edital).
      - Questões: nº de questões respondidas.
      - Flashcards: nº de flashcards revisados + backlog vencido.

    Evidência: aprendizado eficaz alterna teoria (codificação) com prática de
    recuperação (questões/flashcards). Só teoria vira leitura passiva; só
    questões sem base vira decoreba; flashcards vencidos acumulados = curva do
    esquecimento. Retorna o desequilíbrio MAIS relevante (um por vez) ou None.

    Retorna dict {tipo, title, body, url} pronto para enviar, ou None.
    """
    hoje = date.today()
    ini_7d = (hoje - timedelta(days=6)).isoformat()

    # Tipos de sessão considerados "teoria/estudo" (exclui questões/simulado).
    tipos_teoria = ("edital", "ciclo", "leitura", "timer", "studyroom", "video", "revisao_edital", "feynman", "sumulas")
    ph = ",".join("?" for _ in tipos_teoria)
    horas_teoria = conn.execute(
        f"SELECT COALESCE(SUM(horas),0) FROM sessoes_estudo WHERE user_id = ? AND data >= ? AND tipo IN ({ph})",
        (user_id, ini_7d, *tipos_teoria),
    ).fetchone()[0] or 0

    n_questoes = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ? AND data >= ?",
        (user_id, ini_7d),
    ).fetchone()[0] or 0

    fc_revisados = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados),0) FROM streaks WHERE user_id = ? AND data >= ?",
        (user_id, ini_7d),
    ).fetchone()[0] or 0

    fc_vencidos = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE user_id = ? AND proxima_revisao <= ?",
        (user_id, hoje.isoformat()),
    ).fetchone()[0] or 0

    # Só faz sentido alertar sobre desequilíbrio se houve ALGUMA atividade na
    # semana (não confundir com inatividade total, já coberta por outro trigger).
    ativo = (horas_teoria > 0) or (n_questoes > 0) or (fc_revisados > 0)
    if not ativo:
        return None

    # 1) Flashcards vencidos acumulando e pouca revisão → priorizar revisão.
    if fc_vencidos >= 20 and fc_revisados < 10:
        return {
            "tipo": "balance_flashcards",
            "title": "🧠 Flashcards acumulando",
            "body": (
                f"Você tem {fc_vencidos} flashcards vencidos e revisou pouco esta semana. "
                "Revisar no prazo trava a curva do esquecimento — 10 min já ajudam muito."
            ),
            "url": "/#flashcards",
        }

    # 2) Muita prática (questões) mas SEM teoria nova → risco de decorar sem base.
    if n_questoes >= 20 and horas_teoria < 0.5:
        return {
            "tipo": "balance_teoria",
            "title": "📖 Hora de reforçar a teoria",
            "body": (
                f"Você resolveu {n_questoes} questões, mas quase não estudou teoria esta semana. "
                "Sem base conceitual, o acerto vira sorte — intercale teoria para fixar de verdade."
            ),
            "url": "/#edital",
        }

    # 3) Muita teoria mas QUASE sem questões → falta prática de recuperação.
    if horas_teoria >= 3 and n_questoes < 5:
        return {
            "tipo": "balance_questoes",
            "title": "✍️ Pratique com questões",
            "body": (
                f"Você estudou {horas_teoria:.1f}h de teoria, mas resolveu poucas questões. "
                "Resolver questões (retrieval practice) fixa muito mais do que reler — teste-se hoje!"
            ),
            "url": "/questoes.html",
        }

    # 4) MATÉRIA específica do ciclo ATIVO parada há muitos dias → retomar.
    # Filtra pelo ciclo ativo (regra do projeto: recomendações nunca mostram
    # matérias de concursos inativos). Escolhe a mais tempo sem ser estudada.
    materia_defasada = _detectar_materia_defasada(conn, user_id, dias_limite=7)
    if materia_defasada:
        return materia_defasada

    return None


def _detectar_materia_defasada(conn, user_id: int, dias_limite: int = 7) -> dict | None:
    """Acha a matéria do CICLO ATIVO parada há mais dias (>= dias_limite) e sugere
    retomá-la, para o estudo não ficar desbalanceado entre disciplinas.

    Regra do projeto: filtra por ciclo_estudos WHERE ativo = 1 (nunca sugere
    matéria de concurso inativo). Retorna dict pronto ou None.
    """
    try:
        materias_ciclo = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?",
                (user_id,),
            ).fetchall()
        ]
    except Exception:
        materias_ciclo = []
    if not materias_ciclo:
        return None

    hoje = date.today()
    ultima = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT materia, MAX(data) FROM sessoes_estudo WHERE user_id = ? GROUP BY materia",
            (user_id,),
        ).fetchall()
    }

    pior_materia = None
    pior_dias = -1
    for materia in materias_ciclo:
        u = ultima.get(materia)
        try:
            dias = (hoje - date.fromisoformat(u)).days if u else 999
        except (ValueError, TypeError):
            dias = 999
        # 999 = nunca estudada: só alerta se houver histórico geral (evita
        # spammar quem acabou de montar o ciclo). Tratado pelo 'ativo' externo.
        if dias >= dias_limite and dias > pior_dias:
            pior_dias = dias
            pior_materia = materia

    if not pior_materia:
        return None

    if pior_dias >= 999:
        corpo = (
            f"Você ainda não estudou '{pior_materia}' (está no seu ciclo ativo). "
            "Não deixe nenhuma disciplina para trás — comece com 25 min hoje."
        )
    else:
        corpo = (
            f"Faz {pior_dias} dias que você não estuda '{pior_materia}' (do seu ciclo ativo). "
            "Retome antes que a curva do esquecimento apague o que já viu — 25 min ajudam."
        )
    return {
        "tipo": "balance_materia",
        "title": "🔄 Matéria em atraso",
        "body": corpo,
        "url": "/#ciclo",
    }


def _contar_erros_pendentes_ciclo(conn, user_id: int, hoje: str) -> int:
    """Conta questões do caderno de erros (erros_revisao) com revisão VENCIDA,
    filtrando por matérias do CICLO ATIVO (regra nº 2 do projeto).

    Espelha a lógica do badge do sidebar para que push e UI sejam consistentes.
    Sem ciclo ativo → conta todas (fallback). Falha silenciosa → 0.
    """
    try:
        from utils import get_materias_ciclo_ativo

        materias_ativas = get_materias_ciclo_ativo(conn, user_id)
        if materias_ativas is None:
            row = conn.execute(
                "SELECT COUNT(*) FROM erros_revisao WHERE proxima_revisao <= ? AND user_id = ?",
                (hoje, user_id),
            ).fetchone()
            return row[0] if row else 0
        placeholders = ",".join("?" for _ in materias_ativas)
        row = conn.execute(
            f"""SELECT COUNT(*)
                FROM erros_revisao er
                JOIN questoes q ON q.id = er.questao_id
                WHERE er.proxima_revisao <= ? AND er.user_id = ?
                  AND q.materia IN ({placeholders})""",
            (hoje, user_id, *materias_ativas),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


@router.post("/api/push/check-triggers", summary="Verificar e disparar notificações agendadas")
def check_triggers(conn=Depends(get_db_session)):
    """Endpoint HTTP que dispara a verificação de gatilhos de notificação.

    Wrapper fino sobre `run_trigger_checks`, compartilhado com o scheduler de
    background (push_scheduler.py). Chamável manualmente (admin/cron externo) ou
    pelo agendador interno.
    """
    return run_trigger_checks(conn)


def run_trigger_checks(conn) -> dict:
    """Verifica todas as condições de notificação e envia para usuários elegíveis.

    Função pura (recebe uma conexão) para poder ser chamada tanto pelo endpoint
    HTTP quanto pelo scheduler de background. Verifica:
    - Streak em risco: sem atividade hoje, com urgência escalável (gentle/urgent/critical)
    - Flashcards atrasados: >10 flashcards pendentes
    - Prova se aproximando: data da prova dentro de 30 dias
    - Desafio prestes a expirar: <1 dia restante em desafio ativo
    - Inatividade: sem estudo há 2+ dias
    - Caderno de erros: questões erradas pendentes de revisão (ciclo ativo)
    - ... e demais gatilhos anti-relaxamento.
    """
    _ensure_tables(conn)

    results = {
        "streak_at_risk": 0,
        "flashcards_overdue": 0,
        "exam_approaching": 0,
        "challenge_expiring": 0,
        "inactivity": 0,
        "plano_expirando": 0,
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

        def _pref(col, default=1, _prefs=prefs):
            """Lê uma preferência nova com fallback (rows antigas podem não ter a coluna)."""
            if not _prefs:
                return default
            try:
                v = _prefs[col]
                return default if v is None else v
            except (IndexError, KeyError):
                return default

        study_time_enabled = _pref("study_time_reminder")
        study_time_hour = _pref("study_time_hour", 19)
        edital_review_enabled = _pref("edital_review_reminders")
        pace_drop_enabled = _pref("pace_drop_alerts")
        milestone_enabled = _pref("milestone_celebrations")
        balance_enabled = _pref("balance_alerts")

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
        if flashcard_enabled and not _already_sent_today(conn, uid, "flashcards_overdue"):
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
        if exam_enabled and not _already_sent_today(conn, uid, "exam_approaching"):
            # Check calendario_eventos for upcoming exams. A tabela pode não
            # existir em bancos que nunca usaram o calendário → falha silenciosa.
            threshold = (date.today() + timedelta(days=30)).isoformat()
            try:
                exams = conn.execute(
                    """SELECT titulo, data_inicio, banca FROM calendario_eventos
                           WHERE user_id = ? AND tipo = 'prova' AND data_inicio >= ? AND data_inicio <= ?
                           ORDER BY data_inicio ASC LIMIT 1""",
                    (uid, hoje, threshold)
                ).fetchone()
            except Exception:
                exams = None

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
        if challenge_enabled:  # noqa: SIM102 (comentário entre os ifs; fundir reduz clareza)
            if not _already_sent_today(conn, uid, "challenge_expiring"):
                # Active challenges with <1 day remaining
                try:
                    desafios = conn.execute(
                        "SELECT id, titulo, dias, created_at, progresso, meta FROM desafios WHERE user_id = ? AND finalizado = 0",
                        (uid,)
                    ).fetchall()
                except Exception:
                    desafios = []

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
        if streak_enabled:  # noqa: SIM102 (comentário entre os ifs; fundir reduz clareza)
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
        if flashcard_enabled and 21 <= now.hour <= 22:  # noqa: SIM102 (comentário entre os ifs; fundir reduz clareza)
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
        if streak_enabled and 20 <= now.hour <= 21:  # noqa: SIM102 (comentário entre os ifs; fundir reduz clareza)
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

        # --- 8. PLANO PREMIUM EXPIRANDO (≤7 dias) ---
        if not _already_sent_today(conn, uid, "plano_expirando"):
            try:
                urow = conn.execute("SELECT plano, plano_expira FROM users WHERE id = ?", (uid,)).fetchone()
                if urow and urow["plano"] == "premium":
                    exp = (urow["plano_expira"] or "").strip()
                    if exp and exp.lower() not in ("vitalicio", "vitalício", "lifetime"):
                        try:
                            dt = datetime.fromisoformat(exp)
                            if dt.tzinfo is not None:
                                dt = dt.replace(tzinfo=None)
                            dias = (dt - now).days
                        except (ValueError, TypeError):
                            dias = None
                        if dias is not None and 0 <= dias <= 7:
                            if dias == 0:
                                msg = "Seu Premium expira hoje! Renove com créditos para não perder o acesso aos recursos."
                            else:
                                msg = f"Seu Premium expira em {dias} dia(s). Renove com créditos para manter acesso ilimitado!"
                            sent = _send_push_to_user(conn, uid, "⏳ Plano expirando", msg, "/", "plano_expirando")
                            if sent > 0:
                                _log_notification(conn, uid, "plano_expirando", "⏳ Plano expirando", msg)
                                results["plano_expirando"] = results.get("plano_expirando", 0) + 1
            except Exception:
                pass

        # --- 9. LEMBRETE DE HORÁRIO DE ESTUDO (rotina anti-relaxamento) ---
        # No horário configurado (study_time_hour), se ainda não estudou hoje,
        # dá um empurrão para começar a sessão. Reforça o hábito diário.
        if study_time_enabled and now.hour == study_time_hour:  # noqa: SIM102
            if not _already_sent_today(conn, uid, "study_time"):
                atividade = conn.execute(
                    "SELECT 1 FROM streaks WHERE data = ? AND user_id = ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)",
                    (hoje, uid),
                ).fetchone()
                if not atividade:
                    sugestao = get_study_suggestion(conn, uid)
                    msg = f"Hora de estudar! ⏰ Que tal {sugestao}? Começar é o mais difícil — 25 min já contam."
                    sent = _send_push_to_user(conn, uid, "📚 Hora de estudar", msg, "/", "study_time")
                    if sent > 0:
                        _log_notification(conn, uid, "study_time", "📚 Hora de estudar", msg)
                        results["study_time"] = results.get("study_time", 0) + 1

        # --- 10. REVISÕES DO EDITAL VENCIDAS (FSRS, além dos flashcards) ---
        if edital_review_enabled and now.hour >= 17:  # noqa: SIM102
            if not _already_sent_today(conn, uid, "edital_review"):
                vencidas = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM edital WHERE user_id = ? AND arquivado = 0 "
                    "AND proxima_revisao != '' AND proxima_revisao IS NOT NULL AND proxima_revisao <= ?",
                    (uid, hoje),
                ).fetchone()
                if vencidas and vencidas["cnt"] > 0:
                    n = vencidas["cnt"]
                    msg = f"Você tem {n} tópico(s) do edital com revisão VENCIDA. Revisar no prazo evita reaprender do zero (curva do esquecimento)."
                    sent = _send_push_to_user(conn, uid, "📌 Revisões do edital", msg, "/", "edital_review")
                    if sent > 0:
                        _log_notification(conn, uid, "edital_review", "📌 Revisões do edital", msg)
                        results["edital_review"] = results.get("edital_review", 0) + 1

        # --- 11. QUEDA DE RITMO SEMANAL (compara horas vs semana anterior) ---
        # Domingo à noite (ou início da semana) alerta se as horas caíram muito.
        if pace_drop_enabled and now.weekday() == 6 and now.hour >= 18:  # noqa: SIM102 (domingo)
            if not _already_sent_today(conn, uid, "pace_drop"):
                ini_semana = (date.today() - timedelta(days=date.today().weekday())).isoformat()
                ini_ant = (date.today() - timedelta(days=date.today().weekday() + 7)).isoformat()
                fim_ant = (date.today() - timedelta(days=date.today().weekday() + 1)).isoformat()
                h_atual = conn.execute(
                    "SELECT COALESCE(SUM(horas_estudadas),0) AS h FROM streaks WHERE user_id = ? AND data >= ?",
                    (uid, ini_semana),
                ).fetchone()["h"] or 0
                h_ant = conn.execute(
                    "SELECT COALESCE(SUM(horas_estudadas),0) AS h FROM streaks WHERE user_id = ? AND data >= ? AND data <= ?",
                    (uid, ini_ant, fim_ant),
                ).fetchone()["h"] or 0
                # Só alerta se a semana anterior teve ritmo relevante e caiu >40%.
                if h_ant >= 3 and h_atual < h_ant * 0.6:
                    queda = round((1 - (h_atual / h_ant)) * 100)
                    msg = f"Seu ritmo caiu {queda}% esta semana ({h_atual:.1f}h vs {h_ant:.1f}h). Não deixe o esforço acumulado esfriar — retome amanhã!"
                    sent = _send_push_to_user(conn, uid, "📉 Ritmo caindo", msg, "/", "pace_drop")
                    if sent > 0:
                        _log_notification(conn, uid, "pace_drop", "📉 Ritmo caindo", msg)
                        results["pace_drop"] = results.get("pace_drop", 0) + 1

        # --- 12. COMEMORAÇÃO DE MARCO DE STREAK (reforço positivo) ---
        # Reforço positivo sustenta o hábito tanto quanto a cobrança. Dispara ao
        # atingir marcos (7, 14, 30, 60, 100, 200, 365 dias) e SÓ se estudou hoje.
        if milestone_enabled:  # noqa: SIM102
            if not _already_sent_today(conn, uid, "milestone"):
                estudou_hoje = conn.execute(
                    "SELECT 1 FROM streaks WHERE data = ? AND user_id = ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)",
                    (hoje, uid),
                ).fetchone()
                if estudou_hoje:
                    from utils import calculate_streak
                    try:
                        streak_atual = calculate_streak(conn, user_id=uid)
                    except Exception:
                        streak_atual = 0
                    marcos = {7, 14, 30, 60, 100, 200, 365}
                    if streak_atual in marcos:
                        msg = f"🎉 {streak_atual} dias seguidos de estudo! Consistência é o que aprova. Continue firme — o hábito está sólido!"
                        sent = _send_push_to_user(conn, uid, "🏆 Marco alcançado!", msg, "/", "milestone")
                        if sent > 0:
                            _log_notification(conn, uid, "milestone", "🏆 Marco alcançado!", msg)
                            results["milestone"] = results.get("milestone", 0) + 1

        # --- 13. DEFASAGEM / DESEQUILÍBRIO DE ESTUDO (foco por pilar) ---
        # Percebe quando o estudante está negligenciando teoria, questões ou
        # flashcards e sugere focar no pilar defasado (sem perder o foco geral).
        # Roda à tarde/noite, 1x/dia, e não durante quiet hours (já filtrado acima).
        if balance_enabled and now.hour >= 16:  # noqa: SIM102
            if not _already_sent_today(conn, uid, "balance_alert"):
                defasagem = _detectar_defasagem(conn, uid)
                if defasagem:
                    # Um alerta de balanceamento por dia (qualquer que seja o pilar).
                    sent = _send_push_to_user(
                        conn, uid, defasagem["title"], defasagem["body"], defasagem["url"], defasagem["tipo"]
                    )
                    if sent > 0:
                        _log_notification(conn, uid, "balance_alert", defasagem["title"], defasagem["body"])
                        results["balance_alert"] = results.get("balance_alert", 0) + 1

        # --- 14. CADERNO DE ERROS: questões erradas pendentes de revisão ---
        # Errar e revisar (Successive Relearning) é onde o aprendizado mais rende.
        # Alerta quando há questões no caderno de erros com revisão VENCIDA,
        # aplicando o filtro de CICLO ATIVO (regra nº 2: nunca sugerir matéria de
        # concurso inativo). Reusa a preferência de "revisões" (edital_review).
        if edital_review_enabled and now.hour >= 17:  # noqa: SIM102
            if not _already_sent_today(conn, uid, "caderno_erros"):
                n_erros = _contar_erros_pendentes_ciclo(conn, uid, hoje)
                if n_erros >= 3:
                    msg = (
                        f"Você tem {n_erros} questão(ões) errada(s) aguardando revisão no caderno de erros. "
                        "Revisar o próprio erro é o que mais fixa (Successive Relearning) — 10 min rendem muito!"
                    )
                    sent = _send_push_to_user(conn, uid, "📝 Caderno de erros", msg, "/caderno-erros.html", "caderno_erros")
                    if sent > 0:
                        _log_notification(conn, uid, "caderno_erros", "📝 Caderno de erros", msg)
                        results["caderno_erros"] = results.get("caderno_erros", 0) + 1

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

    # Erros pendentes de revisão (com filtro de CICLO ATIVO — consistente com o
    # badge do sidebar e o trigger de push do caderno de erros).
    try:
        n_erros = _contar_erros_pendentes_ciclo(conn, user_id, hoje)
        if n_erros > 3:
            alertas.append({"tipo": "erros", "icone": "📝", "msg": f"{n_erros} questões erradas agendadas para revisão", "acao": "/caderno-erros.html"})
    except Exception:
        pass

    # Sleep consolidation (se 21h-1h)
    if now.hour >= 21 or now.hour <= 1:
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
            "study_time_reminder": True,
            "study_time_hour": 19,
            "edital_review_reminders": True,
            "pace_drop_alerts": True,
            "milestone_celebrations": True,
            "balance_alerts": True,
        }

    def _b(col, default):
        try:
            v = row[col]
            return bool(v) if v is not None else bool(default)
        except (IndexError, KeyError):
            return bool(default)

    def _i(col, default):
        try:
            v = row[col]
            return int(v) if v is not None else int(default)
        except (IndexError, KeyError, ValueError, TypeError):
            return int(default)

    return {
        "streak_reminders": bool(row["streak_reminders"]),
        "flashcard_reminders": bool(row["flashcard_reminders"]),
        "exam_reminders": bool(row["exam_reminders"]),
        "challenge_reminders": bool(row["challenge_reminders"]),
        "quiet_hours_start": row["quiet_hours_start"],
        "quiet_hours_end": row["quiet_hours_end"],
        "study_time_reminder": _b("study_time_reminder", 1),
        "study_time_hour": _i("study_time_hour", 19),
        "edital_review_reminders": _b("edital_review_reminders", 1),
        "pace_drop_alerts": _b("pace_drop_alerts", 1),
        "milestone_celebrations": _b("milestone_celebrations", 1),
        "balance_alerts": _b("balance_alerts", 1),
    }


@router.put("/api/push/preferences", summary="Atualizar preferências de notificação")
def update_preferences(body: NotificationPreferences, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Atualiza as preferências de notificação do usuário."""
    _ensure_tables(conn)

    conn.execute("""
        INSERT INTO notification_preferences (user_id, streak_reminders, flashcard_reminders, exam_reminders, challenge_reminders, quiet_hours_start, quiet_hours_end,
            study_time_reminder, study_time_hour, edital_review_reminders, pace_drop_alerts, milestone_celebrations, balance_alerts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            streak_reminders = excluded.streak_reminders,
            flashcard_reminders = excluded.flashcard_reminders,
            exam_reminders = excluded.exam_reminders,
            challenge_reminders = excluded.challenge_reminders,
            quiet_hours_start = excluded.quiet_hours_start,
            quiet_hours_end = excluded.quiet_hours_end,
            study_time_reminder = excluded.study_time_reminder,
            study_time_hour = excluded.study_time_hour,
            edital_review_reminders = excluded.edital_review_reminders,
            pace_drop_alerts = excluded.pace_drop_alerts,
            milestone_celebrations = excluded.milestone_celebrations,
            balance_alerts = excluded.balance_alerts
    """, (
        user_id,
        int(body.streak_reminders),
        int(body.flashcard_reminders),
        int(body.exam_reminders),
        int(body.challenge_reminders),
        body.quiet_hours_start,
        body.quiet_hours_end,
        int(body.study_time_reminder),
        body.study_time_hour,
        int(body.edital_review_reminders),
        int(body.pace_drop_alerts),
        int(body.milestone_celebrations),
        int(body.balance_alerts),
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


# ============================================================
# BROADCAST FEED (anúncios do admin, in-app)
# ============================================================


def _user_matches_segmento(conn, user_id: int, segmento: str) -> bool:
    """Verifica se o usuário pertence ao segmento de um broadcast."""
    if segmento == "todos":
        return True
    row = conn.execute("SELECT plano FROM users WHERE id = ?", (user_id,)).fetchone()
    plano = (row["plano"] if row else None) or "free"
    if segmento == "free":
        return plano in ("free", "guest")
    if segmento == "premium":
        return plano not in ("free", "guest")
    if segmento == "ativos":
        from datetime import date, timedelta
        limite = (date.today() - timedelta(days=7)).isoformat()
        r = conn.execute(
            "SELECT 1 FROM streaks WHERE user_id = ? AND data >= ? AND "
            "(horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0) LIMIT 1",
            (user_id, limite)
        ).fetchone()
        return r is not None
    return False


@router.get("/api/broadcasts/feed", summary="Anúncios do admin para o usuário (não lidos)")
def broadcasts_feed(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna anúncios recentes direcionados ao usuário que ele ainda não dispensou."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        rows = conn.execute("""
            SELECT b.id, b.titulo, b.corpo, b.url, b.segmento, b.created_at
            FROM broadcasts b
            WHERE b.id NOT IN (SELECT broadcast_id FROM broadcast_reads WHERE user_id = ?)
              AND (COALESCE(b.expira_em, '') = '' OR b.expira_em > ?)
            ORDER BY b.id DESC LIMIT 50
        """, (user_id, now_iso)).fetchall()
    except Exception:
        return {"anuncios": []}
    anuncios = []
    for r in rows:
        if _user_matches_segmento(conn, user_id, r["segmento"]):
            anuncios.append({
                "id": r["id"], "titulo": r["titulo"], "corpo": r["corpo"],
                "url": r["url"], "created_at": r["created_at"],
            })
    return {"anuncios": anuncios, "total": len(anuncios)}


@router.post("/api/broadcasts/{broadcast_id}/dispensar", summary="Dispensar um anúncio")
def dispensar_broadcast(broadcast_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Marca um anúncio como lido/dispensado para o usuário (não reaparece)."""
    from datetime import datetime, timezone
    conn.execute(
        "INSERT OR IGNORE INTO broadcast_reads (broadcast_id, user_id, read_at) VALUES (?, ?, ?)",
        (broadcast_id, user_id, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    return {"ok": True}
