"""Map validated generic actions to EmulatorAdapter buttons. No PyBoy import."""

from __future__ import annotations

from memnara.agent.actions import ActionProposal, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.exceptions import ExecutionFailedError, InvalidActionError
from memnara.agent.execute import ActionExecutor, ExecutionResult
from memnara.emulators.base import EmulatorAdapter
from memnara.emulators.buttons import Button

ACTION_TO_BUTTON: dict[str, Button] = {
    "MOVE_UP": Button.UP,
    "MOVE_DOWN": Button.DOWN,
    "MOVE_LEFT": Button.LEFT,
    "MOVE_RIGHT": Button.RIGHT,
    "PRESS_A": Button.A,
    "PRESS_B": Button.B,
    "PRESS_START": Button.START,
    "PRESS_SELECT": Button.SELECT,
}


class GameBoyActionExecutor(ActionExecutor):
    def __init__(
        self,
        emulator: EmulatorAdapter,
        *,
        tap_frames: int = 8,
        wait_frames: int = 30,
        settle_frames: int = 24,
    ) -> None:
        self._emulator = emulator
        self.tap_frames = tap_frames
        self.wait_frames = wait_frames
        self.settle_frames = settle_frames

    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        if proposal.action not in DEFAULT_GAMEPLAY_ACTIONS:
            raise InvalidActionError(f"executor does not support {proposal.action}")
        try:
            if proposal.action == "WAIT":
                frames = int(proposal.parameters.get("frames", self.wait_frames))
                self._emulator.tick(frames, render=True)
            else:
                button = ACTION_TO_BUTTON[proposal.action]
                self._emulator.press_button(button, delay_frames=self.tap_frames)
                self._emulator.tick(self.settle_frames, render=True)
            self.release_all()
            return ExecutionResult(ok=True, executed=True, released=True, detail=proposal.action)
        except Exception as exc:
            self.release_all()
            raise ExecutionFailedError(f"{proposal.action} failed: {exc}") from exc

    def release_all(self) -> None:
        for button in Button:
            try:
                self._emulator.release_button(button)
            except Exception:
                continue
