"""Módulo de ordenação inteligente baseado em técnicas de estudo com evidência científica.

Técnicas aplicadas (6 estratégias validadas por décadas de pesquisa cognitiva):
1. Spaced Practice — SRS (FSRS/SM-2) controla QUANDO revisar
2. Interleaving — Round-robin entre matérias/temas (evita blocked practice)
3. Desirable Difficulty — Mistura níveis (2 difíceis + 1 fácil)
4. Retrieval Practice — Reforço imediato de itens esquecidos
5. Successive Relearning — Re-teste de itens recém-aprendidos (consolidação)
6. Pre-testing Effect — Itens novos antes dos dominados (erro produtivo)

Fontes:
- Dunlosky et al. (2013) "Improving Students' Learning"
- Bjork & Bjork (2011) "Desirable Difficulties"
- Rawson & Dunlosky (2022) "Successive Relearning"
- Pan & Carpenter (2023) "Prequestioning and Pretesting Effects"
- Rohrer (2012) "Interleaving helps students distinguish among similar concepts"

Uso:
    from study_ordering import order_items_intelligently
    ordered = order_items_intelligently(items, key_config)
"""

import random
from collections import defaultdict
from typing import Any


def order_items_intelligently(
    items: list[dict],
    *,
    materia_key: str = "materia",
    reps_key: str = "repetitions",
    interval_key: str = "intervalo_dias",
    ef_key: str = "easiness_factor",
    stability_key: str = "stability",
    importance_fn: callable | None = None,
) -> list[dict]:
    """Ordena itens de estudo aplicando todas as técnicas baseadas em evidência.

    Args:
        items: Lista de dicts com dados do item (flashcard, súmula, questão)
        materia_key: Chave para agrupamento de interleaving
        reps_key: Chave para número de repetições
        interval_key: Chave para intervalo em dias
        ef_key: Chave para easiness factor
        stability_key: Chave para estabilidade FSRS
        importance_fn: Função opcional (item) -> float para peso de importância

    Returns:
        Lista reordenada aplicando as 6 técnicas
    """
    if not items or len(items) <= 1:
        return items

    # === ETAPA 1: Classificar em faixas cognitivas ===
    faixa_pretesting = []  # Itens NOVOS (nunca revisados) — Pre-testing Effect
    faixa_reforco = []     # Esqueceu/errou — Retrieval Practice imediato
    faixa_relearning = []  # Acertou recente mas frágil — Successive Relearning
    faixa_dificeis = []    # EF baixo, estabilidade baixa — Desirable Difficulty
    faixa_regulares = []   # Manutenção — prática distribuída

    for item in items:
        reps = item.get(reps_key) or 0
        intervalo = item.get(interval_key) or 1
        ef = item.get(ef_key) or 2.5
        stability = item.get(stability_key) or 0

        if reps == 0 and intervalo <= 1:
            # Nunca revisou com sucesso → Pre-testing (item novo)
            faixa_pretesting.append(item)
        elif intervalo <= 1 and reps > 0:
            # Já tentou mas errou (reset) → Reforço imediato
            faixa_reforco.append(item)
        elif reps <= 2 and ef < 2.5:
            # Acertou 1-2x mas com dificuldade → Successive Relearning
            faixa_relearning.append(item)
        elif ef < 2.1 or (stability > 0 and stability < 3.0):
            # Difícil / instável → Desirable Difficulty (desafio)
            faixa_dificeis.append(item)
        else:
            # Regular → manutenção espaçada
            faixa_regulares.append(item)

    # === ETAPA 2: Randomizar dentro de cada faixa ===
    random.shuffle(faixa_pretesting)
    random.shuffle(faixa_reforco)
    random.shuffle(faixa_relearning)
    random.shuffle(faixa_dificeis)
    random.shuffle(faixa_regulares)

    # === ETAPA 3: Aplicar importância (ROI) se fornecida ===
    if importance_fn:
        for faixa in [faixa_pretesting, faixa_reforco, faixa_relearning, faixa_dificeis, faixa_regulares]:
            faixa.sort(key=lambda x: importance_fn(x), reverse=True)

    # === ETAPA 4: Montar sequência com Desirable Difficulty + Pre-testing ===
    # Padrão baseado em evidência:
    # 1. Pre-testing: itens novos primeiro (gera "erro produtivo" → atenção elevada)
    # 2. Reforço: itens que errou (recuperação imediata consolida)
    # 3. Successive Relearning: frágeis recentes (verifica consolidação)
    # 4. Mix de difíceis + regulares no padrão 2:1 (desirable difficulty)
    ordered = []

    # Pre-testing primeiro (máx 20% do total para não sobrecarregar)
    max_pretest = max(1, len(items) // 5)
    ordered.extend(faixa_pretesting[:max_pretest])
    overflow_pretest = faixa_pretesting[max_pretest:]

    # Reforço imediato
    ordered.extend(faixa_reforco)

    # Successive Relearning
    ordered.extend(faixa_relearning)

    # Desirable Difficulty: 2 difíceis + 1 regular
    todos_dificeis = faixa_dificeis + overflow_pretest
    d_idx, r_idx = 0, 0
    while d_idx < len(todos_dificeis) or r_idx < len(faixa_regulares):
        for _ in range(2):
            if d_idx < len(todos_dificeis):
                ordered.append(todos_dificeis[d_idx])
                d_idx += 1
        if r_idx < len(faixa_regulares):
            ordered.append(faixa_regulares[r_idx])
            r_idx += 1

    # === ETAPA 5: Interleaving por matéria ===
    result = _interleave(ordered, materia_key)

    # === ETAPA 6: Expanding Retrieval intra-sessão ===
    # Inserir itens de reforço novamente mais adiante na sessão (micro-spacing)
    result = _apply_expanding_retrieval(result, faixa_reforco)

    return result


def _interleave(items: list[dict], key: str) -> list[dict]:
    """Interleaving: round-robin entre grupos para evitar blocked practice.

    Evidência: Rohrer (2012) — Interleaving melhora discriminação entre
    conceitos similares e retenção em 20-40%.
    """
    if len(items) <= 2:
        return items

    buckets = defaultdict(list)
    for item in items:
        group = item.get(key) or "geral"
        buckets[group].append(item)

    if len(buckets) <= 1:
        return items

    result = []
    bucket_keys = list(buckets.keys())
    random.shuffle(bucket_keys)

    key_idx = 0
    total = len(items)
    while len(result) < total:
        attempts = 0
        while attempts < len(bucket_keys):
            k = bucket_keys[key_idx % len(bucket_keys)]
            key_idx += 1
            if buckets[k]:
                result.append(buckets[k].pop(0))
                break
            attempts += 1
        else:
            break

    return result


def _apply_expanding_retrieval(items: list[dict], reforco_items: list[dict]) -> list[dict]:
    """Expanding Retrieval: re-insere itens de reforço mais adiante na sessão.

    Evidência: Karpicke & Roediger (2007) — Expanding spacing intra-sessão
    (testar imediatamente, depois novamente após 5+ itens) melhora retenção
    comparado com testar apenas uma vez.

    Limita a 3 itens de re-exposição para não inflacionar a sessão.
    """
    if not reforco_items or len(items) < 8:
        return items

    # Re-inserir até 3 itens de reforço em posições mais avançadas
    # (spacing de ~5-8 itens depois da primeira aparição)
    items_to_repeat = reforco_items[:3]
    result = list(items)

    for i, item in enumerate(items_to_repeat):
        # Encontrar posição original
        try:
            original_pos = result.index(item)
        except ValueError:
            continue

        # Inserir cópia marcada 5-8 posições depois
        insert_pos = original_pos + random.randint(5, 8)
        if insert_pos < len(result):
            # Marcar como re-exposição (frontend pode mostrar diferente)
            repeated = dict(item)
            repeated["_expanding_retrieval"] = True
            result.insert(insert_pos, repeated)

    return result
