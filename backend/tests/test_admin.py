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

    O seed cria user id=1 com email 'admin@concurseiroos.app' e role='admin'.
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
        assert "admin@concurseiroos.app" in emails

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
        r = client.get("/api/admin/users?search=Bartholomew", headers=_auth_header(token))
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
# MONETIZAÇÃO
# ============================================================

class TestMonetizacao:
    def test_get_monetizacao_admin(self, client):
        """GET /api/admin/monetizacao — retorna config de vitalício e créditos."""
        token = _get_admin_token(client)
        r = client.get("/api/admin/monetizacao", headers=_auth_header(token))
        assert r.status_code == 200
        data = r.json()
        assert "vitalicio" in data
        assert "creditos" in data
        assert "preco" in data["vitalicio"]
        assert "status" in data["vitalicio"]
        assert "precos" in data["creditos"]

    def test_get_monetizacao_non_admin_403(self, client):
        """GET /api/admin/monetizacao — non-admin recebe 403."""
        token = _register_and_get_token(client, "nonadmin_mon@example.com", "NA Mon")
        r = client.get("/api/admin/monetizacao", headers=_auth_header(token))
        assert r.status_code == 403

    def test_update_janela_vitalicio(self, client):
        """PUT /api/admin/monetizacao — salva janela e afeta disponibilidade."""
        token = _get_admin_token(client)
        # Definir janela no passado → vitalício indisponível
        r = client.put("/api/admin/monetizacao", headers=_auth_header(token), json={
            "vitalicio_venda_inicio": "2020-01-01",
            "vitalicio_venda_fim": "2020-01-07",
        })
        assert r.status_code == 200
        # Verificar via status
        r2 = client.get("/api/auth/vitalicio-status")
        assert r2.status_code == 200
        assert r2.json()["disponivel"] is False

    def test_update_janela_vitalicio_disponivel(self, client):
        """PUT janela cobrindo hoje → vitalício disponível."""
        token = _get_admin_token(client)
        from datetime import date, timedelta as _td
        ontem = (date.today() - _td(days=1)).isoformat()
        amanha = (date.today() + _td(days=1)).isoformat()
        r = client.put("/api/admin/monetizacao", headers=_auth_header(token), json={
            "vitalicio_venda_inicio": ontem,
            "vitalicio_venda_fim": amanha,
        })
        assert r.status_code == 200
        r2 = client.get("/api/auth/vitalicio-status")
        assert r2.json()["disponivel"] is True

    def test_update_preco_vitalicio(self, client):
        """PUT preço do vitalício persiste."""
        token = _get_admin_token(client)
        r = client.put("/api/admin/monetizacao", headers=_auth_header(token), json={"vitalicio_preco": 129.90})
        assert r.status_code == 200
        r2 = client.get("/api/admin/monetizacao", headers=_auth_header(token))
        assert abs(r2.json()["vitalicio"]["preco"] - 129.90) < 0.01

    def test_update_precos_creditos(self, client):
        """PUT preços de créditos persiste."""
        token = _get_admin_token(client)
        r = client.put("/api/admin/monetizacao", headers=_auth_header(token), json={
            "creditos_precos": {"1": 5.90, "10": 39.90}
        })
        assert r.status_code == 200
        r2 = client.get("/api/admin/monetizacao", headers=_auth_header(token))
        precos = r2.json()["creditos"]["precos"]
        assert abs(float(precos["1"]) - 5.90) < 0.01

    def test_update_janela_invalida_400(self, client):
        """PUT janela com data inválida retorna 400."""
        token = _get_admin_token(client)
        r = client.put("/api/admin/monetizacao", headers=_auth_header(token), json={
            "vitalicio_venda_inicio": "not-a-date"
        })
        assert r.status_code == 400

    def test_dar_creditos_brinde(self, client):
        """POST /api/admin/users/{uid}/creditos — adiciona créditos."""
        token = _get_admin_token(client)
        # Criar user alvo
        uid = client.post("/api/admin/users", headers=_auth_header(token),
                          json={"email": "brinde@example.com", "nome": "Brinde", "username": "brinde", "plano": "free"}).json()["id"]
        r = client.post(f"/api/admin/users/{uid}/creditos", headers=_auth_header(token),
                       json={"quantidade": 15, "motivo": "Teste"})
        assert r.status_code == 200
        data = r.json()
        assert data["saldo_posterior"] == data["saldo_anterior"] + 15

    def test_dar_creditos_zero_400(self, client):
        """POST créditos com quantidade zero retorna 400."""
        token = _get_admin_token(client)
        r = client.post("/api/admin/users/1/creditos", headers=_auth_header(token), json={"quantidade": 0})
        assert r.status_code == 400

    def test_ativar_premium_premio(self, client):
        """POST /api/admin/users/{uid}/ativar-plano — Premium por N dias."""
        token = _get_admin_token(client)
        uid = client.post("/api/admin/users", headers=_auth_header(token),
                          json={"email": "premio@example.com", "nome": "Premio", "username": "premio", "plano": "free"}).json()["id"]
        r = client.post(f"/api/admin/users/{uid}/ativar-plano", headers=_auth_header(token),
                       json={"tipo": "premium", "dias": 60})
        assert r.status_code == 200
        assert r.json()["plano"] == "premium"
        assert r.json()["dias"] == 60

    def test_ativar_vitalicio_premio(self, client):
        """POST ativar-plano vitalício → plano ilimitado."""
        token = _get_admin_token(client)
        uid = client.post("/api/admin/users", headers=_auth_header(token),
                          json={"email": "vit@example.com", "nome": "Vit", "username": "vit", "plano": "free"}).json()["id"]
        r = client.post(f"/api/admin/users/{uid}/ativar-plano", headers=_auth_header(token),
                       json={"tipo": "vitalicio"})
        assert r.status_code == 200
        assert r.json()["plano"] == "ilimitado"
        assert r.json()["expira"] == "vitalicio"

    def test_ativar_plano_tipo_invalido_400(self, client):
        """POST ativar-plano com tipo inválido retorna 400."""
        token = _get_admin_token(client)
        r = client.post("/api/admin/users/1/ativar-plano", headers=_auth_header(token), json={"tipo": "xyz"})
        assert r.status_code == 400

    def test_monetizacao_non_admin_bloqueado(self, client):
        """Endpoints de monetização bloqueiam non-admin."""
        token = _register_and_get_token(client, "namon2@example.com", "NA Mon2")
        r1 = client.post("/api/admin/users/1/creditos", headers=_auth_header(token), json={"quantidade": 5})
        r2 = client.post("/api/admin/users/1/ativar-plano", headers=_auth_header(token), json={"tipo": "premium", "dias": 30})
        assert r1.status_code == 403
        assert r2.status_code == 403


