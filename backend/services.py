"""Service layer — queries reutilizáveis para evitar duplicação nos routers.

Funções centralizadas para os padrões de consulta mais comuns:
- Acertos por matéria (questões)
- Dias até a prova
- Horas estudadas
"""
import re
from datetime import date, timedelta


def get_acertos_por_materia(conn, user_id: int, data_inicio: str = None) -> list[dict]:
    """Query unificada: acertos/erros por matéria.

    Retorna lista de dicts com: materia, total, acertos, pct
    Opcionalmente filtra por data_inicio (inclusive).
    """
    if data_inicio:
        rows = conn.execute("""
            SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND qr.data >= ?
            GROUP BY q.materia
        """, (user_id, data_inicio)).fetchall()
    else:
        rows = conn.execute("""
            SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ?
            GROUP BY q.materia
        """, (user_id,)).fetchall()

    result = []
    for r in rows:
        total = r[1] or 0
        acertos = r[2] or 0
        pct = round((acertos / total * 100), 1) if total > 0 else 0
        result.append({
            "materia": r[0],
            "total": total,
            "acertos": acertos,
            "pct": pct,
        })
    return result


def get_dias_ate_prova(conn, user_id: int) -> int | None:
    """Calcula dias restantes até a próxima prova futura do usuário.

    Busca em edital_info a data_prova_objetiva mais próxima que ainda não passou.
    Retorna None se não houver prova cadastrada ou todas já passaram.
    """
    rows = conn.execute("""
        SELECT data_prova_objetiva FROM edital_info
        WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?
    """, (user_id,)).fetchall()

    hoje = date.today()
    menor_dias = None

    for row in rows:
        data_str = row[0]
        parts = re.match(r'(\d+)[/\-](\d+)[/\-](\d+)', data_str)
        if not parts:
            continue
        try:
            if len(parts.group(3)) == 4:
                # dd/mm/yyyy
                d = date(int(parts.group(3)), int(parts.group(2)), int(parts.group(1)))
            else:
                # yyyy-mm-dd
                d = date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
            dias = (d - hoje).days
            if dias > 0 and (menor_dias is None or dias < menor_dias):
                menor_dias = dias
        except (ValueError, TypeError):
            continue

    return menor_dias


def get_horas_estudadas(conn, user_id: int, periodo_dias: int = None) -> float:
    """Total de horas estudadas (opcionalmente nos últimos N dias).

    Se periodo_dias for None, retorna o total geral.
    """
    if periodo_dias is not None:
        data_inicio = (date.today() - timedelta(days=periodo_dias)).isoformat()
        row = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND user_id = ?",
            (data_inicio, user_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    return float(row[0])
