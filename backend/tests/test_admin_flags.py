"""
Testes de feature flags / kill switch (/api/admin/flags + enforcement).

Executar: pytest tests/test_admin_flags.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_flags.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient

from deps import get_user_id, get_optional_user_id
from main import app


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)


def _override_user_id(uid):
    async def override():
        return uid
    return override


def _seed():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (1,'Admin','a@t.com','admin',?, 'admin')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (80,'Comum','c@t.com','comum',?, 'user')",
        (now,),
    )
    # Reset flags entre testes
    conn.execute("DELETE FROM app_config WHERE chave LIKE 'flag.%'")
    conn.execute("DELETE FROM app_config WHERE chave = 'auth_code_expire_minutes'")
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)
    app.dependency_overrides.pop(get_optional_user_id, None)


def test_nao_admin_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    assert client.get("/api/admin/flags").status_code == 403
    assert client.put("/api/admin/flags/ai_tutor", json={"ativo": False}).status_code == 403


def test_listar_flags_defaults():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/flags")
    assert r.status_code == 200
    flags = {f["chave"]: f["ativo"] for f in r.json()["flags"]}
    assert flags["ai_tutor"] is True
    assert flags["manutencao"] is False


def test_toggle_persiste():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/batalhas", json={"ativo": False})
    assert r.status_code == 200
    r = client.get("/api/admin/flags")
    flags = {f["chave"]: f["ativo"] for f in r.json()["flags"]}
    assert flags["batalhas"] is False
    # Público reflete
    r = client.get("/api/config/flags")
    assert r.json()["batalhas"] is False


def test_flag_desconhecida_404():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/inexistente", json={"ativo": True})
    assert r.status_code == 404


def test_flag_auditada():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})
    r = client.get("/api/admin/auditoria?acao=flag")
    items = r.json()["items"]
    assert any(it["acao"] == "flag.set" for it in items)


def test_kill_switch_ai_tutor():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Admin desliga a IA
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})
    # Para um usuário COMUM, analisar-pdf deve responder 503 (kill switch).
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    r = client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"})
    assert r.status_code == 503


def test_ai_tutor_admin_isento_do_kill_switch():
    """Com a flag desligada, o ADMIN não é bloqueado pela flag (isenção por role).

    O admin pode falhar adiante por outros motivos (PDF inexistente/budget), mas
    NUNCA deve receber 503 causado pela feature flag.
    """
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})
    r = client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"})
    assert r.status_code != 503, "admin deveria ser isento do kill switch da flag"


def test_config_flags_publico_reflete_ai_tutor_off():
    """O endpoint público /api/config/flags reflete o estado por ROLE do solicitante.

    Com ai_tutor desligada: usuário comum vê False; admin vê True (isenção por
    role) — contrato que o widget do frontend consome para decidir a UI por role.
    """
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Ligada por padrão (todos veem True)
    r = client.get("/api/config/flags")
    assert r.status_code == 200
    assert r.json()["ai_tutor"] is True

    # Admin desliga a flag globalmente
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})

    # Usuário comum: vê ai_tutor=False
    app.dependency_overrides[get_optional_user_id] = _override_user_id(80)
    r = client.get("/api/config/flags")
    assert r.status_code == 200
    assert r.json()["ai_tutor"] is False

    # Admin: vê ai_tutor=True (isento), mesmo com a flag globalmente desligada
    app.dependency_overrides[get_optional_user_id] = _override_user_id(1)
    r = client.get("/api/config/flags")
    assert r.status_code == 200
    assert r.json()["ai_tutor"] is True

    app.dependency_overrides.pop(get_optional_user_id, None)


# ============================================================
# VALIDADE DO CÓDIGO DE LOGIN (config admin)
# ============================================================

def test_auth_code_expire_get_nao_admin_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    assert client.get("/api/admin/config/auth-code-expire").status_code == 403
    assert client.put("/api/admin/config/auth-code-expire", json={"minutes": 30}).status_code == 403


def test_auth_code_expire_get_default():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/config/auth-code-expire")
    assert r.status_code == 200
    d = r.json()
    assert d["min"] == 1 and d["max"] == 1440
    assert 1 <= d["minutes"] <= 1440


def test_auth_code_expire_set_persiste():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/config/auth-code-expire", json={"minutes": 120})
    assert r.status_code == 200
    assert r.json()["minutes"] == 120
    # Persiste e é lido de volta
    r = client.get("/api/admin/config/auth-code-expire")
    assert r.json()["minutes"] == 120


def test_auth_code_expire_rejeita_fora_do_limite():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    assert client.put("/api/admin/config/auth-code-expire", json={"minutes": 0}).status_code == 400
    assert client.put("/api/admin/config/auth-code-expire", json={"minutes": 1441}).status_code == 400
    assert client.put("/api/admin/config/auth-code-expire", json={"minutes": "abc"}).status_code == 400


def test_auth_code_expire_helper_aplica_teto_24h():
    """Mesmo com valor absurdo persistido, o helper limita a 1440 min (24h)."""
    from plans import set_app_config, get_auth_code_expire_minutes, AUTH_CODE_EXPIRE_KEY
    import sqlite3 as _sq
    conn = _sq.connect(_tmp_db.name, timeout=10)
    set_app_config(conn, AUTH_CODE_EXPIRE_KEY, "999999")
    conn.close()
    assert get_auth_code_expire_minutes() == 1440


def test_auth_code_expire_auditado():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.put("/api/admin/config/auth-code-expire", json={"minutes": 45})
    r = client.get("/api/admin/auditoria?acao=config")
    items = r.json()["items"]
    assert any(it["acao"] == "config.set" for it in items)


# ============================================================
# ISENÇÃO POR ROLE (unitário)
# ============================================================

def test_is_feature_enabled_for_isencao_admin():
    """is_feature_enabled_for: admin isento em ai_tutor; comum segue a flag."""
    from plans import (
        set_app_config, is_feature_enabled_for, get_all_flags_for, _FLAG_PREFIX,
    )
    import sqlite3 as _sq
    # Desliga ai_tutor globalmente
    conn = _sq.connect(_tmp_db.name, timeout=10)
    set_app_config(conn, _FLAG_PREFIX + "ai_tutor", "0")
    conn.close()

    # Comum: bloqueado; admin: isento (True)
    assert is_feature_enabled_for("ai_tutor", "user") is False
    assert is_feature_enabled_for("ai_tutor", None) is False
    assert is_feature_enabled_for("ai_tutor", "admin") is True

    # get_all_flags_for reflete o role
    assert get_all_flags_for("admin")["ai_tutor"] is True
    assert get_all_flags_for("user")["ai_tutor"] is False

    # Flag sem roles_isentos (batalhas): admin NÃO é isento
    conn = _sq.connect(_tmp_db.name, timeout=10)
    set_app_config(conn, _FLAG_PREFIX + "batalhas", "0")
    conn.close()
    assert is_feature_enabled_for("batalhas", "admin") is False


# ============================================================
# RECORTE POR-ROLE (ligar/desligar por role específico)
# ============================================================

def test_desligar_ai_tutor_apenas_para_user():
    """Admin desliga o Tutor IA só para 'user'; admin permanece com acesso."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "roles": ["user"]})
    assert r.status_code == 200
    d = r.json()
    assert d["roles_off"] == ["user"]
    assert d["estado_por_role"]["user"] is False
    assert d["estado_por_role"]["admin"] is True

    # Público reflete por role
    app.dependency_overrides[get_optional_user_id] = _override_user_id(80)  # user
    assert client.get("/api/config/flags").json()["ai_tutor"] is False
    app.dependency_overrides[get_optional_user_id] = _override_user_id(1)   # admin
    assert client.get("/api/config/flags").json()["ai_tutor"] is True
    app.dependency_overrides.pop(get_optional_user_id, None)

    # Enforcement: usuário comum recebe 503; admin não.
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    assert client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"}).status_code == 503
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    assert client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"}).status_code != 503


