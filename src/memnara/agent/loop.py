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
from memnara.agent.freshness import DecisionSignature, signature_of, staleness_reason, transition_started
from memnara.agent.history import RecentStep, StepHistory
from memnara.agent.interaction import InteractionOutcome, classify_interaction
from memnara.agent.movement import MovementOutcome, classify_movement
from memnara.agent.observe import ObservedState, PerceptionObserver, digest_pixels, meaningful_progress
from memnara.agent.ownership import ControlGate
from memnara.agent.readiness import (
    DEFAULT_PASSIVE_BUDGET_FRAMES,
    DEFAULT_PASSIVE_CHUNK_FRAMES,
    DEFAULT_PASSIVE_WALL_S,
    PASSIVE_GUIDANCE,
    DecisionReadiness,
    frames_meaningfully_changed,
)
from memnara.agent.reasoning import ReasoningProvider
from memnara.agent.stuck import StuckDetector, StuckState
from memnara.agent.thinking import DEFAULT_THINKING_PROFILE, ThinkingSettings, resolve_thinking
from memnara.agent.transition import (
    DEFAULT_TRANSITION_CHUNK_FRAMES,
    DEFAULT_TRANSITION_GRACE_FRAMES,
    TRANSITION_GUIDANCE,
    SceneStability,
    frame_stability,
)
from memnara.agent.validator import ActionValidator
from memnara.perception.vision.exceptions import ModelUnavailableError, OllamaUnavailableError


_TRANSIENT_STALE = "the scene started transitioning"


