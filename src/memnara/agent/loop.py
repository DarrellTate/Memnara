"""Bounded observe → reason → validate → execute → re-observe loop."""

from __future__ import annotations

import time
from dataclasses import dataclass

from memnara.agent.actions import ActionProposal
from memnara.agent.battle import derive_battle_view, mode_label, mode_transition
from memnara.agent.exceptions import (
    InvalidActionError,
    MalformedProposalError,
    PerceptionFailedError,
    ReasoningError,
)
from memnara.agent.execute import ActionExecutor, ExecutionResult
from memnara.agent.history import RecentStep, StepHistory
from memnara.agent.observe import PerceptionObserver
from memnara.agent.ownership import ControlGate
from memnara.agent.reasoning import ReasoningProvider
from memnara.agent.stuck import StuckDetector, StuckState
from memnara.agent.validator import ActionValidator
from memnara.perception.vision.exceptions import ModelUnavailableError, OllamaUnavailableError


@dataclass(frozen=True)
class LoopResult:
    halt_reason: str
    stuck_state: str
    steps: tuple[RecentStep, ...]
    goal: str
    dry_run: bool


class AgentLoop:
    def __init__(
        self,
        *,
        observer: PerceptionObserver,
        reasoner: ReasoningProvider,
        validator: ActionValidator,
        executor: ActionExecutor,
        ownership: ControlGate,
        stuck: StuckDetector | None = None,
        history: StepHistory | None = None,
        max_steps: int = 8,
        max_consecutive_failures: int = 5,
        dry_run: bool = False,
        goal: str = "Explore and make progress through the game.",
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")
        self.observer = observer
        self.reasoner = reasoner
        self.validator = validator
        self.executor = executor
        self.ownership = ownership
        self.stuck = stuck or StuckDetector()
        self.history = history or StepHistory()
        self.max_steps = max_steps
        self.max_consecutive_failures = max_consecutive_failures
        self.dry_run = dry_run
        self.goal = goal

    def run(self) -> LoopResult:
        consecutive_failures = 0
        halt = "max_steps"
        for index in range(1, self.max_steps + 1):
            started = time.perf_counter()
            try:
                before = self.observer.observe()
            except Exception as exc:
                raise PerceptionFailedError(f"observe failed: {exc}") from exc
            proposal: ActionProposal | None = None
            validation_ok = False
            executed = False
            execution_ok = False
            error = ""
            reasoning_ms: float | None = None
            execution_ms: float | None = None
            after = before
            interaction_mode = derive_battle_view(before.context).mode.value
            reason_started = time.perf_counter()
            try:
                proposal = self.reasoner.propose(
                    context=before.context,
                    goal=self.goal,
                    stuck_state=self.stuck.state.value,
                    discouraged=self.stuck.discouraged,
                    history_lines=self.history.action_lines(),
                    validator=self.validator,
                )
                thinking_flag = bool(proposal.metadata.get("json_in_message.thinking"))
                proposal = self.validator.parse_and_validate(
                    {
                        "action": proposal.action,
                        "parameters": proposal.parameters,
                        "reason": proposal.reason,
                        "confidence": proposal.confidence,
                    }
                )
                if thinking_flag:
                    proposal = ActionProposal(
                        action=proposal.action,
                        parameters=proposal.parameters,
                        reason=proposal.reason,
                        confidence=proposal.confidence,
                        metadata={"json_in_message.thinking": True},
                    )
                validation_ok = True
            except (
                MalformedProposalError,
                InvalidActionError,
                ReasoningError,
                ModelUnavailableError,
                OllamaUnavailableError,
            ) as exc:
                error = f"{type(exc).__name__}: {exc}"
                consecutive_failures += 1
            reasoning_ms = (time.perf_counter() - reason_started) * 1000

            if validation_ok and proposal is not None:
                if not self.ownership.allows_gameplay():
                    error = f"OwnershipDeniedError: owner={self.ownership.owner.value}"
                else:
                    confirmed = self._confirm_execution(before)
                    reasoned_mode = derive_battle_view(before.context).mode
                    confirmed_mode = derive_battle_view(confirmed.context).mode
                    if reasoned_mode != confirmed_mode:
                        error = (
                            f"StaleModeError: reasoned={reasoned_mode.value} "
                            f"confirmed={confirmed_mode.value}"
                        )
                    elif self.dry_run:
                        # execution_ok True means the no-execution policy completed, not that input occurred.
                        execution_ok = True
                        consecutive_failures = 0
                    else:
                        exec_started = time.perf_counter()
                        try:
                            result = self.executor.execute(proposal)
                        except Exception as exc:
                            result = ExecutionResult(
                                ok=False,
                                executed=False,
                                released=True,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        finally:
                            self.executor.release_all()
                        execution_ms = (time.perf_counter() - exec_started) * 1000
                        executed = result.executed
                        execution_ok = result.ok
                        if result.error:
                            error = result.error
                        if not result.ok:
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0
                            try:
                                after = self.observer.observe()
                            except Exception as exc:
                                error = f"PerceptionFailedError: {exc}"
                                consecutive_failures += 1
                                after = before

            # Fingerprint is semantic (token + flags/text/caption, or visual-only description). Not raw pixels.
            progress = after.fingerprint != before.fingerprint
            screen_changed = bool(after.screen_digest) and after.screen_digest != before.screen_digest
            state_changed = after.progress_token != before.progress_token
            stuck_state = self.stuck.update(
                fingerprint=after.fingerprint,
                action=proposal.action if proposal else None,
                progressed=progress,
            )
            total_ms = (time.perf_counter() - started) * 1000
            self.history.append(
                RecentStep(
                    step=index,
                    before_summary=before.summary,
                    before_fingerprint=before.fingerprint,
                    proposal=proposal,
                    validation_ok=validation_ok,
                    executed=executed,
                    execution_ok=execution_ok,
                    after_summary=after.summary if after is not before else before.summary,
                    after_fingerprint=after.fingerprint,
                    screen_changed=screen_changed,
                    state_changed=state_changed,
                    stuck_state=stuck_state.value,
                    progress=progress,
                    error=error,
                    perception_ms=before.perception_ms,
                    reasoning_ms=reasoning_ms,
                    execution_ms=execution_ms,
                    total_ms=total_ms,
                    interaction_mode=interaction_mode,
                )
            )
            if stuck_state is StuckState.INTERVENTION_REQUIRED:
                halt = "intervention_required"
                break
            if consecutive_failures >= self.max_consecutive_failures:
                halt = "consecutive_failures"
                break
        return LoopResult(
            halt_reason=halt,
            stuck_state=self.stuck.state.value,
            steps=self.history.items,
            goal=self.goal,
            dry_run=self.dry_run,
        )

    def _confirm_execution(self, prior):
        confirm = getattr(self.observer, "confirm_execution", None)
        if confirm is None:
            return prior
        return confirm(prior)


def format_step(step: RecentStep, *, previous_mode: str | None = None) -> str:
    action = step.proposal.action if step.proposal else "NONE"
    reason = step.proposal.reason if step.proposal else ""
    confidence = step.proposal.confidence if step.proposal else None
    conf_text = f"{confidence:.2f}" if isinstance(confidence, float) else "unspecified"
    label = mode_label(step.interaction_mode)
    transition = mode_transition(previous_mode, step.interaction_mode)
    transition_line = f"\nTRANSITION {transition}" if transition else ""
    return (
        f"STEP {step.step}\n"
        f"MODE {label}{transition_line}\n"
        f"PERCEPTION\n{step.before_summary}\n"
        f"DECISION\n{action}\n"
        f"REASON\n{reason}\n"
        f"CONFIDENCE {conf_text}\n"
        f"RESULT\n"
        f"validated={step.validation_ok} executed={step.executed} execution_ok={step.execution_ok}\n"
        f"screen_changed={step.screen_changed} state_changed={step.state_changed} "
        f"progress={step.progress} stuck_state={step.stuck_state}\n"
        f"error={step.error or 'none'}\n"
        f"timings_ms perception={step.perception_ms} reasoning={step.reasoning_ms} "
        f"execution={step.execution_ms} total={step.total_ms}"
    )
