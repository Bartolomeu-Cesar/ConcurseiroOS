"""Endpoints CRUD de batalha: criar, entrar, reconfigurar, minhas, sala."""
import json
import random
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log
from sanitize import sanitize_input
from schemas import CriarBatalhaRequest, EntrarBatalhaRequest, ReconfigurarBatalhaRequest

from .helpers import (
    _ensure_battle_tables,
    _generate_code,
    _is_battle_admin,
    _round_difficulty,
    _calcular_tempo_questao_batalha,
)

router = APIRouter(prefix="/api/batalha", tags=["Batalha de Questões"])


@router.post("/criar", summary="Criar sala de batalha",
             description="Cria uma nova sala de batalha multiplayer. O criador entra automaticamente. Configurações: matérias, rodadas (3-20), tempo por questão (10-120s) e max jogadores (2-5). Limites variam por plano.",
             responses={403: {"description": "Batalha não disponível no plano do usuário"}})
def criar_batalha(
    body: CriarBatalhaRequest,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """
    Cria uma nova sala de batalha.
    Body: {titulo, materias: ["Dir. Penal", "Dir. Const."], total_rodadas: 5-20, tempo_por_questao: 15-60, max_jogadores: 2-5}
    Limites por plano: Guest=sem acesso, Free=3 jogadores/5 rodadas, Premium/Vitalício=5 jogadores/20 rodadas.
    """
    _ensure_battle_tables(conn)

    # Verificar plano do usuário
    from plans import get_limits, check_feature, PLANS, get_plan
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    user_dict = dict(user) if user else {}
    limites = get_limits(user_dict)

    if not limites.get("batalha", False):
        plano = get_plan(user_dict)
        raise HTTPException(status_code=403, detail=f"Batalha não disponível no plano {PLANS[plano]['nome']}. Faça upgrade!")

    plan_max_jogadores = limites.get("batalha_max_jogadores", 5)
    plan_max_rodadas = limites.get("batalha_max_rodadas", 20)

    titulo = sanitize_input(body.titulo)
    materias = [sanitize_input(m) for m in body.materias]
    total_rodadas = max(3, min(plan_max_rodadas, body.total_rodadas))
    tempo_por_questao = max(10, min(120, body.tempo_por_questao))
    max_jogadores = max(2, min(plan_max_jogadores, body.max_jogadores))

    codigo = _generate_code()
    # Garantir unicidade
    while conn.execute("SELECT id FROM battles WHERE codigo = ?", (codigo,)).fetchone():
        codigo = _generate_code()

    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO battles (codigo, criador_id, titulo, materias, total_rodadas, tempo_por_questao, max_jogadores, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'aguardando', ?)
    """, (codigo, user_id, titulo, json.dumps(materias), total_rodadas, tempo_por_questao, max_jogadores, now))

    battle_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Criador entra automaticamente
    user = conn.execute("SELECT nome, avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    nome = user["nome"] if user else "Jogador 1"
    avatar = user["avatar"] if user else ""
    conn.execute(
        "INSERT INTO battle_players (battle_id, user_id, nome, avatar, joined_at) VALUES (?, ?, ?, ?, ?)",
        (battle_id, user_id, nome, avatar, now)
    )
    conn.commit()

    log.info(f"[batalha] Sala criada: {codigo} por user={user_id} ({total_rodadas} rodadas, materias={materias})")

    # Verificar quantas questões estão disponíveis para aviso prévio
    if materias:
        placeholders = ",".join("?" * len(materias))
        qtd_disponivel = conn.execute(
            f"SELECT COUNT(*) FROM questoes WHERE materia IN ({placeholders}) AND user_id = ? AND resposta_correta != '' AND resposta_correta IS NOT NULL",
            (*materias, user_id)
        ).fetchone()[0]
    else:
        qtd_disponivel = conn.execute(
            "SELECT COUNT(*) FROM questoes WHERE user_id = ? AND resposta_correta != '' AND resposta_correta IS NOT NULL",
            (user_id,)
        ).fetchone()[0]

    aviso = ""
    if qtd_disponivel == 0:
        aviso = "⚠️ Nenhuma questão disponível para as matérias selecionadas. Adicione questões antes de iniciar."
    elif qtd_disponivel < total_rodadas:
        aviso = f"⚠️ Apenas {qtd_disponivel} questões disponíveis (configurado para {total_rodadas} rodadas). Questões poderão repetir."

    return {
        "id": battle_id,
        "codigo": codigo,
        "titulo": titulo,
        "materias": materias,
        "total_rodadas": total_rodadas,
        "tempo_por_questao": tempo_por_questao,
        "max_jogadores": max_jogadores,
        "status": "aguardando",
        "questoes_disponiveis": qtd_disponivel,
        "aviso": aviso,
    }


@router.post("/entrar", summary="Entrar em sala de batalha",
             description="Entra em uma sala existente pelo código de 6 caracteres. Limite de jogadores definido na criação.",
             responses={400: {"description": "Código inválido"}, 404: {"description": "Sala não encontrada"}, 409: {"description": "Sala cheia ou jogador já presente"}})
def entrar_batalha(
    body: EntrarBatalhaRequest,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Entra em uma sala pelo código."""
    _ensure_battle_tables(conn)
    codigo = body.codigo.strip().upper()
    if not codigo:
        raise HTTPException(status_code=400, detail="Código da sala é obrigatório.")

    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo,)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada. Verifique o código.")

    if battle["status"] != "aguardando":
        raise HTTPException(status_code=400, detail="Esta batalha já começou ou foi finalizada.")

    # Check if already in
    existing = conn.execute(
        "SELECT id FROM battle_players WHERE battle_id = ? AND user_id = ?", (battle["id"], user_id)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Você já está nesta sala.")

    # Check max players
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM battle_players WHERE battle_id = ?", (battle["id"],)
    ).fetchone()["cnt"]
    if count >= battle["max_jogadores"]:
        raise HTTPException(status_code=400, detail=f"Sala cheia ({count}/{battle['max_jogadores']}).")

    user = conn.execute("SELECT nome, avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    nome = (sanitize_input(body.nome) if body.nome else None) or (user["nome"] if user else f"Jogador {count + 1}")
    avatar = user["avatar"] if user else ""

    conn.execute(
        "INSERT INTO battle_players (battle_id, user_id, nome, avatar, joined_at) VALUES (?, ?, ?, ?, ?)",
        (battle["id"], user_id, nome, avatar, datetime.now().isoformat())
    )
    conn.commit()

    log.info(f"[batalha] {nome} entrou na sala {codigo}")
    return {"message": f"Bem-vindo à batalha!", "battle_id": battle["id"], "codigo": codigo}


@router.get("/sala/{codigo}", summary="Status da sala",
            description="Retorna estado completo da sala: jogadores, rodada atual, questão ativa e configurações.",
            responses={404: {"description": "Sala não encontrada"}})
def status_sala(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna status completo da sala (jogadores, rodada atual, etc.)."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    players = conn.execute(
        "SELECT user_id, nome, avatar, pontos, acertos, erros, tempo_total_seg, posicao FROM battle_players WHERE battle_id = ? ORDER BY pontos DESC",
        (battle["id"],)
    ).fetchall()

    # Rodada atual
    current_round = None
    if battle["status"] == "em_andamento" and battle["rodada_atual"] > 0:
        round_data = conn.execute(
            "SELECT * FROM battle_rounds WHERE battle_id = ? AND rodada_num = ?",
            (battle["id"], battle["rodada_atual"])
        ).fetchone()
        if round_data:
            # Quem já respondeu nesta rodada (NÃO revelar se acertou até todos responderem)
            answers = conn.execute(
                "SELECT user_id, acertou, tempo_seg, pontos_ganhos FROM battle_answers WHERE battle_id = ? AND rodada_num = ?",
                (battle["id"], battle["rodada_atual"])
            ).fetchall()
            total_players_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM battle_players WHERE battle_id = ?", (battle["id"],)
            ).fetchone()["cnt"]
            all_answered = len(answers) >= total_players_count

            # Randomizar alternativas para anti-cola (seed baseado em user_id + rodada)
            alts_original = json.loads(round_data["alternativas"])
            alt_items = [(k, v) for k, v in alts_original.items() if v]  # Filtrar vazias
            # Shuffle com seed determinístico por usuário (para que o mesmo user veja a mesma ordem ao recarregar)
            rng = random.Random(user_id * 1000 + battle["rodada_atual"])
            rng.shuffle(alt_items)
            # Criar mapeamento: posição visual → letra real
            visual_letters = ['a', 'b', 'c', 'd', 'e'][:len(alt_items)]
            alternativas_shuffled = {}
            mapping = {}  # visual_letter → real_letter
            for i, (real_letter, text) in enumerate(alt_items):
                vl = visual_letters[i]
                alternativas_shuffled[vl] = text
                mapping[vl] = real_letter

            current_round = {
                "rodada_num": round_data["rodada_num"],
                "materia": round_data["materia"],
                "topico": round_data["topico"],
                "enunciado": round_data["enunciado"],
                "alternativas": alternativas_shuffled,
                "_mapping": mapping,  # Para o frontend traduzir ao responder
                "dificuldade": _round_difficulty(round_data["rodada_num"], battle["total_rodadas"]),
                "tempo_segundos": _calcular_tempo_questao_batalha(
                    round_data["enunciado"], len(alt_items), battle["tempo_por_questao"],
                    alternativas=[{"texto": t} for _, t in alt_items],
                    dificuldade=_round_difficulty(round_data["rodada_num"], battle["total_rodadas"])["nivel"],
                ),
                # Só revelar acertos depois que todos responderam
                "responderam": [
                    {"user_id": a["user_id"], "respondeu": True,
                     "acertou": bool(a["acertou"]) if all_answered else None,
                     "tempo_seg": a["tempo_seg"] if all_answered else None,
                     "pontos": a["pontos_ganhos"] if all_answered else None}
                    for a in answers
                ],
                "total_responderam": len(answers),
                "todos_responderam": all_answered,
            }

    return {
        "id": battle["id"],
        "codigo": battle["codigo"],
        "titulo": battle["titulo"],
        "materias": json.loads(battle["materias"]),
        "total_rodadas": battle["total_rodadas"],
        "rodada_atual": battle["rodada_atual"],
        "status": battle["status"],
        "tempo_por_questao": battle["tempo_por_questao"],
        "max_jogadores": battle["max_jogadores"],
        "criador_id": battle["criador_id"],
        "coautores": json.loads(battle["coautores"] if "coautores" in battle.keys() else "[]"),
        "jogadores": [dict(p) for p in players],
        "rodada": current_round,
    }


