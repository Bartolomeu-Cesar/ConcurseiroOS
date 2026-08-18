from datetime import date, timedelta
from pathlib import Path
from pypdf import PdfReader


def today_str():
    return date.today().isoformat()


def get_pdf_pages(filepath: str) -> int:
    try:
        return len(PdfReader(filepath).pages)
    except Exception:
        return 1


def build_tree(root: str) -> list:
    result = []
    root_path = Path(root).resolve()
    for entry in sorted(Path(root).iterdir()):
        if entry.is_dir():
            children = build_tree(str(entry))
            if children:
                result.append({"type": "folder", "name": entry.name, "children": children})
        elif entry.suffix.lower() == ".pdf" and ":" not in entry.name:
            rel = str(entry.resolve().relative_to(root_path))
            result.append({"type": "pdf", "name": entry.name, "path": rel})
    return result


def calculate_streak(conn) -> dict:
    """Calcula streak atual e melhor streak histórico."""
    rows = conn.execute(
        "SELECT data FROM streaks WHERE horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0 ORDER BY data DESC"
    ).fetchall()

    streak = 0
    check_date = date.today()
    for row in rows:
        if row[0] == check_date.isoformat():
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    # Melhor streak histórico
    all_dates = [row[0] for row in rows]
    best_streak = 0
    current_best = 0
    if all_dates:
        sorted_dates = sorted(set(all_dates))
        current_best = 1
        for i in range(1, len(sorted_dates)):
            d1 = date.fromisoformat(sorted_dates[i - 1])
            d2 = date.fromisoformat(sorted_dates[i])
            if (d2 - d1).days == 1:
                current_best += 1
            else:
                best_streak = max(best_streak, current_best)
                current_best = 1
        best_streak = max(best_streak, current_best)

    return {"streak_atual": streak, "melhor_streak": best_streak}
