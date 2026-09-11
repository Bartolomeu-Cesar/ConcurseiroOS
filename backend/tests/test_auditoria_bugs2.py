"""Testes de regressão dos bugs latentes da 2ª RODADA de auditoria de cobertura.

Bugs (todos silenciosos — sem erro visível mas com lógica quebrada/morta):
1. studyroom.gamification: Boss Fight consultava colunas inexistentes
   (alternativas/resposta) → sempre 404/500. Corrigido p/ alternativa_a..e +
   resposta_correta.
2. studyroom.discussion: idem ao iniciar discussão a partir de questão da base.
3. studyroom.metacognition: .get() em sqlite3.Row → session-summary 500.
4. ai_tutor._get_user_plan: SELECT plan (coluna é plano) → 'ilimitado' virava
   'free' e o usuário ficava limitado indevidamente.
5. leagues.helpers: status='concluido' (é 'Concluído') → XP de tópicos na liga
   nunca creditado.
6. leagues.endpoints: guard de idempotência por semana pulava ligas extras.
7. analytics.core plano_automatico: parse de data de prova frágil → 500.
8. analytics.advanced raio_x_edital: código morto if False.

Executar: pytest tests/test_auditoria_bugs2.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_auditoria2.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app

_UID = 1


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
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


def _conn():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _criar_questao(client, materia="Informática"):
    r = client.post("/api/questoes", json={
        "materia": materia, "topico": "T", "enunciado": "Qual a resposta?",
        "alternativa_a": "Op A", "alternativa_b": "Op B", "alternativa_c": "Op C",
        "alternativa_d": "Op D", "alternativa_e": "", "resposta_correta": "A",
        "explicacao": "x", "dificuldade": "Médio",
    })
    assert r.status_code == 200
    return r.json()["id"]


def _criar_sala(codigo="SALA01"):
    from utils import today_str

    from routers.studyroom.tables import (
        ensure_challenge_tables,
        ensure_discussion_tables,
        ensure_studyroom_tables,
    )
    conn = _conn()
    ensure_studyroom_tables(conn)
    ensure_challenge_tables(conn)
    ensure_discussion_tables(conn)
    conn.execute("DELETE FROM study_rooms WHERE codigo = ?", (codigo,))
    cur = conn.execute(
        "INSERT INTO study_rooms (codigo, criador_id, titulo, created_at) VALUES (?, ?, 'T', ?)",
        (codigo, _UID, today_str()),
    )
    rid = cur.lastrowid
    conn.execute(
        "INSERT INTO study_room_participants (room_id, user_id, nome, meta, joined_at) VALUES (?, ?, 'Eu', 'Estudar 2h', ?)",
        (rid, _UID, today_str()),
    )
    conn.commit()
    conn.close()
    return codigo, rid


# ============================================================
# BUG 1 — Boss Fight (gamification)
# ============================================================

class TestBossFight:
    def test_start_e_answer_boss_fight(self, client):
        """Boss Fight deve achar questões (antes 404 por coluna inexistente) e
        responder sem 500 (antes SELECT resposta quebrava)."""
        _criar_questao(client, "Informática")
        _criar_questao(client, "Informática")
        codigo, _ = _criar_sala("BOSS01")

        r = client.post(f"/api/studyroom/challenge/{codigo}/start",
                        json={"materia": "Informática", "quantidade": 2, "tempo_limite_min": 15})
        assert r.status_code == 200, f"Boss Fight não iniciou: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "challenge_id" in data
        # As questões devem ter alternativas montadas
        conn = _conn()
        import json as _json
        ch = conn.execute("SELECT questoes_json FROM study_room_challenges WHERE id = ?", (data["challenge_id"],)).fetchone()
        conn.close()
        qs = _json.loads(ch["questoes_json"])
        assert qs and qs[0]["alternativas"], "alternativas devem ser montadas"
        qid = qs[0]["id"]

        # Responder (antes: SELECT resposta → 500)
        r2 = client.post(f"/api/studyroom/challenge/{codigo}/answer",
                         json={"challenge_id": data["challenge_id"], "questao_id": qid, "resposta": "A"})
        assert r2.status_code == 200, f"answer quebrou: {r2.status_code} {r2.text[:200]}"
        assert r2.json()["acertou"] is True


# ============================================================
# BUG 2 — Discussão a partir de questão da base
# ============================================================

class TestDiscussion:
    def test_start_discussion_da_base(self, client):
        qid = _criar_questao(client, "Direito")
        codigo, _ = _criar_sala("DISC01")
        r = client.post(f"/api/studyroom/discussion/{codigo}/start", json={"questao_id": qid})
        assert r.status_code == 200, f"discussão da base quebrou: {r.status_code} {r.text[:200]}"


# ============================================================
# BUG 3 — session-summary (.get() em sqlite3.Row)
# ============================================================

class TestSessionSummary:
    def test_session_summary_nao_quebra(self, client):
        codigo, _ = _criar_sala("SUMM01")
        r = client.get(f"/api/studyroom/session-summary/{codigo}")
        assert r.status_code == 200, f"session-summary 500 (.get em Row): {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "ciclos_total" in str(data) or isinstance(data, dict)


# ============================================================
# BUG 4 — ai_tutor plano ilimitado
# ============================================================

class TestAiTutorPlano:
    def test_plano_ilimitado_nao_e_free(self, client):
        """_get_user_plan deve retornar 'ilimitado' quando users.plano='ilimitado'
        (antes lia coluna 'plan' inexistente → sempre 'free')."""
        from routers.ai_tutor import _get_user_plan

        conn = _conn()
        conn.execute("INSERT OR IGNORE INTO users (id, email, plano, created_at) VALUES (?, 'ilim@test.com', 'ilimitado', '2026-01-01')", (777,))
        conn.execute("UPDATE users SET plano='ilimitado' WHERE id=?", (777,))
        conn.commit()
        # confirma o setup
        chk = conn.execute("SELECT plano FROM users WHERE id=?", (777,)).fetchone()
        assert chk and chk[0] == "ilimitado", "pré-condição: user 777 com plano ilimitado"
        plano = _get_user_plan(conn, 777)
        conn.close()
        assert plano == "ilimitado", f"esperado 'ilimitado', veio '{plano}'"


# ============================================================
# BUG 5 — liga XP de tópicos concluídos
# ============================================================

class TestLigaXpTopicos:
    def test_topico_concluido_credita_xp(self, client):
        """calculate_user_weekly_xp deve creditar XP por tópico 'Concluído' na
        semana (antes usava 'concluido' minúsculo → nunca creditava)."""
        from datetime import date, timedelta

        from routers.leagues.helpers import calculate_user_weekly_xp

        conn = _conn()
        conn.execute("DELETE FROM edital WHERE user_id=?", (888,))
        hoje = date.today().isoformat()
        # tópico Concluído com mastery_updated_at nesta semana
        conn.execute(
            "INSERT INTO edital (edital_nome, cargo, materia, topico, status, mastery_updated_at, arquivado, user_id) "
            "VALUES ('G','','Info','T1','Concluído', ?, 0, ?)",
            (hoje, 888),
        )
        conn.commit()
        week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
        week_end = (date.today() + timedelta(days=1)).isoformat()
        resultado = calculate_user_weekly_xp(conn, 888, week_start, week_end)
        conn.close()
        # retorno: {"total": int, "breakdown": {...}}
        assert isinstance(resultado, dict)
        assert resultado["breakdown"].get("topicos", 0) >= 25, \
            f"XP de tópico concluído não creditado: {resultado['breakdown']}"


# ============================================================
# BUG 7 — parse de data de prova robusto (plano_automatico)
# ============================================================

class TestPlanoAutomaticoData:
    def test_data_malformada_nao_quebra(self, client):
        """plano-automatico não deve dar 500 com data de prova malformada."""
        conn = _conn()
        # edital_info com data malformada
        try:
            conn.execute("DELETE FROM edital_info WHERE user_id=?", (_UID,))
            conn.execute(
                "INSERT INTO edital_info (edital_nome, cargo, data_prova_objetiva, user_id) "
                "VALUES ('G', '', 'data-invalida-xyz', ?)",
                (_UID,),
            )
            conn.commit()
        except Exception:
            pass
        conn.close()
        r = client.get("/api/plano-automatico")
        # não pode ser 500
        assert r.status_code != 500, f"plano-automatico quebrou com data malformada: {r.text[:200]}"

    def test_data_valida_ddmmyyyy(self, client):
        from datetime import date

        conn = _conn()
        futura = date(date.today().year + 1, 12, 20).strftime("%d/%m/%Y")
        conn.execute("DELETE FROM edital_info WHERE user_id=?", (_UID,))
        conn.execute(
            "INSERT INTO edital_info (edital_nome, cargo, data_prova_objetiva, user_id) VALUES ('G','',?,?)",
            (futura, _UID),
        )
        conn.commit()
        conn.close()
        r = client.get("/api/plano-automatico")
        assert r.status_code == 200


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
