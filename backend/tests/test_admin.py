"""
Testes do módulo de administração (routers/admin.py).
Testa CRUD de usuários e controle de acesso (admin vs non-admin).
Com AUTH_ENABLED=true — usa fluxo real de autenticação.

O user_id=1 (seed) possui role='admin' por padrão.
Para obter token de admin: register com email do seed → login → verify-code.

Executar: pytest tests/test_admin.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "true"

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

# Garantir que o user seed (id=1) tem role='admin' — a migration roda antes do seed,
# então o UPDATE SET role='admin' WHERE id=1 não pega. Forçamos aqui.
_conn_setup = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
_conn_setup.execute("UPDATE users SET role = 'admin' WHERE id = 1")
_conn_setup.commit()
_conn_setup.close()

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


def _get_admin_token(client) -> str:
    """Obtém token JWT para o usuário admin (id=1).

    O seed cria user id=1 com email 'guest@concurseiroos.local' e role='admin'.
    Como o email seed usa TLD .local (rejeitado pelo Pydantic EmailStr),
    geramos o token JWT diretamente — equivalente ao que verify-code faria.
    """
    import jwt as pyjwt
    from settings import settings

    # Atualizar email do admin seed para um email válido, para permitir login via API em outros testes
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    # Verificar dados do admin
    admin = conn.execute("SELECT id, email, role FROM users WHERE id = 1").fetchone()
    conn.close()

    assert admin is not None, "Admin seed (id=1) não encontrado no banco"

    # Gerar token JWT diretamente (mesmo algoritmo que auth.py usa)
    payload = {
        "sub": str(admin["id"]),
        "email": admin["email"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _register_and_get_token(client, email: str, nome: str = "Test User") -> str:
    """Registra um usuário comum e retorna seu token JWT."""
    client.post("/api/auth/register", json={"email": email, "nome": nome})
    code = _get_code_from_db(email)
    resp = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    return resp.json()["token"]


def _auth_header(token: str) -> dict:
    """Retorna header Authorization com Bearer token."""
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# LISTAR USUÁRIOS
# ============================================================

class TestListUsers:
    def test_list_users_admin(self, client):
        """GET /api/admin/users — admin pode listar usuários."""
        token = _get_admin_token(client)
        r = client.get("/api/admin/users", headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert "users" in data
        assert "total" in data
        assert data["total"] >= 1
        # O admin (seed user) deve estar na lista
        emails = [u["email"] for u in data["users"]]
        assert "guest@concurseiroos.local" in emails

    def test_list_users_non_admin_403(self, client):
        """GET /api/admin/users — non-admin recebe 403."""
        token = _register_and_get_token(client, "nonadmin@example.com", "Non Admin")
        r = client.get("/api/admin/users", headers=_auth_header(token))
        assert r.status_code == 403
        assert "administrador" in r.json()["detail"].lower() or "restrito" in r.json()["detail"].lower()

    def test_list_users_sem_token_401(self, client):
        """GET /api/admin/users — sem token retorna 401."""
        r = client.get("/api/admin/users")
        assert r.status_code == 401

    def test_list_users_pagination(self, client):
        """GET /api/admin/users — paginação funciona."""
        token = _get_admin_token(client)
        r = client.get("/api/admin/users?page=1&limit=5", headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert data["page"] == 1
        assert data["limit"] == 5

    def test_list_users_search(self, client):
        """GET /api/admin/users — busca por nome/email."""
        token = _get_admin_token(client)
        r = client.get("/api/admin/users?search=guest", headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1


# ============================================================
# CRIAR USUÁRIO
# ============================================================

class TestCreateUser:
    def test_create_user_admin(self, client):
        """POST /api/admin/users — admin cria usuário com sucesso."""
        token = _get_admin_token(client)
        r = client.post("/api/admin/users",
                        json={
                            "email": "created@example.com",
                            "nome": "Created User",
                            "username": "created",
                            "plano": "premium",
                            "password": "senha123"
                        },
                        headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["email"] == "created@example.com"
        assert data["nome"] == "Created User"
        assert data["plano"] == "premium"
        assert "id" in data

    def test_create_user_email_duplicado(self, client):
        """POST /api/admin/users — email duplicado retorna 409."""
        token = _get_admin_token(client)
        # Tentar criar com email que já existe
        r = client.post("/api/admin/users",
                        json={
                            "email": "created@example.com",
                            "nome": "Dup",
                            "username": "dup"
                        },
                        headers=_auth_header(token))
        assert r.status_code == 409
        assert "já cadastrado" in r.json()["detail"].lower()

    def test_create_user_non_admin_403(self, client):
        """POST /api/admin/users — non-admin recebe 403."""
        token = _register_and_get_token(client, "nonadmin2@example.com", "Non Admin 2")
        r = client.post("/api/admin/users",
                        json={"email": "hack@example.com", "nome": "Hacker"},
                        headers=_auth_header(token))
        assert r.status_code == 403


# ============================================================
# ATUALIZAR USUÁRIO
# ============================================================

class TestUpdateUser:
    def test_update_user_admin(self, client):
        """PUT /api/admin/users/{id} — admin atualiza usuário."""
        token = _get_admin_token(client)

        # Primeiro criar um usuário para atualizar
        r = client.post("/api/admin/users",
                        json={"email": "update@example.com", "nome": "Original", "username": "orig"},
                        headers=_auth_header(token))
        uid = r.json()["id"]

        # Atualizar nome
        r = client.put(f"/api/admin/users/{uid}",
                       json={"nome": "Updated Name", "plano": "ilimitado"},
                       headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "nome" in data["updated_fields"]
        assert "plano" in data["updated_fields"]

    def test_update_user_not_found(self, client):
        """PUT /api/admin/users/{id} — usuário inexistente retorna 404."""
        token = _get_admin_token(client)
        r = client.put("/api/admin/users/99999",
                       json={"nome": "Ghost"},
                       headers=_auth_header(token))
        assert r.status_code == 404

    def test_update_user_non_admin_403(self, client):
        """PUT /api/admin/users/{id} — non-admin recebe 403."""
        token = _register_and_get_token(client, "nonadmin3@example.com", "Non Admin 3")
        r = client.put("/api/admin/users/1",
                       json={"nome": "Hacked"},
                       headers=_auth_header(token))
        assert r.status_code == 403

    def test_update_user_email_duplicado(self, client):
        """PUT /api/admin/users/{id} — email duplicado retorna 409."""
        token = _get_admin_token(client)

        # Criar dois usuários
        r1 = client.post("/api/admin/users",
                         json={"email": "emaila@example.com", "nome": "A", "username": "a"},
                         headers=_auth_header(token))
        r2 = client.post("/api/admin/users",
                         json={"email": "emailb@example.com", "nome": "B", "username": "b"},
                         headers=_auth_header(token))
        uid_b = r2.json()["id"]

        # Tentar mudar email de B para o email de A
        r = client.put(f"/api/admin/users/{uid_b}",
                       json={"email": "emaila@example.com"},
                       headers=_auth_header(token))
        assert r.status_code == 409

    def test_update_user_role(self, client):
        """PUT /api/admin/users/{id} — admin altera role do usuário."""
        token = _get_admin_token(client)

        r = client.post("/api/admin/users",
                        json={"email": "rolechange@example.com", "nome": "Role", "username": "roleuser"},
                        headers=_auth_header(token))
        uid = r.json()["id"]

        r = client.put(f"/api/admin/users/{uid}",
                       json={"role": "admin"},
                       headers=_auth_header(token))
        assert r.status_code == 200
        assert "role" in r.json()["updated_fields"]


# ============================================================
# EXCLUIR USUÁRIO
# ============================================================

class TestDeleteUser:
    def test_delete_user_admin(self, client):
        """DELETE /api/admin/users/{id} — admin exclui usuário."""
        token = _get_admin_token(client)

        # Criar usuário para deletar
        r = client.post("/api/admin/users",
                        json={"email": "delete@example.com", "nome": "Delete Me", "username": "del"},
                        headers=_auth_header(token))
        uid = r.json()["id"]

        r = client.delete(f"/api/admin/users/{uid}", headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["deleted_user"]["email"] == "delete@example.com"

    def test_delete_admin_user_blocked(self, client):
        """DELETE /api/admin/users/1 — não pode excluir o admin (id=1)."""
        token = _get_admin_token(client)
        r = client.delete("/api/admin/users/1", headers=_auth_header(token))
        assert r.status_code == 400
        assert "administrador" in r.json()["detail"].lower()

    def test_delete_user_not_found(self, client):
        """DELETE /api/admin/users/{id} — usuário inexistente retorna 404."""
        token = _get_admin_token(client)
        r = client.delete("/api/admin/users/99999", headers=_auth_header(token))
        assert r.status_code == 404

    def test_delete_user_non_admin_403(self, client):
        """DELETE /api/admin/users/{id} — non-admin recebe 403."""
        token = _register_and_get_token(client, "nonadmin4@example.com", "Non Admin 4")
        r = client.delete("/api/admin/users/2", headers=_auth_header(token))
        assert r.status_code == 403


# ============================================================
# ACESSO SEM AUTENTICAÇÃO
# ============================================================

class TestAdminNoAuth:
    def test_all_admin_endpoints_require_auth(self, client):
        """Todos os endpoints admin retornam 401 sem token."""
        endpoints = [
            ("GET", "/api/admin/users"),
            ("POST", "/api/admin/users"),
            ("PUT", "/api/admin/users/1"),
            ("DELETE", "/api/admin/users/2"),
            ("GET", "/api/admin/stats"),
        ]
        for method, url in endpoints:
            if method == "GET":
                r = client.get(url)
            elif method == "POST":
                r = client.post(url, json={"email": "x@x.com", "nome": "x"})
            elif method == "PUT":
                r = client.put(url, json={"nome": "x"})
            elif method == "DELETE":
                r = client.delete(url)
            assert r.status_code == 401, f"{method} {url} deveria retornar 401, retornou {r.status_code}"


# ============================================================
# ESTATÍSTICAS GLOBAIS
# ============================================================

class TestAdminStats:
    def test_stats_admin(self, client):
        """GET /api/admin/stats — admin acessa estatísticas globais."""
        token = _get_admin_token(client)
        r = client.get("/api/admin/stats", headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert "total_users" in data
        assert "usuarios_por_plano" in data
        assert data["total_users"] >= 1

    def test_stats_non_admin_403(self, client):
        """GET /api/admin/stats — non-admin recebe 403."""
        token = _register_and_get_token(client, "nonadmin5@example.com", "Non Admin 5")
        r = client.get("/api/admin/stats", headers=_auth_header(token))
        assert r.status_code == 403


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
