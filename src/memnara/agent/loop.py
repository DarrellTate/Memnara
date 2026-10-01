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
from memnara.agent.interaction import InteractionOutcome, classify_interaction
from memnara.agent.movement import MovementOutcome, classify_movement
from memnara.agent.observe import ObservedState, PerceptionObserver, meaningful_progress
from memnara.agent.ownership import ControlGate
from memnara.agent.reasoning import ReasoningProvider
from memnara.agent.stuck import StuckDetector, StuckState
from memnara.agent.transition import (
    DEFAULT_TRANSITION_CHUNK_FRAMES,
    DEFAULT_TRANSITION_GRACE_FRAMES,
    TRANSITION_GUIDANCE,
    SceneStability,
    frame_stability,
)
from memnara.agent.validator import ActionValidator
from memnara.perception.vision.exceptions import ModelUnavailableError, OllamaUnavailableError


@dataclass(frozen=True)
class LoopResult:
    halt_reason: str
    stuck_state: str
    steps: tuple[RecentStep, ...]
    goal: str
    dry_run: bool


@dataclass(frozen=True)
class _Acquisition:
    state: ObservedState
    passive_frames: int
    saw_transition: bool
    grace_remaining: int
    suppressed: bool


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
        transition_grace_frames: int = DEFAULT_TRANSITION_GRACE_FRAMES,
        transition_chunk_frames: int = DEFAULT_TRANSITION_CHUNK_FRAMES,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")
        if transition_grace_frames < 1:
            raise ValueError("transition_grace_frames must be >= 1")
        if transition_chunk_frames < 1:
            raise ValueError("transition_chunk_frames must be >= 1")
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
        self.transition_grace_frames = transition_grace_frames
        self.transition_chunk_frames = transition_chunk_frames
        self._grace_used = 0

    def run(self) -> LoopResult:
        consecutive_failures = 0
        halt = "max_steps"
        for index in range(1, self.max_steps + 1):
            started = time.perf_counter()
            try:
                before_acq = self._acquire()
            except Exception as exc:
                raise PerceptionFailedError(f"observe failed: {exc}") from exc
            before = before_acq.state
            proposal: ActionProposal | None = None
            validation_ok = False
            executed = False
            execution_ok = False
            error = ""
            reasoning_ms: float | None = None
            execution_ms: float | None = None
            after = before
            after_acq: _Acquisition | None = None
            interaction_mode = derive_battle_view(before.context).mode.value

            if not before_acq.suppressed:
                history_lines = self.history.action_lines()
                if before.scene_stability == SceneStability.TRANSIENT.value:
                    history_lines = (TRANSITION_GUIDANCE,) + history_lines
                reason_started = time.perf_counter()
                try:
                    proposal = self.reasoner.propose(
                        context=before.context,
                        goal=self.goal,
                        stuck_state=self.stuck.state.value,
                        discouraged=self.stuck.discouraged,
                        history_lines=history_lines,
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
                    elif (
                        before.scene_stability == SceneStability.TRANSIENT.value
                        and proposal.action != "WAIT"
                    ):
                        # The grace budget is already spent and the scene is still
                        # unsettled. WAIT may run. Other gameplay input may not.
                        error = "TransitionInputError: gameplay input refused while the scene is transient"
                    else:
                        confirmed = self._confirm_execution(before)
                        reasoned_mode = derive_battle_view(before.context).mode
                        confirmed_mode = derive_battle_view(confirmed.context).mode
                        if reasoned_mode != confirmed_mode:
                            error = (
                                f"StaleModeError: reasoned={reasoned_mode.value} "
                                f"confirmed={confirmed_mode.value}"
                            )
                        elif self._scene_went_transient(before):
                            error = (
                                "StaleSceneError: reasoned=STABLE confirmed=TRANSIENT"
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
                                    after_acq = self._acquire()
                                    after = after_acq.state
                                except Exception as exc:
                                    error = f"PerceptionFailedError: {exc}"
                                    consecutive_failures += 1
                                    after = before
                                    after_acq = None

            movement = self._movement(proposal, executed, before, after, after_acq)
            unconfirmed = executed and after is before
            # A fade that has already settled is classified from the stable frame.
            # Movement still treats the pumped gap as UNCERTAIN.
            transient = (
                unconfirmed
                or before.scene_stability == SceneStability.TRANSIENT.value
                or after.scene_stability == SceneStability.TRANSIENT.value
            )
            interaction = classify_interaction(
                action=proposal.action if proposal else None,
                executed=executed,
                before=before,
                after=after,
                transient=transient,
            )
            progress = meaningful_progress(before, after, movement=movement, interaction=interaction)
            screen_changed = bool(after.screen_digest) and after.screen_digest != before.screen_digest
            state_changed = after.progress_token != before.progress_token
            skip_stuck = before_acq.suppressed or error.startswith("StaleSceneError")
            if skip_stuck:
                stuck_state = self.stuck.state
                if before_acq.suppressed:
                    progress = False
            else:
                stuck_state = self.stuck.update(
                    fingerprint=after.fingerprint,
                    action=proposal.action if proposal else None,
                    progressed=progress,
                )
            saw = before_acq.saw_transition or (after_acq.saw_transition if after_acq else False)
            passive = before_acq.passive_frames + (after_acq.passive_frames if after_acq else 0)
            grace_remaining = after_acq.grace_remaining if after_acq else before_acq.grace_remaining
            transition_state = SceneStability.TRANSIENT.value if saw else SceneStability.STABLE.value
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
                    movement_outcome=movement.value,
                    interaction_outcome=interaction.value,
                    perception_reused=before.perception_reused,
                    confirmation_ms=after.perception_ms if after_acq is not None else None,
                    vision_ms=before.vision_ms,
                    error=error,
                    perception_ms=before.perception_ms,
                    reasoning_ms=reasoning_ms,
                    execution_ms=execution_ms,
                    total_ms=total_ms,
                    interaction_mode=interaction_mode,
                    scene_stability=before.scene_stability,
                    transition_state=transition_state,
                    transition_grace_remaining=grace_remaining,
                    passive_frames=passive,
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

    def _can_pump(self) -> bool:
        return self.ownership.allows_gameplay() and not self.dry_run

    def _can_step_runtime(self) -> bool:
        observer = self.observer
        return all(
            callable(getattr(observer, name, None))
            for name in ("peek_frame", "passive_advance", "observe_frame")
        )

    def _acquire(self) -> _Acquisition:
        if self._can_step_runtime():
            return self._acquire_steppable()
        return self._acquire_fallback(self.observer.observe())

    def _acquire_steppable(self) -> _Acquisition:
        """Pump button-free frames while the scene is transient, then one vision call.

        Tick calls here are runtime progression. They are not MOVE, PRESS, or WAIT.
        """
        frame = self.observer.peek_frame()
        stability = frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format)
        passive = 0
        saw = stability is SceneStability.TRANSIENT
        if saw and self._can_pump() and self._grace_used < self.transition_grace_frames:
            while stability is SceneStability.TRANSIENT and self._grace_used < self.transition_grace_frames:
                chunk = min(
                    self.transition_chunk_frames,
                    self.transition_grace_frames - self._grace_used,
                )
                if chunk < 1:
                    break
                frame = self.observer.passive_advance(chunk)
                self._grace_used += chunk
                passive += chunk
                stability = frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format)
                if stability is SceneStability.TRANSIENT:
                    saw = True
        if stability is SceneStability.STABLE:
            self._grace_used = 0
        elif stability is SceneStability.TRANSIENT:
            saw = True
        if saw:
            invalidate = getattr(self.observer, "invalidate_perception_reuse", None)
            if callable(invalidate):
                invalidate()
        state = self.observer.observe_frame(frame)
        return _Acquisition(
            state=state,
            passive_frames=passive,
            saw_transition=saw,
            grace_remaining=max(0, self.transition_grace_frames - self._grace_used),
            suppressed=False,
        )

    def _acquire_fallback(self, state: ObservedState) -> _Acquisition:
        """Observers that cannot advance frames still get a bounded grace.

        Each observation spends one grace unit. Reasoning is skipped until the
        budget is gone so a short run of transient states does not escalate stuck.
        """
        if state.scene_stability != SceneStability.TRANSIENT.value:
            self._grace_used = 0
            return _Acquisition(
                state=state,
                passive_frames=0,
                saw_transition=False,
                grace_remaining=self.transition_grace_frames,
                suppressed=False,
            )
        if not self._can_pump():
            return _Acquisition(
                state=state,
                passive_frames=0,
                saw_transition=True,
                grace_remaining=max(0, self.transition_grace_frames - self._grace_used),
                suppressed=False,
            )
        self._grace_used += 1
        suppressed = self._grace_used <= self.transition_grace_frames
        return _Acquisition(
            state=state,
            passive_frames=0,
            saw_transition=True,
            grace_remaining=max(0, self.transition_grace_frames - self._grace_used),
            suppressed=suppressed,
        )

    def _scene_went_transient(self, before: ObservedState) -> bool:
        if before.scene_stability != SceneStability.STABLE.value:
            return False
        probe = getattr(self.observer, "probe_stability", None)
        if not callable(probe):
            return False
        return probe() == SceneStability.TRANSIENT.value

    def _confirm_execution(self, prior: ObservedState) -> ObservedState:
        confirm = getattr(self.observer, "confirm_execution", None)
        if confirm is None:
            return prior
        return confirm(prior)

    def _movement(self, proposal, executed: bool, before: ObservedState, after: ObservedState, after_acq: _Acquisition | None):
        # A failed re-observe keeps the same object, so there is no after-frame to judge.
        if executed and after is before and proposal is not None and proposal.action.startswith("MOVE_"):
            return MovementOutcome.UNCERTAIN
        stability_after = after.scene_stability
        if after_acq is not None and after_acq.saw_transition:
            stability_after = SceneStability.TRANSIENT.value
        return classify_movement(
            action=proposal.action if proposal else None,
            executed=executed,
            navigation_before=before.navigation_token,
            navigation_after=after.navigation_token,
            scene_before=before.scene,
            scene_after=after.scene,
            stability_before=before.scene_stability,
            stability_after=stability_after,
        )


