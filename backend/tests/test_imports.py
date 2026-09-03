"""
Testes dos endpoints de importação do ConcurseiroOS.
Executar: pytest tests/test_imports.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_imports.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session
import settings as settings_mod

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app


def _override_db_session():
    """Override para garantir que FastAPI use o DB temporário deste módulo."""
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session


@pytest.fixture(scope="module")
def client():
    """TestClient compartilhado por todo o módulo de testes."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db_imports():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


class TestImports:
    def test_importar_edital_json(self, client):
        import json
        content = json.dumps([
            {"edital_nome": "Import Test", "cargo": "Analista", "materia": "Dir. Admin", "topico": "Atos administrativos"},
            {"edital_nome": "Import Test", "cargo": "Analista", "materia": "Dir. Admin", "topico": "Licitações"}
        ])
        r = client.post("/api/edital/importar", files={"file": ("edital.json", content, "application/json")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_edital_csv(self, client):
        csv_content = "edital_nome,cargo,materia,topico,status,horas_estudadas\nCSV Test,Tecnico,Portugues,Crase,Não Iniciado,0\n"
        r = client.post("/api/edital/importar", files={"file": ("edital.csv", csv_content, "text/csv")})
        assert r.status_code == 200
        assert r.json()["importados"] == 1

    def test_importar_ciclo_json(self, client):
        import json
        content = json.dumps([
            {"materia": "Matemática", "horas_alvo": 3.0},
            {"materia": "Português", "horas_alvo": 2.5}
        ])
        r = client.post("/api/ciclo/importar", files={"file": ("ciclo.json", content, "application/json")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_flashcards_json(self, client):
        import json
        content = json.dumps([
            {"pergunta": "O que é CPU?", "resposta": "Unidade Central de Processamento"},
            {"pergunta": "O que é RAM?", "resposta": "Memória de Acesso Aleatório"}
        ])
        r = client.post("/api/flashcards/importar", files={"file": ("flash.json", content, "application/json")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_flashcards_anki(self, client):
        anki_content = "O que é SSD?\tDisco de Estado Sólido\nO que é HDD?\tDisco Rígido\n"
        r = client.post("/api/flashcards/importar", files={"file": ("cards.txt", anki_content, "text/plain")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_flashcards_csv(self, client):
        csv_content = "pergunta,resposta\nO que é GPU?,Unidade de Processamento Gráfico\n"
        r = client.post("/api/flashcards/importar", files={"file": ("flash.csv", csv_content, "text/csv")})
        assert r.status_code == 200
        assert r.json()["importados"] == 1

    def test_importar_flashcards_csv_ponto_e_virgula(self, client):
        # CSV estilo Excel pt-BR: separador ';', campos entre aspas,
        # cabeçalho com inicial maiúscula e 3ª coluna de disciplina.
        csv_content = (
            '"Pergunta";"Resposta";"📚 Disciplina (Edital)"\n'
            '"Capital do MA?";"São Luís";"Geografia do Maranhão"\n'
            '"Ano da adesão do MA à independência?";"1823";"História do Maranhão"\n'
        )
        r = client.post(
            "/api/flashcards/importar",
            files={"file": ("historia e geografia do maranhao.csv", csv_content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_flashcards_csv_vincula_materia(self, client):
        # A coluna de disciplina deve virar a matéria do flashcard.
        csv_content = (
            'Pergunta;Resposta;Disciplina\n'
            'Pergunta A;Resposta A;Geografia do Maranhão\n'
        )
        r = client.post(
            "/api/flashcards/importar",
            files={"file": ("cards.csv", csv_content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["importados"] == 1
        materias = client.get("/api/flashcards/materias").json()
        assert any(m["materia"] == "Geografia do Maranhão" for m in materias)

    def test_importar_flashcards_csv_com_bom(self, client):
        # Arquivo salvo pelo Excel costuma vir com BOM UTF-8 no início.
        csv_content = "\ufeffpergunta,resposta\nQ1,R1\n"
        r = client.post(
            "/api/flashcards/importar",
            files={"file": ("bom.csv", csv_content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["importados"] == 1

    def test_importar_flashcards_dedup_segundo_import(self, client):
        """Reimportar o mesmo arquivo não deve duplicar: 2º import ignora tudo."""
        csv_content = (
            "pergunta,resposta\n"
            "Dedup Q1 unica,Dedup R1\n"
            "Dedup Q2 unica,Dedup R2\n"
        )
        r1 = client.post("/api/flashcards/importar", files={"file": ("dedup.csv", csv_content, "text/csv")})
        assert r1.status_code == 200
        assert r1.json()["importados"] == 2
        assert r1.json()["duplicados_ignorados"] == 0

        r2 = client.post("/api/flashcards/importar", files={"file": ("dedup.csv", csv_content, "text/csv")})
        assert r2.status_code == 200
        assert r2.json()["importados"] == 0
        assert r2.json()["duplicados_ignorados"] == 2

    def test_importar_flashcards_dedup_intra_arquivo(self, client):
        """Linhas repetidas dentro do mesmo arquivo são inseridas apenas uma vez."""
        csv_content = (
            "pergunta,resposta\n"
            "Intra Q unica,Intra R\n"
            "Intra Q unica,Intra R\n"
            "Intra Q unica,Intra R\n"
        )
        r = client.post("/api/flashcards/importar", files={"file": ("intra.csv", csv_content, "text/csv")})
        assert r.status_code == 200
        assert r.json()["importados"] == 1
        assert r.json()["duplicados_ignorados"] == 2

    def test_importar_flashcards_dedup_normalizado(self, client):
        """Diferenças de caixa/espaços não criam duplicata (comparação normalizada)."""
        r1 = client.post(
            "/api/flashcards/importar",
            files={"file": ("n1.csv", "pergunta,resposta\nNorm Question,Norm Answer\n", "text/csv")},
        )
        assert r1.json()["importados"] == 1
        # Mesma pergunta/resposta com caixa e espaços diferentes
        r2 = client.post(
            "/api/flashcards/importar",
            files={"file": ("n2.csv", "pergunta,resposta\n  norm   QUESTION ,  NORM answer\n", "text/csv")},
        )
        assert r2.json()["importados"] == 0
        assert r2.json()["duplicados_ignorados"] == 1


# ============================================================
# IMPORTAÇÃO .apkg (Anki)
# ============================================================

def _gerar_apkg(notas, decks=None, deck_por_nota=None, db_name="collection.anki2"):
    """Gera um .apkg mínimo em memória (ZIP com SQLite estilo Anki).

    - notas: lista de (nid, flds) onde flds são os campos já unidos por \x1f.
    - decks: dict {deck_id(int): nome(str)} para a coluna col.decks (JSON).
    - deck_por_nota: dict {nid: deck_id} para a tabela cards.
    - db_name: nome do arquivo interno ('collection.anki2' ou 'collection.anki21').
    Retorna os bytes do .apkg.
    """
    import io
    import json
    import os
    import sqlite3
    import tempfile
    import zipfile

    decks = decks or {}
    deck_por_nota = deck_por_nota or {}

    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    try:
        con = sqlite3.connect(tmp.name)
        con.execute("CREATE TABLE col (id INTEGER PRIMARY KEY, decks TEXT NOT NULL)")
        decks_json = {str(did): {"name": nome} for did, nome in decks.items()}
        con.execute("INSERT INTO col (id, decks) VALUES (1, ?)", (json.dumps(decks_json),))
        con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT NOT NULL)")
        for nid, flds in notas:
            con.execute("INSERT INTO notes (id, flds) VALUES (?, ?)", (nid, flds))
        con.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER)")
        cid = 1
        for nid, did in deck_por_nota.items():
            con.execute("INSERT INTO cards (id, nid, did) VALUES (?, ?, ?)", (cid, nid, did))
            cid += 1
        con.commit()
        con.close()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            with open(tmp.name, "rb") as f:
                zf.writestr(db_name, f.read())
            zf.writestr("media", "{}")
        return buf.getvalue()
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


SEP = "\x1f"


def _gerar_apkg_modelos(notas, models, decks=None, deck_por_nota=None, db_name="collection.anki2"):
    """Gera um .apkg com tabela col.models e notes.mid (formato Anki completo).

    - notas: lista de (nid, mid, flds) — flds já unidos por \x1f.
    - models: dict {mid(int): {"name","type","sortf","flds":[nomes...]}}.
    - decks / deck_por_nota / db_name: como em _gerar_apkg.
    """
    import io
    import json
    import os
    import sqlite3
    import tempfile
    import zipfile

    decks = decks or {}
    deck_por_nota = deck_por_nota or {}

    models_json = {}
    for mid, m in models.items():
        models_json[str(mid)] = {
            "name": m.get("name", "Basic"),
            "type": m.get("type", 0),
            "sortf": m.get("sortf", 0),
            "flds": [{"name": nome, "ord": i} for i, nome in enumerate(m.get("flds", ["Front", "Back"]))],
            "tmpls": [{"name": "Card 1", "ord": 0, "qfmt": "", "afmt": ""}],
        }

    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    try:
        con = sqlite3.connect(tmp.name)
        con.execute("CREATE TABLE col (id INTEGER PRIMARY KEY, decks TEXT NOT NULL, models TEXT NOT NULL)")
        decks_json = {str(did): {"name": nome} for did, nome in decks.items()}
        con.execute(
            "INSERT INTO col (id, decks, models) VALUES (1, ?, ?)",
            (json.dumps(decks_json), json.dumps(models_json)),
        )
        con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, mid INTEGER NOT NULL, flds TEXT NOT NULL)")
        for nid, mid, flds in notas:
            con.execute("INSERT INTO notes (id, mid, flds) VALUES (?, ?, ?)", (nid, mid, flds))
        con.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER)")
        cid = 1
        for nid, did in deck_por_nota.items():
            con.execute("INSERT INTO cards (id, nid, did) VALUES (?, ?, ?)", (cid, nid, did))
            cid += 1
        con.commit()
        con.close()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            with open(tmp.name, "rb") as f:
                zf.writestr(db_name, f.read())
            zf.writestr("media", "{}")
        return buf.getvalue()
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)


class TestImportApkg:
    def test_importar_apkg_basico(self, client):
        """Importa um .apkg com 2 notas (frente/verso separados por 0x1f)."""
        apkg = _gerar_apkg(
            notas=[
                (1001, f"O que é HTTP?{SEP}HyperText Transfer Protocol"),
                (1002, f"O que é DNS?{SEP}Domain Name System"),
            ],
            decks={1700000000000: "Redes"},
            deck_por_nota={1001: 1700000000000, 1002: 1700000000000},
        )
        r = client.post("/api/flashcards/importar", files={"file": ("deck.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 2

    def test_importar_apkg_usa_deck_como_materia(self, client):
        """O nome do deck vira a matéria; sub-deck usa o último segmento."""
        apkg = _gerar_apkg(
            notas=[(2001, f"Capital do Maranhão?{SEP}São Luís")],
            decks={555: "Concurso::Geografia do Maranhão"},
            deck_por_nota={2001: 555},
        )
        r = client.post("/api/flashcards/importar", files={"file": ("geo.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 1
        conn = sqlite3.connect(_tmp_db.name)
        materia = conn.execute(
            "SELECT materia FROM flashcards WHERE pergunta = 'Capital do Maranhão?' AND user_id = 1"
        ).fetchone()[0]
        conn.close()
        assert materia == "Geografia do Maranhão"

    def test_importar_apkg_limpa_html(self, client):
        """Campos HTML do Anki (<br>, tags, entidades, [sound:]) são limpos."""
        apkg = _gerar_apkg(
            notas=[(3001, f"Linha 1<br>Linha 2 &amp; fim[sound:a.mp3]{SEP}<div>Resposta</div> &nbsp;ok")],
            decks={1: "Default"},
            deck_por_nota={3001: 1},
        )
        r = client.post("/api/flashcards/importar", files={"file": ("html.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 1
        conn = sqlite3.connect(_tmp_db.name)
        row = conn.execute(
            "SELECT pergunta, resposta, materia FROM flashcards WHERE pergunta LIKE 'Linha 1%' AND user_id = 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "Linha 1\nLinha 2 & fim"  # <br>->\n, &amp;->&, [sound:] removido
        assert "Resposta" in row[1] and "<div>" not in row[1]
        # Deck "Default" não é usado como matéria
        assert row[2] == ""

    def test_importar_apkg_schema_anki21(self, client):
        """Também aceita o schema novo 'collection.anki21' (SQLite puro)."""
        apkg = _gerar_apkg(
            notas=[(4001, f"2+2?{SEP}4")],
            decks={9: "Matemática"},
            deck_por_nota={4001: 9},
            db_name="collection.anki21",
        )
        r = client.post("/api/flashcards/importar", files={"file": ("m.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 1

    def test_importar_apkg_zip_invalido_400(self, client):
        """Arquivo .apkg que não é um ZIP válido → 400 com mensagem clara."""
        r = client.post(
            "/api/flashcards/importar",
            files={"file": ("bad.apkg", b"isto nao e um zip", "application/octet-stream")},
        )
        assert r.status_code == 400
        assert "apkg" in r.json()["detail"].lower() or "zip" in r.json()["detail"].lower()

    def test_importar_apkg_zstd_corrompido_400(self, client):
        """.apkg com 'collection.anki21b' de dados Zstandard inválidos → 400.

        Com a lib 'zstandard' instalada, a descompressão falha e retorna erro
        claro. Sem a lib, retorna 400 orientando instalar/exportar legacy.
        Ambos os caminhos resultam em 400."""
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("collection.anki21b", b"\x28\xb5\x2f\xfd" + b"lixo invalido")  # zstd magic + dados corrompidos
            zf.writestr("media", "{}")
        r = client.post(
            "/api/flashcards/importar",
            files={"file": ("novo.apkg", buf.getvalue(), "application/octet-stream")},
        )
        assert r.status_code == 400
        detail = r.json()["detail"].lower()
        # Aceita tanto a mensagem de lib ausente quanto a de falha na descompressão
        assert any(t in detail for t in ("zstandard", "legacy", "texto simples", "descomprimir", "corrompido"))


class TestImportApkgFormatoReal:
    """Cobre o conteúdo/formato real dos decks do Anki (baseado nos .apkg reais):
    collection.db, modelos com campos variados e notas Cloze."""

    def test_importar_apkg_collection_db(self, client):
        """Aceita coleção nomeada 'collection.db' (genanki e similares)."""
        apkg = _gerar_apkg(
            notas=[(7001, f"O que é fato?{SEP}Informação verificável")],
            decks={42: "Língua Portuguesa"},
            deck_por_nota={7001: 42},
            db_name="collection.db",
        )
        r = client.post("/api/flashcards/importar", files={"file": ("lp.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 1
        conn = sqlite3.connect(_tmp_db.name)
        materia = conn.execute(
            "SELECT materia FROM flashcards WHERE pergunta = 'O que é fato?' AND user_id = 1"
        ).fetchone()[0]
        conn.close()
        assert materia == "Língua Portuguesa"

    def test_importar_apkg_campos_front_back(self, client):
        """Modelo com campos 'Front'/'Back' (via col.models)."""
        apkg = _gerar_apkg_modelos(
            notas=[(8001, 1000, f"What is RAM?{SEP}Random Access Memory")],
            models={1000: {"name": "Basic", "type": 0, "sortf": 0, "flds": ["Front", "Back"]}},
            decks={7: "Informática"},
            deck_por_nota={8001: 7},
        )
        r = client.post("/api/flashcards/importar", files={"file": ("fb.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 1
        conn = sqlite3.connect(_tmp_db.name)
        row = conn.execute(
            "SELECT resposta FROM flashcards WHERE pergunta = 'What is RAM?' AND user_id = 1"
        ).fetchone()
        conn.close()
        assert row[0] == "Random Access Memory"

    def test_importar_apkg_campos_pergunta_resposta(self, client):
        """Modelo 'Básico (Pergunta/Resposta)' com nomes de campos em pt-BR."""
        apkg = _gerar_apkg_modelos(
            notas=[(8101, 1010, f"Capital da França?{SEP}Paris")],
            models={1010: {"name": "Básico (Pergunta/Resposta)", "type": 0, "sortf": 0,
                           "flds": ["Pergunta", "Resposta"]}},
            decks={8: "Geografia"},
            deck_por_nota={8101: 8},
        )
        r = client.post("/api/flashcards/importar", files={"file": ("pr.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        conn = sqlite3.connect(_tmp_db.name)
        row = conn.execute(
            "SELECT resposta FROM flashcards WHERE pergunta = 'Capital da França?' AND user_id = 1"
        ).fetchone()
        conn.close()
        assert row is not None and row[0] == "Paris"

    def test_importar_apkg_cloze(self, client):
        """Nota Cloze (modelo type=1): {{c1::resposta}} vira pergunta com lacuna + resposta."""
        texto = "O maior rio do mundo é o {{c1::Amazonas}}."
        apkg = _gerar_apkg_modelos(
            notas=[(9001, 2000, f"{texto}{SEP}")],
            models={2000: {"name": "Cloze", "type": 1, "sortf": 0, "flds": ["Text", "Extra"]}},
            decks={9: "Cloze Geografia Mundial"},
            deck_por_nota={9001: 9},
        )
        r = client.post("/api/flashcards/importar", files={"file": ("cloze.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 1
        conn = sqlite3.connect(_tmp_db.name)
        row = conn.execute(
            "SELECT pergunta, resposta FROM flashcards WHERE materia = 'Cloze Geografia Mundial' AND user_id = 1"
        ).fetchone()
        conn.close()
        assert row is not None, "card cloze não foi importado corretamente"
        assert "[...]" in row[0]  # lacuna na pergunta
        assert "Amazonas" not in row[0]  # a resposta não aparece na pergunta
        assert row[1] == "Amazonas"

    def test_importar_apkg_cloze_com_dica(self, client):
        """Cloze com dica {{c1::resp::dica}} usa a dica como rótulo da lacuna."""
        texto = "O protocolo seguro da web é o {{c1::HTTPS::sigla}}."
        apkg = _gerar_apkg_modelos(
            notas=[(9101, 2010, f"{texto}{SEP}")],
            models={2010: {"name": "Cloze", "type": 1, "sortf": 0, "flds": ["Text", "Extra"]}},
            decks={11: "Informática"},
            deck_por_nota={9101: 11},
        )
        r = client.post("/api/flashcards/importar", files={"file": ("clozed.apkg", apkg, "application/octet-stream")})
        assert r.status_code == 200, r.text
        conn = sqlite3.connect(_tmp_db.name)
        row = conn.execute(
            "SELECT pergunta, resposta FROM flashcards WHERE resposta = 'HTTPS' AND user_id = 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert "[sigla]" in row[0]
        assert row[1] == "HTTPS"

    def test_importar_apkg_moderno_zstd(self, client):
        """Formato moderno do Anki: collection.anki21b comprimido com Zstandard.

        Requer a lib opcional 'zstandard'; se ausente, o teste é pulado
        (o endpoint retorna 400 orientando a instalar/exportar legacy)."""
        import io
        import json
        import os
        import sqlite3 as _sq
        import tempfile
        import zipfile

        zstd = pytest.importorskip("zstandard")

        # Monta um SQLite estilo Anki e comprime com zstd
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            con = _sq.connect(tmp.name)
            con.execute("CREATE TABLE col (id INTEGER PRIMARY KEY, decks TEXT, models TEXT)")
            models = {"3000": {"name": "Basic", "type": 0, "sortf": 0,
                               "flds": [{"name": "Front", "ord": 0}, {"name": "Back", "ord": 1}]}}
            decks = {"12": {"name": "Concurso Moderno"}}
            con.execute("INSERT INTO col VALUES (1, ?, ?)", (json.dumps(decks), json.dumps(models)))
            con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, mid INTEGER, flds TEXT)")
            con.execute("INSERT INTO notes VALUES (1, 3000, ?)", (f"O que é zstd?{SEP}Algoritmo de compressão",))
            con.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER)")
            con.execute("INSERT INTO cards VALUES (1, 1, 12)")
            con.commit()
            con.close()
            with open(tmp.name, "rb") as f:
                sqlite_bytes = f.read()
        finally:
            if os.path.exists(tmp.name):
                os.remove(tmp.name)

        comprimido = zstd.ZstdCompressor().compress(sqlite_bytes)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("collection.anki21b", comprimido)
            zf.writestr("media", "{}")

        r = client.post("/api/flashcards/importar", files={"file": ("moderno.apkg", buf.getvalue(), "application/octet-stream")})
        assert r.status_code == 200, r.text
        assert r.json()["importados"] == 1
        conn = sqlite3.connect(_tmp_db.name)
        row = conn.execute(
            "SELECT resposta, materia FROM flashcards WHERE pergunta = 'O que é zstd?' AND user_id = 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "Algoritmo de compressão"
        assert row[1] == "Concurso Moderno"
