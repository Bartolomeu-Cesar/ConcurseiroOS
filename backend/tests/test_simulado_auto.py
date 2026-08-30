"""Testes do simulado automático (/api/simulado/auto-gerar) com filtro de matérias."""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_simauto.db", delete=False)
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
def _seed():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        for tbl in ("ciclo_estudos", "edital", "questoes", "simulados", "simulado_questoes"):
            try:
                c.execute(f"DELETE FROM {tbl}")
            except Exception:
                pass
        # Ciclo com 2 matérias
        c.execute(
            "INSERT INTO ciclo_estudos (materia, horas_alvo, ordem, ativo, user_id) VALUES ('Português', 1, 0, 1, 1)"
        )
        c.execute(
            "INSERT INTO ciclo_estudos (materia, horas_alvo, ordem, ativo, user_id) VALUES ('Informática', 1, 1, 1, 1)"
        )
        # Tópicos no edital (peso)
        for i in range(5):
            c.execute(
                "INSERT INTO edital (materia, topico, arquivado, user_id) VALUES ('Português', ?, 0, 1)", (f"P{i}",)
            )
            c.execute(
                "INSERT INTO edital (materia, topico, arquivado, user_id) VALUES ('Informática', ?, 0, 1)", (f"I{i}",)
            )
        # Questões com gabarito
        for i in range(15):
            c.execute(
                "INSERT INTO questoes (enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, resposta_correta, materia, dificuldade, created_at, user_id) VALUES (?, 'a', 'b', 'c', 'd', 'A', 'Português', 'Médio', '2026-01-01', 1)",
                (f"PQ{i}",),
            )
            c.execute(
                "INSERT INTO questoes (enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, resposta_correta, materia, dificuldade, created_at, user_id) VALUES (?, 'a', 'b', 'c', 'd', 'A', 'Informática', 'Médio', '2026-01-01', 1)",
                (f"IQ{i}",),
            )
        c.commit()
    finally:
        c.close()
    yield


def _materias_do_simulado(client, sim_id):
    """Retorna o conjunto de matérias das questões do simulado gerado."""
    detalhe = client.get(f"/api/simulados/{sim_id}").json()
    mats = set()
    for q in detalhe.get("questoes", []):
        if q.get("materia"):
            mats.add(q["materia"])
    return mats


def test_auto_gerar_multidisciplinar_por_padrao(client):
    r = client.post("/api/simulado/auto-gerar", json={"total_questoes": 10, "tempo_limite_min": 60})
    assert r.status_code == 200
    data = r.json()
    materias_distribuicao = {d["materia"] for d in data["distribuicao"]}
    # Sem filtro → deve conter as duas matérias do ciclo
    assert "Português" in materias_distribuicao
    assert "Informática" in materias_distribuicao


def test_auto_gerar_filtra_uma_materia(client):
    r = client.post(
        "/api/simulado/auto-gerar", json={"total_questoes": 8, "tempo_limite_min": 60, "materias": ["Português"]}
    )
    assert r.status_code == 200
    data = r.json()
    materias_distribuicao = {d["materia"] for d in data["distribuicao"]}
    assert materias_distribuicao == {"Português"}


def test_auto_gerar_materia_fora_do_ciclo_retorna_400(client):
    r = client.post(
        "/api/simulado/auto-gerar", json={"total_questoes": 8, "tempo_limite_min": 60, "materias": ["Direito Penal"]}
    )
    assert r.status_code == 400


def test_auto_gerar_respeita_tempo_configurado(client):
    """O tempo_limite_min enviado deve ser refletido no simulado gerado."""
    r = client.post("/api/simulado/auto-gerar", json={"total_questoes": 10, "tempo_limite_min": 90})
    assert r.status_code == 200
    assert r.json()["tempo_limite_min"] == 90


def test_auto_gerar_respeita_total_questoes_configurado(client):
    """O total_questoes configurado deve ser respeitado (ou o máximo disponível)."""
    r = client.post("/api/simulado/auto-gerar", json={"total_questoes": 6, "tempo_limite_min": 30})
    assert r.status_code == 200
    # Não pode gerar mais do que o solicitado
    assert r.json()["total_questoes"] <= 6


def test_auto_gerar_rejeita_total_questoes_invalido(client):
    """Número de questões fora do intervalo 5-200 é rejeitado."""
    r = client.post("/api/simulado/auto-gerar", json={"total_questoes": 1, "tempo_limite_min": 60})
    assert r.status_code == 400
    r = client.post("/api/simulado/auto-gerar", json={"total_questoes": 500, "tempo_limite_min": 60})
    assert r.status_code == 400


def test_auto_gerar_rejeita_tempo_invalido(client):
    """Tempo fora do intervalo 5-600 é rejeitado."""
    r = client.post("/api/simulado/auto-gerar", json={"total_questoes": 10, "tempo_limite_min": 1})
    assert r.status_code == 400
    r = client.post("/api/simulado/auto-gerar", json={"total_questoes": 10, "tempo_limite_min": 999})
    assert r.status_code == 400


def test_auto_gerar_materia_sem_gabarito_retorna_erro_especifico(client):
    """Matéria no ciclo cujas questões não têm resposta_correta → 400 com mensagem
    específica citando a matéria (reproduz o caso das questões importadas sem gabarito)."""
    # Substitui as questões de Informática por questões SEM gabarito
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM questoes WHERE materia = 'Informática'")
        for i in range(10):
            c.execute(
                "INSERT INTO questoes (enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, resposta_correta, materia, dificuldade, created_at, user_id) "
                "VALUES (?, 'Certo.', 'Errado.', '', '', '', 'Informática', 'Médio', '2026-01-01', 1)",
                (f"SEMGAB{i}",),
            )
        c.commit()
    finally:
        c.close()

    r = client.post(
        "/api/simulado/auto-gerar", json={"total_questoes": 8, "tempo_limite_min": 60, "materias": ["Informática"]}
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "Informática" in detail
    assert "gabarito" in detail.lower()