def format_step(step: RecentStep, *, previous_mode: str | None = None, timing_details: bool = False) -> str:
    action = step.proposal.action if step.proposal else "NONE"
    reason = step.proposal.reason if step.proposal else ""
    confidence = step.proposal.confidence if step.proposal else None
    conf_text = f"{confidence:.2f}" if isinstance(confidence, float) else "unspecified"
    label = mode_label(step.interaction_mode)
    transition = mode_transition(previous_mode, step.interaction_mode)
    transition_line = f"\nTRANSITION {transition}" if transition else ""
    timing_line = ""
    if timing_details:
        timing_line = (
            f"\nTIMING reused={step.perception_reused} "
            f"vision_ms={step.vision_ms} perception_ms={step.perception_ms} "
            f"reasoning_ms={step.reasoning_ms} execution_ms={step.execution_ms} "
            f"confirmation_ms={step.confirmation_ms} total_ms={step.total_ms}"
        )
    return (
        f"STEP {step.step}\n"
        f"MODE {label}{transition_line}\n"
        f"SCENE STABILITY {step.scene_stability}\n"
        f"PERCEPTION\n{step.before_summary}\n"
        f"DECISION\n{action}\n"
        f"REASON\n{reason}\n"
        f"CONFIDENCE {conf_text}\n"
        f"RESULT\n"
        f"validated={step.validation_ok} executed={step.executed} execution_ok={step.execution_ok}\n"
        f"screen_changed={step.screen_changed}\n"
        f"state_changed={step.state_changed}\n"
        f"movement={step.movement_outcome}\n"
        f"interaction={step.interaction_outcome}\n"
        f"transition={step.transition_state}\n"
        f"transition_grace_remaining={step.transition_grace_remaining}\n"
        f"passive_frames={step.passive_frames}\n"
        f"progress={step.progress}\n"
        f"stuck_state={step.stuck_state}\n"
        f"error={step.error or 'none'}\n"
        f"timings_ms perception={step.perception_ms} reasoning={step.reasoning_ms} "
        f"execution={step.execution_ms} total={step.total_ms}{timing_line}"
    )
