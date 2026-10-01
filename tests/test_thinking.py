"""Thinking profiles, latency accounting, and provider generation budgets."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from memnara.agent.actions import ActionProposal, ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.execute import ExecutionResult
from memnara.agent.history import RecentStep, StepHistory
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import ObservedState, VisualOnlyObserver, fingerprint_context
from memnara.agent.ollama import OllamaReasoningProvider
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.reasoning import PROPOSAL_FORMAT, SYSTEM_PROMPT, system_prompt_for
from memnara.agent.thinking import (
    DEFAULT_THINKING_PROFILE,
    ThinkingProfile,
    parse_thinking_profile,
    prompt_size_report,
    resolve_thinking,
)
from memnara.agent.validator import ActionValidator
from memnara.demo.autonomy import build_parser, step_record, wire_continuous_runtime
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.http import LocalJsonSession
from memnara.perception.vision.models import SceneType, VisualObservation
from memnara.perception.vision.ollama import OllamaVisionProvider
from memnara.perception.vision.prompts import COMPACT_USER_PROMPT, OBSERVATION_FORMAT, USER_PROMPT
from tests.support.frames import IDLE_PIXELS, frame, paint


def _visual(**overrides) -> VisualObservation:
    data = dict(
        scene_type=SceneType.OVERWORLD,
        description="A room.",
        visible_text=(),
        entities=(),
        menu_visible=False,
        dialogue_visible=False,
        battle_visible=False,
        confidence=0.9,
        notable_changes="",
        source="VISUAL",
        model="qwen3-vl:8b",
    )
    data.update(overrides)
    return VisualObservation(**data)


def _state(*, digest: str = "aaa", **visual_kw) -> ObservedState:
    visual = _visual(**visual_kw)
    context = fuse(visual=visual)
    return ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, None),
        progress_token=None,
        screen_digest=digest,
        perception_ms=1.0,
        summary=compact_summary(context),
        scene_stability="STABLE",
    )


class SequenceObserver:
    def __init__(self, states: list[ObservedState]) -> None:
        self.states = states
        self.calls = 0

    def observe(self) -> ObservedState:
        idx = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[idx]


class Scripted:
    def __init__(self, actions: list) -> None:
        self.actions = list(actions)
        self.lines: list[tuple[str, ...]] = []
        self.contexts = []

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        self.lines.append(tuple(history_lines))
        self.contexts.append(context)
        raw = self.actions.pop(0) if self.actions else {"action": "WAIT", "reason": "fallback"}
        if isinstance(raw, Exception):
            raise raw
        return validator.parse_and_validate(raw)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        self.calls.append(proposal.action)
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        return None


def _loop(states, actions, *, thinking, owner=ControlOwner.AI_CONTROL, dry_run=False, max_steps=1):
    return AgentLoop(
        observer=SequenceObserver(list(states)),
        reasoner=Scripted(list(actions)),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=RecordingExecutor(),
        ownership=ControlGate(owner),
        thinking=thinking,
        dry_run=dry_run,
        max_steps=max_steps,
    )


def test_profiles_resolve_and_default_is_balanced() -> None:
    assert DEFAULT_THINKING_PROFILE is ThinkingProfile.BALANCED
    assert parse_thinking_profile(None) is ThinkingProfile.BALANCED
    assert parse_thinking_profile("FAST") is ThinkingProfile.FAST
    balanced = resolve_thinking()
    fast = resolve_thinking("fast")
    deliberate = resolve_thinking("deliberate")
    assert balanced.name == "balanced"
    assert fast.history_prompt_lines == balanced.history_prompt_lines == 4
    assert deliberate.history_prompt_lines == 8
    assert fast.history_maxlen < balanced.history_maxlen < deliberate.history_maxlen
    assert fast.vision_num_predict < balanced.vision_num_predict < deliberate.vision_num_predict
    assert fast.reasoner_num_predict < balanced.reasoner_num_predict < deliberate.reasoner_num_predict
    assert fast.perception_reuse == "similar"
    assert balanced.perception_reuse == "similar"
    assert deliberate.perception_reuse == "exact"
    assert fast.vision_scale == 2
    assert balanced.vision_scale == 2
    assert deliberate.vision_scale == 3
    assert fast.reason_limit < balanced.reason_limit < deliberate.reason_limit
    with pytest.raises(ValueError, match="unknown thinking profile"):
        parse_thinking_profile("turbo")


def test_cli_accepts_profiles_and_rejects_unknown() -> None:
    parser = build_parser()
    assert parser.parse_args([]).thinking == "balanced"
    assert parser.parse_args(["--thinking", "fast"]).thinking == "fast"
    assert parser.parse_args(["--thinking", "deliberate"]).thinking == "deliberate"
    with pytest.raises(SystemExit):
        parser.parse_args(["--thinking", "turbo"])
    help_text = parser.format_help()
    assert "--thinking" in help_text
    assert "balanced" in help_text


def test_profile_changes_generation_budgets_not_action_schema() -> None:
    captured: list[dict] = []

    def post(path, body):
        captured.append(body)
        return {"message": {"content": '{"action":"WAIT","reason":"ok"}'}}

    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    context = _state().context
    for name in ("fast", "balanced", "deliberate"):
        settings = resolve_thinking(name)
        provider = OllamaReasoningProvider(
            http_post=post,
            num_predict=settings.reasoner_num_predict,
            compact_prompt=settings.reasoner_compact_prompt,
            reason_limit=settings.reason_limit,
        )
        proposal = provider.propose(
            context=context,
            goal="Explore",
            stuck_state="NORMAL",
            discouraged=(),
            history_lines=("PRESS_B → NO_EFFECT",),
            validator=validator,
        )
        assert proposal.action == "WAIT"
        body = captured[-1]
        assert body["format"]["required"] == PROPOSAL_FORMAT["required"]
        assert body["format"]["properties"]["reason"]["maxLength"] == settings.reason_limit
        assert body["options"]["num_predict"] == settings.reasoner_num_predict
        assert body["keep_alive"] == "30m"
        assert body["think"] is False
        if settings.reasoner_compact_prompt:
            assert body["messages"][0]["content"] == system_prompt_for(compact=True)
        else:
            assert body["messages"][0]["content"] == SYSTEM_PROMPT
    assert system_prompt_for(compact=False) == SYSTEM_PROMPT
    assert "NO_EFFECT" in system_prompt_for(compact=True)
    assert "BLOCKED" in system_prompt_for(compact=True)


def test_vision_payload_follows_thinking_budgets() -> None:
    captured: list[dict] = []
    content = json.dumps(
        {
            "scene_type": "OVERWORLD",
            "description": "A path.",
            "menu_visible": False,
            "dialogue_visible": False,
            "battle_visible": False,
            "confidence": 0.8,
        }
    )

    def http_post(path, body):
        if path == "/api/show":
            return {"capabilities": ["vision"]}
        captured.append(body)
        return {"message": {"content": content}}

    settings = resolve_thinking("fast")
    provider = OllamaVisionProvider(
        http_get=lambda path: {"models": [{"name": "qwen3-vl:8b"}]},
        http_post=http_post,
        num_predict=settings.vision_num_predict,
        description_limit=settings.vision_description_limit,
        compact_prompt=True,
    )
    obs = provider.observe(frame(paint(1)))
    assert obs.description == "A path."
    body = captured[-1]
    assert body["format"]["required"] == OBSERVATION_FORMAT["required"]
    assert body["options"]["num_predict"] == settings.vision_num_predict
    assert body["messages"][1]["content"] == COMPACT_USER_PROMPT
    assert body["messages"][1]["content"] != USER_PROMPT


def test_truncated_model_output_fails_closed() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    reasoner = OllamaReasoningProvider(
        http_post=lambda path, body: {"message": {"content": '{"action":"PRESS_A","rea'}}
    )
    with pytest.raises(Exception, match="JSON|malformed|not JSON"):
        reasoner.propose(
            context=_state().context,
            goal="Explore",
            stuck_state="NORMAL",
            discouraged=(),
            history_lines=(),
            validator=validator,
        )
    vision = OllamaVisionProvider(
        http_get=lambda path: {"models": [{"name": "qwen3-vl:8b"}]},
        http_post=lambda path, body: (
            {"capabilities": ["vision"]}
            if path == "/api/show"
            else {"message": {"content": '{"scene_type":"OVERWORLD","descr'}}
        ),
    )
    with pytest.raises(Exception, match="JSON|not JSON"):
        vision.observe(frame(paint(1)))


def test_fast_keeps_recent_blocked_and_no_effect() -> None:
    thinking = resolve_thinking("fast")
    history = StepHistory(maxlen=thinking.history_maxlen)
    history.append(
        RecentStep(
            step=1,
            before_summary="s",
            before_fingerprint="f",
            proposal=ActionProposal(action="MOVE_RIGHT", reason="go", confidence=0.5),
            validation_ok=True,
            executed=True,
            execution_ok=True,
            after_summary="s",
            after_fingerprint="f",
            screen_changed=False,
            state_changed=False,
            stuck_state="NORMAL",
            progress=False,
            movement_outcome="BLOCKED",
        )
    )
    history.append(
        RecentStep(
            step=2,
            before_summary="m",
            before_fingerprint="g",
            proposal=ActionProposal(action="PRESS_B", reason="back", confidence=0.5),
            validation_ok=True,
            executed=True,
            execution_ok=True,
            after_summary="m",
            after_fingerprint="g",
            screen_changed=False,
            state_changed=False,
            stuck_state="NORMAL",
            progress=False,
            interaction_outcome="NO_EFFECT",
        )
    )
    reasoner = Scripted([{"action": "PRESS_A", "reason": "other"}])
    loop = AgentLoop(
        observer=SequenceObserver([_state()]),
        reasoner=reasoner,
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=RecordingExecutor(),
        ownership=ControlGate(),
        thinking=thinking,
        history=history,
        dry_run=True,
        max_steps=1,
    )
    loop.run()
    assert "MOVE_RIGHT → BLOCKED" in reasoner.lines[0]
    assert "PRESS_B → NO_EFFECT" in reasoner.lines[0]


def test_all_profiles_emit_valid_structured_actions() -> None:
    for name in ("fast", "balanced", "deliberate"):
        thinking = resolve_thinking(name)
        result = _loop(
            [_state(), _state(digest="changed")],
            [{"action": "MOVE_UP", "reason": "path"}],
            thinking=thinking,
        ).run()
        step = result.steps[0]
        assert step.validation_ok is True
        assert step.proposal is not None
        assert step.proposal.action == "MOVE_UP"
        assert step.thinking_profile == name
        record = step_record(step)
        assert record["thinking_profile"] == name


def test_ownership_and_stale_handling_ignore_profile() -> None:
    for name in ("fast", "balanced", "deliberate"):
        thinking = resolve_thinking(name)
        denied = _loop(
            [_state()],
            [{"action": "PRESS_A", "reason": "no"}],
            thinking=thinking,
            owner=ControlOwner.USER_CONTROL,
        ).run()
        assert denied.steps[0].executed is False
        assert "OwnershipDeniedError" in denied.steps[0].error


def test_stale_scene_drops_the_proposal_on_every_profile() -> None:
    """Freshness is not a FAST shortcut. A changed live frame is stale for all presets."""

    class Steppable:
        def __init__(self) -> None:
            self.live = frame(paint(1))
            self.vision_calls = 0

        def peek_frame(self):
            return self.live

        def passive_advance(self, count: int):
            return self.live, True

        def observe_frame(self, captured):
            self.vision_calls += 1
            visual = _visual(description=f"call-{self.vision_calls}")
            context = fuse(visual=visual)
            return ObservedState(
                context=context,
                fingerprint=fingerprint_context(context, None),
                progress_token=None,
                screen_digest=f"digest-{self.vision_calls}",
                perception_ms=1.0,
                summary=compact_summary(context),
                scene_stability="STABLE",
            )

    class FlipScene(Scripted):
        def __init__(self, observer: Steppable, actions: list) -> None:
            super().__init__(actions)
            self.observer = observer

        def propose(self, **kwargs):
            self.observer.live = frame(paint(80))
            return super().propose(**kwargs)

    for name in ("fast", "balanced", "deliberate"):
        observer = Steppable()
        reasoner = FlipScene(observer, [{"action": "PRESS_A", "reason": "menu"}])
        executor = RecordingExecutor()
        result = AgentLoop(
            observer=observer,
            reasoner=reasoner,
            validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
            executor=executor,
            ownership=ControlGate(),
            thinking=resolve_thinking(name),
            max_steps=1,
        ).run()
        step = result.steps[0]
        assert step.executed is False, name
        assert executor.calls == []
        assert "StaleObservationError" in step.error, (name, step.error)


def test_fast_similar_reuse_skips_idle_animation_vision() -> None:
    class CountingVision:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, captured):
            self.calls += 1
            return _visual(description=f"call-{self.calls}")

    class Emu:
        def __init__(self) -> None:
            self.idle = 0

        def capture_frame(self):
            self.idle += 1
            return frame(paint(1, idle=min(self.idle, IDLE_PIXELS)))

        def tick(self, count=1, *, render=True):
            return True

    vision = CountingVision()
    observer = VisualOnlyObserver(Emu(), vision, reuse_policy="similar")
    first = observer.observe()
    second = observer.observe()
    assert first.perception_reused is False
    assert second.perception_reused is True
    assert vision.calls == 1
    exact = VisualOnlyObserver(Emu(), CountingVision(), reuse_policy="exact")
    exact.observe()
    later = exact.observe()
    assert later.perception_reused is False


def test_timing_accounting_has_no_large_synthetic_gap() -> None:
    class PauseObserver(SequenceObserver):
        def observe(self) -> ObservedState:
            time.sleep(0.03)
            return super().observe()

    class PauseReasoner(Scripted):
        def propose(self, **kwargs):
            time.sleep(0.02)
            return super().propose(**kwargs)

    loop = AgentLoop(
        observer=PauseObserver([_state(), _state(digest="after")]),
        reasoner=PauseReasoner([{"action": "WAIT", "reason": "pause"}]),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=RecordingExecutor(),
        ownership=ControlGate(),
        thinking=resolve_thinking("balanced"),
        max_steps=1,
    )
    step = loop.run().steps[0]
    assert step.acquire_ms is not None and step.acquire_ms >= 20
    assert step.reasoning_ms is not None and step.reasoning_ms >= 15
    assert step.unaccounted_ms is not None
    assert step.unaccounted_ms < 25, step.unaccounted_ms
    detailed = format_step(step, timing_details=True)
    assert "unaccounted_ms=" in detailed
    assert "thinking=balanced" in detailed
    accounted = (
        (step.acquire_ms or 0)
        + (step.reasoning_ms or 0)
        + (step.freshness_ms or 0)
        + (step.execution_ms or 0)
        + (step.post_acquire_ms or 0)
        + (step.classification_ms or 0)
    )
    assert abs((step.total_ms or 0) - accounted - (step.unaccounted_ms or 0)) < 2


def test_http_session_reuses_then_closes() -> None:
    hits = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            hits["n"] += 1
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            payload = json.dumps({"ok": True, "n": hits["n"]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        session = LocalJsonSession(host="127.0.0.1", port=server.server_address[1], timeout_s=2.0)
        first = session.post_json("/api/chat", {"a": 1})
        second = session.post_json("/api/chat", {"a": 2})
        assert first["ok"] is True
        assert second["n"] == 2
        assert session.requests == 2
        session.close()
        assert session.closed is True
        with pytest.raises(OSError, match="closed"):
            session.post_json("/api/chat", {"a": 3})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_prompt_size_report_is_character_based() -> None:
    report = prompt_size_report("abcd", "efghijkl")
    assert report["system_chars"] == 4
    assert report["user_chars"] == 8
    assert report["total_chars"] == 12
    assert report["approx_tokens"] == 3


def test_evidence_records_thinking_and_component_timings() -> None:
    step = _loop(
        [_state()],
        [{"action": "WAIT", "reason": "hold"}],
        thinking=resolve_thinking("fast"),
        dry_run=True,
    ).run().steps[0]
    record = step_record(step)
    assert record["thinking_profile"] == "fast"
    assert "unaccounted_ms" in record["timings"]
    assert "acquire_ms" in record["timings"]
    assert "prompt_sizes" in record


def test_continuous_wiring_still_uses_one_runtime() -> None:
    class Adapter:
        def __init__(self) -> None:
            self.frames = 0

        def tick(self, count=1, *, render=True):
            self.frames += count
            return True

        def capture_frame(self):
            return frame(paint(self.frames or 1))

        def press_button(self, button, *, delay_frames=1):
            return None

        def release_button(self, button):
            return None

    class Vision:
        def observe(self, captured):
            return _visual()

    adapter = Adapter()
    gate = ControlGate()
    runtime, observer, executor = wire_continuous_runtime(
        adapter, Vision(), gate, reuse_policy="similar"
    )
    assert observer._reuse_policy == "similar"
    assert executor._runtime is runtime


def test_history_window_grows_for_deliberate_not_fast() -> None:
    def seeded(profile: str) -> tuple[str, ...]:
        thinking = resolve_thinking(profile)
        history = StepHistory(maxlen=thinking.history_maxlen)
        for index in range(10):
            history.append(
                RecentStep(
                    step=index + 1,
                    before_summary="s",
                    before_fingerprint="f",
                    proposal=ActionProposal(action="MOVE_RIGHT", reason="go", confidence=0.5),
                    validation_ok=True,
                    executed=True,
                    execution_ok=True,
                    after_summary="s",
                    after_fingerprint="f",
                    screen_changed=False,
                    state_changed=False,
                    stuck_state="NORMAL",
                    progress=False,
                    movement_outcome="BLOCKED",
                )
            )
        return history.action_lines(limit=thinking.history_prompt_lines)

    fast_lines = seeded("fast")
    deliberate_lines = seeded("deliberate")
    assert len(fast_lines) == 4
    assert len(deliberate_lines) == 8
    assert fast_lines[-1] == "MOVE_RIGHT → BLOCKED"
    assert deliberate_lines[-1] == "MOVE_RIGHT → BLOCKED"
