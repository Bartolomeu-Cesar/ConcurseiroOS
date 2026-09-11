"""
Testes dos fixes de revisão diária:

1. Filtro de ciclo ativo no caderno de erros (regra nº 2): questões de matérias
   fora do ciclo ativo NÃO devem aparecer como pendentes de revisão.
2. Graduação FSRS (atualizar_fsrs_ao_responder): questões acertadas
   repetidamente avançam o agendamento e, ao dominar (reps >= 3), saem do
   caderno de erros — deixando de reaparecer todo dia.
3. Integração: responder o desafio diário atualiza erros_revisao.

Executar: pytest tests/test_caderno_erros_ciclo_fsrs.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_caderno_ciclo_fsrs.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

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


def _conn():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _reset():
    conn = _conn()
    for t in ("questoes", "questoes_respostas", "erros_revisao", "ciclo_estudos", "desafio_diario"):
        try:
            conn.execute(f"DELETE FROM {t} WHERE 1=1")
        except Exception:
            pass
    conn.commit()
    conn.close()


def _criar_questao(client, materia, resposta_correta="A"):
    r = client.post("/api/questoes", json={
        "materia": materia,
        "topico": "T",
        "enunciado": f"Questão de {materia}?",
        "alternativa_a": "A", "alternativa_b": "B",
        "alternativa_c": "C", "alternativa_d": "D", "alternativa_e": "",
        "resposta_correta": resposta_correta, "explicacao": "x", "dificuldade": "Médio",
    })
    assert r.status_code == 200
    return r.json()["id"]


def _registrar_erro(qid, resposta_id_base=1000):
    """Insere uma resposta ERRADA + entrada em erros_revisao pendente para hoje."""
    from utils import today_str
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id) "
        "VALUES (?, 'B', 0, 30, ?, 1)",
        (qid, today_str()),
    )
    resposta_id = cur.lastrowid
    conn.execute(
        "INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao, "
        "revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review) "
        "VALUES (1, ?, ?, 1, ?, 0, ?, 0, 0, 0, ?, NULL)",
        (qid, resposta_id, today_str(), today_str(), 0),
    )
    conn.commit()
    conn.close()
    return resposta_id


# ============================================================
# 1. Filtro de ciclo ativo no caderno de erros
# ============================================================

class TestCadernoErrosFiltroCiclo:
    def test_questao_fora_do_ciclo_nao_aparece(self, client):
        """Questão errada de matéria FORA do ciclo ativo não deve aparecer no caderno."""
        _reset()
        conn = _conn()
        # Ciclo ativo só com 'Informática'
        conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Informática', 1, 1)")
        conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Direito Constitucional', 0, 1)")
        conn.commit()
        conn.close()

        q_ativa = _criar_questao(client, "Informática")
        q_inativa = _criar_questao(client, "Direito Constitucional")
        _registrar_erro(q_ativa)
        _registrar_erro(q_inativa)

        data = client.get("/api/questoes/erros/caderno").json()
        materias = {e["materia"] for e in data["pendentes_hoje"]}
        ids = {e["id"] for e in data["pendentes_hoje"]}

        assert q_ativa in ids, "questão do ciclo ativo deve aparecer"
        assert q_inativa not in ids, "questão fora do ciclo NÃO deve aparecer"
        assert "Direito Constitucional" not in materias

    def test_sem_ciclo_ativo_mostra_todas(self, client):
        """Sem nenhum ciclo ativo, o filtro não se aplica (fallback = todas)."""
        _reset()
        q1 = _criar_questao(client, "Informática")
        q2 = _criar_questao(client, "Direito Constitucional")
        _registrar_erro(q1)
        _registrar_erro(q2)

        data = client.get("/api/questoes/erros/caderno").json()
        ids = {e["id"] for e in data["pendentes_hoje"]}
        assert q1 in ids and q2 in ids, "sem ciclo, todas as matérias aparecem"


# ============================================================
# 2. Graduação FSRS via helper
# ============================================================

class TestGraduacaoFSRS:
    def test_acerto_avanca_proxima_revisao(self, client):
        """Acertar uma questão do caderno empurra proxima_revisao para o futuro."""
        _reset()
        from routers.questoes.caderno_erros import atualizar_fsrs_ao_responder

        from utils import today_str

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)

        conn = _conn()
        res = atualizar_fsrs_ao_responder(conn, qid, acertou=True, user_id=1)
        conn.commit()
        assert res is not None
        assert res["graduou"] is False
        # proxima_revisao deve ser posterior a hoje
        row = conn.execute(
            "SELECT proxima_revisao, reps FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()
        conn.close()
        assert row is not None, "questão ainda no caderno (não graduou no 1º acerto)"
        assert row["proxima_revisao"] > today_str()
        assert row["reps"] == 1

    def test_graduacao_remove_apos_dominio(self, client):
        """Após reps >= 3 e novo acerto, a questão GRADUA e sai do caderno."""
        _reset()
        from routers.questoes.caderno_erros import GRADUACAO_REPS_MIN, atualizar_fsrs_ao_responder

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)

        conn = _conn()
        # Simula reps já no limiar de graduação
        conn.execute(
            "UPDATE erros_revisao SET reps=?, fsrs_state=2, stability=10, difficulty=5 WHERE questao_id=? AND user_id=1",
            (GRADUACAO_REPS_MIN, qid),
        )
        conn.commit()

        res = atualizar_fsrs_ao_responder(conn, qid, acertou=True, user_id=1)
        conn.commit()
        assert res is not None
        assert res["graduou"] is True

        restante = conn.execute(
            "SELECT COUNT(*) FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()[0]
        conn.close()
        assert restante == 0, "questão dominada deve sair do caderno de erros"

    def test_questao_fora_do_caderno_retorna_none(self, client):
        """Se a questão não está em erros_revisao, o helper não faz nada."""
        _reset()
        from routers.questoes.caderno_erros import atualizar_fsrs_ao_responder

        qid = _criar_questao(client, "Informática")
        conn = _conn()
        res = atualizar_fsrs_ao_responder(conn, qid, acertou=True, user_id=1)
        conn.close()
        assert res is None


# ============================================================
# 3. Integração: desafio diário atualiza o FSRS
# ============================================================

class TestDesafioDiarioAtualizaFSRS:
    def test_responder_desafio_avanca_fsrs(self, client):
        """Responder (acertando) uma questão do caderno via desafio diário
        avança o agendamento em erros_revisao (não fica presa)."""
        _reset()
        from utils import today_str

        # Ciclo ativo com Informática para o desafio poder selecioná-la
        conn = _conn()
        conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Informática', 1, 1)")
        conn.commit()
        conn.close()

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)

        proxima_antes = today_str()

        # Gera o desafio (deve incluir a questão pendente de revisão) e responde certo
        data = client.get("/api/desafio-diario").json()
        assert qid in [q["id"] for q in data["questoes"]], "questão pendente deve entrar no desafio"

        respostas = [{"questao_id": q["id"], "resposta": "A"} for q in data["questoes"]]
        r = client.post("/api/desafio-diario/responder", json={"respostas": respostas})
        assert r.status_code == 200

        conn = _conn()
        row = conn.execute(
            "SELECT proxima_revisao, reps FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()
        conn.close()
        # Ou graduou (removida) ou avançou a próxima revisão para o futuro.
        if row is not None:
            assert row["proxima_revisao"] > proxima_antes
            assert row["reps"] >= 1


# ============================================================
# 4. Graduação via endpoint de revisão dedicada (revisar_erro)
# ============================================================

class TestGraduacaoViaRevisarEndpoint:
    def test_revisar_acerto_facil_com_dominio_gradua_e_remove(self, client):
        """Revisar acertando com ALTA FACILIDADE (Easy) DENTRO do caderno, com
        reps >= limiar e dificuldade baixa, deve graduar: a questão sai do
        caderno e o retorno traz graduou=True."""
        _reset()
        from routers.questoes.caderno_erros import GRADUACAO_REPS_MIN

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)

        # Limiar de reps + card já fácil (difficulty baixa, estado review).
        conn = _conn()
        conn.execute(
            "UPDATE erros_revisao SET reps=?, fsrs_state=2, stability=20, difficulty=3 "
            "WHERE questao_id=? AND user_id=1",
            (GRADUACAO_REPS_MIN, qid),
        )
        conn.commit()
        conn.close()

        # facilidade=4 (Easy) → acerto fácil
        r = client.post(f"/api/questoes/erros/revisar/{qid}", json={"acertou": True, "facilidade": 4})
        assert r.status_code == 200
        body = r.json()
        assert body.get("graduou") is True, f"acerto fácil com domínio deve graduar (difficulty={body.get('difficulty')})"

        conn = _conn()
        restante = conn.execute(
            "SELECT COUNT(*) FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()[0]
        conn.close()
        assert restante == 0, "questão dominada (fácil) deve sair do caderno"

    def test_revisar_acerto_dificil_nao_gradua(self, client):
        """Acertar 'mas foi difícil' (facilidade=Hard=2) NÃO gradua, mesmo com
        reps altas: o acerto sofrido mantém a questão em revisão."""
        _reset()
        from routers.questoes.caderno_erros import GRADUACAO_REPS_MIN

        from utils import today_str

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)
        conn = _conn()
        conn.execute(
            "UPDATE erros_revisao SET reps=?, fsrs_state=2, stability=20, difficulty=3 "
            "WHERE questao_id=? AND user_id=1",
            (GRADUACAO_REPS_MIN + 2, qid),
        )
        conn.commit()
        conn.close()

        # facilidade=2 (Hard) → rating < Good → não gradua
        r = client.post(f"/api/questoes/erros/revisar/{qid}", json={"acertou": True, "facilidade": 2})
        assert r.status_code == 200
        assert r.json().get("graduou") is False, "acerto difícil (Hard) não pode graduar"

        conn = _conn()
        row = conn.execute(
            "SELECT proxima_revisao FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()
        conn.close()
        assert row is not None, "acerto difícil deve manter a questão no caderno"
        assert row["proxima_revisao"] > today_str()

    def test_revisar_acerto_facil_sem_dominio_mantem(self, client):
        """Acerto fácil mas com poucas reps (< limiar) NÃO gradua: continua no
        caderno com proxima_revisao no futuro."""
        _reset()
        from utils import today_str

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)  # reps = 0

        r = client.post(f"/api/questoes/erros/revisar/{qid}", json={"acertou": True, "facilidade": 4})
        assert r.status_code == 200
        assert r.json().get("graduou") is False

        conn = _conn()
        row = conn.execute(
            "SELECT proxima_revisao, reps FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()
        conn.close()
        assert row is not None, "sem reps suficientes, mantém no caderno"
        assert row["reps"] == 1
        assert row["proxima_revisao"] > today_str()

    def test_revisar_erro_nao_gradua(self, client):
        """Errar na revisão nunca gradua, mesmo com reps altas."""
        _reset()
        from routers.questoes.caderno_erros import GRADUACAO_REPS_MIN

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)
        conn = _conn()
        conn.execute(
            "UPDATE erros_revisao SET reps=? WHERE questao_id=? AND user_id=1",
            (GRADUACAO_REPS_MIN + 2, qid),
        )
        conn.commit()
        conn.close()

        r = client.post(f"/api/questoes/erros/revisar/{qid}", json={"acertou": False})
        assert r.status_code == 200
        assert r.json().get("graduou") is False

        conn = _conn()
        restante = conn.execute(
            "SELECT COUNT(*) FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()[0]
        conn.close()
        assert restante == 1, "errar não pode remover a questão do caderno"


# ============================================================
# 5. Múltiplas linhas por questão + refresh (bug: reaparecia no mesmo dia)
# ============================================================

class TestRevisaoNaoReapareceNoMesmoDia:
    def _registrar_erro_extra(self, qid, data="2026-09-08"):
        """Insere OUTRA resposta errada + entrada em erros_revisao ANTIGA
        (proxima_revisao no passado), simulando erros em contextos diferentes."""
        conn = _conn()
        cur = conn.execute(
            "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id) "
            "VALUES (?, 'C', 0, 40, ?, 1)",
            (qid, data),
        )
        resposta_id = cur.lastrowid
        conn.execute(
            "INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao, "
            "revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review) "
            "VALUES (1, ?, ?, 1, ?, 0, ?, 0, 0, 0, 0, NULL)",
            (qid, resposta_id, data, data),
        )
        conn.commit()
        conn.close()
        return resposta_id

    def test_revisar_avanca_todas_as_linhas_da_questao(self, client):
        """Questão com VÁRIAS linhas em erros_revisao: ao revisar (não graduar),
        TODAS as linhas devem avançar proxima_revisao para o futuro, senão a
        questão reaparece como pendente no refresh."""
        _reset()
        from utils import today_str

        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)              # linha 1 (hoje)
        self._registrar_erro_extra(qid)   # linha 2 (antiga, passado)
        self._registrar_erro_extra(qid, "2026-09-07")  # linha 3 (antiga)

        conn = _conn()
        n_linhas = conn.execute(
            "SELECT COUNT(*) FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchone()[0]
        conn.close()
        assert n_linhas == 3, "pré-condição: 3 linhas para a mesma questão"

        # Revisa uma vez (acerto difícil → não gradua)
        r = client.post(f"/api/questoes/erros/revisar/{qid}", json={"acertou": True, "facilidade": 3})
        assert r.status_code == 200
        assert r.json().get("graduou") is False

        # TODAS as linhas devem ter proxima_revisao no futuro
        conn = _conn()
        rows = conn.execute(
            "SELECT proxima_revisao FROM erros_revisao WHERE questao_id=? AND user_id=1", (qid,)
        ).fetchall()
        conn.close()
        assert len(rows) == 3, "revisão não graduada mantém as linhas"
        for row in rows:
            assert row["proxima_revisao"] > today_str(), \
                f"linha ficou no passado ({row['proxima_revisao']}) → reapareceria no refresh"

    def test_questao_revisada_nao_aparece_como_pendente_apos_refresh(self, client):
        """Simula o refresh: após revisar, novo GET /caderno NÃO deve trazer a
        questão como pendente (mesmo tendo linhas antigas no passado)."""
        _reset()
        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)
        self._registrar_erro_extra(qid)
        self._registrar_erro_extra(qid, "2026-09-06")

        # Antes: é pendente
        data = client.get("/api/questoes/erros/caderno").json()
        assert qid in [q["id"] for q in data["pendentes_hoje"]], "deve começar pendente"

        # Revisa (não gradua)
        r = client.post(f"/api/questoes/erros/revisar/{qid}", json={"acertou": True, "facilidade": 3})
        assert r.status_code == 200

        # Refresh: NÃO deve mais aparecer como pendente hoje
        data2 = client.get("/api/questoes/erros/caderno").json()
        ids_pendentes = [q["id"] for q in data2["pendentes_hoje"]]
        assert qid not in ids_pendentes, "questão revisada hoje NÃO pode reaparecer no refresh"

    def test_pendentes_sem_duplicar_por_questao(self, client):
        """Uma questão com múltiplas respostas erradas pendentes deve aparecer
        uma ÚNICA vez em pendentes_hoje (dedupe por questao_id)."""
        _reset()
        qid = _criar_questao(client, "Informática")
        _registrar_erro(qid)
        self._registrar_erro_extra(qid, "2026-09-09")
        self._registrar_erro_extra(qid, "2026-09-08")

        data = client.get("/api/questoes/erros/caderno").json()
        ids_pendentes = [q["id"] for q in data["pendentes_hoje"]]
        assert ids_pendentes.count(qid) == 1, "questão não pode aparecer duplicada em pendentes_hoje"


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
