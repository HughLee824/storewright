from __future__ import annotations

from decimal import Decimal
from math import sqrt
from statistics import NormalDist
from typing import Any

from shop_scout.domain.enums import ShopDecision
from shop_scout.domain.models import ShopContext, ShopDecisionResult


def rejection_rate(exact_count: int, search_success_count: int) -> float:
    return exact_count / search_success_count if search_success_count else 0.0


def wilson_lower_bound(successes: int, trials: int, confidence: float) -> float:
    """Lower Wilson score bound for a binomial proportion."""
    if trials <= 0:
        return 0.0
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = proportion + z * z / (2 * trials)
    margin = z * sqrt((proportion * (1 - proportion) + z * z / (4 * trials)) / trials)
    return (centre - margin) / denominator


def should_reject_early(
    *,
    exact_count: int,
    search_success_count: int,
    minimum_searches: int,
    reject_rate_threshold: float,
    confidence: float,
) -> bool:
    if search_success_count < minimum_searches:
        return False
    return (
        wilson_lower_bound(exact_count, search_success_count, confidence)
        >= reject_rate_threshold
    )


def decide_shop(context: ShopContext) -> ShopDecisionResult:
    rate = rejection_rate(context.exact_count, context.search_success_count)
    error_denominator = context.search_success_count + context.error_count
    error_rate = context.error_count / error_denominator if error_denominator else 0.0
    base: dict[str, Any] = dict(
        discovered_count=context.discovered_count,
        processed_count=context.processed_count,
        search_success_count=context.search_success_count,
        exact_count=context.exact_count,
        qualified_count=context.qualified_count,
        skipped_count=context.skipped_count,
        error_count=context.error_count,
        rejection_rate=Decimal(f"{rate:.4f}"),
        early_stopped=context.early_stopped,
    )
    if context.discovered_count == 0:
        return ShopDecisionResult(
            decision=ShopDecision.INSUFFICIENT_DATA,
            reason_code="NO_PRODUCTS_DISCOVERED",
            summary="未发现可处理商品，数据不足。",
            **base,
        )
    if not context.catalog_complete:
        return ShopDecisionResult(
            decision=ShopDecision.REVIEW,
            reason_code="CATALOG_TRUNCATED",
            summary="商品发现达到安全上限，无法确认已覆盖全店。",
            **base,
        )
    if context.early_stopped:
        return ShopDecisionResult(
            decision=ShopDecision.REJECTED,
            reason_code="REJECTION_RATE_CONFIDENTLY_HIGH",
            summary="已搜索商品的精确匹配淘汰率高于阈值，店铺提前淘汰。",
            **base,
        )
    if error_rate > context.max_search_error_rate:
        return ShopDecisionResult(
            decision=ShopDecision.REVIEW,
            reason_code="SEARCH_ERROR_RATE_TOO_HIGH",
            summary="图片检索错误率过高，不能自动判断店铺。",
            **base,
        )
    if not context.search_success_count:
        return ShopDecisionResult(
            decision=ShopDecision.REVIEW,
            reason_code="NO_SUCCESSFUL_SEARCHES",
            summary="没有成功完成的图片检索，不能自动判断店铺。",
            **base,
        )
    if rate >= context.reject_rate_threshold:
        return ShopDecisionResult(
            decision=ShopDecision.REJECTED,
            reason_code="FINAL_REJECTION_RATE_HIGH",
            summary="全部已处理商品的精确匹配淘汰率达到店铺阈值。",
            **base,
        )
    return ShopDecisionResult(
        decision=ShopDecision.CANDIDATE,
        reason_code="QUALIFIED_CATALOG_READY",
        summary="店铺淘汰率低于阈值，已按类目保留合格商品。",
        **base,
    )
