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
    # id=1: admin com plano ilimitado (tem IA por plano)
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (1,'Admin','a@t.com','admin',?, 'admin')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin', plano='ilimitado', plano_expira='' WHERE id=1")
    # id=80: usuário comum plano FREE (sem IA por padrão)
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (80,'Comum','c@t.com','comum',?, 'user')",
        (now,),
    )
    conn.execute("UPDATE users SET role='user', plano='free', plano_expira='' WHERE id=80")
    # id=81: usuário comum plano PREMIUM (tem IA por padrão) — mesma role de 80
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (81,'Premium','p@t.com','premiumuser',?, 'user')",
        (now,),
    )
    conn.execute("UPDATE users SET role='user', plano='premium', plano_expira='' WHERE id=81")
    # Reset flags e recortes por-plano entre testes
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


def test_kill_switch_global_bloqueia_todos_os_planos():
    """Kill switch global (ativo:false sem planos) bloqueia IA para TODOS,
    inclusive plano premium/ilimitado."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})
    # Premium (id=81) normalmente teria IA, mas o kill switch bloqueia.
    app.dependency_overrides[get_user_id] = _override_user_id(81)
    r = client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"})
    assert r.status_code == 503


def test_ai_por_plano_free_sem_premium_com():
    """Sem qualquer override do admin: plano FREE não tem IA (503); plano
    PREMIUM tem (não 503) — mesma role 'user', acesso diferente pelo plano."""
    # Free (id=80): bloqueado por plano.
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    assert client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"}).status_code == 503
    # Premium (id=81): liberado por plano (pode falhar adiante, mas não 503).
    app.dependency_overrides[get_user_id] = _override_user_id(81)
    assert client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"}).status_code != 503


def test_config_flags_publico_reflete_ai_tutor_por_plano():
    """/api/config/flags reflete o acesso à IA conforme o PLANO do solicitante.

    Free vê ai_tutor=False; premium/ilimitado veem True — contrato que o widget
    consome para decidir a UI por plano.
    """
    app.dependency_overrides[get_user_id] = _override_user_id(1)

    # Free: sem IA
    app.dependency_overrides[get_optional_user_id] = _override_user_id(80)
    assert client.get("/api/config/flags").json()["ai_tutor"] is False
    # Premium: com IA
    app.dependency_overrides[get_optional_user_id] = _override_user_id(81)
    assert client.get("/api/config/flags").json()["ai_tutor"] is True
    # Ilimitado (admin id=1): com IA
    app.dependency_overrides[get_optional_user_id] = _override_user_id(1)
    assert client.get("/api/config/flags").json()["ai_tutor"] is True

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
# ACESSO POR PLANO (unitário)
# ============================================================

def test_is_feature_enabled_for_plan_defaults():
    """is_feature_enabled_for_plan: free sem IA; premium/ilimitado com IA."""
    from plans import get_all_flags_for_plan, is_feature_enabled_for_plan

    # Defaults por plano (sem override do admin)
    assert is_feature_enabled_for_plan("ai_tutor", "free") is False
    assert is_feature_enabled_for_plan("ai_tutor", "guest") is False
    assert is_feature_enabled_for_plan("ai_tutor", None) is False  # trata como guest
    assert is_feature_enabled_for_plan("ai_tutor", "premium") is True
    assert is_feature_enabled_for_plan("ai_tutor", "ilimitado") is True

    # get_all_flags_for_plan reflete o plano
    assert get_all_flags_for_plan("free")["ai_tutor"] is False
    assert get_all_flags_for_plan("premium")["ai_tutor"] is True

    # Flag não por-plano (batalhas) segue o estado global (ligada por default)
    assert is_feature_enabled_for_plan("batalhas", "free") is True


def test_kill_switch_global_afeta_is_feature_enabled_for_plan():
    """Kill switch global desliga a IA até para premium."""
    import sqlite3 as _sq

    from plans import _FLAG_PREFIX, is_feature_enabled_for_plan, set_app_config
    conn = _sq.connect(_tmp_db.name, timeout=10)
    set_app_config(conn, _FLAG_PREFIX + "ai_tutor", "0")
    conn.close()
    assert is_feature_enabled_for_plan("ai_tutor", "premium") is False
    assert is_feature_enabled_for_plan("ai_tutor", "ilimitado") is False


# ============================================================
# RECORTE POR-PLANO (ligar/desligar por plano específico)
# ============================================================

def test_desligar_ai_tutor_apenas_para_premium():
    """Admin desliga o Tutor IA só para 'premium'; ilimitado mantém acesso."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "planos": ["premium"]})
    assert r.status_code == 200
    d = r.json()
    assert d["planos_off"] == ["premium"]
    assert d["estado_por_plano"]["premium"] is False
    assert d["estado_por_plano"]["ilimitado"] is True
    assert d["estado_por_plano"]["free"] is False  # free já era False por default

    # Público reflete por plano
    app.dependency_overrides[get_optional_user_id] = _override_user_id(81)  # premium
    assert client.get("/api/config/flags").json()["ai_tutor"] is False
    app.dependency_overrides[get_optional_user_id] = _override_user_id(1)   # ilimitado
    assert client.get("/api/config/flags").json()["ai_tutor"] is True
    app.dependency_overrides.pop(get_optional_user_id, None)

    # Enforcement: premium recebe 503; ilimitado não.
    app.dependency_overrides[get_user_id] = _override_user_id(81)
    assert client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"}).status_code == 503
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    assert client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"}).status_code != 503


def test_habilitar_ai_tutor_para_free():
    """Admin pode LIGAR a IA para o plano free (que por padrão não tem)."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # free por default não tem IA
    app.dependency_overrides[get_optional_user_id] = _override_user_id(80)
    assert client.get("/api/config/flags").json()["ai_tutor"] is False
    app.dependency_overrides.pop(get_optional_user_id, None)

    # Liga para free
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": True, "planos": ["free"]})
    assert r.status_code == 200
    assert r.json()["estado_por_plano"]["free"] is True

    # Agora free tem IA (enforcement não 503)
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    assert client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"}).status_code != 503


def test_planos_invalidos_ou_nao_lista_400():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Lista só com plano inválido → 400
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "planos": ["ouro"]})
    assert r.status_code == 400
    # planos não-lista → 400
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "planos": "free"})
    assert r.status_code == 400


def test_planos_em_flag_nao_por_plano_400():
    """Recorte por plano só é válido em flags por_plano (ai_tutor). Batalhas não."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/batalhas", json={"ativo": False, "planos": ["free"]})
    assert r.status_code == 400


def test_acao_global_limpa_recorte_por_plano():
    """Ação global (sem 'planos') zera qualquer recorte por-plano anterior."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False, "planos": ["premium"]})
    # Global ON limpa planos_off
    r = client.put("/api/admin/flags/ai_tutor", json={"ativo": True})
    assert r.json()["planos_off"] == []
    # Premium volta ao default (True)
    r = client.get("/api/admin/flags")
    f = next(x for x in r.json()["flags"] if x["chave"] == "ai_tutor")
    assert f["estado_por_plano"]["premium"] is True


def test_listar_flags_inclui_estado_por_plano():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/flags")
    assert r.status_code == 200
    body = r.json()
    assert "planos" in body and "free" in body["planos"] and "premium" in body["planos"]
    f = next(x for x in body["flags"] if x["chave"] == "ai_tutor")
    assert f["por_plano"] is True
    assert "planos_off" in f and "estado_por_plano" in f
    # Flag não por-plano não expõe estado_por_plano preenchido
    fb = next(x for x in body["flags"] if x["chave"] == "batalhas")
    assert fb["por_plano"] is False
