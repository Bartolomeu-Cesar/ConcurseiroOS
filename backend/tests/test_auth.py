"""
Testes do módulo de autenticação (routers/auth.py).
Testa o fluxo completo: register → login → verify-code → token → perfil.
Com AUTH_ENABLED=true para validar autenticação real.

Executar: pytest tests/test_auth.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_auth.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "true"

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app
from settings import settings


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    """TestClient compartilhado por todo o módulo de testes."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db():
    """Garante que o DB correto está ativo e AUTH_ENABLED=true antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    settings.AUTH_ENABLED = True
    app.dependency_overrides[get_db_session] = _override_db_session
    yield
    settings.AUTH_ENABLED = False


def _get_code_from_db(email: str) -> str:
    """Busca o código de verificação mais recente no banco para um email."""
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT code FROM auth_codes WHERE email = ? AND used = 0 ORDER BY created_at DESC LIMIT 1",
        (email,)
    ).fetchone()
    conn.close()
    return row["code"] if row else ""


def _register_and_get_token(client, email="test@example.com", nome="Test User") -> str:
    """Registra usuário, pega código do DB e verifica para obter token JWT."""
    client.post("/api/auth/register", json={"email": email, "nome": nome})
    code = _get_code_from_db(email)
    resp = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    return resp.json()["token"]


def _auth_header(token: str) -> dict:
    """Retorna header Authorization com Bearer token."""
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# REGISTER
# ============================================================

class TestRegister:
    def test_register_success(self, client):
        """POST /api/auth/register — cria conta com sucesso."""
        r = client.post("/api/auth/register", json={
            "email": "novo@example.com",
            "nome": "Novo Usuário"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "Conta criada" in data["message"]

        # Verificar que código foi gerado no DB
        code = _get_code_from_db("novo@example.com")
        assert len(code) == 6
        assert code.isdigit()

    def test_register_email_duplicado(self, client):
        """POST /api/auth/register — email já cadastrado retorna 409."""
        # Registrar a primeira vez
        client.post("/api/auth/register", json={
            "email": "dup@example.com",
            "nome": "Primeiro"
        })
        # Tentar registrar novamente
        r = client.post("/api/auth/register", json={
            "email": "dup@example.com",
            "nome": "Segundo"
        })
        assert r.status_code == 409
        assert "já cadastrado" in r.json()["detail"]


# ============================================================
# LOGIN
# ============================================================

class TestLogin:
    def test_login_success(self, client):
        """POST /api/auth/login — envia código para email cadastrado."""
        # Primeiro registrar
        client.post("/api/auth/register", json={
            "email": "login@example.com",
            "nome": "Login User"
        })
        # Fazer login
        r = client.post("/api/auth/login", json={"email": "login@example.com"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True

        # Verificar que novo código foi gerado
        code = _get_code_from_db("login@example.com")
        assert len(code) == 6

    def test_login_email_nao_cadastrado(self, client):
        """POST /api/auth/login — email não cadastrado retorna 404."""
        r = client.post("/api/auth/login", json={"email": "inexistente@example.com"})
        assert r.status_code == 404
        assert "não cadastrado" in r.json()["detail"]


# ============================================================
# VERIFY-CODE
# ============================================================

class TestVerifyCode:
    def test_verify_code_valido(self, client):
        """POST /api/auth/verify-code — código válido retorna token JWT."""
        # Registrar novo usuário
        client.post("/api/auth/register", json={
            "email": "verify@example.com",
            "nome": "Verify User"
        })
        code = _get_code_from_db("verify@example.com")

        r = client.post("/api/auth/verify-code", json={
            "email": "verify@example.com",
            "code": code
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "token" in data
        assert len(data["token"]) > 20  # JWT tem pelo menos ~100 chars
        assert data["user"]["email"] == "verify@example.com"
        assert data["user"]["nome"] == "Verify User"

    def test_verify_code_errado(self, client):
        """POST /api/auth/verify-code — código errado retorna 401."""
        client.post("/api/auth/register", json={
            "email": "wrong@example.com",
            "nome": "Wrong Code"
        })

        r = client.post("/api/auth/verify-code", json={
            "email": "wrong@example.com",
            "code": "000000"  # Código inválido
        })
        assert r.status_code == 401
        assert "inválido" in r.json()["detail"].lower() or "expirado" in r.json()["detail"].lower()

    def test_verify_code_rate_limit(self, client):
        """POST /api/auth/verify-code — muitas tentativas retorna 429."""
        email = "ratelimit@example.com"
        client.post("/api/auth/register", json={"email": email, "nome": "Rate"})

        # Inserir 5 tentativas falhadas diretamente no banco
        conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
        now = datetime.now(timezone.utc).isoformat()
        for _ in range(5):
            conn.execute(
                "INSERT INTO auth_attempts (email, ip, created_at) VALUES (?, ?, ?)",
                (email, "testclient", now)
            )
        conn.commit()
        conn.close()

        # Agora tentar verificar — deve ser bloqueado
        r = client.post("/api/auth/verify-code", json={
            "email": email,
            "code": "123456"
        })
        assert r.status_code == 429
        assert "Muitas tentativas" in r.json()["detail"]


# ============================================================
# GET /api/auth/me
# ============================================================

class TestMe:
    def test_me_com_token_valido(self, client):
        """GET /api/auth/me — token válido retorna dados do usuário."""
        token = _register_and_get_token(client, "me@example.com", "Me User")

        r = client.get("/api/auth/me", headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == "me@example.com"
        assert data["nome"] == "Me User"
        assert data["auth_enabled"] is True

    def test_me_sem_token(self, client):
        """GET /api/auth/me — sem token retorna fallback (guest) pois usa get_optional_user."""
        r = client.get("/api/auth/me")
        assert r.status_code == 200
        # Sem token, retorna o user padrão (id=1) como fallback
        data = r.json()
        assert data["auth_enabled"] is True

    def test_me_token_expirado(self, client):
        """GET /api/auth/me — token expirado. get_optional_user retorna None (fallback)."""
        import jwt
        from settings import settings
        # Criar token já expirado
        payload = {
            "sub": "999",
            "email": "expired@example.com",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

        r = client.get("/api/auth/me", headers=_auth_header(expired_token))
        # get_optional_user captura exceções e retorna None → fallback para guest
        assert r.status_code == 200

    def test_me_token_invalido(self, client):
        """GET /api/auth/me — token inválido. get_optional_user retorna None (fallback)."""
        r = client.get("/api/auth/me", headers=_auth_header("token.invalido.aqui"))
        # get_optional_user captura exceções e retorna None → fallback para guest
        assert r.status_code == 200


# ============================================================
# PUT /api/auth/profile
# ============================================================

class TestProfile:
    def test_update_nome(self, client):
        """PUT /api/auth/profile — atualizar nome com sucesso."""
        token = _register_and_get_token(client, "profile@example.com", "Old Name")

        r = client.put("/api/auth/profile",
                       json={"nome": "New Name"},
                       headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["nome"] == "New Name"

    def test_update_profile_sem_token(self, client):
        """PUT /api/auth/profile — sem token retorna 401 (usa get_current_user)."""
        r = client.put("/api/auth/profile", json={"nome": "Hacker"})
        assert r.status_code == 401

    def test_update_profile_token_invalido(self, client):
        """PUT /api/auth/profile — token inválido retorna 401."""
        r = client.put("/api/auth/profile",
                       json={"nome": "Hacker"},
                       headers=_auth_header("invalid.token.here"))
        assert r.status_code == 401


# ============================================================
# TOKEN JWT — ACESSO A ENDPOINTS PROTEGIDOS
# ============================================================

class TestTokenJWT:
    def test_token_valido_da_acesso(self, client):
        """Token JWT válido permite acesso a endpoints protegidos."""
        token = _register_and_get_token(client, "jwt@example.com", "JWT User")

        # /api/auth/profile requer get_current_user (AUTH_ENABLED=true)
        r = client.put("/api/auth/profile",
                       json={"nome": "Updated"},
                       headers=_auth_header(token))
        assert r.status_code == 200

    def test_token_invalido_retorna_401(self, client):
        """Token JWT inválido retorna 401 em endpoints protegidos."""
        r = client.put("/api/auth/profile",
                       json={"nome": "Hacker"},
                       headers=_auth_header("eyJhbGciOiJIUzI1NiJ9.invalid.payload"))
        assert r.status_code == 401

    def test_token_expirado_retorna_401(self, client):
        """Token JWT expirado retorna 401 em endpoints protegidos."""
        import jwt
        from settings import settings
        payload = {
            "sub": "1",
            "email": "expired@example.com",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

        r = client.put("/api/auth/profile",
                       json={"nome": "Hacker"},
                       headers=_auth_header(expired_token))
        assert r.status_code == 401

    def test_sem_token_retorna_401(self, client):
        """Sem token retorna 401 em endpoints que usam get_current_user."""
        r = client.put("/api/auth/profile", json={"nome": "Hacker"})
        assert r.status_code == 401


# ============================================================
# AUTH STATUS (endpoint público)
# ============================================================

class TestAuthStatus:
    def test_auth_status(self, client):
        """GET /api/auth/status — retorna status da autenticação."""
        r = client.get("/api/auth/status")
        assert r.status_code == 200
        data = r.json()
        assert data["auth_enabled"] is True
        assert "smtp_configured" in data


# ============================================================
# EXPIRAÇÃO DO CÓDIGO DE LOGIN
# ============================================================

class TestCodigoExpiracao:
    def test_codigo_expirado_rejeitado(self, client):
        """verify-code rejeita (401) um código cujo expires_at já passou."""
        email = "expira_codigo@example.com"
        client.post("/api/auth/register", json={"email": email, "nome": "Expira"})
        code = _get_code_from_db(email)
        assert len(code) == 6

        # Força o código a estar expirado (expires_at no passado).
        passado = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
        conn.execute(
            "UPDATE auth_codes SET expires_at = ? WHERE email = ? AND used = 0",
            (passado, email),
        )
        conn.commit()
        conn.close()

        r = client.post("/api/auth/verify-code", json={"email": email, "code": code})
        assert r.status_code == 401
        assert "expirado" in r.json()["detail"].lower() or "inválido" in r.json()["detail"].lower()

    def test_codigo_valido_dentro_da_validade(self, client):
        """verify-code aceita um código dentro da validade (expires_at futuro)."""
        email = "valido_codigo@example.com"
        client.post("/api/auth/register", json={"email": email, "nome": "Valido"})
        code = _get_code_from_db(email)
        # expires_at padrão é futuro; verificação deve funcionar.
        r = client.post("/api/auth/verify-code", json={"email": email, "code": code})
        assert r.status_code == 200
        assert "token" in r.json()

    def test_validade_no_maximo_24h(self):
        """O teto de validade do código nunca ultrapassa 24h (1440 min)."""
        assert settings.AUTH_CODE_EXPIRE_MINUTES <= 1440
        assert settings.AUTH_CODE_EXPIRE_MINUTES >= 1

    def test_login_usa_validade_configurada(self, client):
        """O login respeita a validade em minutos gravada em app_config (config do admin)."""
        from datetime import datetime as _dt, timezone as _tz
        email = "cfg_expire@example.com"
        client.post("/api/auth/register", json={"email": email, "nome": "Cfg"})

        # Admin configura a validade para 120 minutos (grava em app_config).
        conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
        conn.execute(
            """INSERT INTO app_config (chave, valor, updated_at) VALUES ('auth_code_expire_minutes', '120', ?)
               ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor, updated_at=excluded.updated_at""",
            (_dt.now(_tz.utc).isoformat(),),
        )
        conn.commit()
        conn.close()

        # Novo login gera código com expires_at ~ agora + 120 min.
        client.post("/api/auth/login", json={"email": email})
        conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT created_at, expires_at FROM auth_codes WHERE email = ? ORDER BY created_at DESC LIMIT 1",
            (email,),
        ).fetchone()
        # Limpa a config para não vazar para outros testes.
        conn.execute("DELETE FROM app_config WHERE chave = 'auth_code_expire_minutes'")
        conn.commit()
        conn.close()

        created = _dt.fromisoformat(row["created_at"])
        expires = _dt.fromisoformat(row["expires_at"])
        delta_min = (expires - created).total_seconds() / 60
        assert 119 <= delta_min <= 121, f"esperado ~120 min, obtido {delta_min:.1f}"


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
