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
from sanitize import sanitize_input
from schemas import LoginRequest, RegisterRequest, VerifyCodeRequest, ProfileUpdateRequest, UpgradePlanRequest, RefreshTokenRequest
from settings import settings

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])

_DEBUG = os.environ.get("DEBUG", "false").lower() == "true"


# ==================== HELPERS ====================

def _generate_code(length=6):
    """Gera código numérico de verificação usando secrets (CSPRNG)."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _create_access_token(user_id: int, email: str) -> str:
    """Cria access token JWT (curta duração)."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _create_refresh_token(user_id: int) -> str:
    """Cria refresh token JWT (longa duração)."""
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS),
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


def _bloquear_se_conta_inativa(conn, email: str):
    """Levanta 403 se a conta estiver banida ou suspensa (moderação).

    Suspensão com `conta_status_ate` no passado é tratada como expirada
    (reativa automaticamente). Best-effort: se as colunas não existirem, não bloqueia.
    """
    from datetime import datetime, timezone
    try:
        row = conn.execute(
            "SELECT conta_status, conta_status_motivo, conta_status_ate FROM users WHERE email = ?",
            (email,)
        ).fetchone()
    except Exception:
        return  # colunas ausentes → não bloquear
    if not row:
        return
    status = (row["conta_status"] if not isinstance(row, tuple) else row[0]) or "ativo"
    motivo = (row["conta_status_motivo"] if not isinstance(row, tuple) else row[1]) or ""
    ate = (row["conta_status_ate"] if not isinstance(row, tuple) else row[2]) or ""

    if status == "banido":
        detalhe = "Conta banida." + (f" Motivo: {motivo}" if motivo else "")
        raise HTTPException(status_code=403, detail=detalhe)
    if status == "suspenso":
        # Suspensão expirada → reativa
        if ate:
            try:
                dt = datetime.fromisoformat(ate)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= dt:
                    conn.execute("UPDATE users SET conta_status = 'ativo', conta_status_ate = '' WHERE email = ?", (email,))
                    conn.commit()
                    return
            except (ValueError, TypeError):
                pass
        detalhe = "Conta suspensa." + (f" Motivo: {motivo}" if motivo else "") + (f" Até: {ate}" if ate else "")
        raise HTTPException(status_code=403, detail=detalhe)


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
    from plans import get_auth_code_expire_minutes
    _mins = get_auth_code_expire_minutes()
    _validade = f"{_mins // 60}h" if _mins % 60 == 0 and _mins >= 60 else f"{_mins} minutos"
    """Envia email com código de verificação."""
    # Se SMTP não configurado, exibir código no terminal (modo desenvolvimento)
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
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
            Este código expira em {_validade}.<br>
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

    # Rejeitar refresh tokens — só aceita access ou tokens legados (sem type)
    if payload.get("type") == "refresh":
        raise HTTPException(status_code=401, detail="Refresh token não é aceito para autenticação")

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
        # Rejeitar refresh tokens
        if payload.get("type") == "refresh":
            return None
        user_id = int(payload["sub"])
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(user) if user else None
    except Exception:
        return None


# ==================== ENDPOINTS ====================

@router.post("/register", summary="Registrar novo usuário",
             description="Cria uma conta e envia código de verificação por email. Se SMTP não configurado, o código é exibido no terminal.",
             responses={409: {"description": "Email já cadastrado"}})
def register(body: RegisterRequest, conn=Depends(get_db_session)):
    """Registra um novo usuário e envia código de verificação."""
    email = body.email.strip().lower()
    nome = sanitize_input(body.nome.strip(), max_length=100)

    # Feature flag: bloquear registro se desligado (exceto bootstrap do 1º usuário)
    from plans import is_feature_enabled
    total_users_flag = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if total_users_flag > 0 and not is_feature_enabled("registro"):
        raise HTTPException(status_code=403, detail="Registro de novos usuários está temporariamente desativado.")

    # Verificar se já existe
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email já cadastrado. Use o login.")

    # Criar usuário
    now = datetime.now(timezone.utc).isoformat()
    # O primeiro usuário do sistema vira admin automaticamente (bootstrap do dono)
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    role = "admin" if total_users == 0 else "user"
    conn.execute(
        "INSERT INTO users (email, nome, role, created_at) VALUES (?, ?, ?, ?)",
        (email, nome, role, now)
    )
    conn.commit()
    if role == "admin":
        log.info(f"Primeiro usuário registrado ({email}) promovido a admin.")

    # Gerar e enviar código
    code = _generate_code()
    from plans import get_auth_code_expire_minutes
    expires = (datetime.now(timezone.utc) + timedelta(minutes=get_auth_code_expire_minutes())).isoformat()
    conn.execute(
        "INSERT INTO auth_codes (email, code, tipo, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (email, code, "verify", now, expires)
    )
    conn.commit()

    sent = _send_code_email(email, code)

    return {
        "ok": True,
        "message": "Conta criada! Verifique seu email." if sent else "Conta criada! Código no console do servidor.",
        "email_sent": sent,
    }


