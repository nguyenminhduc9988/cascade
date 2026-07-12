"""Auto-decision service — the autonomy improvement.

Implements the user requirement: "for choices we need to just do the most
sensible one and auto choose". The agent should almost never ask a human;
only genuinely irreversible/destructive operations escalate.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cascade.models import Message
from cascade.services.task_service import TaskService
from cascade.utils import dumps, new_id

logger = logging.getLogger(__name__)

# Operations that are genuinely irreversible or destructive → escalate to human.
DESTRUCTIVE_KEYWORDS = {
    "delete",
    "destroy",
    "drop",
    "purge",
    "format",
    "wipe",
    "irreversible",
    "production-deploy",
    "production_deploy",
    "force-push",
    "force_push",
    "refund",
    "charge",
    "disable",
}

RISK_SCORE = {"low": 3, "medium": 2, "high": 1, None: 2}
EFFORT_SCORE = {"low": 3, "medium": 2, "high": 1, None: 2}


class AutoDecisionService:
    """Auto-resolve choices without human intervention."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def should_ask_human(self, task_id: str, question_type: str) -> bool:
        """Return True ONLY for irreversible/destructive operations.

        Implements the 99%-autonomous policy: the agent decides everything
        except operations it cannot safely undo.
        """
        lowered = (question_type or "").lower().replace("_", "-")
        return any(keyword in lowered for keyword in DESTRUCTIVE_KEYWORDS)

    async def auto_resolve_choice(
        self,
        task_id: str,
        choices: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Pick the most sensible option and record the decision as a message.

        Each choice may carry ``risk`` (low/medium/high), ``effort``
        (low/medium/high) and ``reversible`` (bool). Higher score wins; ties
        broken by original order (first wins).
        """
        if not choices:
            decision = {"task_id": task_id, "chosen": None, "reason": "no options"}
            await self._record(task_id, decision)
            return decision

        best = choices[0]
        best_score = self._score(best)
        for choice in choices[1:]:
            score = self._score(choice)
            if score > best_score:
                best = choice
                best_score = score

        chosen_label = best.get("label") or best.get("title") or str(best)
        decision = {
            "task_id": task_id,
            "chosen": best,
            "reason": (
                f"Auto-selected option '{chosen_label}' as the safest/fastest "
                f"choice (score={best_score})."
            ),
        }
        await self._record(task_id, decision)
        return decision

    def _score(self, choice: dict[str, Any]) -> float:
        """Score a choice: prefer low risk, low effort, reversible."""
        score = 0.0
        score += RISK_SCORE.get(
            (choice.get("risk") or "").lower() if choice.get("risk") else None, 2
        )
        score += EFFORT_SCORE.get(
            (choice.get("effort") or "").lower() if choice.get("effort") else None, 2
        )
        if choice.get("reversible", True):
            score += 2.0
        return score

    async def _record(self, task_id: str, decision: dict[str, Any]) -> Message:
        """Persist the decision as a ``system`` message on the task."""
        task_service = TaskService(self.session)
        return await task_service.add_message(
            task_id=task_id,
            author="system",
            content=decision["reason"],
            message_type="system",
            metadata={"auto_decision": decision["chosen"]},
        )