@router.post("/reconfigurar/{codigo}", summary="Reconfigurar batalha")
def reconfigurar_batalha(
    codigo: str,
    body: ReconfigurarBatalhaRequest = None,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """
    Reseta a batalha para 'aguardando' e permite alterar configurações.
    Apenas o criador pode reconfigurar. Remove rodadas já geradas.
    Body opcional: {materias, total_rodadas, tempo_por_questao, max_jogadores}
    """
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    if not _is_battle_admin(battle, user_id):
        raise HTTPException(status_code=403, detail="Apenas o criador ou coautor pode reconfigurar.")

    if battle["status"] == "finalizada":
        raise HTTPException(status_code=400, detail="Batalha finalizada não pode ser reconfigurada. Crie uma revanche.")

    # Atualizar configurações se fornecidas
    if body is None:
        body = ReconfigurarBatalhaRequest()
    materias = [sanitize_input(m) for m in body.materias] if body.materias is not None else json.loads(battle["materias"])
    total_rodadas = body.total_rodadas if body.total_rodadas is not None else battle["total_rodadas"]
    tempo_por_questao = body.tempo_por_questao if body.tempo_por_questao is not None else battle["tempo_por_questao"]
    max_jogadores = body.max_jogadores if body.max_jogadores is not None else battle["max_jogadores"]

    # Limpar rodadas geradas (reset)
    conn.execute("DELETE FROM battle_rounds WHERE battle_id = ?", (battle["id"],))
    conn.execute("DELETE FROM battle_answers WHERE battle_id = ?", (battle["id"],))

    # Resetar status para aguardando
    conn.execute("""
        UPDATE battles SET status = 'aguardando', rodada_atual = 0,
            materias = ?, total_rodadas = ?, tempo_por_questao = ?, max_jogadores = ?
        WHERE id = ?
    """, (json.dumps(materias), total_rodadas, tempo_por_questao, max_jogadores, battle["id"]))
    conn.commit()

    # Contar questões disponíveis
    if materias:
        placeholders = ",".join("?" * len(materias))
        qtd = conn.execute(
            f"SELECT COUNT(*) FROM questoes WHERE materia IN ({placeholders}) AND user_id = ? AND resposta_correta != '' AND resposta_correta IS NOT NULL",
            (*materias, user_id)
        ).fetchone()[0]
    else:
        qtd = conn.execute(
            "SELECT COUNT(*) FROM questoes WHERE user_id = ? AND resposta_correta != '' AND resposta_correta IS NOT NULL",
            (user_id,)
        ).fetchone()[0]

    log.info(f"[batalha] Sala {codigo} reconfigurada por user={user_id}")
    return {
        "ok": True,
        "codigo": codigo,
        "materias": materias,
        "total_rodadas": total_rodadas,
        "tempo_por_questao": tempo_por_questao,
        "max_jogadores": max_jogadores,
        "questoes_disponiveis": qtd,
        "message": f"Batalha reconfigurada. {qtd} questões disponíveis.",
    }


@router.get("/minhas", summary="Minhas batalhas",
            description="Lista todas as batalhas que o usuário participou, ordenadas por data de criação.")
def minhas_batalhas(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista batalhas que o usuário participou."""
    _ensure_battle_tables(conn)
    rows = conn.execute("""
        SELECT b.id, b.codigo, b.titulo, b.status, b.total_rodadas, b.created_at,
               bp.pontos, bp.posicao, bp.acertos, bp.erros
        FROM battles b
        JOIN battle_players bp ON bp.battle_id = b.id AND bp.user_id = ?
        ORDER BY b.created_at DESC
        LIMIT 20
    """, (user_id,)).fetchall()

    return [dict(r) for r in rows]
