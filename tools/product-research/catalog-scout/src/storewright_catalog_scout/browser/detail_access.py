from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from storewright_catalog_scout.exceptions import RiskCooldownRequiredError


class DetailAccessPolicy:
    """Persistent, workspace-wide pacing and risk cooldown for detail navigation."""

    def __init__(
        self,
        state_path: Path,
        *,
        interval_seconds: float,
        jitter_seconds: float,
        max_per_hour: int,
        risk_cooldown_seconds: int,
        max_risk_cooldown_seconds: int,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        random_uniform: Callable[[float, float], float] | None = None,
    ) -> None:
        self.state_path = state_path
        self.interval_seconds = interval_seconds
        self.jitter_seconds = jitter_seconds
        self.max_per_hour = max_per_hour
        self.risk_cooldown_seconds = risk_cooldown_seconds
        self.max_risk_cooldown_seconds = max_risk_cooldown_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep or asyncio.sleep
        self._random_uniform = random_uniform or random.SystemRandom().uniform
        self._session_started_at = self._now()

    async def wait_before_request(self) -> None:
        now = self._now()
        state = self._load()
        retry_at = _parse_datetime(state.get("backoff_until"))
        if retry_at and retry_at > now:
            raise RiskCooldownRequiredError("DETAIL_RISK_COOLDOWN_ACTIVE", retry_at.isoformat())

        request_times = self._recent_request_times(state, now)
        if self.max_per_hour > 0 and len(request_times) >= self.max_per_hour:
            retry_at = request_times[0] + timedelta(hours=1)
            state["backoff_until"] = retry_at.isoformat()
            self._save(state)
            raise RiskCooldownRequiredError("DETAIL_HOURLY_BUDGET_REACHED", retry_at.isoformat())

        last_request_at = _parse_datetime(state.get("last_request_at"))
        pacing_anchor = max(
            value for value in (last_request_at, self._session_started_at) if value is not None
        )
        delay = self.interval_seconds + self._random_uniform(0, self.jitter_seconds)
        remaining = (pacing_anchor + timedelta(seconds=delay) - now).total_seconds()
        if remaining > 0:
            await self._sleep(remaining)

    def record_request(self) -> None:
        now = self._now()
        state = self._load()
        request_times = self._recent_request_times(state, now)
        request_times.append(now)
        state["last_request_at"] = now.isoformat()
        state["request_times"] = [value.isoformat() for value in request_times]
        self._save(state)

    def record_success(self) -> None:
        state = self._load()
        state["consecutive_risk_signals"] = 0
        state["backoff_until"] = None
        self._save(state)

    def record_risk(self, reason: str) -> str:
        now = self._now()
        state = self._load()
        signals = int(state.get("consecutive_risk_signals") or 0) + 1
        cooldown = min(
            self.risk_cooldown_seconds * (2 ** (signals - 1)),
            self.max_risk_cooldown_seconds,
        )
        retry_at = now + timedelta(seconds=cooldown)
        state["consecutive_risk_signals"] = signals
        state["backoff_until"] = retry_at.isoformat()
        state["last_risk_reason"] = reason
        self._save(state)
        return retry_at.isoformat()

    def _recent_request_times(self, state: dict[str, Any], now: datetime) -> list[datetime]:
        cutoff = now - timedelta(hours=1)
        parsed = (_parse_datetime(value) for value in state.get("request_times", []))
        return sorted(value for value in parsed if value is not None and value > cutoff)

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as error:
            raise self._invalid_state_error() from error
        if not isinstance(value, dict):
            raise self._invalid_state_error()
        return value

    def _invalid_state_error(self) -> RiskCooldownRequiredError:
        retry_at = self._now() + timedelta(seconds=self.max_risk_cooldown_seconds)
        return RiskCooldownRequiredError("DETAIL_ACCESS_STATE_INVALID", retry_at.isoformat())

    def _save(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
