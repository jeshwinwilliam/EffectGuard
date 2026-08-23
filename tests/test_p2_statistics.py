from __future__ import annotations

from analysis.statistics import bootstrap_mean_ci, holm_bonferroni, paired_mean_difference, paired_sign_test, wilcoxon_signed_rank


def test_paired_mean_difference_uses_paired_deltas() -> None:
    assert paired_mean_difference([5.0, 7.0, 11.0], [3.0, 6.0, 5.0]) == 3.0


def test_bootstrap_mean_ci_is_deterministic_for_seed() -> None:
    first = bootstrap_mean_ci([1.0, 2.0, 3.0, 4.0], seed=7, iterations=100)
    second = bootstrap_mean_ci([1.0, 2.0, 3.0, 4.0], seed=7, iterations=100)
    assert first == second


def test_paired_sign_test_reports_full_support() -> None:
    assert paired_sign_test([3.0, 4.0, 5.0], [1.0, 2.0, 3.0]) == 0.25


def test_holm_bonferroni_preserves_name_mapping() -> None:
    adjusted = holm_bonferroni({"a": 0.01, "b": 0.04, "c": 0.2})
    assert adjusted == {"a": 0.03, "b": 0.08, "c": 0.2}


def test_wilcoxon_signed_rank_reports_deterministic_advantage() -> None:
    result = wilcoxon_signed_rank([1.0, 2.0, 3.0])
    assert result["non_zero_pairs"] == 3
    assert result["rank_biserial_correlation"] == 1.0
    assert result["p_value"] == 0.25


def test_wilcoxon_signed_rank_handles_all_zero_differences() -> None:
    result = wilcoxon_signed_rank([0.0, 0.0, 0.0])
    assert result["non_zero_pairs"] == 0
    assert result["p_value"] == 1.0
