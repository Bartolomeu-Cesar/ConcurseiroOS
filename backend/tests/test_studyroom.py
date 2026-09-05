"""
Testes de integração do Study Room (Sala de Estudos Virtual).
Cobre criação, entrada, status, atualização de status, chat, listagem,
meta/goal, todo list, XP integration, histórico, pomodoro cycles, modo foco.

Executar: pytest tests/test_studyroom.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

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

    def test_criar_sala_com_meta(self, client):
        """Cria sala com meta/goal declarado."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Meta",
            "meta": "Estudar Direito Administrativo",
        })
        assert r.status_code == 200
        data = r.json()
        codigo = data["codigo"]

        # Verificar que a meta está no participante via status
        r2 = client.get(f"/api/studyroom/sala/{codigo}")
        assert r2.status_code == 200
        me = [p for p in r2.json()["participantes"] if p["is_me"]][0]
        assert me["meta"] == "Estudar Direito Administrativo"

    def test_criar_sala_com_pomodoro_config(self, client):
        """Cria sala com configuração de pomodoro personalizada."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Pomodoro Custom",
            "ciclo_foco_min": 30,
            "ciclo_pausa_min": 10,
            "ciclos_total": 3,
            "pausa_longa_min": 20,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ciclo_foco_min"] == 30
        assert data["ciclo_pausa_min"] == 10
        assert data["ciclos_total"] == 3
        assert data["pausa_longa_min"] == 20

    def test_criar_sala_com_modo_foco(self, client):
        """Cria sala com modo foco ativado."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Foco Ativo",
            "modo_foco": True,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["modo_foco"] is True


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
            INSERT INTO study_room_participants (room_id, user_id, nome, status, meta, joined_at)
            VALUES (?, ?, 'Extra', 'focando', '', datetime('now'))
        """, (room_id, 999))
        conn.commit()
        conn.close()

        # Tentar entrar com outro user (simulamos removendo o user_id=1 e tentando novamente)
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM study_room_participants WHERE room_id = ? AND user_id = 1", (room_id,))
        conn.execute("""
            INSERT INTO study_room_participants (room_id, user_id, nome, status, meta, joined_at)
            VALUES (?, ?, 'Outro', 'focando', '', datetime('now'))
        """, (room_id, 998))
        conn.commit()
        conn.close()

        # Agora a sala tem 2 participantes (998, 999) e user_id=1 não está
        r = client.post("/api/studyroom/entrar", json={"codigo": codigo})
        assert r.status_code == 400
        assert "cheia" in r.json()["detail"]

    def test_entrar_sala_com_meta(self, client):
        """Entra em sala com meta declarada."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Meta Entrar"})
        codigo = r.json()["codigo"]

        # Re-entrar com meta (já está, mas deve atualizar meta)
        r = client.post("/api/studyroom/entrar", json={
            "codigo": codigo,
            "meta": "Revisar Constitucional",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verificar meta no status
        r2 = client.get(f"/api/studyroom/sala/{codigo}")
        me = [p for p in r2.json()["participantes"] if p["is_me"]][0]
        assert me["meta"] == "Revisar Constitucional"


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
        # New fields
        assert "todos" in data
        assert "ciclo_foco_min" in data
        assert "ciclo_pausa_min" in data
        assert "ciclos_total" in data
        assert "pausa_longa_min" in data
        assert "modo_foco" in data

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

    def test_status_inclui_meta_participante(self, client):
        """Status retorna meta de cada participante."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Meta Status",
            "meta": "Estudar AFO",
        })
        codigo = r.json()["codigo"]

        r = client.get(f"/api/studyroom/sala/{codigo}")
        participantes = r.json()["participantes"]
        me = [p for p in participantes if p["is_me"]][0]
        assert "meta" in me
        assert me["meta"] == "Estudar AFO"

    def test_status_inclui_pomodoro_config(self, client):
        """Status retorna configuração de pomodoro."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Pomo Config",
            "ciclo_foco_min": 30,
            "ciclo_pausa_min": 7,
            "ciclos_total": 5,
            "pausa_longa_min": 20,
        })
        codigo = r.json()["codigo"]

        r = client.get(f"/api/studyroom/sala/{codigo}")
        data = r.json()
        assert data["ciclo_foco_min"] == 30
        assert data["ciclo_pausa_min"] == 7
        assert data["ciclos_total"] == 5
        assert data["pausa_longa_min"] == 20


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

    def test_xp_awarded_on_focus_end(self, client):
        """XP é concedido ao sair do modo foco."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala XP"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        # Manipular ultimo_checkin para simular tempo de foco
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute(
            "UPDATE study_room_participants SET ultimo_checkin = ?, status = 'focando' WHERE room_id = ? AND user_id = 1",
            (past, room_id)
        )
        conn.commit()
        conn.close()

        # Mudar para pausando
        r = client.post(f"/api/studyroom/status/{codigo}", json={"status": "pausando"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        # Should have xp_gained field (approx 20 for 1 hour)
        assert "xp_gained" in data
        assert data["xp_gained"] >= 18  # ~20 XP per hour, allow slight delta
        assert data["tempo_estudado"] >= 3500  # ~1 hour in seconds


# ============================================================
# POST /api/studyroom/heartbeat/{codigo} — Consolida tempo focado
# POST /api/studyroom/sair/{codigo} — Sai da sala com flush final
# ============================================================


def _horas_hoje_studyroom(user_id=1):
    """Soma horas registradas hoje em sessoes_estudo (tipo studyroom)."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(_tmp_db.name)
    row = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data = ? AND tipo = 'studyroom' AND user_id = ?",
        (hoje, user_id),
    ).fetchone()
    conn.close()
    return row[0]