# ============================================================
# COMPARTILHAMENTO DE RECURSOS
# ============================================================

class TestCompartilhamento:
    def _criar_user(self, client, token, email, nome):
        return client.post("/api/admin/users", headers=_auth_header(token),
                          json={"email": email, "nome": nome, "username": email.split("@")[0], "plano": "free"}).json()["id"]

    def _seed_recursos(self, origem_uid):
        """Insere questão, flashcard, súmula, caderno, edital, vademecum e planejador para o user origem."""
        conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        now = datetime.now().isoformat()
        # Questão
        cur = conn.execute("""
            INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, resposta_correta, created_at, user_id)
            VALUES ('Dir', 'T1', 'Q?', 'a', 'b', 'c', 'd', '', 'A', ?, ?)
        """, (now, origem_uid))
        qid = cur.lastrowid
        # Flashcard
        conn.execute("INSERT INTO flashcards (pergunta, resposta, proxima_revisao, user_id) VALUES ('P', 'R', ?, ?)", (now, origem_uid))
        # Súmula
        conn.execute("INSERT INTO sumulas (tribunal, numero, enunciado, proxima_revisao, user_id) VALUES ('STF', 1, 'Enun', ?, ?)", (now, origem_uid))
        # Caderno + associação
        cur2 = conn.execute("INSERT INTO cadernos (nome, descricao, created_at, user_id) VALUES ('Cad', '', ?, ?)", (now, origem_uid))
        cad_id = cur2.lastrowid
        try:
            conn.execute("INSERT INTO cadernos_questoes (caderno_id, questao_id, ordem, added_at) VALUES (?, ?, 0, ?)", (cad_id, qid, now))
        except Exception:
            pass
        # Edital verticalizado + info + resumo + nota
        cur3 = conn.execute("""
            INSERT INTO edital (edital_nome, cargo, materia, topico, status, user_id)
            VALUES ('TJ 2026', 'Analista', 'Dir Const', 'Princípios', 'Concluído', ?)
        """, (origem_uid,))
        edital_id = cur3.lastrowid
        try:
            conn.execute("INSERT INTO edital_info (edital_nome, cargo, orgao, user_id) VALUES ('TJ 2026', 'Analista', 'TJ', ?)", (origem_uid,))
        except Exception:
            pass
        try:
            conn.execute("INSERT INTO resumos (edital_id, resumo, tipo, created_at, user_id) VALUES (?, 'Resumo X', 'texto', ?, ?)", (edital_id, now, origem_uid))
        except Exception:
            pass
        try:
            conn.execute("INSERT INTO notas_topico (edital_id, conteudo, created_at, user_id) VALUES (?, 'Nota Y', ?, ?)", (edital_id, now, origem_uid))
        except Exception:
            pass
        # Vade mécum: lei + artigo
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vademecum_leis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1,
                    nome TEXT NOT NULL, sigla TEXT DEFAULT '', numero TEXT DEFAULT '',
                    data_publicacao TEXT DEFAULT '', ementa TEXT DEFAULT '', created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vademecum_artigos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, lei_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL DEFAULT 1, numero TEXT NOT NULL, caput TEXT NOT NULL,
                    paragrafos TEXT DEFAULT '', incisos TEXT DEFAULT '', alineas TEXT DEFAULT '',
                    capitulo TEXT DEFAULT '', secao TEXT DEFAULT '', destacado INTEGER DEFAULT 0, anotacao TEXT DEFAULT ''
                )
            """)
            curl = conn.execute("INSERT INTO vademecum_leis (nome, sigla, created_at, user_id) VALUES ('CF', 'CF88', ?, ?)", (now, origem_uid))
            lei_id = curl.lastrowid
            conn.execute("INSERT INTO vademecum_artigos (lei_id, user_id, numero, caput) VALUES (?, ?, '5', 'Todos são iguais')", (lei_id, origem_uid))
        except Exception:
            pass
        # Planejador
        try:
            conn.execute("INSERT INTO planejador_semanal (dia_semana, materia, horas, user_id) VALUES ('seg', 'Dir', 2, ?)", (origem_uid,))
        except Exception:
            pass
        try:
            conn.execute("INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id) VALUES ('seg', 'Dir', 'T1', 60, 'estudo', 0, ?)", (origem_uid,))
        except Exception:
            pass
        conn.commit()
        conn.close()

    def test_contar_recursos(self, client):
        token = _get_admin_token(client)
        uid = self._criar_user(client, token, "origem_r@example.com", "Origem R")
        self._seed_recursos(uid)
        r = client.get(f"/api/admin/users/{uid}/recursos", headers=_auth_header(token))
        assert r.status_code == 200
        rec = r.json()["recursos"]
        assert rec["questoes"] >= 1
        assert rec["flashcards"] >= 1
        assert rec["sumulas"] >= 1
        assert rec["cadernos"] >= 1
        assert rec["editais"] >= 1
        assert rec["vademecum"] >= 1
        assert rec["planejador"] >= 1

    def test_compartilhar_copia_recursos(self, client):
        token = _get_admin_token(client)
        origem = self._criar_user(client, token, "origem_c@example.com", "Origem C")
        destino = self._criar_user(client, token, "destino_c@example.com", "Destino C")
        self._seed_recursos(origem)

        r = client.post("/api/admin/compartilhar", headers=_auth_header(token), json={
            "origem_uid": origem,
            "destino_uids": [destino],
            "recursos": ["questoes", "flashcards", "sumulas", "cadernos", "editais", "vademecum", "planejador"]
        })
        assert r.status_code == 200
        copiados = r.json()["resultado"][str(destino)]["copiados"]
        assert copiados["questoes"] >= 1
        assert copiados["flashcards"] >= 1
        assert copiados["sumulas"] >= 1
        assert copiados["cadernos"] >= 1
        assert copiados["editais"] >= 1
        assert copiados["vademecum"] >= 1
        assert copiados["planejador"] >= 1

        # Verificar que o destino agora tem os recursos
        rc = client.get(f"/api/admin/users/{destino}/recursos", headers=_auth_header(token)).json()["recursos"]
        assert rc["questoes"] >= 1
        assert rc["flashcards"] >= 1
        assert rc["cadernos"] >= 1
        assert rc["editais"] >= 1
        assert rc["vademecum"] >= 1
        assert rc["planejador"] >= 1

    def test_compartilhar_editais_com_dependentes(self, client):
        """Editais copiam edital_info, resumos e notas remapeando edital_id."""
        token = _get_admin_token(client)
        origem = self._criar_user(client, token, "origem_ed@example.com", "Origem Ed")
        destino = self._criar_user(client, token, "destino_ed@example.com", "Destino Ed")
        self._seed_recursos(origem)
        r = client.post("/api/admin/compartilhar", headers=_auth_header(token), json={
            "origem_uid": origem, "destino_uids": [destino], "recursos": ["editais"]
        })
        assert r.status_code == 200
        assert r.json()["resultado"][str(destino)]["copiados"]["editais"] >= 1
        # Verificar resumos/notas copiados com novo edital_id
        conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        resumos = conn.execute("SELECT r.edital_id FROM resumos r WHERE r.user_id = ?", (destino,)).fetchall()
        editais_ids = [row["id"] for row in conn.execute("SELECT id FROM edital WHERE user_id = ?", (destino,)).fetchall()]
        conn.close()
        # Se houve resumo, seu edital_id deve apontar para um edital do destino
        for rr in resumos:
            assert rr["edital_id"] in editais_ids

    def test_compartilhar_multiplos_destinos(self, client):
        token = _get_admin_token(client)
        origem = self._criar_user(client, token, "origem_m@example.com", "Origem M")
        d1 = self._criar_user(client, token, "dest_m1@example.com", "D1")
        d2 = self._criar_user(client, token, "dest_m2@example.com", "D2")
        self._seed_recursos(origem)
        r = client.post("/api/admin/compartilhar", headers=_auth_header(token), json={
            "origem_uid": origem, "destino_uids": [d1, d2], "recursos": ["flashcards"]
        })
        assert r.status_code == 200
        assert r.json()["resultado"][str(d1)]["copiados"]["flashcards"] >= 1
        assert r.json()["resultado"][str(d2)]["copiados"]["flashcards"] >= 1

    def test_compartilhar_mesmo_usuario_erro(self, client):
        token = _get_admin_token(client)
        uid = self._criar_user(client, token, "self_share@example.com", "Self")
        r = client.post("/api/admin/compartilhar", headers=_auth_header(token), json={
            "origem_uid": uid, "destino_uids": [uid], "recursos": ["flashcards"]
        })
        assert r.status_code == 200
        assert "erro" in r.json()["resultado"][str(uid)]

    def test_compartilhar_recurso_invalido_400(self, client):
        token = _get_admin_token(client)
        r = client.post("/api/admin/compartilhar", headers=_auth_header(token), json={
            "origem_uid": 1, "destino_uids": [2], "recursos": ["xyz"]
        })
        assert r.status_code == 400

    def test_compartilhar_sem_destino_400(self, client):
        token = _get_admin_token(client)
        r = client.post("/api/admin/compartilhar", headers=_auth_header(token), json={
            "origem_uid": 1, "destino_uids": [], "recursos": ["flashcards"]
        })
        assert r.status_code == 400

    def test_compartilhar_non_admin_403(self, client):
        token = _register_and_get_token(client, "na_share@example.com", "NA Share")
        r = client.post("/api/admin/compartilhar", headers=_auth_header(token), json={
            "origem_uid": 1, "destino_uids": [2], "recursos": ["flashcards"]
        })
        assert r.status_code == 403

    def test_contar_recursos_non_admin_403(self, client):
        token = _register_and_get_token(client, "na_count@example.com", "NA Count")
        r = client.get("/api/admin/users/1/recursos", headers=_auth_header(token))
        assert r.status_code == 403


# ============================================================
# UPGRADE DE PLANO (self-service admin vs usuário comum)
# ============================================================

class TestUpgradePlano:
    def test_admin_upgrade_ilimitado_direto(self, client):
        """Admin muda o próprio plano para ilimitado SEM pagamento (via /api/auth/upgrade)."""
        token = _get_admin_token(client)
        r = client.post("/api/auth/upgrade", headers=_auth_header(token), json={"plano": "ilimitado"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["plano"] == "ilimitado"
        assert data["expira"] == "vitalicio"

    def test_admin_upgrade_premium_vitalicio(self, client):
        """Admin ativa premium vitalício (sem expiração)."""
        token = _get_admin_token(client)
        r = client.post("/api/auth/upgrade", headers=_auth_header(token), json={"plano": "premium", "vitalicio": True})
        assert r.status_code == 200
        assert r.json()["expira"] == "vitalicio"

    def test_usuario_comum_upgrade_bloqueado_403(self, client):
        """Usuário comum não pode ativar premium/ilimitado direto (deve usar créditos)."""
        token = _register_and_get_token(client, "up_comum@example.com", "Comum Up")
        r = client.post("/api/auth/upgrade", headers=_auth_header(token), json={"plano": "ilimitado"})
        assert r.status_code == 403

    def test_downgrade_free_sempre_permitido(self, client):
        """Downgrade para free é sempre permitido (mesmo usuário comum)."""
        token = _register_and_get_token(client, "up_down@example.com", "Down Up")
        r = client.post("/api/auth/upgrade", headers=_auth_header(token), json={"plano": "free"})
        assert r.status_code == 200
        assert r.json()["plano"] == "free"


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
