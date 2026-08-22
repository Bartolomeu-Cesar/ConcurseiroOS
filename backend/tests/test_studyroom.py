"""
Testes de integração do Study Room (Sala de Estudos Virtual).
Cobre criação, entrada, status, atualização de status, chat e listagem.

Executar: pytest tests/test_studyroom.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_studyroom.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

# Ajustar path para imports
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
    """TestClient compartilhado por todo o módulo de testes."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


# ============================================================
# POST /api/studyroom/criar — Criar sala de estudos
# ============================================================

class TestCriarSala:
    def test_criar_sala_padrao(self, client):
        """Cria sala com valores padrão e retorna código."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala de Teste",
            "max_participantes": 10,
            "tecnica": "pomodoro",
            "duracao_min": 50,
        })
        assert r.status_code == 200
        data = r.json()
        assert "codigo" in data
        assert len(data["codigo"]) == 6
        assert data["titulo"] == "Sala de Teste"
        assert data["tecnica"] == "pomodoro"
        assert data["duracao_min"] == 50
        assert data["max_participantes"] == 10
        assert data["criador_id"] == 1

    def test_criar_sala_tecnica_livre(self, client):
        """Cria sala com técnica 'livre'."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Livre",
            "tecnica": "livre",
            "duracao_min": 120,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["tecnica"] == "livre"
        assert data["duracao_min"] == 120

    def test_criar_sala_tecnica_invalida(self, client):
        """Rejeita técnica inválida."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Inválida",
            "tecnica": "invalida",
        })
        assert r.status_code == 400
        assert "Técnica" in r.json()["detail"]

    def test_criar_sala_duracao_invalida(self, client):
        """Rejeita duração fora do range (5-240min)."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Curta",
            "duracao_min": 2,
        })
        assert r.status_code == 400
        assert "Duração" in r.json()["detail"]

    def test_criar_sala_participantes_invalidos(self, client):
        """Rejeita max_participantes fora do range (2-50)."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Unitária",
            "max_participantes": 1,
        })
        assert r.status_code == 400
        assert "participantes" in r.json()["detail"]


# ============================================================
# POST /api/studyroom/entrar — Entrar em sala
# ============================================================

class TestEntrarSala:
    def test_entrar_sala_existente(self, client):
        """Entrar em sala existente (já está como criador, retorna ok)."""
        # Criar sala primeiro
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Entrar"})
        codigo = r.json()["codigo"]

        # Tentar entrar (user_id=1 já é o criador)
        r = client.post("/api/studyroom/entrar", json={"codigo": codigo})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "Já está" in data["msg"]

    def test_entrar_sala_inexistente(self, client):
        """Retorna 404 para sala inexistente."""
        r = client.post("/api/studyroom/entrar", json={"codigo": "ZZZZZZ"})
        assert r.status_code == 404
        assert "não encontrada" in r.json()["detail"]

    def test_entrar_sala_cheia(self, client):
        """Rejeita entrada em sala cheia."""
        # Criar sala com max=2
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Lotada",
            "max_participantes": 2,
        })
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        # Inserir participante extra para lotar a sala (criador + 1 = 2)
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("""
            INSERT INTO study_room_participants (room_id, user_id, nome, status, joined_at)
            VALUES (?, ?, 'Extra', 'focando', datetime('now'))
        """, (room_id, 999))
        conn.commit()
        conn.close()

        # Tentar entrar com outro user (simulamos removendo o user_id=1 e tentando novamente)
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM study_room_participants WHERE room_id = ? AND user_id = 1", (room_id,))
        conn.execute("""
            INSERT INTO study_room_participants (room_id, user_id, nome, status, joined_at)
            VALUES (?, ?, 'Outro', 'focando', datetime('now'))
        """, (room_id, 998))
        conn.commit()
        conn.close()

        # Agora a sala tem 2 participantes (998, 999) e user_id=1 não está
        r = client.post("/api/studyroom/entrar", json={"codigo": codigo})
        assert r.status_code == 400
        assert "cheia" in r.json()["detail"]


# ============================================================
# GET /api/studyroom/sala/{codigo} — Status da sala
# ============================================================

class TestStatusSala:
    def test_obter_status_sala(self, client):
        """Retorna status completo da sala."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Status",
            "tecnica": "pomodoro",
            "duracao_min": 25,
        })
        codigo = r.json()["codigo"]

        r = client.get(f"/api/studyroom/sala/{codigo}")
        assert r.status_code == 200
        data = r.json()
        assert data["codigo"] == codigo
        assert data["titulo"] == "Sala Status"
        assert data["tecnica"] == "pomodoro"
        assert data["duracao_min"] == 25
        assert data["status"] == "ativa"
        assert "participantes" in data
        assert len(data["participantes"]) >= 1
        assert "chat_messages" in data
        assert "timer_global" in data
        assert data["timer_global"] >= 0

    def test_status_sala_inexistente(self, client):
        """Retorna 404 para sala inexistente."""
        r = client.get("/api/studyroom/sala/XYZXYZ")
        assert r.status_code == 404

    def test_participante_marcado_como_is_me(self, client):
        """O participante corrente é marcado com is_me=True."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Me"})
        codigo = r.json()["codigo"]

        r = client.get(f"/api/studyroom/sala/{codigo}")
        participantes = r.json()["participantes"]
        me = [p for p in participantes if p["is_me"]]
        assert len(me) == 1
        assert me[0]["user_id"] == 1


# ============================================================
# POST /api/studyroom/status/{codigo} — Atualizar status
# ============================================================

class TestAtualizarStatus:
    def test_atualizar_status_para_pausando(self, client):
        """Atualiza status do participante para 'pausando'."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Pausa"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/status/{codigo}", json={"status": "pausando"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "pausando"
        assert "tempo_estudado" in data

    def test_atualizar_status_para_focando(self, client):
        """Atualiza status para 'focando'."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Foco"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/status/{codigo}", json={"status": "focando"})
        assert r.status_code == 200
        assert r.json()["status"] == "focando"

    def test_atualizar_status_invalido(self, client):
        """Rejeita status inválido."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Inv"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/status/{codigo}", json={"status": "dormindo"})
        assert r.status_code == 400
        assert "Status" in r.json()["detail"]

    def test_atualizar_status_sala_inexistente(self, client):
        """Retorna 404 para sala inexistente."""
        r = client.post("/api/studyroom/status/AAAAAA", json={"status": "focando"})
        assert r.status_code == 404

    def test_atualizar_status_nao_participante(self, client):
        """Retorna 404 se não é participante da sala."""
        # Criar sala e remover o participante do banco
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Forasteiro"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM study_room_participants WHERE room_id = ? AND user_id = 1", (room_id,))
        conn.commit()
        conn.close()

        r = client.post(f"/api/studyroom/status/{codigo}", json={"status": "focando"})
        assert r.status_code == 404
        assert "não está" in r.json()["detail"]


