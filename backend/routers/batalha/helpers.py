"""Funções auxiliares compartilhadas do módulo Batalha de Questões."""
import json
import random


def _ensure_battle_tables(conn):
    """Cria tabelas de batalha se não existirem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            criador_id INTEGER NOT NULL,
            coautores TEXT DEFAULT '[]',
            titulo TEXT DEFAULT 'Batalha de Questões',
            materias TEXT DEFAULT '[]',
            total_rodadas INTEGER DEFAULT 5,
            rodada_atual INTEGER DEFAULT 0,
            status TEXT DEFAULT 'aguardando',
            tempo_por_questao INTEGER DEFAULT 30,
            max_jogadores INTEGER DEFAULT 5,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battle_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT 'Jogador',
            avatar TEXT DEFAULT '',
            pontos INTEGER DEFAULT 0,
            acertos INTEGER DEFAULT 0,
            erros INTEGER DEFAULT 0,
            tempo_total_seg INTEGER DEFAULT 0,
            posicao INTEGER DEFAULT 0,
            joined_at TEXT NOT NULL,
            FOREIGN KEY (battle_id) REFERENCES battles(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battle_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            rodada_num INTEGER NOT NULL,
            questao_id INTEGER,
            materia TEXT DEFAULT '',
            topico TEXT DEFAULT '',
            enunciado TEXT NOT NULL,
            alternativas TEXT NOT NULL,
            resposta_correta TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (battle_id) REFERENCES battles(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battle_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            rodada_num INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            resposta TEXT DEFAULT '',
            acertou INTEGER DEFAULT 0,
            tempo_seg INTEGER DEFAULT 0,
            pontos_ganhos INTEGER DEFAULT 0,
            answered_at TEXT NOT NULL,
            FOREIGN KEY (battle_id) REFERENCES battles(id)
        )
    """)
    # Migration: add coautores column if missing
    try:
        conn.execute("SELECT coautores FROM battles LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE battles ADD COLUMN coautores TEXT DEFAULT '[]'")
        except Exception:
            pass
    conn.commit()


def _generate_code():
    """Gera código de sala de 6 caracteres."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(chars, k=6))


def _is_battle_admin(battle, user_id: int) -> bool:
    """Verifica se o usuário é criador ou coautor da batalha."""
    if battle["criador_id"] == user_id:
        return True
    try:
        coautores = json.loads(battle["coautores"] if "coautores" in battle.keys() else "[]")
        return user_id in coautores
    except (json.JSONDecodeError, TypeError):
        return False


def _round_difficulty(rodada_num: int, total_rodadas: int) -> dict:
    """Retorna indicador de dificuldade baseado na posição da rodada."""
    terco = max(1, total_rodadas // 3)
    if rodada_num <= terco:
        return {"nivel": "Fácil", "emoji": "🟢", "cor": "#a6e3a1"}
    elif rodada_num <= terco * 2:
        return {"nivel": "Médio", "emoji": "🟡", "cor": "#f9e2af"}
    else:
        return {"nivel": "Difícil", "emoji": "🔴", "cor": "#f38ba8"}


def _calculate_points(acertou: bool, tempo_seg: int, tempo_max: int, streak: int = 0) -> int:
    """Calcula pontos: acerto + bonus velocidade + streak. Após o tempo, perde pontos progressivamente."""
    if not acertou:
        return 0
    # Base: 100 pontos por acerto
    base = 100

    if tempo_seg <= tempo_max:
        # Respondeu dentro do tempo: bonus por velocidade (até 50 pontos extras)
        speed_bonus = int(50 * (1 - tempo_seg / tempo_max)) if tempo_max > 0 else 0
        subtotal = base + speed_bonus
    else:
        # Respondeu após o tempo: penalidade progressiva (perde 10% por segundo extra)
        excesso = tempo_seg - tempo_max
        penalidade = min(0.9, excesso * 0.1)  # Máximo 90% de penalidade
        subtotal = max(10, int(base * (1 - penalidade)))  # Mínimo 10 pontos

    # Streak multiplier: 1.5x após 3 acertos, 2x após 5 acertos
    if streak >= 5:
        subtotal = int(subtotal * 2.0)
    elif streak >= 3:
        subtotal = int(subtotal * 1.5)
    return subtotal


def _calcular_tempo_questao_batalha(enunciado: str, num_alternativas: int, tempo_config: int) -> int:
    """Calcula tempo adaptativo para questão de batalha.

    Usa a mesma fórmula baseada em evidência (Brysbaert 2019: 200 wpm),
    mas garante que o tempo nunca seja inferior ao configurado pelo criador
    da sala (tempo_config).

    Retorna o MAIOR entre: tempo calculado pela complexidade e tempo_config.
    Isso garante que questões longas tenham tempo justo sem reduzir
    o tempo que o criador definiu para questões curtas.
    """
    palavras = len(enunciado.split()) if enunciado else 10
    tempo_leitura = (palavras / 200) * 60  # segundos para ler
    tempo_alternativas = num_alternativas * 3  # 3s por alternativa
    tempo_decisao = 5
    tempo_calculado = int(tempo_leitura + tempo_alternativas + tempo_decisao)
    tempo_calculado = max(20, min(120, tempo_calculado))  # clamp 20-120s para batalha
    # Usar o MAIOR entre o configurado e o calculado
    return max(tempo_config, tempo_calculado)