def test_desligar_para_todos_os_roles_bloqueia_ate_admin():
    """Selecionar admin+user no desligamento bloqueia inclusive o admin
    (a escolha explícita do admin prevalece sobre a isenção estática)."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "roles": ["admin", "user"]})
    assert r.status_code == 200
    d = r.json()
    assert d["estado_por_role"]["user"] is False
    assert d["estado_por_role"]["admin"] is False

    # Admin agora também é bloqueado no enforcement.
    r = client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"})
    assert r.status_code == 503


def test_reabilitar_para_role_remove_do_roles_off():
    """Reabilitar um role removido antes volta o acesso só para aquele role."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Desliga para ambos
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "roles": ["admin", "user"]})
    # Reabilita só para user
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": True, "roles": ["user"]})
    d = r.json()
    assert d["estado_por_role"]["user"] is True
    assert d["estado_por_role"]["admin"] is False
    assert "admin" in d["roles_off"] and "user" not in d["roles_off"]


def test_roles_invalidos_sao_ignorados_ou_400():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Lista só com role inválido → 400
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "roles": ["hacker"]})
    assert r.status_code == 400
    # roles não-lista → 400
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "roles": "user"})
    assert r.status_code == 400


def test_acao_global_limpa_recorte_por_role():
    """Ação global (sem 'roles') zera qualquer recorte por-role anterior."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "roles": ["user"]})
    # Global ON limpa roles_off
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": True})
    assert r.json()["roles_off"] == []
    # Ambos veem True
    r = client.get("/api/admin/flags")
    f = next(x for x in r.json()["flags"] if x["chave"] == "ai_tutor")
    assert f["estado_por_role"]["user"] is True
    assert f["estado_por_role"]["admin"] is True


def test_listar_flags_inclui_estado_por_role():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/flags")
    assert r.status_code == 200
    body = r.json()
    assert "roles" in body and "admin" in body["roles"] and "user" in body["roles"]
    f = next(x for x in body["flags"] if x["chave"] == "ai_tutor")
    assert "roles_off" in f and "estado_por_role" in f
