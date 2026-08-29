"""
Testes do catálogo público de materiais (routers/catalogo.py).
Cobre: publicar (admin), listar, importar (estudante copia + incrementa download),
permissões (só admin publica/remove), item inativo.

AUTH_ENABLED=true para distinguir admin (id=1) de estudantes comuns.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_catalogo.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

# Garantir admin
_c = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
_c.execute("UPDATE users SET role = 'admin' WHERE id = 1")
_c.commit()
_c.close()

from fastapi.testclient import TestClient
from main import app
from settings import settings


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
    settings.AUTH_ENABLED = True
    app.dependency_overrides[get_db_session] = _override_db_session
    yield
    settings.AUTH_ENABLED = False


def _conn():
    c = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _token(uid, email):
    import jwt as pyjwt
    payload = {
        "sub": str(uid), "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _admin_token():
    conn = _conn()
    admin = conn.execute("SELECT id, email FROM users WHERE id = 1").fetchone()
    conn.close()
    return _token(admin["id"], admin["email"])


def _criar_estudante(uid, email):
    conn = _conn()
    conn.execute("""
        INSERT OR IGNORE INTO users (id, nome, username, email, password_hash, plano, role, created_at)
        VALUES (?, ?, ?, ?, 'hash', 'free', 'user', '2026-01-01')
    """, (uid, f"Estudante {uid}", f"est{uid}", email))
    conn.commit()
    conn.close()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_curador(curador_uid=1):
    """Cria recursos na conta do curador (admin id=1) para publicar."""
    conn = _conn()
    now = datetime.now().isoformat()
    # Edital
    conn.execute("""
        INSERT INTO edital (edital_nome, cargo, materia, topico, status, user_id)
        VALUES ('PF 2026', 'Agente', 'Dir Penal', 'Crimes', 'Concluído', ?)
    """, (curador_uid,))
    # Flashcards da matéria "Direito"
    conn.execute("INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id) VALUES ('P1', 'R1', ?, 'Direito', ?)", (now, curador_uid))
    conn.execute("INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id) VALUES ('P2', 'R2', ?, 'Direito', ?)", (now, curador_uid))
    # Questões da matéria "Direito"
    conn.execute("""
        INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, resposta_correta, created_at, user_id)
        VALUES ('Direito', 'T', 'Q?', 'a', 'b', 'c', 'd', '', 'A', ?, ?)
    """, (now, curador_uid))
    conn.commit()
    conn.close()


class TestPublicar:
    def test_publicar_edital_admin(self, client):
        _seed_curador(1)
        token = _admin_token()
        r = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "edital", "titulo": "Edital PF 2026", "descricao": "Completo",
            "categoria": "Polícia", "origem_uid": 1, "ref": "PF 2026"
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_publicar_recurso_inexistente_404(self, client):
        token = _admin_token()
        r = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "edital", "titulo": "Fantasma", "origem_uid": 1, "ref": "NAO_EXISTE"
        })
        assert r.status_code == 404

    def test_publicar_tipo_invalido_400(self, client):
        token = _admin_token()
        r = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "xyz", "titulo": "X", "origem_uid": 1, "ref": ""
        })
        assert r.status_code == 400

    def test_publicar_non_admin_403(self, client):
        _criar_estudante(50, "est50@test.com")
        token = _token(50, "est50@test.com")
        r = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "edital", "titulo": "X", "origem_uid": 1, "ref": "PF 2026"
        })
        assert r.status_code == 403


class TestListar:
    def test_listar_catalogo(self, client):
        _seed_curador(1)
        token = _admin_token()
        client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "deck_flashcards", "titulo": "Deck Direito", "categoria": "Geral",
            "origem_uid": 1, "ref": "Direito"
        })
        # Estudante lista
        _criar_estudante(51, "est51@test.com")
        r = client.get("/api/catalogo", headers=_h(_token(51, "est51@test.com")))
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        titulos = [i["titulo"] for i in data["itens"]]
        assert "Deck Direito" in titulos

    def test_filtrar_por_tipo(self, client):
        token = _admin_token()
        r = client.get("/api/catalogo?tipo=deck_flashcards", headers=_h(token))
        assert r.status_code == 200
        assert all(i["tipo"] == "deck_flashcards" for i in r.json()["itens"])


class TestImportar:
    def test_importar_deck_flashcards(self, client):
        _seed_curador(1)
        token = _admin_token()
        pub = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "deck_flashcards", "titulo": "Deck FC", "origem_uid": 1, "ref": "Direito"
        }).json()
        item_id = pub["id"]

        _criar_estudante(60, "est60@test.com")
        est_token = _token(60, "est60@test.com")
        r = client.post(f"/api/catalogo/{item_id}/importar", headers=_h(est_token))
        assert r.status_code == 200
        assert r.json()["importados"] >= 2  # 2 flashcards de Direito

        # Verificar que o estudante agora tem os flashcards
        conn = _conn()
        n = conn.execute("SELECT COUNT(*) FROM flashcards WHERE user_id = 60").fetchone()[0]
        conn.close()
        assert n >= 2

    def test_importar_incrementa_downloads(self, client):
        _seed_curador(1)
        token = _admin_token()
        pub = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "deck_questoes", "titulo": "Q Direito", "origem_uid": 1, "ref": "Direito"
        }).json()
        item_id = pub["id"]
        _criar_estudante(61, "est61@test.com")
        client.post(f"/api/catalogo/{item_id}/importar", headers=_h(_token(61, "est61@test.com")))
        # Verificar downloads
        conn = _conn()
        dl = conn.execute("SELECT downloads FROM catalogo_itens WHERE id = ?", (item_id,)).fetchone()[0]
        conn.close()
        assert dl >= 1

    def test_importar_edital_completo(self, client):
        _seed_curador(1)
        token = _admin_token()
        pub = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "edital", "titulo": "Edital PF", "origem_uid": 1, "ref": "PF 2026"
        }).json()
        _criar_estudante(62, "est62@test.com")
        r = client.post(f"/api/catalogo/{pub['id']}/importar", headers=_h(_token(62, "est62@test.com")))
        assert r.status_code == 200
        assert r.json()["importados"] >= 1
        conn = _conn()
        n = conn.execute("SELECT COUNT(*) FROM edital WHERE user_id = 62 AND edital_nome = 'PF 2026'").fetchone()[0]
        conn.close()
        assert n >= 1

    def test_importar_item_inexistente_404(self, client):
        _criar_estudante(63, "est63@test.com")
        r = client.post("/api/catalogo/99999/importar", headers=_h(_token(63, "est63@test.com")))
        assert r.status_code == 404


class TestRemover:
    def test_remover_admin_desativa(self, client):
        _seed_curador(1)
        token = _admin_token()
        pub = client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "deck_sumulas", "titulo": "Súmulas STF", "origem_uid": 1, "ref": ""
        })
        # deck_sumulas requer súmulas — pode retornar 404 se não houver; então criamos uma
        if pub.status_code == 404:
            conn = _conn()
            conn.execute("INSERT INTO sumulas (tribunal, numero, enunciado, proxima_revisao, user_id) VALUES ('STF', 1, 'E', '2026-01-01', 1)")
            conn.commit()
            conn.close()
            pub = client.post("/api/catalogo/publicar", headers=_h(token), json={
                "tipo": "deck_sumulas", "titulo": "Súmulas STF", "origem_uid": 1, "ref": ""
            })
        item_id = pub.json()["id"]
        r = client.delete(f"/api/catalogo/{item_id}", headers=_h(token))
        assert r.status_code == 200
        # Não deve mais aparecer na listagem pública
        lst = client.get("/api/catalogo", headers=_h(token)).json()
        assert item_id not in [i["id"] for i in lst["itens"]]

    def test_remover_non_admin_403(self, client):
        _criar_estudante(64, "est64@test.com")
        r = client.delete("/api/catalogo/1", headers=_h(_token(64, "est64@test.com")))
        assert r.status_code == 403


class TestAvaliacoes:
    def _publicar(self, client):
        _seed_curador(1)
        token = _admin_token()
        return client.post("/api/catalogo/publicar", headers=_h(token), json={
            "tipo": "deck_flashcards", "titulo": "Deck Aval", "origem_uid": 1, "ref": "Direito"
        }).json()["id"]

    def test_avaliar_e_media(self, client):
        item_id = self._publicar(client)
        _criar_estudante(70, "est70@test.com")
        _criar_estudante(71, "est71@test.com")
        r1 = client.post(f"/api/catalogo/{item_id}/avaliar", headers=_h(_token(70, "est70@test.com")), json={"nota": 5, "comentario": "Ótimo!"})
        assert r1.status_code == 200
        r2 = client.post(f"/api/catalogo/{item_id}/avaliar", headers=_h(_token(71, "est71@test.com")), json={"nota": 3})
        assert r2.status_code == 200
        # Média deve ser 4.0
        assert abs(r2.json()["media_estrelas"] - 4.0) < 0.01
        assert r2.json()["total_avaliacoes"] == 2

    def test_avaliar_upsert(self, client):
        item_id = self._publicar(client)
        _criar_estudante(72, "est72@test.com")
        tok = _token(72, "est72@test.com")
        client.post(f"/api/catalogo/{item_id}/avaliar", headers=_h(tok), json={"nota": 1})
        r = client.post(f"/api/catalogo/{item_id}/avaliar", headers=_h(tok), json={"nota": 5})
        # Upsert: continua 1 avaliação, nota atualizada
        assert r.json()["total_avaliacoes"] == 1
        assert abs(r.json()["media_estrelas"] - 5.0) < 0.01

    def test_avaliar_nota_invalida_400(self, client):
        item_id = self._publicar(client)
        _criar_estudante(73, "est73@test.com")
        r = client.post(f"/api/catalogo/{item_id}/avaliar", headers=_h(_token(73, "est73@test.com")), json={"nota": 9})
        assert r.status_code == 400

    def test_nao_avaliar_proprio(self, client):
        item_id = self._publicar(client)  # curador = admin (id 1)
        r = client.post(f"/api/catalogo/{item_id}/avaliar", headers=_h(_admin_token()), json={"nota": 5})
        assert r.status_code == 400

    def test_listar_avaliacoes(self, client):
        item_id = self._publicar(client)
        _criar_estudante(74, "est74@test.com")
        client.post(f"/api/catalogo/{item_id}/avaliar", headers=_h(_token(74, "est74@test.com")), json={"nota": 4, "comentario": "Bom"})
        r = client.get(f"/api/catalogo/{item_id}/avaliacoes", headers=_h(_token(74, "est74@test.com")))
        assert r.status_code == 200
        assert r.json()["total_avaliacoes"] >= 1
        assert r.json()["minha_avaliacao"]["nota"] == 4


class TestPublicacaoPremium:
    def _criar_premium(self, uid, email):
        conn = _conn()
        conn.execute("""
            INSERT OR IGNORE INTO users (id, nome, username, email, password_hash, plano, role, created_at)
            VALUES (?, ?, ?, ?, 'hash', 'premium', 'user', '2026-01-01')
        """, (uid, f"Premium {uid}", f"prem{uid}", email))
        # Dar um recurso para publicar
        conn.execute("INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id) VALUES ('P', 'R', '2026-01-01', 'MatPrem', ?)", (uid,))
        conn.commit()
        conn.close()

    def test_premium_publica_pendente(self, client):
        self._criar_premium(80, "prem80@test.com")
        tok = _token(80, "prem80@test.com")
        r = client.post("/api/catalogo/publicar", headers=_h(tok), json={
            "tipo": "deck_flashcards", "titulo": "Meu Deck", "origem_uid": 0, "ref": "MatPrem"
        })
        assert r.status_code == 200
        assert r.json()["status"] == "pendente"
        # Não deve aparecer na listagem pública (só aprovados)
        lst = client.get("/api/catalogo", headers=_h(tok)).json()
        assert "Meu Deck" not in [i["titulo"] for i in lst["itens"]]

    def test_free_nao_publica_403(self, client):
        _criar_estudante(81, "est81@test.com")  # free
        r = client.post("/api/catalogo/publicar", headers=_h(_token(81, "est81@test.com")), json={
            "tipo": "deck_flashcards", "titulo": "X", "origem_uid": 0, "ref": "Y"
        })
        assert r.status_code == 403

    def test_premium_verificado_publica_aprovado(self, client):
        self._criar_premium(82, "prem82@test.com")
        # Admin verifica o curador
        client.post("/api/catalogo/curador/82/verificar", headers=_h(_admin_token()), json={"verificado": True})
        tok = _token(82, "prem82@test.com")
        r = client.post("/api/catalogo/publicar", headers=_h(tok), json={
            "tipo": "deck_flashcards", "titulo": "Deck Verificado", "origem_uid": 0, "ref": "MatPrem"
        })
        assert r.status_code == 200
        assert r.json()["status"] == "aprovado"

    def test_meus_materiais(self, client):
        self._criar_premium(83, "prem83@test.com")
        tok = _token(83, "prem83@test.com")
        client.post("/api/catalogo/publicar", headers=_h(tok), json={
            "tipo": "deck_flashcards", "titulo": "Meu Material", "origem_uid": 0, "ref": "MatPrem"
        })
        r = client.get("/api/catalogo/meus", headers=_h(tok))
        assert r.status_code == 200
        assert "Meu Material" in [i["titulo"] for i in r.json()["itens"]]


class TestModeracao:
    def test_verificar_curador(self, client):
        _criar_estudante(90, "est90@test.com")
        r = client.post("/api/catalogo/curador/90/verificar", headers=_h(_admin_token()), json={"verificado": True})
        assert r.status_code == 200
        assert r.json()["curador_verificado"] is True

    def test_verificar_non_admin_403(self, client):
        _criar_estudante(91, "est91@test.com")
        r = client.post("/api/catalogo/curador/1/verificar", headers=_h(_token(91, "est91@test.com")), json={"verificado": True})
        assert r.status_code == 403

    def test_moderar_aprovar(self, client):
        # Premium publica pendente
        conn = _conn()
        conn.execute("INSERT OR IGNORE INTO users (id, nome, username, email, password_hash, plano, role, created_at) VALUES (92, 'P92', 'p92', 'p92@t.com', 'h', 'premium', 'user', '2026-01-01')")
        conn.execute("INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, resposta_correta, created_at, user_id) VALUES ('ModMat', 'T', 'Q', 'a','b','c','d','', 'A', '2026-01-01', 92)")
        conn.commit(); conn.close()
        pub = client.post("/api/catalogo/publicar", headers=_h(_token(92, "p92@t.com")), json={
            "tipo": "deck_questoes", "titulo": "Pendente Q", "origem_uid": 0, "ref": "ModMat"
        }).json()
        item_id = pub["id"]
        # Aparece em pendentes
        pend = client.get("/api/catalogo/admin/pendentes", headers=_h(_admin_token())).json()
        assert item_id in [i["id"] for i in pend["itens"]]
        # Admin aprova
        r = client.post(f"/api/catalogo/{item_id}/moderar", headers=_h(_admin_token()), json={"acao": "aprovar"})
        assert r.status_code == 200
        # Agora aparece na listagem pública
        lst = client.get("/api/catalogo", headers=_h(_admin_token())).json()
        assert "Pendente Q" in [i["titulo"] for i in lst["itens"]]

    def test_moderar_acao_invalida_400(self, client):
        _seed_curador(1)
        pub = client.post("/api/catalogo/publicar", headers=_h(_admin_token()), json={
            "tipo": "deck_flashcards", "titulo": "X", "origem_uid": 1, "ref": "Direito"
        }).json()
        r = client.post(f"/api/catalogo/{pub['id']}/moderar", headers=_h(_admin_token()), json={"acao": "xyz"})
        assert r.status_code == 400


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
