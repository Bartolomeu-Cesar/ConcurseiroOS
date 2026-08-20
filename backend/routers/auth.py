"""Router de autenticação — registro, login via código email, perfil."""
import os
import secrets
import smtplib
import string
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bcrypt
import jwt
from fastapi import APIRouter, Body, Depends, HTTPException, Header, Request

from database import get_db_session
from logger import log
from settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

_DEBUG = os.environ.get("DEBUG", "false").lower() == "true"


# ==================== HELPERS ====================

def _generate_code(length=6):
    """Gera código numérico de verificação usando secrets (CSPRNG)."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


def _send_email(to_email: str, subject: str, html_body: str):
    """Envia email via SMTP."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        log.warning(f"SMTP não configurado. Código para {to_email} não enviado.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        if settings.SMTP_USE_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(msg["From"], [to_email], msg.as_string())
        server.quit()
        log.info(f"Email enviado para {to_email}")
        return True
    except Exception as e:
        log.error(f"Erro ao enviar email: {e}")
        return False


def _send_code_email(email: str, code: str):
    """Envia email com código de verificação."""
    # Se SMTP não configurado, exibir código no terminal SOMENTE em modo DEBUG
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        if _DEBUG:
            print(f"\n{'='*50}")
            print(f"  🔑 CÓDIGO DE LOGIN: {code}")
            print(f"  📧 Email: {email}")
            print(f"{'='*50}\n")

    html = f"""
    <div style="font-family:sans-serif;max-width:400px;margin:0 auto;padding:24px;background:#1e1e2e;color:#cdd6f4;border-radius:12px;">
        <h2 style="color:#cba6f7;text-align:center;">📚 ConcurseiroOS</h2>
        <p style="text-align:center;font-size:0.9rem;">Seu código de verificação:</p>
        <div style="text-align:center;font-size:2.5rem;font-weight:700;letter-spacing:8px;color:#a6e3a1;padding:16px;background:#313244;border-radius:8px;margin:16px 0;">
            {code}
        </div>
        <p style="text-align:center;font-size:0.8rem;color:#9399b2;">
            Este código expira em {settings.AUTH_CODE_EXPIRE_MINUTES} minutos.<br>
            Se você não solicitou, ignore este email.
        </p>
    </div>
    """
    return _send_email(email, f"ConcurseiroOS — Código: {code}", html)


def _check_rate_limit(email: str, conn) -> bool:
    """Verifica se email excedeu 5 tentativas nos últimos 15 minutos. Retorna True se bloqueado."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    count = conn.execute(
        "SELECT COUNT(*) FROM auth_attempts WHERE email = ? AND created_at > ?",
        (email, cutoff)
    ).fetchone()[0]
    return count >= 5


def _record_failed_attempt(email: str, ip: str, conn):
    """Registra tentativa falhada de verificação."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO auth_attempts (email, ip, created_at) VALUES (?, ?, ?)",
        (email, ip, now)
    )
    conn.commit()


# ==================== DEPENDENCY: GET CURRENT USER ====================

async def get_current_user(authorization: str = Header(None), conn=Depends(get_db_session)):
    """Dependency que extrai o usuário atual do token JWT."""
    if not settings.AUTH_ENABLED:
        return None

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")

    token = authorization.replace("Bearer ", "")
    payload = _decode_token(token)
    user_id = int(payload["sub"])

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")

    return dict(user)


