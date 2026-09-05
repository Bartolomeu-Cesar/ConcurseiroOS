"""
Testes da detecção de fadiga intra-sessão (/api/sessao/*).

Foco na correção do falso positivo: acertar 80% num ritmo rápido (8 questões
em ~3 min) NÃO deve disparar "fadiga_alta". Fadiga por tempo agora exige
amostra/duração suficientes e usa mediana (robusta a outliers). fadiga_alta
exige queda de acerto (isolada forte OU combinada com tempo).

Executar: pytest tests/test_fatigue.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_fatigue.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import settings as settings_mod
from database import get_db_session

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
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


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


def _iniciar():
    r = client.post("/api/sessao/iniciar", json={"materia": "Teste", "tipo": "questoes"})
    assert r.status_code == 200
    return r.json()["session_id"]


def _enviar(session_id, questoes):
    """questoes: lista de (tempo_ms, acertou). Retorna a última resposta."""
    last = None
    for i, (tempo_ms, acertou) in enumerate(questoes, start=1):
        r = client.post("/api/sessao/heartbeat", json={
            "session_id": session_id,
            "questao_num": i,
            "tempo_ms": tempo_ms,
            "acertou": acertou,
        })
        assert r.status_code == 200, r.text
        last = r.json()
    return last


class TestFadigaFalsoPositivo:
    """Regressão: o cenário reportado não deve mais disparar fadiga_alta."""

    def test_80pct_ritmo_rapido_nao_e_fadiga_alta(self):
        """8 questões, 80% de acerto, ~3 min: NÃO é fadiga_alta.

        Reproduz exatamente a sessão real reportada:
        tempos crescentes no fim (27s, 47s) faziam a MÉDIA disparar fadiga por
        tempo. Com mediana + exigência de >=12 questões/>=10min, isso some.
        """
        sid = _iniciar()
        questoes = [
            (11000, True), (13000, True), (20000, True), (14000, True),
            (17000, True), (11000, True), (27000, False), (47000, True),
        ]
        res = _enviar(sid, questoes)
        assert res["status"] != "fadiga_alta", (
            f"80% de acerto em ritmo rápido não deve ser fadiga_alta, veio: {res['status']}"
        )

    def test_tempo_isolado_nao_gera_alta(self):
        """Aumento de tempo sem queda de acerto → no máximo fadiga_leve."""
        sid = _iniciar()
        # 12 questões, todas certas, tempos crescentes mas curtos (< piso de 45s)
        questoes = [(10000 + i * 2000, True) for i in range(12)]
        res = _enviar(sid, questoes)
        assert res["status"] in ("flow", "fadiga_leve"), res["status"]


class TestFadigaVerdadeira:
    """Casos que DEVEM disparar fadiga."""

    def test_queda_acerto_forte_e_fadiga_alta(self):
        """Queda de acerto forte (isolada) → fadiga_alta."""
        sid = _iniciar()
        # 10 questões: início 100%, fim 0% → queda enorme
        questoes = [
            (15000, True), (15000, True), (15000, True), (15000, True),
            (15000, True),
            (15000, False), (15000, False), (15000, False), (15000, False),
            (15000, False),
        ]
        res = _enviar(sid, questoes)
        assert res["status"] == "fadiga_alta", res["status"]

    def test_flow_quando_estavel(self):
        """Desempenho estável (acerto e tempo constantes) → flow."""
        sid = _iniciar()
        questoes = [(15000, True) for _ in range(10)]
        res = _enviar(sid, questoes)
        assert res["status"] == "flow", res["status"]


class TestFadigaMetricas:
    def test_heartbeat_retorna_metricas(self):
        sid = _iniciar()
        res = _enviar(sid, [(15000, True)] * 8)
        assert "metricas" in res
        m = res["metricas"]
        assert m["questoes_respondidas"] == 8
        assert "pct_acerto_inicio" in m and "pct_acerto_recente" in m
