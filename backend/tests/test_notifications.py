"""
Testes do endpoint de triggers de notificação (routers/notifications.py).
Foco: o trigger de 'plano_expirando' está integrado ao check-triggers.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_notif.db", delete=False)
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


class TestCheckTriggers:
    def test_check_triggers_inclui_plano_expirando(self, client):
        """check-triggers retorna a chave plano_expirando no resultado."""
        r = client.post("/api/push/check-triggers")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "plano_expirando" in data["notifications_sent"]

    def test_check_triggers_sem_subscriptions(self, client):
        """Sem push subscriptions, não envia nada mas responde ok."""
        r = client.post("/api/push/check-triggers")
        assert r.status_code == 200
        assert r.json()["notifications_sent"]["plano_expirando"] == 0


class TestRunTriggerChecks:
    """A lógica pura (run_trigger_checks) é compartilhada pelo endpoint e pelo
    scheduler de background."""

    def test_run_trigger_checks_roda_sem_erro(self):
        """run_trigger_checks executa com conexão própria e retorna estrutura ok."""
        from routers.notifications import run_trigger_checks

        conn = sqlite3.connect(_tmp_db.name, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            result = run_trigger_checks(conn)
        finally:
            conn.close()
        assert result["ok"] is True
        assert isinstance(result["notifications_sent"], dict)


class TestTriggerCadernoErros:
    """Trigger nº 14: questões erradas pendentes de revisão, com filtro de ciclo
    ativo (regra nº 2)."""

    def _conn(self):
        conn = sqlite3.connect(_tmp_db.name, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def test_contar_erros_pendentes_respeita_ciclo_ativo(self, client):
        """O helper conta apenas erros de matérias do ciclo ativo."""
        from routers.notifications import _contar_erros_pendentes_ciclo

        from utils import today_str

        def _cria(materia):
            r = client.post("/api/questoes", json={
                "materia": materia, "topico": "T", "enunciado": "E?",
                "alternativa_a": "A", "alternativa_b": "B", "alternativa_c": "C",
                "alternativa_d": "D", "alternativa_e": "", "resposta_correta": "A",
                "explicacao": "x", "dificuldade": "Médio",
            })
            assert r.status_code == 200
            return r.json()["id"]

        # Cria via HTTP primeiro (sem conexão direta aberta → evita db lock).
        q_ativa = _cria("Informática")
        q_inativa = _cria("Direito Constitucional")

        conn = self._conn()
        try:
            conn.execute("DELETE FROM erros_revisao WHERE 1=1")
            conn.execute("DELETE FROM ciclo_estudos WHERE 1=1")
            conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Informática', 1, 1)")
            conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Direito Constitucional', 0, 1)")
            for qid in (q_ativa, q_inativa):
                conn.execute(
                    "INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, "
                    "proxima_revisao, revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review) "
                    "VALUES (1, ?, 0, 1, ?, 0, ?, 0, 0, 0, 0, NULL)",
                    (qid, today_str(), today_str()),
                )
            conn.commit()
            n = _contar_erros_pendentes_ciclo(conn, 1, today_str())
        finally:
            conn.close()
        assert n == 1, "deve contar apenas a questão do ciclo ativo (não a inativa)"

    def test_trigger_caderno_erros_dispara_e_loga(self, client, monkeypatch):
        """Com erros pendentes suficientes (>=3) no ciclo ativo, no horário certo,
        o trigger 14 dispara: chama push e registra no notification_log."""
        import routers.notifications as notif

        from utils import today_str

        def _cria(materia):
            r = client.post("/api/questoes", json={
                "materia": materia, "topico": "T", "enunciado": "E?",
                "alternativa_a": "A", "alternativa_b": "B", "alternativa_c": "C",
                "alternativa_d": "D", "alternativa_e": "", "resposta_correta": "A",
                "explicacao": "x", "dificuldade": "Médio",
            })
            assert r.status_code == 200
            return r.json()["id"]

        # Cria as 3 questões via HTTP ANTES de abrir conexão direta (evita lock).
        qids = [_cria("Informática") for _ in range(3)]

        # Agora escreve o setup numa conexão direta e FECHA antes de rodar o trigger.
        conn = self._conn()
        for t in ("erros_revisao", "ciclo_estudos", "push_subscriptions", "notification_log", "notification_preferences"):
            try:
                conn.execute(f"DELETE FROM {t} WHERE 1=1")
            except Exception:
                pass
        conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Informática', 1, 1)")
        conn.execute(
            "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) "
            "VALUES (1, 'https://example/fake', 'p', 'a', ?)",
            (today_str(),),
        )
        for qid in qids:
            conn.execute(
                "INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, "
                "proxima_revisao, revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review) "
                "VALUES (1, ?, 0, 1, ?, 0, ?, 0, 0, 0, 0, NULL)",
                (qid, today_str(), today_str()),
            )
        conn.commit()
        conn.close()

        # Mock: push "enviado" com sucesso (sem rede) e hora fixada às 18h.
        monkeypatch.setattr(notif, "_send_push_to_user", lambda *a, **k: 1)

        class _FakeDateTime(notif.datetime):
            @classmethod
            def now(cls, tz=None):
                return notif.datetime.fromisoformat(f"{today_str()}T18:30:00")
        monkeypatch.setattr(notif, "datetime", _FakeDateTime)
        monkeypatch.setattr(notif, "_is_quiet_hours", lambda conn, uid: False)

        conn = self._conn()
        try:
            result = notif.run_trigger_checks(conn)
        finally:
            conn.close()

        assert result["ok"] is True
        assert result["notifications_sent"].get("caderno_erros", 0) == 1, \
            "trigger do caderno de erros deve disparar 1x"

        conn = self._conn()
        logged = conn.execute(
            "SELECT COUNT(*) FROM notification_log WHERE user_id = 1 AND tag = 'caderno_erros'"
        ).fetchone()[0]
        conn.close()
        assert logged == 1, "trigger deve registrar no notification_log"

    def test_auto_check_erros_respeita_ciclo_ativo(self, client):
        """O alerta inline de erros (auto-check) conta apenas matérias do ciclo
        ativo — consistente com o badge do sidebar e o push."""
        from utils import today_str

        def _cria(materia):
            r = client.post("/api/questoes", json={
                "materia": materia, "topico": "T", "enunciado": "E?",
                "alternativa_a": "A", "alternativa_b": "B", "alternativa_c": "C",
                "alternativa_d": "D", "alternativa_e": "", "resposta_correta": "A",
                "explicacao": "x", "dificuldade": "Médio",
            })
            assert r.status_code == 200
            return r.json()["id"]

        # 4 erros de matéria ATIVA (> 3 dispara) + 4 de matéria INATIVA (ignorados)
        ativas = [_cria("Informática") for _ in range(4)]
        inativas = [_cria("Direito Constitucional") for _ in range(4)]

        conn = self._conn()
        try:
            conn.execute("DELETE FROM erros_revisao WHERE 1=1")
            conn.execute("DELETE FROM ciclo_estudos WHERE 1=1")
            conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Informática', 1, 1)")
            conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Direito Constitucional', 0, 1)")
            for qid in ativas + inativas:
                conn.execute(
                    "INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, "
                    "proxima_revisao, revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review) "
                    "VALUES (1, ?, 0, 1, ?, 0, ?, 0, 0, 0, 0, NULL)",
                    (qid, today_str(), today_str()),
                )
            conn.commit()
        finally:
            conn.close()

        data = client.get("/api/push/auto-check").json()
        erros_alertas = [a for a in data["alertas"] if a["tipo"] == "erros"]
        # Deve haver alerta (4 ativas > 3) e a contagem deve ser 4 (não 8)
        assert len(erros_alertas) == 1, "deve haver alerta de erros"
        assert "4 " in erros_alertas[0]["msg"], f"deve contar só as 4 do ciclo ativo: {erros_alertas[0]['msg']}"


class TestPushScheduler:
    """Scheduler de background (push_scheduler.py)."""

    def test_scheduler_agenda_e_para_sem_travar(self):
        import push_scheduler as ps

        # Agenda com o DB de teste e verifica timer daemon; depois cancela.
        ps.schedule_trigger_checks(_tmp_db.name)
        assert ps._scheduler_timer is not None
        assert ps._scheduler_timer.daemon is True
        ps.stop_scheduler()
        assert ps._scheduler_timer is None

    def test_scheduler_respeita_flag_desabilitado(self, monkeypatch):
        import push_scheduler as ps
        from settings import settings

        ps.stop_scheduler()
        monkeypatch.setattr(settings, "PUSH_SCHEDULER_ENABLED", False)
        ps.schedule_trigger_checks(_tmp_db.name)
        assert ps._scheduler_timer is None, "não deve agendar quando desabilitado"

    def test_run_once_nao_levanta_excecao(self):
        import push_scheduler as ps

        # Mesmo com caminho de DB inexistente, run_once não pode levantar.
        result = ps.run_once("/tmp/definitely_missing_db_xyz.db")
        assert isinstance(result, dict)


def teardown_module():
    try:
        import push_scheduler as ps
        ps.stop_scheduler()
    except Exception:
        pass
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
