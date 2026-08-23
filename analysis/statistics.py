from __future__ import annotations

from math import comb, erf, sqrt
import random


def paired_mean_difference(a_values: list[float], b_values: list[float]) -> float:
    if len(a_values) != len(b_values):
        raise ValueError("paired samples must have the same length")
    if not a_values:
        raise ValueError("paired samples must not be empty")
    differences = [a - b for a, b in zip(a_values, b_values)]
    return sum(differences) / len(differences)


def bootstrap_mean_ci(values: list[float], *, seed: int = 20260823, iterations: int = 200) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap requires at least one value")
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sample = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(sum(sample) / len(sample))
    estimates.sort()
    lower_index = max(0, int(iterations * 0.025) - 1)
    upper_index = min(iterations - 1, int(iterations * 0.975))
    return estimates[lower_index], estimates[upper_index]


def paired_sign_test(a_values: list[float], b_values: list[float]) -> float:
    if len(a_values) != len(b_values):
        raise ValueError("paired samples must have the same length")
    positive = 0
    negative = 0
    for a_value, b_value in zip(a_values, b_values):
        if a_value > b_value:
            positive += 1
        elif a_value < b_value:
            negative += 1
    n = positive + negative
    if n == 0:
        return 1.0
    tail = min(positive, negative)
    cumulative = sum(comb(n, k) for k in range(0, tail + 1)) / (2 ** n)
    return min(1.0, 2 * cumulative)


def holm_bonferroni(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    m = len(ordered)
    for index, (name, p_value) in enumerate(ordered):
        adjusted[name] = min(1.0, p_value * (m - index))
    return adjusted


def wilcoxon_signed_rank(differences: list[float]) -> dict[str, float]:
    non_zero = [(index, abs(value), 1 if value > 0 else -1) for index, value in enumerate(differences) if abs(value) > 1e-12]
    if not non_zero:
        return {
            "p_value": 1.0,
            "w_positive": 0.0,
            "w_negative": 0.0,
            "rank_biserial_correlation": 0.0,
            "non_zero_pairs": 0,
        }

    ranked: list[tuple[float, int]] = []
    position = 1
    cursor = 0
    ordered = sorted(non_zero, key=lambda item: item[1])
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and abs(ordered[end][1] - ordered[cursor][1]) <= 1e-12:
            end += 1
        average_rank = (position + (position + (end - cursor) - 1)) / 2
        for _, _, sign in ordered[cursor:end]:
            ranked.append((average_rank, sign))
        position += end - cursor
        cursor = end

    w_positive = sum(rank for rank, sign in ranked if sign > 0)
    w_negative = sum(rank for rank, sign in ranked if sign < 0)
    total_rank = w_positive + w_negative
    test_statistic = min(w_positive, w_negative)

    if len(ranked) <= 25:
        distribution = {0.0: 1}
        for rank, _ in ranked:
            next_distribution: dict[float, int] = {}
            for subtotal, count in distribution.items():
                next_distribution[subtotal] = next_distribution.get(subtotal, 0) + count
                with_rank = subtotal + rank
                next_distribution[with_rank] = next_distribution.get(with_rank, 0) + count
            distribution = next_distribution
        total_assignments = 2 ** len(ranked)
        tail_probability = sum(
            count for subtotal, count in distribution.items()
            if subtotal <= test_statistic + 1e-12 or subtotal >= (total_rank - test_statistic) - 1e-12
        ) / total_assignments
        p_value = min(1.0, tail_probability)
    else:
        n = len(ranked)
        mean_w = n * (n + 1) / 4
        variance_w = n * (n + 1) * (2 * n + 1) / 24
        z_score = (abs(w_positive - mean_w) - 0.5) / sqrt(variance_w)
        normal_cdf = 0.5 * (1 + erf(z_score / sqrt(2)))
        p_value = min(1.0, max(0.0, 2 * (1 - normal_cdf)))
    return {
        "p_value": p_value,
        "w_positive": w_positive,
        "w_negative": w_negative,
        "rank_biserial_correlation": (w_positive - w_negative) / total_rank if total_rank else 0.0,
        "non_zero_pairs": len(ranked),
    }