def _prompt_size(reasoner, key: str) -> int | None:
    sizes = getattr(reasoner, "last_prompt_sizes", None)
    if isinstance(sizes, dict) and key in sizes:
        return int(sizes[key])
    return None


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
    frame: object | None = None
    decision_readiness: str = "UNKNOWN"
    progression_frames: int = 0
    progression_chunks: int = 0
    passive_runtime_ms: float = 0.0


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
        thinking: ThinkingSettings | None = None,
        transition_grace_frames: int = DEFAULT_TRANSITION_GRACE_FRAMES,
        transition_chunk_frames: int = DEFAULT_TRANSITION_CHUNK_FRAMES,
        passive_budget_frames: int = DEFAULT_PASSIVE_BUDGET_FRAMES,
        passive_chunk_frames: int = DEFAULT_PASSIVE_CHUNK_FRAMES,
        passive_wall_s: float = DEFAULT_PASSIVE_WALL_S,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")
        if transition_grace_frames < 1:
            raise ValueError("transition_grace_frames must be >= 1")
        if transition_chunk_frames < 1:
            raise ValueError("transition_chunk_frames must be >= 1")
        if passive_budget_frames < 0:
            raise ValueError("passive_budget_frames must be >= 0")
        if passive_chunk_frames < 1:
            raise ValueError("passive_chunk_frames must be >= 1")
        if passive_wall_s <= 0:
            raise ValueError("passive_wall_s must be > 0")
        self.observer = observer
        self.reasoner = reasoner
        self.validator = validator
        self.executor = executor
        self.ownership = ownership
        self.stuck = stuck or StuckDetector()
        self.thinking = thinking or resolve_thinking(DEFAULT_THINKING_PROFILE)
        self.history = history or StepHistory(maxlen=self.thinking.history_maxlen)
        self.max_steps = max_steps
        self.max_consecutive_failures = max_consecutive_failures
        self.dry_run = dry_run
        self.goal = goal
        self.transition_grace_frames = transition_grace_frames
        self.transition_chunk_frames = transition_chunk_frames
        self.passive_budget_frames = passive_budget_frames
        self.passive_chunk_frames = passive_chunk_frames
        self.passive_wall_s = passive_wall_s
        self._grace_used = 0

    def run(self) -> LoopResult:
        consecutive_failures = 0
        halt = "max_steps"
        stale_dropped = 0
        for index in range(1, self.max_steps + 1):
            started = time.perf_counter()
            acquire_ms = 0.0
            freshness_ms = 0.0
            post_acquire_ms = 0.0
            classification_ms = 0.0
            try:
                acquire_started = time.perf_counter()
                before_acq = self._acquire()
                acquire_ms = (time.perf_counter() - acquire_started) * 1000
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
            execution_frames = 0
            applied_observation_id = ""
            after = before
            after_acq: _Acquisition | None = None
            interaction_mode = derive_battle_view(before.context).mode.value
            signature = signature_of(
                before,
                owner=self.ownership.owner.value,
                interaction_mode=interaction_mode,
            )
            proposal_age_ms: float | None = None
            frames_since_observation = 0

            if not before_acq.suppressed:
                history_lines = self.history.action_lines(limit=self.thinking.history_prompt_lines)
                if before.scene_stability == SceneStability.TRANSIENT.value:
                    history_lines = (TRANSITION_GUIDANCE,) + history_lines
                elif before_acq.progression_frames > 0:
                    history_lines = (PASSIVE_GUIDANCE,) + history_lines
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
                    proposal_age_ms = max(0.0, (time.time() - before.observed_at) * 1000)
                    frames_since_observation = max(
                        0, self._runtime_frame() - before.runtime_frame
                    )
                    fresh_started = time.perf_counter()
                    if not self.ownership.allows_gameplay():
                        # Ownership moved while the model was thinking, so this
                        # proposal is as stale as a changed scene.
                        freshness_ms = (time.perf_counter() - fresh_started) * 1000
                        stale_dropped += 1
                        error = f"OwnershipDeniedError: owner={self.ownership.owner.value}"
                    elif (
                        before.scene_stability == SceneStability.TRANSIENT.value
                        and proposal.action != "WAIT"
                    ):
                        # The grace budget is already spent and the scene is still
                        # unsettled. WAIT may run. Other gameplay input may not.
                        freshness_ms = (time.perf_counter() - fresh_started) * 1000
                        error = "TransitionInputError: gameplay input refused while the scene is transient"
                    else:
                        confirmed = self._confirm_execution(before)
                        confirmed_mode = derive_battle_view(confirmed.context).mode
                        stale = self._staleness(signature, before_acq, confirmed_mode.value)
                        freshness_ms = (time.perf_counter() - fresh_started) * 1000
                        if confirmed_mode.value != signature.interaction_mode:
                            stale_dropped += 1
                            error = (
                                f"StaleModeError: reasoned={signature.interaction_mode} "
                                f"confirmed={confirmed_mode.value}"
                            )
                        elif stale == _TRANSIENT_STALE or self._scene_went_transient(before):
                            stale_dropped += 1
                            error = (
                                "StaleSceneError: reasoned=STABLE confirmed=TRANSIENT"
                            )
                        elif stale:
                            stale_dropped += 1
                            error = f"StaleObservationError: {stale}"
                        elif self.dry_run:
                            # execution_ok True means the no-execution policy completed, not that input occurred.
                            execution_ok = True
                            consecutive_failures = 0
                        else:
                            exec_started = time.perf_counter()
                            bind = getattr(self.executor, "bind_observation", None)
                            if callable(bind):
                                bind(before.observation_id)
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
                            execution_frames = result.frames_applied
                            applied_observation_id = result.applied_observation_id
                            if result.error:
                                error = result.error
                            if not result.ok:
                                consecutive_failures += 1
                            else:
                                consecutive_failures = 0
                                try:
                                    post_started = time.perf_counter()
                                    after_acq = self._acquire()
                                    after = after_acq.state
                                    post_acquire_ms = (time.perf_counter() - post_started) * 1000
                                except Exception as exc:
                                    error = f"PerceptionFailedError: {exc}"
                                    consecutive_failures += 1
                                    after = before
                                    after_acq = None

            classify_started = time.perf_counter()
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
            skip_stuck = before_acq.suppressed or error.startswith(
                ("StaleSceneError", "StaleObservationError")
            )
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
            progression = before_acq.progression_frames + (
                after_acq.progression_frames if after_acq else 0
            )
            progression_chunks = before_acq.progression_chunks + (
                after_acq.progression_chunks if after_acq else 0
            )
            passive_runtime_ms = before_acq.passive_runtime_ms + (
                after_acq.passive_runtime_ms if after_acq else 0
            )
            grace_remaining = after_acq.grace_remaining if after_acq else before_acq.grace_remaining
            transition_state = SceneStability.TRANSIENT.value if saw else SceneStability.STABLE.value
            classification_ms = (time.perf_counter() - classify_started) * 1000
            total_ms = (time.perf_counter() - started) * 1000
            accounted = (
                acquire_ms
                + (reasoning_ms or 0.0)
                + freshness_ms
                + (execution_ms or 0.0)
                + post_acquire_ms
                + classification_ms
            )
            unaccounted_ms = max(0.0, total_ms - accounted)
            model_wait_ms = before.vision_ms + (reasoning_ms or 0.0)
            if after_acq is not None:
                model_wait_ms += after.vision_ms
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
                    decision_readiness=before_acq.decision_readiness,
                    progression_frames=progression,
                    progression_chunks=progression_chunks,
                    passive_runtime_ms=passive_runtime_ms,
                    model_wait_ms=model_wait_ms,
                    observation_id=before.observation_id,
                    proposal_age_ms=proposal_age_ms,
                    frames_since_observation=frames_since_observation,
                    stale_proposals_dropped=stale_dropped,
                    execution_frames=execution_frames,
                    applied_observation_id=applied_observation_id,
                    thinking_profile=self.thinking.name,
                    acquire_ms=acquire_ms,
                    freshness_ms=freshness_ms,
                    post_acquire_ms=post_acquire_ms,
                    classification_ms=classification_ms,
                    unaccounted_ms=unaccounted_ms,
                    prompt_system_chars=_prompt_size(self.reasoner, "system_chars"),
                    prompt_user_chars=_prompt_size(self.reasoner, "user_chars"),
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
        """Advance button-free frames, then one vision call.

        A fade uses the transition budget. A stable frame that keeps changing
        on its own uses the passive-progression budget. Neither path is a
        MOVE, PRESS, or WAIT, and neither calls the vision model per frame.
        """
        frame = self.observer.peek_frame()
        stability = frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format)
        passive = 0
        saw = stability is SceneStability.TRANSIENT
        if saw:
            frame, stability, pumped = self._pump_transient(frame, stability)
            passive += pumped
        progression_frames = 0
        progression_chunks = 0
        passive_runtime_ms = 0.0
        readiness = DecisionReadiness.UNKNOWN.value
        if stability is SceneStability.STABLE:
            frame, stability, readiness, progressed, chunks, runtime_ms = self._advance_passive(frame)
            progression_frames += progressed
            progression_chunks += chunks
            passive_runtime_ms += runtime_ms
            if stability is SceneStability.TRANSIENT:
                saw = True
                frame, stability, pumped = self._pump_transient(frame, stability)
                passive += pumped
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
            frame=frame,
            decision_readiness=readiness,
            progression_frames=progression_frames,
            progression_chunks=progression_chunks,
            passive_runtime_ms=passive_runtime_ms,
        )

    def _pump_transient(self, frame, stability):
        """Button-free ticks while the frame stays near-black or near-uniform."""
        passive = 0
        if self._can_pump() and self._grace_used < self.transition_grace_frames:
            while stability is SceneStability.TRANSIENT and self._grace_used < self.transition_grace_frames:
                chunk = min(
                    self.transition_chunk_frames,
                    self.transition_grace_frames - self._grace_used,
                )
                if chunk < 1:
                    break
                frame, advanced = self.observer.passive_advance(chunk)
                self._grace_used += chunk
                if not advanced:
                    break
                passive += chunk
                stability = frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format)
        return frame, stability, passive

    def _advance_passive(self, frame):
        """Tick while a stable framebuffer keeps changing with no button held.

        The first unchanged chunk stops the episode. A transient chunk is handed
        back to the fade pump. Budget and wall-clock both stop the loop, and the
        caller then takes one vision reading.
        """
        started = time.perf_counter()
        if self.passive_budget_frames < 1 or not self._can_pump():
            elapsed = (time.perf_counter() - started) * 1000
            return frame, SceneStability.STABLE, DecisionReadiness.UNKNOWN.value, 0, 0, elapsed
        used = 0
        episode = 0
        chunks = 0
        readiness = DecisionReadiness.INPUT_REQUIRED.value
        stability = SceneStability.STABLE
        current = frame
        while used < self.passive_budget_frames and (time.perf_counter() - started) < self.passive_wall_s:
            step = min(self.passive_chunk_frames, self.passive_budget_frames - used)
            if step < 1:
                break
            nxt, advanced = self.observer.passive_advance(step)
            used += step
            stability = frame_stability(nxt.pixels, nxt.width, nxt.height, nxt.pixel_format)
            if not advanced:
                # The runtime did not deliver those frames, so do not count them.
                readiness = DecisionReadiness.UNKNOWN.value
                current = nxt
                break
            changed = frames_meaningfully_changed(current, nxt)
            current = nxt
            if stability is SceneStability.TRANSIENT:
                readiness = DecisionReadiness.UNKNOWN.value
                break
            if not changed:
                readiness = DecisionReadiness.INPUT_REQUIRED.value
                break
            episode += step
            chunks += 1
            readiness = DecisionReadiness.PASSIVE_PROGRESS.value
        elapsed = (time.perf_counter() - started) * 1000 if episode else 0.0
        return current, stability, readiness, episode, chunks, elapsed

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
        try:
            return probe() == SceneStability.TRANSIENT.value
        except Exception:
            return False

    def _runtime_frame(self) -> int:
        """Live runtime frame counter. Zero on a runtime that does not expose one."""
        return int(getattr(self.observer, "runtime_frame", 0) or 0)

    def _staleness(self, signature: DecisionSignature, before_acq: _Acquisition, mode_now: str) -> str:
        """Why the proposal no longer targets the reasoned state, or "" if it does.

        Peek does not advance the runtime. An idle animation that moves a few
        pixels stays equivalent. A transition, a structured-state change, a
        material scene change, an unreadable frame, or an ownership change is
        stale. Runtimes that cannot peek keep the previous execute path.
        """
        owner_now = self.ownership.owner.value
        if owner_now != signature.owner:
            return f"ownership changed from {signature.owner} to {owner_now}"
        peek = getattr(self.observer, "peek_frame", None)
        if not callable(peek) or before_acq.frame is None:
            return ""
        try:
            frame_now = peek()
        except Exception as exc:
            return f"the live frame could not be read ({type(exc).__name__})"
        digest_now = digest_pixels(frame_now.pixels)
        if not digest_now:
            return "the live frame has no pixels"
        stability_now = frame_stability(
            frame_now.pixels, frame_now.width, frame_now.height, frame_now.pixel_format
        ).value
        if transition_started(signature, stability_now):
            return _TRANSIENT_STALE
        return staleness_reason(
            signature=signature,
            owner_now=owner_now,
            mode_now=mode_now,
            stability_now=stability_now,
            digest_now=digest_now,
            frame_before=before_acq.frame,
            frame_now=frame_now,
            token_now=self._peek_progress_token(),
        )

    def _peek_progress_token(self) -> str | None:
        """Structured token for the live frame, when a runtime can supply one.

        Generic VISION has none without another model call, so this stays None
        there. A structured-state observer can answer cheaply.
        """
        peek_token = getattr(self.observer, "peek_progress_token", None)
        if not callable(peek_token):
            return None
        try:
            token = peek_token()
        except Exception:
            return None
        return token if token else None

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
        throughput = ""
        # Only the progression episode is timed, so only its frames may be
        # divided by that time. Fade-pump frames are advanced outside this window.
        runtime_ms = step.passive_runtime_ms or 0.0
        if runtime_ms > 0 and step.progression_frames:
            throughput = f" emulated_fps={step.progression_frames / (runtime_ms / 1000):.1f}"
        timing_line = (
                f"\nTIMING reused={step.perception_reused} "
                f"vision_ms={step.vision_ms} perception_ms={step.perception_ms} "
                f"reasoning_ms={step.reasoning_ms} execution_ms={step.execution_ms} "
                f"confirmation_ms={step.confirmation_ms} total_ms={step.total_ms} "
                f"model_wait_ms={step.model_wait_ms} passive_runtime_ms={step.passive_runtime_ms} "
                f"acquire_ms={step.acquire_ms} freshness_ms={step.freshness_ms} "
                f"post_acquire_ms={step.post_acquire_ms} classification_ms={step.classification_ms} "
                f"unaccounted_ms={step.unaccounted_ms} thinking={step.thinking_profile} "
                f"progression_frames={step.progression_frames} "
                f"progression_chunks={step.progression_chunks}{throughput}\n"
                f"RUNTIME observation={step.observation_id or 'none'} "
                f"applied_observation={step.applied_observation_id or 'none'} "
                f"proposal_age_ms={step.proposal_age_ms} "
                f"frames_since_observation={step.frames_since_observation} "
                f"execution_frames={step.execution_frames} "
                f"stale_proposals_dropped_total={step.stale_proposals_dropped}"
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
        f"readiness={step.decision_readiness}\n"
        f"transition={step.transition_state}\n"
        f"transition_grace_remaining={step.transition_grace_remaining}\n"
        f"passive_frames={step.passive_frames}\n"
        f"progress={step.progress}\n"
        f"stuck_state={step.stuck_state}\n"
        f"error={step.error or 'none'}\n"
        f"timings_ms perception={step.perception_ms} reasoning={step.reasoning_ms} "
        f"execution={step.execution_ms} total={step.total_ms}{timing_line}"
    )
