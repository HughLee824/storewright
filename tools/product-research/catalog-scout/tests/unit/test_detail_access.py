from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from storewright_catalog_scout.browser.detail_access import DetailAccessPolicy
from storewright_catalog_scout.exceptions import RiskCooldownRequiredError


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 19, tzinfo=UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += timedelta(seconds=seconds)


def policy(path: Path, clock: Clock, *, max_per_hour: int = 20) -> DetailAccessPolicy:
    return DetailAccessPolicy(
        path,
        interval_seconds=60,
        jitter_seconds=15,
        max_per_hour=max_per_hour,
        risk_cooldown_seconds=900,
        max_risk_cooldown_seconds=21_600,
        now=clock.now,
        sleep=clock.sleep,
        random_uniform=lambda _start, _end: 0,
    )


async def test_first_request_and_resume_share_persisted_pacing(tmp_path: Path) -> None:
    clock = Clock()
    state_path = tmp_path / "detail-access.json"
    first = policy(state_path, clock)

    await first.wait_before_request()
    first.record_request()
    resumed = policy(state_path, clock)
    await resumed.wait_before_request()

    assert clock.sleeps == [60, 60]


async def test_risk_cooldown_persists_across_policy_instances(tmp_path: Path) -> None:
    clock = Clock()
    state_path = tmp_path / "detail-access.json"
    retry_at = policy(state_path, clock).record_risk("DETAIL_HTTP_429")

    with pytest.raises(RiskCooldownRequiredError) as captured:
        await policy(state_path, clock).wait_before_request()

    assert captured.value.reason == "DETAIL_RISK_COOLDOWN_ACTIVE"
    assert captured.value.retry_at == retry_at


async def test_hourly_budget_pauses_instead_of_waiting(tmp_path: Path) -> None:
    clock = Clock()
    state_path = tmp_path / "detail-access.json"
    first = policy(state_path, clock, max_per_hour=1)
    first.record_request()

    with pytest.raises(RiskCooldownRequiredError) as captured:
        await policy(state_path, clock, max_per_hour=1).wait_before_request()

    assert captured.value.reason == "DETAIL_HOURLY_BUDGET_REACHED"


async def test_invalid_persisted_state_fails_closed(tmp_path: Path) -> None:
    clock = Clock()
    state_path = tmp_path / "detail-access.json"
    state_path.write_text("not-json")

    with pytest.raises(RiskCooldownRequiredError) as captured:
        await policy(state_path, clock).wait_before_request()

    assert captured.value.reason == "DETAIL_ACCESS_STATE_INVALID"