async def get_optional_user(authorization: str = Header(None), conn=Depends(get_db_session)):
    """Dependency que retorna o usuário se autenticado, ou None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        token = authorization.replace("Bearer ", "")
        payload = _decode_token(token)
        user_id = int(payload["sub"])
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(user) if user else None
    except Exception:
        return None


# ==================== ENDPOINTS ====================

@router.post("/register")
def register(body: dict = Body(...), conn=Depends(get_db_session)):
    """Registra um novo usuário e envia código de verificação."""
    email = body.get("email", "").strip().lower()
    nome = body.get("nome", "").strip()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email inválido")

    # Verificar se já existe
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email já cadastrado. Use o login.")

    # Criar usuário
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (email, nome, created_at) VALUES (?, ?, ?)",
        (email, nome, now)
    )
    conn.commit()

    # Gerar e enviar código
    code = _generate_code()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=settings.AUTH_CODE_EXPIRE_MINUTES)).isoformat()
    conn.execute(
        "INSERT INTO auth_codes (email, code, tipo, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (email, code, "verify", now, expires)
    )
    conn.commit()

    sent = _send_code_email(email, code)

    return {
        "ok": True,
        "message": "Conta criada! Verifique seu email." if sent else "Conta criada! Verifique seu email.",
        "email_sent": sent,
        "code": code if _DEBUG else None,
    }


@router.post("/login")
def login(body: dict = Body(...), conn=Depends(get_db_session)):
    """Envia código de verificação para login."""
    email = body.get("email", "").strip().lower()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email inválido")

    # Verificar se existe
    user = conn.execute("SELECT id, nome FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Email não cadastrado. Registre-se primeiro.")

    # Invalidar códigos anteriores
    conn.execute("UPDATE auth_codes SET used = 1 WHERE email = ? AND used = 0", (email,))

    # Gerar novo código
    code = _generate_code()
    now = datetime.now(timezone.utc).isoformat()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=settings.AUTH_CODE_EXPIRE_MINUTES)).isoformat()
    conn.execute(
        "INSERT INTO auth_codes (email, code, tipo, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (email, code, "login", now, expires)
    )
    conn.commit()

    sent = _send_code_email(email, code)

    return {
        "ok": True,
        "message": "Código enviado para seu email!" if sent else "Código enviado!",
        "email_sent": sent,
        "code": code if _DEBUG else None,
    }


@router.post("/verify-code")
def verify_code(body: dict = Body(...), request: Request = None, conn=Depends(get_db_session)):
    """Verifica o código e retorna JWT token."""
    email = body.get("email", "").strip().lower()
    code = body.get("code", "").strip()

    if not email or not code:
        raise HTTPException(status_code=400, detail="Email e código são obrigatórios")

    # Rate limiting: max 5 tentativas por email nos últimos 15 minutos
    if _check_rate_limit(email, conn):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 15 minutos.")

    # Buscar código válido
    now = datetime.now(timezone.utc).isoformat()
    auth = conn.execute(
        """SELECT id FROM auth_codes
           WHERE email = ? AND code = ? AND used = 0 AND expires_at > ?
           ORDER BY created_at DESC LIMIT 1""",
        (email, code, now)
    ).fetchone()

    if not auth:
        # Registrar tentativa falhada
        client_ip = request.client.host if request and request.client else "unknown"
        _record_failed_attempt(email, client_ip, conn)
        raise HTTPException(status_code=401, detail="Código inválido ou expirado")

    # Marcar como usado
    conn.execute("UPDATE auth_codes SET used = 1 WHERE id = ?", (auth["id"],))

    # Atualizar usuário
    conn.execute(
        "UPDATE users SET email_verified = 1, last_login = ? WHERE email = ?",
        (now, email)
    )
    conn.commit()

    # Buscar usuário
    user = conn.execute("SELECT id, email, nome, avatar, plano, plano_expira FROM users WHERE email = ?", (email,)).fetchone()

    # Gerar token
    token = _create_token(user["id"], user["email"])

    return {
        "ok": True,
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "nome": user["nome"],
            "avatar": user["avatar"],
            "plano": user["plano"],
        }
    }


@router.get("/me")
def get_me(user=Depends(get_current_user), conn=Depends(get_db_session)):
    """Retorna dados do perfil do usuário autenticado."""
    if not user:
        return {"id": 0, "email": "", "nome": "Estudante", "avatar": "", "plano": "free", "auth_enabled": False}

    return {
        "id": user["id"],
        "email": user["email"],
        "nome": user["nome"],
        "avatar": user["avatar"],
        "plano": user.get("plano", "free"),
        "plano_expira": user.get("plano_expira", ""),
        "email_verified": bool(user["email_verified"]),
        "created_at": user["created_at"],
        "last_login": user["last_login"],
        "auth_enabled": True,
    }


@router.put("/profile")
def update_profile(body: dict = Body(...), user=Depends(get_current_user), conn=Depends(get_db_session)):
    """Atualiza dados do perfil."""
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")

    nome = body.get("nome", user["nome"])
    avatar = body.get("avatar", user["avatar"])

    conn.execute(
        "UPDATE users SET nome = ?, avatar = ? WHERE id = ?",
        (nome, avatar, user["id"])
    )
    conn.commit()

    return {"ok": True, "nome": nome, "avatar": avatar}


@router.get("/status")
def auth_status():
    """Retorna se a autenticação está habilitada."""
    return {
        "auth_enabled": settings.AUTH_ENABLED,
        "smtp_configured": bool(settings.SMTP_USER and settings.SMTP_PASSWORD),
    }


# ==================== PLANOS ====================

from plans import PLANS, get_plan, get_plan_info, get_limits, check_limit


@router.get("/plans")
def list_plans():
    """Lista todos os planos disponíveis."""
    return [
        {"id": key, "nome": p["nome"], "descricao": p["descricao"], "limites": p["limites"]}
        for key, p in PLANS.items()
        if key != "guest"
    ]


@router.get("/my-plan")
def my_plan(user=Depends(get_optional_user)):
    """Retorna o plano e limites do usuário atual."""
    return get_plan_info(user)


@router.post("/upgrade")
def upgrade_plan(body: dict = Body(...), user=Depends(get_current_user), conn=Depends(get_db_session)):
    """Faz upgrade do plano do usuário (em produção integraria com pagamento)."""
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")

    plano = body.get("plano", "premium")
    if plano not in ("free", "premium", "ilimitado"):
        raise HTTPException(status_code=400, detail="Plano inválido")

    # Em produção: verificar pagamento aqui
    # Por enquanto: ativa diretamente (para testes)
    now = datetime.now(timezone.utc).isoformat()
    if plano == "premium":
        # Premium expira em 30 dias (renovável)
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    elif plano == "ilimitado":
        # Ilimitado: sem expiração
        expires = ""
    else:
        # Free: sem expiração
        expires = ""

    conn.execute(
        "UPDATE users SET plano = ?, plano_expira = ? WHERE id = ?",
        (plano, expires, user["id"])
    )
    conn.commit()

    log.info(f"User {user['email']} upgraded to {plano}")
    return {"ok": True, "plano": plano, "expira": expires}


@router.get("/check-limit/{recurso}")
def check_resource_limit(recurso: str, user=Depends(get_optional_user), conn=Depends(get_db_session)):
    """Verifica se o usuário pode usar mais de um recurso específico."""
    from deps import get_user_id, DEFAULT_USER_ID

    # Determinar user_id para filtro
    uid = user["id"] if user else DEFAULT_USER_ID

    if recurso == "editais":
        count = conn.execute("SELECT COUNT(DISTINCT edital_nome) FROM edital WHERE arquivado = 0 AND user_id = ?", (uid,)).fetchone()[0]
    elif recurso == "flashcards":
        count = conn.execute("SELECT COUNT(*) FROM flashcards WHERE user_id = ?", (uid,)).fetchone()[0]
    elif recurso == "pdfs":
        count = conn.execute("SELECT COUNT(*) FROM progress WHERE user_id = ?", (uid,)).fetchone()[0]
    elif recurso == "simulados":
        count = conn.execute("SELECT COUNT(*) FROM simulados WHERE user_id = ?", (uid,)).fetchone()[0]
    elif recurso == "ciclo_materias":
        count = conn.execute("SELECT COUNT(*) FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (uid,)).fetchone()[0]
    else:
        count = 0

    pode = check_limit(user, recurso, count)
    limites = get_limits(user)
    limite_max = limites.get(recurso, -1)

    return {
        "recurso": recurso,
        "pode": pode,
        "atual": count,
        "limite": limite_max,
        "plano": get_plan(user),
    }
