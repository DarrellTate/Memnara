"""Developer demo: bounded autonomous VISION + INPUT loop. ROM path is runtime input."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from memnara.agent.actions import ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.battle import mode_transition
from memnara.agent.events import structured_step_events
from memnara.agent.history import RecentStep
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import VisualOnlyObserver
from memnara.agent.ollama import OllamaReasoningProvider
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.thinking import ThinkingProfile, resolve_thinking
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.config import load_config
from memnara.emulators.gameplay import GameBoyActionExecutor
from memnara.emulators.pyboy_adapter import VISIBLE_PYBOY_WINDOW, PyBoyAdapter
from memnara.perception.vision.http import LocalJsonSession
from memnara.perception.vision.ollama import OllamaVisionProvider
from memnara.rom_identity import inspect_rom
from memnara.runtime.continuous import (
    DEFAULT_TARGET_FPS,
    RuntimeActionExecutor,
    RuntimeFrameSource,
    ThreadedEmulatorRuntime,
)
from memnara.runtime.exceptions import RuntimeShutdownError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Memnara bounded autonomy demo (generic battle handling included)"
    )
    parser.add_argument("--rom", type=Path, default=None, help="Operator ROM path")
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument("--model", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--goal", default="Explore and make progress through the game.")
    parser.add_argument("--skip-intro", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--owner", default="AI_CONTROL", choices=[item.value for item in ControlOwner])
    parser.add_argument(
        "--show-window",
        action="store_true",
        help="Show the PyBoy window of the same instance Memnara controls",
    )
    parser.add_argument(
        "--timing-details",
        action="store_true",
        help="Print per-step perception reuse and timing on the developer CLI",
    )
    parser.add_argument(
        "--step-runtime",
        action="store_true",
        help="Advance the emulator only around decisions instead of on its own clock",
    )
    parser.add_argument(
        "--target-fps",
        type=float,
        default=DEFAULT_TARGET_FPS,
        help="Continuous runtime cadence in emulated frames per second",
    )
    parser.add_argument(
        "--thinking",
        default="balanced",
        choices=[item.value for item in ThinkingProfile],
        help="Decision latency/depth preset (fast, balanced, deliberate). Not an AI identity.",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="Evidence JSON path (default: D:\\Memnara-Data\\autonomy\\m6_live_autonomy.json)",
    )
    return parser


def controlled_window(*, show_window: bool, configured: str) -> str:
    """Headless unless the operator asks to see the controlled emulator."""
    if show_window:
        return VISIBLE_PYBOY_WINDOW
    return configured


def resolve_vision_scale(thinking, *, environ=None) -> int:
    """Thinking default unless the operator set MEMNARA_VISION_SCALE."""
    env = os.environ if environ is None else environ
    raw = env.get("MEMNARA_VISION_SCALE") if hasattr(env, "get") else None
    if raw not in (None, ""):
        return int(raw)
    return int(thinking.vision_scale)


def wire_controlled_runtime(adapter, vision, *, reuse_policy: str = "exact"):
    """Observer and executor share one emulator. No second process is created."""
    return VisualOnlyObserver(adapter, vision, reuse_policy=reuse_policy), GameBoyActionExecutor(adapter)


def wire_continuous_runtime(
    adapter,
    vision,
    gate: ControlGate,
    *,
    target_fps: float = DEFAULT_TARGET_FPS,
    open_runtime=None,
    close_runtime=None,
    reuse_policy: str = "exact",
):
    """One owner thread advances the same emulator. The agent reads snapshots.

    Opening and closing run on that thread too, so a window the emulator creates
    is created, pumped, and destroyed on one thread.

    `PAUSED` freezes the controlled runtime. The other owners keep it moving so a
    person can play and so automatic sequences continue; AI input is still gated
    by `ControlGate`, on the agent side and again on the owner thread.
    """
    runtime = ThreadedEmulatorRuntime(
        adapter,
        target_fps=target_fps,
        should_advance=lambda: gate.owner is not ControlOwner.PAUSED,
        can_apply_input=gate.allows_gameplay,
        open_runtime=open_runtime,
        close_runtime=close_runtime,
    )
    source = RuntimeFrameSource(runtime)
    return runtime, VisualOnlyObserver(source, vision, reuse_policy=reuse_policy), RuntimeActionExecutor(runtime)


def skip_intro(adapter: PyBoyAdapter) -> None:
    """Optional startup mash so a typical boot sequence advances. Not a scripted route."""
    adapter.tick(200, render=True)
    for _ in range(400):
        adapter.press_button("a", delay_frames=1)
        adapter.tick(8, render=True)


def step_record(step: RecentStep, *, previous_mode: str | None = None) -> dict:
    proposal = step.proposal
    return {
        "step": step.step,
        "interaction_mode": step.interaction_mode,
        "mode_transition": mode_transition(previous_mode, step.interaction_mode),
        "events": list(structured_step_events(step, previous_mode=previous_mode)),
        "goal_progressed": step.progress,
        "before_perception_summary": step.before_summary,
        "action": proposal.action if proposal else None,
        "reason": proposal.reason if proposal else "",
        "action_confidence": proposal.confidence if proposal else None,
        "validation_result": step.validation_ok,
        "executed": step.executed,
        "execution_result": step.execution_ok,
        "after_perception_summary": step.after_summary,
        "screen_changed": step.screen_changed,
        "state_changed": step.state_changed,
        "movement_outcome": step.movement_outcome,
        "interaction_outcome": step.interaction_outcome,
        "perception_reused": step.perception_reused,
        "scene_stability": step.scene_stability,
        "transition_state": step.transition_state,
        "transition_grace_remaining": step.transition_grace_remaining,
        "passive_frames": step.passive_frames,
        "decision_readiness": step.decision_readiness,
        "progression_frames": step.progression_frames,
        "progression_chunks": step.progression_chunks,
        "observation_id": step.observation_id,
        "applied_observation_id": step.applied_observation_id,
        "frames_since_observation": step.frames_since_observation,
        "execution_frames": step.execution_frames,
        # Running total for the whole run, not a count for this step.
        "stale_proposals_dropped_total": step.stale_proposals_dropped,
        "thinking_profile": step.thinking_profile,
        "perception_tier": step.perception_tier,
        "post_vision_skipped": step.post_vision_skipped,
        "vision_call_count": step.vision_call_count,
        "stuck_state": step.stuck_state,
        "error": step.error,
        "timings": {
            "perception_ms": step.perception_ms,
            "vision_ms": step.vision_ms,
            "reasoning_ms": step.reasoning_ms,
            "execution_ms": step.execution_ms,
            "confirmation_ms": step.confirmation_ms,
            "model_wait_ms": step.model_wait_ms,
            "passive_runtime_ms": step.passive_runtime_ms,
            "proposal_age_ms": step.proposal_age_ms,
            "acquire_ms": step.acquire_ms,
            "freshness_ms": step.freshness_ms,
            "post_acquire_ms": step.post_acquire_ms,
            "classification_ms": step.classification_ms,
            "unaccounted_ms": step.unaccounted_ms,
            "total_ms": step.total_ms,
            "vision_encode_ms": step.vision_encode_ms,
            "vision_http_ms": step.vision_http_ms,
            "vision_parse_ms": step.vision_parse_ms,
        },
        "prompt_sizes": {
            "system_chars": step.prompt_system_chars,
            "user_chars": step.prompt_user_chars,
            "vision_chars": step.vision_prompt_chars,
        },
        "vision_cost": {
            "png_bytes": step.vision_png_bytes,
            "eval_count": step.vision_eval_count,
            "generation_chars": step.vision_generation_chars,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(rom_path=args.rom, vision_model=args.model)
    cfg.ensure_runtime_dirs()
    rom = cfg.rom_path
    if not rom.is_file():
        print(f"ROM not found: {rom}", file=sys.stderr)
        return 2
    identity = inspect_rom(rom)
    session_id = str(uuid.uuid4())
    evidence_path = args.evidence or (cfg.autonomy_dir / "m6_live_autonomy.json")
    thinking = resolve_thinking(args.thinking)
    http_session = LocalJsonSession.from_endpoint(cfg.ollama_host, timeout_s=cfg.vision_timeout_s)
    vision_scale = resolve_vision_scale(thinking)
    vision = OllamaVisionProvider(
        endpoint=cfg.ollama_host,
        model=cfg.vision_model,
        scale=vision_scale,
        timeout_s=cfg.vision_timeout_s,
        think=thinking.think,
        keep_alive=thinking.keep_alive,
        num_predict=thinking.vision_num_predict,
        description_limit=thinking.vision_description_limit,
        compact_prompt=thinking.vision_compact_prompt,
        session=http_session,
    )
    reasoner = OllamaReasoningProvider(
        endpoint=cfg.ollama_host,
        model=cfg.vision_model,
        timeout_s=cfg.reasoning_timeout_s,
        think=thinking.think,
        keep_alive=thinking.keep_alive,
        num_predict=thinking.reasoner_num_predict,
        compact_prompt=thinking.reasoner_compact_prompt,
        reason_limit=thinking.reason_limit,
        session=http_session,
    )
    window = controlled_window(show_window=args.show_window, configured=cfg.pyboy_window)
    if args.show_window:
        print("DISPLAY controlled emulator window enabled")
    adapter = PyBoyAdapter(window=window, sound_emulated=False)
    started = time.perf_counter()
    evidence: dict = {
        "session_id": session_id,
        "model": cfg.vision_model,
        "endpoint": cfg.ollama_host,
        "rom_sha1": identity.sha1,
        "backend": "pyboy",
        "dry_run": args.dry_run,
        "goal": args.goal,
        "max_steps": args.max_steps,
        "skip_intro": args.skip_intro,
        "owner": args.owner,
        "observer": "visual_only",
        "thinking_profile": thinking.name,
        "thinking": {
            "history_maxlen": thinking.history_maxlen,
            "history_prompt_lines": thinking.history_prompt_lines,
            "vision_num_predict": thinking.vision_num_predict,
            "reasoner_num_predict": thinking.reasoner_num_predict,
            "vision_description_limit": thinking.vision_description_limit,
            "perception_reuse": thinking.perception_reuse,
            "vision_scale": vision_scale,
            "reason_limit": thinking.reason_limit,
            "keep_alive": thinking.keep_alive,
        },
        "steps": [],
    }
    gate = ControlGate(ControlOwner(args.owner))
    runtime = None

    def open_controlled_runtime() -> None:
        adapter.start(rom)
        if args.skip_intro:
            skip_intro(adapter)

    try:
        if args.step_runtime:
            open_controlled_runtime()
            observer, executor = wire_controlled_runtime(
                adapter, vision, reuse_policy=thinking.perception_reuse
            )
            evidence["runtime_mode"] = "frame_stepped"
        else:
            runtime, observer, executor = wire_continuous_runtime(
                adapter,
                vision,
                gate,
                target_fps=args.target_fps,
                open_runtime=open_controlled_runtime,
                close_runtime=adapter.stop,
                reuse_policy=thinking.perception_reuse,
            )
            runtime.start()
            evidence["runtime_mode"] = "continuous"
            evidence["runtime_target_fps"] = args.target_fps
            print(f"RUNTIME continuous owner thread at ~{args.target_fps:g} emulated fps")
        loop = AgentLoop(
            observer=observer,
            reasoner=reasoner,
            validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
            executor=executor,
            ownership=gate,
            stuck=StuckDetector(StuckConfig()),
            max_steps=args.max_steps,
            dry_run=args.dry_run,
            goal=args.goal,
            thinking=thinking,
        )
        print(f"THINKING {thinking.name}")
        result = loop.run()
        evidence["halt_reason"] = result.halt_reason
        evidence["stuck_state"] = result.stuck_state
        previous_mode = None
        records = []
        for item in result.steps:
            records.append(step_record(item, previous_mode=previous_mode))
            print(format_step(item, previous_mode=previous_mode, timing_details=args.timing_details))
            print("-" * 40)
            previous_mode = item.interaction_mode
        evidence["steps"] = records
        evidence["elapsed_s"] = time.perf_counter() - started
        print(f"HALT {result.halt_reason} stuck={result.stuck_state}")
        print(f"evidence {evidence_path}")
        return 0
    except Exception as exc:
        # A crashed run still owes an evidence file that says what went wrong.
        evidence.setdefault("halt_reason", "error")
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if runtime is not None:
            # The owner thread closes the emulator itself. If it will not stop,
            # say so loudly and leave the emulator alone rather than freeing it
            # underneath a live thread.
            try:
                runtime.stop()
            except RuntimeShutdownError as shutdown_exc:
                print(f"RUNTIME shutdown failed: {shutdown_exc}", file=sys.stderr)
            # Read after stop so release and close failures are recorded too.
            evidence["runtime_frames_advanced"] = runtime.frames_advanced
            evidence["runtime_longest_gap_ms"] = round(runtime.max_gap_ms, 1)
            evidence["runtime_frame_wait_timeouts"] = runtime.frame_wait_timeouts
            if runtime.error:
                evidence["runtime_error"] = runtime.error
                print(f"RUNTIME error {runtime.error}", file=sys.stderr)
        else:
            try:
                adapter.stop()
            except Exception:
                pass
        try:
            http_session.close()
        except Exception:
            pass
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