@router.post("/login", summary="Solicitar código de login",
             description="Envia código de verificação de 6 dígitos para o email cadastrado. Códigos anteriores são invalidados.",
             responses={404: {"description": "Email não cadastrado"}})
def login(body: LoginRequest, conn=Depends(get_db_session)):
    """Envia código de verificação para login."""
    email = body.email.strip().lower()

    # Verificar se existe
    user = conn.execute("SELECT id, nome FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Email não cadastrado. Registre-se primeiro.")

    # Moderação: bloquear conta banida/suspensa antes de enviar código
    _bloquear_se_conta_inativa(conn, email)

    # Invalidar códigos anteriores
    conn.execute("UPDATE auth_codes SET used = 1 WHERE email = ? AND used = 0", (email,))

    # Gerar novo código
    code = _generate_code()
    now = datetime.now(timezone.utc).isoformat()
    from plans import get_auth_code_expire_minutes
    expires = (datetime.now(timezone.utc) + timedelta(minutes=get_auth_code_expire_minutes())).isoformat()
    conn.execute(
        "INSERT INTO auth_codes (email, code, tipo, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (email, code, "login", now, expires)
    )
    conn.commit()

    sent = _send_code_email(email, code)

    return {
        "ok": True,
        "message": "Código enviado para seu email!" if sent else "Código no console do servidor.",
        "email_sent": sent,
    }


@router.post("/verify-code", summary="Verificar código e obter token JWT",
             description="Valida o código de 6 dígitos e retorna um JWT token para autenticação. Rate limit: 5 tentativas a cada 15 minutos.",
             responses={401: {"description": "Código inválido ou expirado"}, 429: {"description": "Muitas tentativas"}})
def verify_code(body: VerifyCodeRequest, request: Request = None, conn=Depends(get_db_session)):
    """Verifica o código e retorna JWT token."""
    email = body.email.strip().lower()
    code = body.code.strip()

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

    # Moderação: bloquear conta banida/suspensa (defense-in-depth)
    _bloquear_se_conta_inativa(conn, email)

    # Atualizar usuário
    conn.execute(
        "UPDATE users SET email_verified = 1, last_login = ? WHERE email = ?",
        (now, email)
    )
    conn.commit()

    # Buscar usuário
    user = conn.execute("SELECT id, email, nome, avatar, plano, plano_expira, role FROM users WHERE email = ?", (email,)).fetchone()

    # Gerar tokens
    access_token = _create_access_token(user["id"], user["email"])
    refresh_token = _create_refresh_token(user["id"])

    return {
        "ok": True,
        "token": access_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "nome": user["nome"],
            "avatar": user["avatar"],
            "plano": user["plano"],
            "role": user["role"] if "role" in user.keys() else "user",
        }
    }


@router.post("/refresh", summary="Renovar tokens via refresh token",
             description="Recebe um refresh_token válido e retorna novos access_token e refresh_token (rotation).",
             responses={401: {"description": "Refresh token inválido ou expirado"}})
