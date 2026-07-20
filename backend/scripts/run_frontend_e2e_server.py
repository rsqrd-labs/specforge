"""Run FastAPI with a deterministic, zero-network LLM for browser E2E.

Only this explicit test-server entrypoint installs the fake. Production and
normal development continue importing the real provider registry unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import uvicorn

from middleware.rate_limit import RateLimitMiddleware
from services.llm.completion import LLMCompletionInfo
from services.pipeline import artifact_validator
from services.pipeline import critic as critic_module
from services.pipeline import spec_clarifier as spec_clarifier_module
from services.pipeline import stage_manager as stage_manager_module


def _stage_for_operation(operation: str | None, system: str) -> str:
    value = f"{operation or ''} {system}".lower()
    for stage in ("spec", "plan", "harness", "tasks"):
        if stage in value:
            return stage
    return "spec"


def _artifact(stage: str) -> str:
    body = (
        "This deterministic browser-test artifact describes observable behavior, "
        "ownership, failure recovery, validation, and concrete verification evidence. "
        "It is intentionally detailed enough to exercise the real persistence and "
        "quality-validation pipeline without contacting an external provider. "
    )
    sections = []
    for heading in artifact_validator.DEMO_DAY_SECTION_CONTRACTS[stage]:
        sections.extend((heading, "", body + body, ""))
    if stage == "spec":
        sections.extend(
            [
                "FR-001 FR-002 FR-003 FR-004 FR-005",
                "NFR-001 NFR-002 NFR-003 SEC-001",
                "AC-001 AC-002 AC-003",
            ]
        )
    if stage == "tasks":
        for number in range(1, 7):
            sections.extend(
                [
                    f"### T-{number:03d}: Implement browser-tested slice {number}",
                    "",
                    "**Phase:** Delivery",
                    "**Spec refs:** FR-001, NFR-001, SEC-001, AC-001",
                    "**Plan refs:** Architecture Overview",
                    "**Harness refs:** `e2e/authenticated.spec.ts`",
                    "**Priority:** MUST",
                    "**Estimate:** S",
                    "**Estimated size:** S",
                    "**Risk:** Low — deterministic test fixture",
                    "**Owner:** Full-stack",
                    "",
                    "**Description**",
                    body,
                    "",
                    "**Inputs**",
                    "Pinned workspace and authenticated browser session.",
                    "",
                    "**Outputs**",
                    "A persisted, independently verifiable task artifact.",
                    "",
                    "**Steps**",
                    "1. Exercise the real API and persistence boundary.",
                    "2. Assert the user-visible result in the browser.",
                    "",
                    "**Acceptance Criteria**",
                    "1. `pnpm test:e2e:backend` passes without external traffic.",
                    "",
                    "**Rollback / Recovery**",
                    "Delete the isolated test workspace and rerun the fixture.",
                    "",
                ]
            )
    sections.append(f"<!-- SPECFORGE_COMPLETE:{stage}:v2 -->")
    return "\n".join(sections)


class DeterministicAdapter:
    def __init__(self, model: str, operation: str | None) -> None:
        self.model = model
        self.operation = operation
        self.last_completion: LLMCompletionInfo | None = None

    async def stream(
        self,
        system: str,
        user: str,
        max_tokens: int,
        **_kwargs: object,
    ) -> AsyncGenerator[str, None]:
        del user
        self.last_completion = LLMCompletionInfo.started(
            provider="e2e",
            model=self.model,
            max_tokens=max_tokens,
        )
        artifact = _artifact(_stage_for_operation(self.operation, system))
        midpoint = len(artifact) // 2
        yield artifact[:midpoint]
        # Cross the pipeline's ~10s silent interval so the browser suite proves
        # the real SSE heartbeat/progress contract as well as token + done.
        await asyncio.sleep(10.5)
        yield artifact[midpoint:]

    async def complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        **kwargs: object,
    ) -> str:
        chunks = [
            chunk async for chunk in self.stream(system, user, max_tokens, **kwargs)
        ]
        return "".join(chunks)


def deterministic_get_llm(
    _provider: str,
    model: str,
    *,
    operation: str | None = None,
    **_kwargs: object,
) -> DeterministicAdapter:
    return DeterministicAdapter(model, operation)


stage_manager_module.get_llm = deterministic_get_llm
spec_clarifier_module.get_llm = deterministic_get_llm


async def no_clarification(*_args: object, **_kwargs: object) -> list[object]:
    return []


spec_clarifier_module.request_clarifying_questions = no_clarification


async def deterministic_judge(**_kwargs: object) -> str:
    return '{"passed": true, "findings": []}'


critic_module.call_judge_model = deterministic_judge


async def bypass_rate_limits(self: object, request: object, call_next: object):
    """Keep the isolated matrix deterministic; rate tiers have backend tests."""
    del self
    return await call_next(request)


RateLimitMiddleware.dispatch = bypass_rate_limits

from main import app  # noqa: E402, I001

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
