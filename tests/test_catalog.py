from __future__ import annotations

from parity.cases import catalog
from parity.model import CLAIMED_CATEGORIES, AttributionCategory


def test_every_claimed_category_has_positive_and_negative_control() -> None:
    cases = catalog()
    positives = {
        item.spec.expected_first_divergence
        for item in cases
        if item.spec.expected_first_divergence
        and item.spec.expected_first_divergence is not AttributionCategory.UNEXPLAINED
    }
    negatives = {
        item.spec.isolated_variable
        for item in cases
        if item.spec.expected_first_divergence is None
    }
    assert set(CLAIMED_CATEGORIES) <= positives
    isolated_for_claimed = {
        item.spec.isolated_variable
        for item in cases
        if item.spec.expected_first_divergence in CLAIMED_CATEGORIES
    }
    assert isolated_for_claimed <= negatives


def test_unexplained_ordering_case_exists() -> None:
    case = next(item for item in catalog() if item.spec.case_id == "rebalance-ordering")
    assert case.spec.expected_first_divergence is AttributionCategory.UNEXPLAINED
