import numpy as np
import pytest

from scripts.extract_load.commodity_benchmark_index import _cap_and_redistribute_weights


def test_cap_and_redistribute_is_noop_without_cap() -> None:
    weights = np.array([0.5, 0.3, 0.2])

    result = _cap_and_redistribute_weights(weights, None)

    assert (result == weights).all()


def test_cap_and_redistribute_keeps_sum_to_one_when_feasible() -> None:
    weights = np.array([0.6, 0.25, 0.15])

    result = _cap_and_redistribute_weights(weights, max_weight=0.4)

    assert result.max() <= 0.4 + 1e-9
    assert result.sum() == pytest.approx(1.0)


def test_cap_and_redistribute_raises_when_cap_is_mathematically_infeasible() -> None:
    # 4 assets capped at 0.2 each can only ever hold 0.8 of the portfolio: build_synthetic_index
    # has no cash bucket, so silently investing 80% would corrupt index_level on the next
    # mark-to-market. This must fail loudly instead.
    weights = np.array([0.25, 0.25, 0.25, 0.25])

    with pytest.raises(ValueError, match="trop restrictif"):
        _cap_and_redistribute_weights(weights, max_weight=0.2)
