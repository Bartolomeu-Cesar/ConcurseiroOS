"""Testes da Trilha de Estudo (routers/trilha/core.py).

Cobre:
- Geração sem tópicos → 400.
- Geração com tópicos → etapas ordenadas, primeira não-concluída = 'atual'.
- Filtro por ciclo ativo (skill rule #2): só matérias do ciclo entram.
- Ordem respeita pré-requisitos (topic_dependencies / knowledge graph).
- Tópicos já 'Concluído' viram etapa 'concluida' e contam no progresso.
- GET /api/trilha retorna a trilha ativa; regenerar desativa a anterior.

AUTH_ENABLED=false → user_id sempre 1 (single-user).
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_trilha.db", delete=False)
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
def _clean_and_override():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    conn = _conn()
    # Limpa tabelas relevantes entre testes
    for tbl in ("trilha_etapas", "trilha", "topic_dependencies", "ciclo_estudos", "edital", "calendario_personalizado", "metas_config"):
        try:
            conn.execute(f"DELETE FROM {tbl}")
        except Exception:
            pass
    conn.commit()
    conn.close()
    yield


def _conn():
    c = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _add_topico(conn, materia, topico, status="Não Iniciado", no_ciclo=True):
    cur = conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
        "VALUES ('Geral', '', ?, ?, ?, 0, 1)",
        (materia, topico, status),
    )
    # Reflete o uso real: a trilha só considera matérias do ciclo de estudos.
    # Por padrão, garante que a matéria do tópico esteja no ciclo ativo.
    if no_ciclo:
        existe = conn.execute(
            "SELECT 1 FROM ciclo_estudos WHERE materia = ? AND ativo = 1 AND user_id = 1",
            (materia,),
        ).fetchone()
        if not existe:
            _add_ciclo(conn, materia, 0)
    return cur.lastrowid


def _add_ciclo(conn, materia, ordem=0):
    conn.execute(
        "INSERT INTO ciclo_estudos (materia, horas_alvo, ordem, ativo, user_id) VALUES (?, 1.0, ?, 1, 1)",
        (materia, ordem),
    )


# ============================================================
# TESTES
# ============================================================


def test_gerar_sem_ciclo_retorna_400(client):
    # Há tópicos no edital, mas nenhum ciclo ativo → a trilha não deve ser gerada
    conn = _conn()
    _add_topico(conn, "Português", "Crase", no_ciclo=False)
    conn.commit()
    conn.close()
    r = client.post("/api/trilha/gerar")
    assert r.status_code == 400
    assert "ciclo" in r.json()["detail"].lower()


def test_gerar_ciclo_sem_topicos_retorna_400(client):
    # Ciclo tem matéria que não possui tópicos no edital
    conn = _conn()
    _add_ciclo(conn, "Português", 0)
    conn.commit()
    conn.close()
    r = client.post("/api/trilha/gerar")
    assert r.status_code == 400
    assert "tópico" in r.json()["detail"].lower()


def test_get_sem_trilha_retorna_vazio(client):
    r = client.get("/api/trilha")
    assert r.status_code == 200
    data = r.json()
    assert data["trilha"] is None
    assert data["etapas"] == []


def test_gerar_cria_etapas_ordenadas_com_atual(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Português", "Regência")
    _add_topico(conn, "Direito", "Princípios")
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    data = r.json()
    assert data["trilha"] is not None
    assert data["progresso"]["total_etapas"] == 3
    assert data["progresso"]["concluidas"] == 0

    etapas = data["etapas"]
    # Ordens sequenciais 1..3
    assert [e["ordem"] for e in etapas] == [1, 2, 3]
    # Exatamente uma etapa 'atual' (a primeira), demais 'bloqueada'
    assert etapas[0]["status"] == "atual"
    assert etapas[0]["desbloqueada"] == 1
    assert sum(1 for e in etapas if e["status"] == "atual") == 1
    assert etapas[1]["status"] == "bloqueada"
    assert etapas[2]["status"] == "bloqueada"


def test_filtra_por_ciclo_ativo(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase", no_ciclo=False)
    _add_topico(conn, "Direito", "Princípios", no_ciclo=False)
    _add_topico(conn, "Informática", "Redes", no_ciclo=False)  # fora do ciclo
    # Ciclo ativo só com Português e Direito
    _add_ciclo(conn, "Português", 0)
    _add_ciclo(conn, "Direito", 1)
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    materias = {e["materia"] for e in r.json()["etapas"]}
    assert materias == {"Português", "Direito"}
    assert "Informática" not in materias


def test_ordem_respeita_prerequisitos(client):
    conn = _conn()
    # "Avançado" depende de "Básico" → Básico deve vir antes na trilha
    id_basico = _add_topico(conn, "Direito", "Básico")
    id_avancado = _add_topico(conn, "Direito", "Avançado")
    conn.execute(
        "INSERT INTO topic_dependencies (topic_id, depends_on_id, relationship, user_id, created_at) "
        "VALUES (?, ?, 'prerequisite', 1, '2026-01-01')",
        (id_avancado, id_basico),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    etapas = sorted(r.json()["etapas"], key=lambda e: e["ordem"])
    topicos_ordem = [e["topico"] for e in etapas]
    assert topicos_ordem.index("Básico") < topicos_ordem.index("Avançado")


def test_topico_concluido_conta_no_progresso(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase", status="Concluído")
    _add_topico(conn, "Português", "Regência", status="Não Iniciado")
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    data = r.json()
    assert data["progresso"]["concluidas"] == 1
    assert data["progresso"]["total_etapas"] == 2
    assert data["progresso"]["pct_conclusao"] == 50.0

    etapas = sorted(data["etapas"], key=lambda e: e["ordem"])
    concluida = next(e for e in etapas if e["topico"] == "Crase")
    atual = next(e for e in etapas if e["topico"] == "Regência")
    assert concluida["status"] == "concluida"
    # A primeira não-concluída vira 'atual'
    assert atual["status"] == "atual"


def test_regenerar_desativa_trilha_anterior(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    conn.commit()
    conn.close()

    r1 = client.post("/api/trilha/gerar")
    id1 = r1.json()["trilha"]["id"]
    r2 = client.post("/api/trilha/gerar")
    id2 = r2.json()["trilha"]["id"]
    assert id2 != id1

    # GET retorna a mais recente e só uma ativa
    r = client.get("/api/trilha")
    assert r.json()["trilha"]["id"] == id2

    conn = _conn()
    ativas = conn.execute("SELECT COUNT(*) FROM trilha WHERE ativo = 1 AND user_id = 1").fetchone()[0]
    conn.close()
    assert ativas == 1


# ============================================================
# FASE 2 — Concluir etapa
# ============================================================

def _etapas_ordenadas(payload):
    return sorted(payload["etapas"], key=lambda e: e["ordem"])


def test_concluir_etapa_marca_topico_e_desbloqueia_proxima(client):
    conn = _conn()
    id_t1 = _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Português", "Regência")
    conn.commit()
    conn.close()

    gerar = client.post("/api/trilha/gerar").json()
    etapas = _etapas_ordenadas(gerar)
    etapa_atual = etapas[0]
    assert etapa_atual["status"] == "atual"

    r = client.post(f"/api/trilha/etapas/{etapa_atual['id']}/concluir")
    assert r.status_code == 200
    data = r.json()

    # XP concedido pelo tópico
    assert data["xp_topico"] == 25

    novas = _etapas_ordenadas(data)
    assert novas[0]["status"] == "concluida"
    # Próxima etapa vira 'atual' e desbloqueada
    assert novas[1]["status"] == "atual"
    assert novas[1]["desbloqueada"] == 1
    assert data["progresso"]["concluidas"] == 1

    # O tópico do edital foi marcado como Concluído (single source of truth)
    conn = _conn()
    status_edital = conn.execute("SELECT status FROM edital WHERE id = ?", (id_t1,)).fetchone()[0]
    conn.close()
    assert status_edital == "Concluído"


def test_concluir_etapa_bloqueada_retorna_409(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Português", "Regência")
    conn.commit()
    conn.close()

    gerar = client.post("/api/trilha/gerar").json()
    etapas = _etapas_ordenadas(gerar)
    bloqueada = etapas[1]
    assert bloqueada["status"] == "bloqueada"

    r = client.post(f"/api/trilha/etapas/{bloqueada['id']}/concluir")
    assert r.status_code == 409
    assert "bloqueada" in r.json()["detail"].lower()


def test_concluir_etapa_inexistente_retorna_404(client):
    r = client.post("/api/trilha/etapas/999999/concluir")
    assert r.status_code == 404


def test_concluir_todas_marca_trilha_completa(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Direito", "Princípios")
    conn.commit()
    conn.close()

    data = client.post("/api/trilha/gerar").json()
    # Conclui em cadeia sempre a etapa 'atual'
    for _ in range(2):
        atual = next(e for e in data["etapas"] if e["status"] == "atual")
        data = client.post(f"/api/trilha/etapas/{atual['id']}/concluir").json()

    assert data["progresso"]["concluidas"] == 2
    assert data["progresso"]["concluida"] is True
    assert data["progresso"]["etapa_atual"] is None


def test_reconcluir_etapa_nao_duplica_xp(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    conn.commit()
    conn.close()

    data = client.post("/api/trilha/gerar").json()
    atual = next(e for e in data["etapas"] if e["status"] == "atual")

    r1 = client.post(f"/api/trilha/etapas/{atual['id']}/concluir").json()
    assert r1["xp_topico"] == 25
    # Reconcluir a mesma etapa (agora 'concluida') não concede XP de novo
    r2 = client.post(f"/api/trilha/etapas/{atual['id']}/concluir").json()
    assert r2["xp_topico"] == 0


# ============================================================
# FASE 4 — Sincronizar com o calendário
# ============================================================

def test_sincronizar_sem_trilha_retorna_404(client):
    r = client.post("/api/trilha/sincronizar-calendario")
    assert r.status_code == 404


def test_sincronizar_distribui_etapas_pendentes(client):
    conn = _conn()
    for i in range(4):
        _add_topico(conn, "Português", f"Tópico {i}")
    conn.commit()
    conn.close()
    client.post("/api/trilha/gerar")

    r = client.post("/api/trilha/sincronizar-calendario?dias_semana=2&tempo_min=45")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["agendadas"] == 4
    assert data["dias_semana"] == 2

    # Confere no calendário: 4 itens tipo='trilha', tempo 45
    conn = _conn()
    rows = conn.execute(
        "SELECT dia_semana, materia, topicos, tempo_min, tipo FROM calendario_personalizado WHERE user_id = 1 AND tipo = 'trilha' ORDER BY dia_semana, ordem"
    ).fetchall()
    conn.close()
    assert len(rows) == 4
    assert all(r["tipo"] == "trilha" for r in rows)
    assert all(r["tempo_min"] == 45 for r in rows)
    # Round-robin em 2 dias → 2 por dia
    dias = [r["dia_semana"] for r in rows]
    assert dias.count(0) == 2
    assert dias.count(1) == 2


def test_sincronizar_e_idempotente(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Direito", "Princípios")
    conn.commit()
    conn.close()
    client.post("/api/trilha/gerar")

    client.post("/api/trilha/sincronizar-calendario")
    client.post("/api/trilha/sincronizar-calendario")

    conn = _conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM calendario_personalizado WHERE user_id = 1 AND tipo = 'trilha'"
    ).fetchone()[0]
    conn.close()
    # Rodar 2x não duplica (idempotente)
    assert total == 2


def test_sincronizar_preserva_atividades_nao_trilha(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    # Atividade manual pré-existente (tipo != 'trilha')
    conn.execute(
        "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id) "
        "VALUES (0, 'Redação', '', 60, 'estudo', 0, 1)"
    )
    conn.commit()
    conn.close()
    client.post("/api/trilha/gerar")

    client.post("/api/trilha/sincronizar-calendario")

    conn = _conn()
    manual = conn.execute(
        "SELECT COUNT(*) FROM calendario_personalizado WHERE user_id = 1 AND tipo = 'estudo'"
    ).fetchone()[0]
    trilha = conn.execute(
        "SELECT COUNT(*) FROM calendario_personalizado WHERE user_id = 1 AND tipo = 'trilha'"
    ).fetchone()[0]
    conn.close()
    # A atividade manual permanece; a de trilha foi criada
    assert manual == 1
    assert trilha == 1


# ============================================================
# FASE 4b — Conclusão automática da etapa via calendário
# ============================================================

def test_marcar_atividade_trilha_conclui_etapa(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Português", "Regência")
    conn.commit()
    conn.close()
    client.post("/api/trilha/gerar")

    # Marca a atividade do calendário correspondente à etapa "Crase" como concluída
    r = client.post("/api/calendario/atividade-concluida", json={
        "data": "2026-08-28", "dia_semana": 0, "materia": "Português",
        "tipo": "trilha", "tempo_min": 60, "total_atividades": 1, "topico": "Crase",
    })
    assert r.status_code == 200
    assert r.json()["trilha_etapa_concluida"] is True

    # A etapa "Crase" ficou concluída e "Regência" virou a atual
    trilha = client.get("/api/trilha").json()
    etapas = {e["topico"]: e for e in trilha["etapas"]}
    assert etapas["Crase"]["status"] == "concluida"
    assert etapas["Regência"]["status"] == "atual"
    # E o tópico do edital foi marcado como Concluído
    conn = _conn()
    st = conn.execute("SELECT status FROM edital WHERE topico = 'Crase'").fetchone()[0]
    conn.close()
    assert st == "Concluído"


def test_marcar_atividade_nao_trilha_nao_afeta(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    conn.commit()
    conn.close()
    client.post("/api/trilha/gerar")

    r = client.post("/api/calendario/atividade-concluida", json={
        "data": "2026-08-28", "dia_semana": 0, "materia": "Português",
        "tipo": "estudo", "tempo_min": 60, "total_atividades": 1, "topico": "Crase",
    })
    assert r.status_code == 200
    assert r.json().get("trilha_etapa_concluida") is False

    trilha = client.get("/api/trilha").json()
    crase = next(e for e in trilha["etapas"] if e["topico"] == "Crase")
    assert crase["status"] == "atual"  # permanece atual (não concluída)


def test_gerar_filtra_por_cargo(client):
    """A mesma matéria (Português) repetida em 2 cargos NÃO deve ser agregada:
    gerar com ?cargo=X restringe a trilha aos tópicos daquele cargo."""
    conn = _conn()
    _add_ciclo(conn, "Português", 0)
    # Cargo A: 2 tópicos de Português
    conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
        "VALUES ('PC-MA', 'Cargo A', 'Português', 'A - Crase', 'Não Iniciado', 0, 1)"
    )
    conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
        "VALUES ('PC-MA', 'Cargo A', 'Português', 'A - Regência', 'Não Iniciado', 0, 1)"
    )
    # Cargo B: 3 tópicos de Português (mesma matéria, cargo diferente)
    for t in ("B - Crase", "B - Regência", "B - Acentuação"):
        conn.execute(
            "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
            "VALUES ('PC-MA', 'Cargo B', 'Português', ?, 'Não Iniciado', 0, 1)",
            (t,),
        )
    conn.commit()
    conn.close()

    # Sem filtro: agrega os 5 (comportamento legado, backward-compatible)
    r_all = client.post("/api/trilha/gerar")
    assert r_all.status_code == 200
    assert r_all.json()["progresso"]["total_etapas"] == 5

    # Com filtro por cargo: só os 2 tópicos do Cargo A
    r_a = client.post("/api/trilha/gerar?cargo=Cargo A")
    assert r_a.status_code == 200
    assert r_a.json()["progresso"]["total_etapas"] == 2
    topicos = {e["topico"] for e in r_a.json()["etapas"]}
    assert topicos == {"A - Crase", "A - Regência"}


def _seed_dois_cargos(conn):
    """Português no ciclo + 2 tópicos no Cargo A e 3 no Cargo B."""
    _add_ciclo(conn, "Português", 0)
    conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
        "VALUES ('PC-MA', 'Cargo A', 'Português', 'A - Crase', 'Não Iniciado', 0, 1)"
    )
    conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
        "VALUES ('PC-MA', 'Cargo A', 'Português', 'A - Regência', 'Não Iniciado', 0, 1)"
    )
    for t in ("B - Crase", "B - Regência", "B - Acentuação"):
        conn.execute(
            "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
            "VALUES ('PC-MA', 'Cargo B', 'Português', ?, 'Não Iniciado', 0, 1)",
            (t,),
        )


def test_cargo_alvo_default_vazio(client):
    r = client.get("/api/trilha/cargo-alvo")
    assert r.status_code == 200
    assert r.json() == {"edital_alvo": "", "cargo_alvo": ""}


def test_cargo_alvo_definir_e_ler(client):
    conn = _conn()
    _seed_dois_cargos(conn)
    conn.commit()
    conn.close()

    r = client.put("/api/trilha/cargo-alvo", json={"edital_alvo": "PC-MA", "cargo_alvo": "Cargo A"})
    assert r.status_code == 200
    assert r.json()["cargo_alvo"] == "Cargo A"

    r2 = client.get("/api/trilha/cargo-alvo")
    assert r2.json() == {"edital_alvo": "PC-MA", "cargo_alvo": "Cargo A"}


def test_cargo_alvo_inexistente_retorna_404(client):
    conn = _conn()
    _seed_dois_cargos(conn)
    conn.commit()
    conn.close()
    r = client.put("/api/trilha/cargo-alvo", json={"edital_alvo": "PC-MA", "cargo_alvo": "Cargo Inexistente"})
    assert r.status_code == 404


def test_gerar_usa_cargo_alvo_salvo(client):
    """Sem query params, a trilha deve usar o cargo alvo salvo (opção 2)."""
    conn = _conn()
    _seed_dois_cargos(conn)
    conn.commit()
    conn.close()

    # Define alvo = Cargo A e gera SEM query params
    client.put("/api/trilha/cargo-alvo", json={"edital_alvo": "PC-MA", "cargo_alvo": "Cargo A"})
    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    assert r.json()["progresso"]["total_etapas"] == 2
    topicos = {e["topico"] for e in r.json()["etapas"]}
    assert topicos == {"A - Crase", "A - Regência"}
