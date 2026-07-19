from storewright_catalog_scout.domain.enums import ShopDecision
from storewright_catalog_scout.domain.models import ShopContext
from storewright_catalog_scout.matching.shop_policy import (
    decide_shop,
    rejection_rate,
    should_reject_early,
    wilson_lower_bound,
)


def context(**overrides: object) -> ShopContext:
    values: dict[str, object] = {
        "discovered_count": 20,
        "processed_count": 20,
        "search_success_count": 20,
        "exact_count": 4,
        "qualified_count": 16,
        "skipped_count": 0,
        "error_count": 0,
    }
    values.update(overrides)
    return ShopContext.model_validate(values)


def test_rate_uses_successful_searches_only() -> None:
    assert rejection_rate(3, 5) == 0.6
    assert rejection_rate(0, 0) == 0


def test_wilson_early_stop_requires_enough_confident_results() -> None:
    assert wilson_lower_bound(9, 10, 0.90) > 0.60
    assert should_reject_early(
        exact_count=9,
        search_success_count=10,
        minimum_searches=10,
        reject_rate_threshold=0.60,
        confidence=0.90,
    )
    assert not should_reject_early(
        exact_count=8,
        search_success_count=10,
        minimum_searches=10,
        reject_rate_threshold=0.60,
        confidence=0.90,
    )


def test_shop_decisions_cover_candidate_rejected_and_review() -> None:
    assert decide_shop(context()).decision == ShopDecision.CANDIDATE
    assert decide_shop(context(exact_count=12, qualified_count=8)).decision == ShopDecision.REJECTED
    assert decide_shop(context(early_stopped=True)).decision == ShopDecision.REJECTED
    assert decide_shop(context(catalog_complete=False)).decision == ShopDecision.REVIEW
    assert (
        decide_shop(context(search_success_count=5, error_count=5)).decision
        == ShopDecision.REVIEW
    )
    assert (
        decide_shop(context(discovered_count=0, processed_count=0, search_success_count=0)).decision
        == ShopDecision.INSUFFICIENT_DATA
    )
