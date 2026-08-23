from __future__ import annotations

from math import comb
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
