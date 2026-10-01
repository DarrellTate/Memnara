"""Developer demo: bounded autonomous VISION + INPUT loop. ROM path is runtime input."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from memnara.agent.actions import ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.battle import mode_transition
from memnara.agent.history import RecentStep
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import VisualOnlyObserver
from memnara.agent.ollama import OllamaReasoningProvider
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.config import load_config
from memnara.emulators.gameplay import GameBoyActionExecutor
from memnara.emulators.pyboy_adapter import VISIBLE_PYBOY_WINDOW, PyBoyAdapter
from memnara.perception.vision.ollama import OllamaVisionProvider
from memnara.rom_identity import inspect_rom


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


def wire_controlled_runtime(adapter, vision):
    """Observer and executor share one emulator. No second process is created."""
    return VisualOnlyObserver(adapter, vision), GameBoyActionExecutor(adapter)


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
            "total_ms": step.total_ms,
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
    vision = OllamaVisionProvider(
        endpoint=cfg.ollama_host,
        model=cfg.vision_model,
        scale=cfg.vision_scale,
        timeout_s=cfg.vision_timeout_s,
        think=False,
    )
    reasoner = OllamaReasoningProvider(
        endpoint=cfg.ollama_host,
        model=cfg.vision_model,
        timeout_s=cfg.reasoning_timeout_s,
        think=False,
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
        "steps": [],
    }
    try:
        adapter.start(rom)
        if args.skip_intro:
            skip_intro(adapter)
        observer, executor = wire_controlled_runtime(adapter, vision)
        loop = AgentLoop(
            observer=observer,
            reasoner=reasoner,
            validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
            executor=executor,
            ownership=ControlGate(ControlOwner(args.owner)),
            stuck=StuckDetector(StuckConfig()),
            max_steps=args.max_steps,
            dry_run=args.dry_run,
            goal=args.goal,
        )
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
    finally:
        try:
            adapter.stop()
        except Exception:
            pass
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
