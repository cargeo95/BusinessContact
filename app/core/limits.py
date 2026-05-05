from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.storage.state_manager import StateManager


@dataclass(frozen=True)
class LimitSnapshot:
    daily_goal: int
    processed_today: int
    remaining: int
    reached: bool


class DailyProcessingLimits:
    def __init__(self, daily_goal: int, state_manager: StateManager) -> None:
        self.daily_goal = max(daily_goal, 0)
        self.state_manager = state_manager

    def snapshot(self, target_date: date | None = None) -> LimitSnapshot:
        processed_today = self.state_manager.processed_count_for(target_date)
        remaining = max(self.daily_goal - processed_today, 0)
        return LimitSnapshot(
            daily_goal=self.daily_goal,
            processed_today=processed_today,
            remaining=remaining,
            reached=remaining == 0,
        )

    def can_process_more(self, requested: int = 1, target_date: date | None = None) -> bool:
        return self.snapshot(target_date).remaining >= max(requested, 1)

    def clamp_requested(self, requested: int | None, target_date: date | None = None) -> int:
        remaining = self.snapshot(target_date).remaining
        if requested is None:
            return remaining
        return max(0, min(requested, remaining))