class TestHeartbeatESair:
    def test_heartbeat_registra_tempo_em_sessoes_estudo(self, client):
        """Heartbeat consolida o tempo focado em sessoes_estudo (aparece no dashboard)."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Heartbeat"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        antes = _horas_hoje_studyroom()

        # Simular 1h de foco desde o último check-in
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute(
            "UPDATE study_room_participants SET ultimo_checkin = ?, status = 'focando' WHERE room_id = ? AND user_id = 1",
            (past, room_id),
        )
        conn.commit()
        conn.close()

        r = client.post(f"/api/studyroom/heartbeat/{codigo}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["tempo_estudado"] >= 3500

        # O tempo deve ter sido gravado em sessoes_estudo (fonte do dashboard)
        depois = _horas_hoje_studyroom()
        assert depois - antes >= 0.9  # ~1h creditada

    def test_heartbeat_mantem_focando_e_nao_conta_duplicado(self, client):
        """Após heartbeat, o participante continua focando e o check-in é resetado
        (chamadas seguidas sem tempo decorrido não creditam nada)."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala HB Idem"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        past = (datetime.now() - timedelta(minutes=30)).isoformat()
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute(
            "UPDATE study_room_participants SET ultimo_checkin = ?, status = 'focando' WHERE room_id = ? AND user_id = 1",
            (past, room_id),
        )
        conn.commit()
        conn.close()

        client.post(f"/api/studyroom/heartbeat/{codigo}")
        meio = _horas_hoje_studyroom()

        # Segundo heartbeat imediato: sem tempo decorrido → não credita
        r2 = client.post(f"/api/studyroom/heartbeat/{codigo}")
        assert r2.status_code == 200
        fim = _horas_hoje_studyroom()
        assert abs(fim - meio) < 0.01  # nada creditado a mais

        # Status permanece 'focando'
        conn = sqlite3.connect(_tmp_db.name)
        status = conn.execute(
            "SELECT status FROM study_room_participants WHERE room_id = ? AND user_id = 1", (room_id,)
        ).fetchone()[0]
        conn.close()
        assert status == "focando"

    def test_sair_faz_flush_final_e_marca_ausente(self, client):
        """POST /sair consolida o tempo pendente e marca o participante como ausente."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Sair"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        antes = _horas_hoje_studyroom()

        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute(
            "UPDATE study_room_participants SET ultimo_checkin = ?, status = 'focando' WHERE room_id = ? AND user_id = 1",
            (past, room_id),
        )
        conn.commit()
        conn.close()

        r = client.post(f"/api/studyroom/sair/{codigo}")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "ausente"
        assert data["tempo_estudado"] >= 3500

        depois = _horas_hoje_studyroom()
        assert depois - antes >= 0.9

        # Status persistido como ausente
        conn = sqlite3.connect(_tmp_db.name)
        status = conn.execute(
            "SELECT status FROM study_room_participants WHERE room_id = ? AND user_id = 1", (room_id,)
        ).fetchone()[0]
        conn.close()
        assert status == "ausente"

    def test_heartbeat_sala_inexistente_404(self, client):
        """Heartbeat em sala inexistente retorna 404."""
        r = client.post("/api/studyroom/heartbeat/ZZZZZZ")
        assert r.status_code == 404

    def test_sair_sala_inexistente_404(self, client):
        """Sair de sala inexistente retorna 404."""
        r = client.post("/api/studyroom/sair/ZZZZZZ")
        assert r.status_code == 404

    def test_tempo_em_pausa_nao_e_contabilizado(self, client):
        """Tempo passado em 'pausando' não conta como estudo.

        Fluxo da pausa automática do pomodoro: focando -> pausando (contabiliza
        o foco) -> permanece em pausa -> pausando -> focando (NÃO contabiliza a
        pausa). Ao voltar a focar, o ultimo_checkin é resetado, então o tempo de
        pausa é descartado.
        """
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Pausa"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        # Simular 1h de foco e mudar para pausando (deve contabilizar ~1h)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute(
            "UPDATE study_room_participants SET ultimo_checkin = ?, status = 'focando' WHERE room_id = ? AND user_id = 1",
            (past, room_id),
        )
        conn.commit()
        conn.close()

        antes = _horas_hoje_studyroom()
        r = client.post(f"/api/studyroom/status/{codigo}", json={"status": "pausando"})
        assert r.status_code == 200
        apos_foco = _horas_hoje_studyroom()
        assert apos_foco - antes >= 0.9  # foco contabilizado

        # Simular 1h em pausa: recuar o ultimo_checkin mas manter status 'pausando'
        past_pausa = (datetime.now() - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute(
            "UPDATE study_room_participants SET ultimo_checkin = ? WHERE room_id = ? AND user_id = 1",
            (past_pausa, room_id),
        )
        conn.commit()
        conn.close()

        # Voltar a focar: NÃO deve contabilizar a hora de pausa
        r = client.post(f"/api/studyroom/status/{codigo}", json={"status": "focando"})
        assert r.status_code == 200
        apos_pausa = _horas_hoje_studyroom()
        assert abs(apos_pausa - apos_foco) < 0.01  # pausa não creditou nada


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

    def test_chat_bloqueado_modo_foco(self, client):
        """Chat bloqueado durante ciclo de foco quando modo_foco ativo."""
        # Criar sala com modo_foco=True e ciclo de foco longo (para garantir que estamos no foco)
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Modo Foco",
            "modo_foco": True,
            "ciclo_foco_min": 60,  # 1 hora de foco - garante que estamos no ciclo de foco
            "ciclo_pausa_min": 5,
            "ciclos_total": 4,
            "pausa_longa_min": 15,
        })
        assert r.status_code == 200
        codigo = r.json()["codigo"]

        # Tentar enviar mensagem - deve ser bloqueada (estamos no primeiro ciclo de foco)
        r = client.post(f"/api/studyroom/chat/{codigo}", json={"mensagem": "Oi"})
        assert r.status_code == 403
        assert "foco" in r.json()["detail"].lower()


# ============================================================
# TODO LIST — POST /api/studyroom/todo/{codigo}
# ============================================================

class TestTodoList:
    def test_adicionar_todo(self, client):
        """Adiciona tarefa ao todo list."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Todo"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/todo/{codigo}", json={"texto": "Revisar flashcards"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["texto"] == "Revisar flashcards"
        assert data["completo"] is False
        assert "id" in data
        assert "created_at" in data

    def test_todo_aparece_no_status(self, client):
        """Tarefa adicionada aparece no status da sala."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Todo Status"})
        codigo = r.json()["codigo"]

        client.post(f"/api/studyroom/todo/{codigo}", json={"texto": "Resolver 10 questões"})

        r = client.get(f"/api/studyroom/sala/{codigo}")
        todos = r.json()["todos"]
        assert len(todos) >= 1
        assert any(t["texto"] == "Resolver 10 questões" for t in todos)

    def test_marcar_todo_completo(self, client):
        """Marca tarefa como completa."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Todo Complete"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/todo/{codigo}", json={"texto": "Tarefa a completar"})
        todo_id = r.json()["id"]

        r = client.put(f"/api/studyroom/todo/{codigo}/{todo_id}", json={"completo": True})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["completo"] is True

    def test_desmarcar_todo(self, client):
        """Desmarca tarefa (completo = false)."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Todo Desmarcar"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/todo/{codigo}", json={"texto": "Tarefa para desmarcar"})
        todo_id = r.json()["id"]

        # Marcar
        client.put(f"/api/studyroom/todo/{codigo}/{todo_id}", json={"completo": True})
        # Desmarcar
        r = client.put(f"/api/studyroom/todo/{codigo}/{todo_id}", json={"completo": False})
        assert r.status_code == 200
        assert r.json()["completo"] is False

    def test_todo_texto_vazio_rejeitado(self, client):
        """Rejeita texto vazio."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Todo Vazio"})
        codigo = r.json()["codigo"]

        r = client.post(f"/api/studyroom/todo/{codigo}", json={"texto": "   "})
        assert r.status_code == 400
        assert "vazio" in r.json()["detail"].lower()

    def test_todo_sala_inexistente(self, client):
        """Retorna 404 para sala inexistente."""
        r = client.post("/api/studyroom/todo/QQQQQQ", json={"texto": "Tarefa"})
        assert r.status_code == 404

    def test_todo_nao_participante(self, client):
        """Retorna 403 se não é participante."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Todo Fechada"})
        codigo = r.json()["codigo"]
        room_id = r.json()["id"]

        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM study_room_participants WHERE room_id = ? AND user_id = 1", (room_id,))
        conn.commit()
        conn.close()

        r = client.post(f"/api/studyroom/todo/{codigo}", json={"texto": "Tarefa"})
        assert r.status_code == 403

    def test_todo_inexistente(self, client):
        """Retorna 404 ao tentar atualizar todo inexistente."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Todo Inex"})
        codigo = r.json()["codigo"]

        r = client.put(f"/api/studyroom/todo/{codigo}/99999", json={"completo": True})
        assert r.status_code == 404