def refresh_token(body: RefreshTokenRequest, conn=Depends(get_db_session)):
    """Renova access_token usando refresh_token (token rotation)."""
    try:
        payload = jwt.decode(body.refresh_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expirado. Faça login novamente.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Refresh token inválido")

    # Validar que é um refresh token
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token fornecido não é um refresh token")

    user_id = int(payload["sub"])

    # Verificar se o usuário ainda existe
    user = conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")

    # Gerar novos tokens (rotation)
    new_access_token = _create_access_token(user["id"], user["email"])
    new_refresh_token = _create_refresh_token(user["id"])

    return {
        "ok": True,
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
    }


@router.get("/me", summary="Dados do usuário autenticado",
            description="Retorna perfil completo do usuário. Se não autenticado, retorna dados do usuário padrão (guest).")
def get_me(user=Depends(get_optional_user), conn=Depends(get_db_session)):
    """Retorna dados do perfil do usuário autenticado (ou guest fallback)."""
    from plans import get_plan, check_and_expire_plan

    if not user:
        # Fallback: return guest/default user info
        default_user = conn.execute("SELECT * FROM users WHERE id = 1").fetchone()
        if default_user:
            keys = default_user.keys()
            return {
                "id": default_user["id"],
                "email": default_user["email"] or "",
                "nome": default_user["nome"] or "Estudante",
                "avatar": default_user["avatar"] or "",
                "plano": default_user["plano"] if "plano" in keys else "ilimitado",
                "plano_expira": default_user["plano_expira"] if "plano_expira" in keys else "",
                "role": default_user["role"] if "role" in keys else "admin",
                "auth_enabled": settings.AUTH_ENABLED,
            }
        return {"id": 1, "email": "", "nome": "Estudante", "avatar": "", "plano": "ilimitado", "role": "admin", "auth_enabled": settings.AUTH_ENABLED}

    # Verificar e persistir expiração do plano (se aplicável)
    plano_efetivo = check_and_expire_plan(conn, user["id"], user)
    plano_expirou = plano_efetivo == "free" and user.get("plano") == "premium"

    return {
        "id": user["id"],
        "email": user["email"],
        "nome": user["nome"],
        "avatar": user["avatar"],
        "plano": plano_efetivo,
        "plano_expira": "" if plano_expirou else user.get("plano_expira", ""),
        "role": user.get("role", "user"),
        "email_verified": bool(user["email_verified"]),
        "created_at": user["created_at"],
        "last_login": user["last_login"],
        "auth_enabled": True,
        "plano_expirado": plano_expirou,
    }


@router.put("/profile", summary="Atualizar perfil",
            description="Atualiza nome e/ou avatar do usuário autenticado.",
            responses={401: {"description": "Não autenticado"}})
def update_profile(body: ProfileUpdateRequest, user=Depends(get_current_user), conn=Depends(get_db_session)):
    """Atualiza dados do perfil."""
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")

    nome = sanitize_input(body.nome, max_length=100) if body.nome is not None else user["nome"]
    avatar = body.avatar if body.avatar is not None else user["avatar"]

    conn.execute(
        "UPDATE users SET nome = ?, avatar = ? WHERE id = ?",
        (nome, avatar, user["id"])
    )
    conn.commit()

    return {"ok": True, "nome": nome, "avatar": avatar}


@router.get("/status", summary="Status da autenticação",
            description="Retorna se a autenticação está habilitada e se SMTP está configurado. Endpoint público.")
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


@router.get("/vitalicio-status", summary="Disponibilidade do plano Vitalício",
            description="Retorna se o plano Vitalício está disponível para compra no período atual.")
def vitalicio_status():
    """Verifica se o plano Vitalício está na janela de venda."""
    from plans import is_vitalicio_disponivel
    return is_vitalicio_disponivel()


@router.get("/my-plan")
def my_plan(user=Depends(get_optional_user)):
    """Retorna o plano e limites do usuário atual."""
    return get_plan_info(user)


@router.post("/upgrade")
def upgrade_plan(body: UpgradePlanRequest, user=Depends(get_current_user), conn=Depends(get_db_session)):
    """Faz upgrade do plano do usuário.

    Requer uma das condições:
    - Usuário é admin (role='admin') → ativa diretamente (gerenciamento).
    - Downgrade para 'free' → sempre permitido.
    - Upgrade para premium/ilimitado → requer créditos suficientes no saldo.
      Premium mensal: 10 créditos (30 dias). Vitalício/Ilimitado: via admin ou créditos/ativar.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")

    plano = body.plano

    # Downgrade para free: sempre permitido
    if plano == "free":
        conn.execute(
            "UPDATE users SET plano = 'free', plano_expira = '' WHERE id = ?",
            (user["id"],)
        )
        conn.commit()
        log.info(f"User {user['email']} downgraded to free")
        return {"ok": True, "plano": "free", "expira": "", "vitalicio": False}

    # Admin pode ativar qualquer plano diretamente (gerenciamento de users)
    is_admin = user.get("role") == "admin"
    if is_admin:
        if plano == "premium":
            expires = "vitalicio" if body.vitalicio else (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        elif plano == "ilimitado":
            # Admin ignora janela de venda
            expires = "vitalicio"
        else:
            expires = ""
        conn.execute(
            "UPDATE users SET plano = ?, plano_expira = ? WHERE id = ?",
            (plano, expires, user["id"])
        )
        conn.commit()
        tipo = "vitalício" if body.vitalicio or plano == "ilimitado" else "mensal"
        log.info(f"Admin {user['email']} upgraded to {plano} ({tipo})")
        return {"ok": True, "plano": plano, "expira": expires, "vitalicio": body.vitalicio or plano == "ilimitado"}

    # Usuário comum: precisa ter créditos — use /api/auth/creditos/ativar para converter
    raise HTTPException(
        status_code=403,
        detail="Para ativar Premium, use seus créditos em 'Ativar Créditos'. Compre créditos via PIX se não tiver saldo."
    )


# ==================== SISTEMA DE CRÉDITOS ====================

@router.get("/creditos")
def get_creditos(user=Depends(get_current_user), conn=Depends(get_db_session)):
    """Retorna saldo de créditos e info do sistema."""
    from plans import CREDIT_CONFIG, calcular_dias_creditos

    saldo = 0
    expira = ""
    try:
        row = conn.execute("SELECT creditos_saldo, creditos_expira FROM users WHERE id = ?", (user["id"],)).fetchone()
        if row:
            saldo = row[0] or 0
            expira = row[1] or ""
    except Exception:
        pass

    # Verificar se créditos expiraram
    if expira and expira not in ("", "never"):
        try:
            exp_date = datetime.fromisoformat(expira)
            if exp_date < datetime.now(timezone.utc):
                # Créditos expiraram — zerar
                conn.execute("UPDATE users SET creditos_saldo = 0, creditos_expira = '' WHERE id = ?", (user["id"],))
                conn.commit()
                saldo = 0
                expira = ""
        except (ValueError, TypeError):
            pass

    dias_disponiveis = calcular_dias_creditos(saldo)
    return {
        "saldo": saldo,
        "dias_disponiveis": dias_disponiveis,
        "creditos_por_mes": CREDIT_CONFIG["creditos_por_mes"],
        "dias_por_credito": CREDIT_CONFIG["dias_por_credito"],
        "expira": expira,
        "precos": CREDIT_CONFIG["precos"],
    }


@router.post("/creditos/comprar")
def comprar_creditos(
    body: dict = Body(...),
    user=Depends(get_current_user),
    conn=Depends(get_db_session)
):
    """Compra créditos e adiciona ao saldo.

    body: {quantidade: int, expiracao_dias: int (opcional, null=sem expiração)}
    Em produção: integraria com gateway de pagamento.
    """
    from plans import CREDIT_CONFIG, calcular_dias_creditos

    quantidade = body.get("quantidade", 0)
    expiracao_dias = body.get("expiracao_dias")  # None = sem expiração

    if quantidade < 1:
        raise HTTPException(status_code=400, detail="Quantidade mínima: 1 crédito")

    # Saldo atual
    row = conn.execute("SELECT creditos_saldo FROM users WHERE id = ?", (user["id"],)).fetchone()
    saldo_anterior = row[0] if row and row[0] else 0
    saldo_posterior = saldo_anterior + quantidade

    # Calcular expiração
    expira = ""
    if expiracao_dias and expiracao_dias > 0:
        expira = (datetime.now(timezone.utc) + timedelta(days=expiracao_dias)).isoformat()

    # Atualizar saldo
    try:
        conn.execute(
            "UPDATE users SET creditos_saldo = ?, creditos_expira = ? WHERE id = ?",
            (saldo_posterior, expira or "never", user["id"])
        )
    except Exception:
        # Se coluna não existe ainda, apenas registrar no histórico
        pass

    # Registrar no histórico
    try:
        conn.execute("""
            INSERT INTO creditos_historico (user_id, tipo, quantidade, saldo_anterior, saldo_posterior, motivo, expira, created_at)
            VALUES (?, 'compra', ?, ?, ?, ?, ?, ?)
        """, (user["id"], quantidade, saldo_anterior, saldo_posterior,
              f"Compra de {quantidade} créditos", expira, datetime.now(timezone.utc).isoformat()))
    except Exception:
        pass

    conn.commit()

    # Calcular preço (em produção viria do gateway)
    preco = CREDIT_CONFIG["precos"].get(quantidade, quantidade * 4.90)

    log.info(f"User {user['email']} comprou {quantidade} créditos (saldo: {saldo_posterior})")
    return {
        "ok": True,
        "quantidade": quantidade,
        "saldo_anterior": saldo_anterior,
        "saldo_posterior": saldo_posterior,
        "dias_adicionados": calcular_dias_creditos(quantidade),
        "preco": preco,
        "expira": expira or "Sem expiração",
    }


@router.post("/creditos/ativar")
def ativar_creditos(
    body: dict = Body(...),
    user=Depends(get_current_user),
    conn=Depends(get_db_session)
):
    """Ativa créditos convertendo em dias de acesso Premium.

    body: {creditos: int} — quantos créditos gastar (mínimo 1 = 3 dias)
    Créditos residuais (saldo após ativação) ficam para próxima ativação.
    """
    from plans import CREDIT_CONFIG, calcular_dias_creditos

    creditos_usar = body.get("creditos", 0)
    if creditos_usar < 1:
        raise HTTPException(status_code=400, detail="Mínimo 1 crédito para ativar")

    # Verificar saldo
    row = conn.execute("SELECT creditos_saldo, plano, plano_expira FROM users WHERE id = ?", (user["id"],)).fetchone()
    saldo = row[0] if row and row[0] else 0

    if creditos_usar > saldo:
        raise HTTPException(status_code=400, detail=f"Saldo insuficiente. Você tem {saldo} créditos.")

    # Calcular dias a adicionar
    dias = calcular_dias_creditos(creditos_usar)
    if dias < 1:
        raise HTTPException(status_code=400, detail="Créditos insuficientes para 1 dia de acesso")

    # Determinar data base (se já tem premium ativo, estender; senão, partir de hoje)
    plano_atual = row[1] or "free"
    plano_expira = row[2] or ""

    if plano_atual == "premium" and plano_expira and plano_expira not in ("vitalicio", "vitalício", "lifetime"):
        try:
            base = datetime.fromisoformat(plano_expira)
            if base > datetime.now(timezone.utc):
                nova_expira = (base + timedelta(days=dias)).isoformat()
            else:
                nova_expira = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()
        except (ValueError, TypeError):
            nova_expira = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()
    else:
        nova_expira = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()

    # Debitar créditos e ativar premium
    novo_saldo = saldo - creditos_usar
    conn.execute(
        "UPDATE users SET creditos_saldo = ?, plano = 'premium', plano_expira = ? WHERE id = ?",
        (novo_saldo, nova_expira, user["id"])
    )

    # Registrar no histórico
    try:
        conn.execute("""
            INSERT INTO creditos_historico (user_id, tipo, quantidade, saldo_anterior, saldo_posterior, motivo, created_at)
            VALUES (?, 'ativacao', ?, ?, ?, ?, ?)
        """, (user["id"], -creditos_usar, saldo, novo_saldo,
              f"Ativação de {dias} dias Premium ({creditos_usar} créditos)",
              datetime.now(timezone.utc).isoformat()))
    except Exception:
        pass

    conn.commit()

    log.info(f"User {user['email']} ativou {creditos_usar} créditos = {dias} dias Premium (saldo: {novo_saldo})")
    return {
        "ok": True,
        "creditos_usados": creditos_usar,
        "dias_ativados": dias,
        "saldo_restante": novo_saldo,
        "plano": "premium",
        "expira": nova_expira,
        "mensagem": f"✅ {dias} dias de Premium ativados! Saldo restante: {novo_saldo} créditos.",
    }


@router.get("/creditos/historico")
def historico_creditos(user=Depends(get_current_user), conn=Depends(get_db_session)):
    """Retorna histórico de compras e ativações de créditos."""
    try:
        rows = conn.execute("""
            SELECT tipo, quantidade, saldo_anterior, saldo_posterior, motivo, expira, created_at
            FROM creditos_historico WHERE user_id = ?
            ORDER BY created_at DESC LIMIT 50
        """, (user["id"],)).fetchall()
        return {"items": [dict(r) for r in rows]}
    except Exception:
        return {"items": []}


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