# ============================================================
# POST /api/studyroom/chat/{codigo} — Enviar mensagem
# ============================================================

class TestChat:
    def test_enviar_mensagem(self, client):
        """Envia mensagem no chat da sala."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Chat"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/chat/{codigo}", json={"mensagem": "Bora estudar!"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["mensagem"] == "Bora estudar!"
        assert "created_at" in data

    def test_mensagem_aparece_no_status(self, client):
        """Mensagem enviada aparece no polling de status."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Chat Poll"})
        codigo = r.json()["codigo"]

        client.post(f"/api/studyroom/chat/{codigo}", json={"mensagem": "Hello World"})

        r = client.get(f"/api/studyroom/sala/{codigo}")
        messages = r.json()["chat_messages"]
        assert any(m["mensagem"] == "Hello World" for m in messages)

    def test_mensagem_vazia_rejeitada(self, client):
        """Rejeita mensagem vazia."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Msg Vazia"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/chat/{codigo}", json={"mensagem": "   "})
        assert r.status_code == 400
        assert "vazia" in r.json()["detail"]

    def test_mensagem_longa_rejeitada(self, client):
        """Rejeita mensagem muito longa (>500 chars)."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Msg Longa"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/chat/{codigo}", json={"mensagem": "x" * 501})
        assert r.status_code == 400
        assert "longa" in r.json()["detail"]

    def test_chat_sala_inexistente(self, client):
        """Retorna 404 para sala inexistente."""
        r = client.post("/api/studyroom/chat/BBBBBB", json={"mensagem": "Oi"})
        assert r.status_code == 404

    def test_chat_nao_participante(self, client):
        """Retorna 403 se não é participante."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Fechada"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        # Remover o participante
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM study_room_participants WHERE room_id = ? AND user_id = 1", (room_id,))
        conn.commit()
        conn.close()

        r = client.post(f"/api/studyroom/chat/{codigo}", json={"mensagem": "Oi"})
        assert r.status_code == 403
        assert "participante" in r.json()["detail"]


# ============================================================
# GET /api/studyroom/minhas — Listar minhas salas
# ============================================================

class TestMinhasSalas:
    def test_listar_minhas_salas(self, client):
        """Retorna lista de salas em que o usuário participa."""
        # Criar uma sala para garantir que existe pelo menos uma
        client.post("/api/studyroom/criar", json={"titulo": "Sala Minha"})

        r = client.get("/api/studyroom/minhas")
        assert r.status_code == 200
        data = r.json()
        assert "salas" in data
        assert len(data["salas"]) >= 1
        # Verificar estrutura
        sala = data["salas"][0]
        assert "codigo" in sala
        assert "titulo" in sala
        assert "tecnica" in sala
        assert "duracao_min" in sala
        assert "status" in sala
        assert "num_participantes" in sala
        assert "is_owner" in sala

    def test_salas_ordenadas_por_data(self, client):
        """Salas são retornadas mais recentes primeiro."""
        r = client.get("/api/studyroom/minhas")
        assert r.status_code == 200
        salas = r.json()["salas"]
        if len(salas) >= 2:
            assert salas[0]["created_at"] >= salas[1]["created_at"]


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