# ============================================================
# GET /api/studyroom/historico — Histórico de sessões
# ============================================================

class TestHistorico:
    def test_historico_retorna_sessoes(self, client):
        """Retorna histórico com sessões participadas."""
        # Criar sala para garantir que existe pelo menos uma
        client.post("/api/studyroom/criar", json={"titulo": "Sala Histórico"})

        r = client.get("/api/studyroom/historico")
        assert r.status_code == 200
        data = r.json()
        assert "historico" in data
        assert len(data["historico"]) >= 1

        item = data["historico"][0]
        assert "codigo" in item
        assert "titulo" in item
        assert "tempo_focado_seg" in item
        assert "tempo_focado_min" in item
        assert "meta" in item
        assert "created_at" in item

    def test_historico_com_meta(self, client):
        """Histórico inclui meta declarada."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Hist Meta",
            "meta": "Estudar Penal",
        })
        codigo = r.json()["codigo"]

        r = client.get("/api/studyroom/historico")
        historico = r.json()["historico"]
        sala = next((h for h in historico if h["codigo"] == codigo), None)
        assert sala is not None
        assert sala["meta"] == "Estudar Penal"


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
# Pomodoro cycles in sala status
# ============================================================

class TestPomodoroCycles:
    def test_pomodoro_defaults(self, client):
        """Sala criada sem config de pomodoro usa defaults."""
        r = client.post("/api/studyroom/criar", json={"titulo": "Sala Pomo Default"})
        codigo = r.json()["codigo"]

        r = client.get(f"/api/studyroom/sala/{codigo}")
        data = r.json()
        assert data["ciclo_foco_min"] == 25
        assert data["ciclo_pausa_min"] == 5
        assert data["ciclos_total"] == 4
        assert data["pausa_longa_min"] == 15

    def test_pomodoro_custom_values(self, client):
        """Sala criada com valores customizados de pomodoro."""
        r = client.post("/api/studyroom/criar", json={
            "titulo": "Sala Pomo Custom",
            "ciclo_foco_min": 45,
            "ciclo_pausa_min": 15,
            "ciclos_total": 2,
            "pausa_longa_min": 30,
        })
        assert r.status_code == 200
        codigo = r.json()["codigo"]

        r = client.get(f"/api/studyroom/sala/{codigo}")
        data = r.json()
        assert data["ciclo_foco_min"] == 45
        assert data["ciclo_pausa_min"] == 15
        assert data["ciclos_total"] == 2
        assert data["pausa_longa_min"] == 30


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
