"""
Testes do tempo de referência por complexidade dos flashcards
(calcular_tempo_flashcard) e da exposição de `tempo_segundos` no payload de
/api/flashcards/today, usado pelo timer regressivo da revisão (análogo ao das
questões).

Executar: pytest tests/test_tempo_flashcard.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import calcular_tempo_flashcard as calc
from utils import detalhar_tempo_flashcard as detalhar

# ---------------------------------------------------------------------------
# Unitários da função de tempo
# ---------------------------------------------------------------------------

def test_respeita_faixa_minima_e_maxima():
    """Card minúsculo cai no piso; card gigante cai no teto (10s–180s)."""
    t_min = calc("a", "b", 2)
    assert t_min == 10
    grande = " ".join(["palavra"] * 500)
    t_max = calc(grande, grande, 0)
    assert t_max == 180


def test_texto_maior_aumenta_o_tempo():
    """Perguntas/respostas mais longas devem elevar o tempo."""
    curto = calc("O que é habeas corpus?", "Remédio constitucional.", 2)
    longo = calc(
        " ".join(["conceito"] * 30),
        " ".join(["explicacao"] * 30),
        2,
    )
    assert longo > curto


def test_fator_fsrs_relearning_maior_que_review():
    """Card em relearning (3) exige mais tempo que um maduro em review (2)."""
    p = " ".join(["palavra"] * 15)
    r = " ".join(["resposta"] * 15)
    t_review = calc(p, r, 2)
    t_relearning = calc(p, r, 3)
    t_novo = calc(p, r, 0)
    assert t_relearning > t_review
    assert t_novo > t_review


def test_fsrs_state_none_nao_quebra():
    """fsrs_state None (schemas antigos) usa fallback sem erro."""
    t = calc("pergunta media aqui", "resposta media aqui", None)
    assert 10 <= t <= 180


def test_recuperacao_escala_com_densidade_da_resposta():
    """Filosofia do desafio (tempo proporcional ao conteúdo): respostas mais
    densas exigem mais recuperação ativa, mesmo com pergunta idêntica."""
    pergunta = "Explique o conceito."
    resp_curta = " ".join(["palavra"] * 3)
    resp_media = " ".join(["palavra"] * 18)
    resp_densa = " ".join(["palavra"] * 60)
    t_curta = calc(pergunta, resp_curta, 2)
    t_media = calc(pergunta, resp_media, 2)
    t_densa = calc(pergunta, resp_densa, 2)
    assert t_curta < t_media < t_densa, (t_curta, t_media, t_densa)


def test_resposta_curta_nao_fica_no_plato_antigo():
    """Regressão do 'sempre ~18s': cards com resposta curta devem ficar BEM
    abaixo do platô fixo antigo (que somava 8s fixos de recuperação)."""
    # Pergunta e resposta curtas, card maduro → deve ser rápido (< 15s).
    t = calc("Prazo do MS?", "120 dias.", 2)
    assert t < 15, t
    assert t >= 10  # respeita o piso


def test_nao_e_constante_para_conteudos_diferentes():
    """Não deve colapsar em um valor único: variar o conteúdo varia o tempo."""
    amostras = {
        calc("P curta?", "R.", 2),
        calc("Pergunta média de tamanho normal aqui?", " ".join(["x"] * 20), 0),
        calc(" ".join(["q"] * 30), " ".join(["a"] * 50), 3),
    }
    assert len(amostras) >= 3, f"tempos colapsaram: {amostras}"


def test_dificuldade_fsrs_aumenta_o_tempo():
    """Complexidade REAL (FSRS difficulty D) eleva o tempo, mesmo com texto igual.

    Este é o cerne da melhoria: um card curto porém DIFÍCIL (D alto) deve exigir
    mais tempo de recall que um card curto e fácil (D baixo), coisa que o cálculo
    baseado só em contagem de palavras não capturava.
    """
    p = "Qual o prazo e o fundamento?"
    r = " ".join(["conceito"] * 14)
    facil = calc(p, r, 2, difficulty=1)
    dificil = calc(p, r, 2, difficulty=10)
    assert dificil > facil, (facil, dificil)


def test_lapses_aumentam_o_tempo():
    """Cards já esquecidos várias vezes (lapses altos) tomam mais tempo de recall."""
    p = "Defina o instituto."
    r = " ".join(["conceito"] * 12)
    sem_lapse = calc(p, r, 2, difficulty=5, lapses=0)
    com_lapses = calc(p, r, 2, difficulty=5, lapses=5)
    assert com_lapses > sem_lapse, (sem_lapse, com_lapses)


def test_lapses_tem_teto():
    """O bônus por lapses satura (+40%), não cresce indefinidamente."""
    p = "P?"
    r = " ".join(["x"] * 10)
    t5 = calc(p, r, 2, difficulty=5, lapses=5)
    t50 = calc(p, r, 2, difficulty=5, lapses=50)
    assert t5 == t50, (t5, t50)


def test_detalhar_retorna_total_e_motivos_coerentes():
    """detalhar_tempo_flashcard: total bate com calc(); motivos citam os fatores
    que pesaram; card neutro (maduro, D baixo, sem lapses) não lista motivos."""
    p = "Enuncie o princípio da legalidade."
    r = " ".join(["conceito"] * 14)
    det = detalhar(p, r, 2, difficulty=9.0, lapses=2)
    assert det["tempo_segundos"] == calc(p, r, 2, difficulty=9.0, lapses=2)
    joined = " ".join(det["motivos"]).lower()
    assert "difícil" in joined
    assert "recaída" in joined or "recaídas" in joined
    # Neutro: maduro (estado ×1.0), sem dificuldade nem lapses → sem motivos.
    det_neutro = detalhar(p, r, 2, difficulty=0, lapses=0)
    assert det_neutro["motivos"] == []


def test_difficulty_ausente_mantem_compatibilidade():
    """Sem difficulty/lapses (chamadores antigos), o resultado é o mesmo de quando
    esses fatores são neutros (=1.0)."""
    p = "Pergunta de tamanho médio para teste."
    r = " ".join(["palavra"] * 15)
    base = calc(p, r, 2)
    com_neutro = calc(p, r, 2, difficulty=0, lapses=0)
    assert base == com_neutro


def test_card_curto_dificil_supera_card_curto_facil_via_payload(client):
    """Integração: dois cards com MESMO texto curto, mas difficulty diferente,
    devem receber tempo_segundos diferentes no payload de /today."""
    from utils import today_str

    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM flashcards WHERE 1=1")
    conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state, difficulty, lapses, user_id) "
        "VALUES ('Prazo?', '5 dias.', ?, 1, 2.5, 3, 'Facil', 2, 1.5, 0, 1)",
        (today_str(),),
    )
    conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state, difficulty, lapses, user_id) "
        "VALUES ('Prazo?', '5 dias.', ?, 1, 2.5, 3, 'Dificil', 2, 9.5, 4, 1)",
        (today_str(),),
    )
    conn.commit()
    conn.close()

    cards = client.get("/api/flashcards/today").json()
    by_mat = {c["materia"]: c["tempo_segundos"] for c in cards}
    assert "Facil" in by_mat and "Dificil" in by_mat
    assert by_mat["Dificil"] > by_mat["Facil"], by_mat


def test_today_expoe_tempo_detalhe_com_motivos(client):
    """O payload de /today deve trazer `tempo_detalhe` com `motivos` para o badge
    de transparência. Card difícil e com recaídas deve listar esses fatores."""
    from utils import today_str

    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM flashcards WHERE 1=1")
    conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state, difficulty, lapses, user_id) "
        "VALUES ('Enuncie o princípio.', 'Resposta razoavelmente densa com varios conceitos aqui.', ?, 1, 2.5, 3, 'DConst', 2, 9.0, 3, 1)",
        (today_str(),),
    )
    conn.commit()
    conn.close()

    cards = client.get("/api/flashcards/today").json()
    assert len(cards) >= 1
    card = cards[0]
    assert "tempo_detalhe" in card, "payload precisa expor tempo_detalhe para o badge"
    det = card["tempo_detalhe"]
    assert det["tempo_segundos"] == card["tempo_segundos"]
    assert isinstance(det.get("motivos"), list)
    # Card difícil (D=9) e com 3 recaídas → deve listar ambos os fatores.
    joined = " ".join(det["motivos"]).lower()
    assert "difícil" in joined or "×" in joined, det["motivos"]
    assert "recaída" in joined, det["motivos"]


# ---------------------------------------------------------------------------
# Integração: payload de /api/flashcards/today contém tempo_segundos
# ---------------------------------------------------------------------------

_tmp_db = tempfile.NamedTemporaryFile(suffix="_tempo_flashcard.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name

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


def test_today_expoe_tempo_segundos(client):
    """Cada card retornado por /api/flashcards/today deve ter tempo_segundos válido."""
    from utils import today_str

    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM flashcards WHERE 1=1")
    # Card pendente (proxima_revisao <= hoje)
    conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state, user_id) "
        "VALUES ('O que e mandado de seguranca?', 'Remedio constitucional para direito liquido e certo.', ?, 1, 2.5, 0, 'Direito Constitucional', 0, 1)",
        (today_str(),),
    )
    conn.commit()
    conn.close()

    cards = client.get("/api/flashcards/today").json()
    assert len(cards) >= 1
    for c in cards:
        assert "tempo_segundos" in c, "payload do flashcard precisa expor tempo_segundos"
        assert isinstance(c["tempo_segundos"], int)
        assert 10 <= c["tempo_segundos"] <= 180


def test_aleatorio_expoe_tempo_segundos(client):
    """A sessão por disciplina/aleatória (/api/flashcards/aleatorio) também deve
    expor tempo_segundos, para o timer não cair no fallback fixo (~20s)."""
    from utils import today_str

    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM flashcards WHERE 1=1")
    conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state, user_id) "
        "VALUES ('P?', 'Resposta curta.', ?, 1, 2.5, 0, 'Geral', 2, 1)",
        (today_str(),),
    )
    conn.commit()
    conn.close()

    cards = client.get("/api/flashcards/aleatorio?quantidade=5").json()
    assert len(cards) >= 1
    for c in cards:
        assert "tempo_segundos" in c, "aleatorio precisa expor tempo_segundos"
        assert 10 <= c["tempo_segundos"] <= 180
        assert "fsrs_state" not in c  # campo interno removido do payload


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass
