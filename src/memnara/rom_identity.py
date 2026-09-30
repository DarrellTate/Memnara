"""Generic GB header/hash identity. No title-specific RAM or title heuristics."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from memnara.emulators.exceptions import RomNotFoundError, RomUnreadableError

TITLE_START = 0x0134
TITLE_END = 0x0144
CART_TYPE = 0x0147
HEADER_CHECKSUM = 0x014D

CART_TYPES = {
    0x00: "ROM ONLY",
    0x01: "MBC1",
    0x02: "MBC1+RAM",
    0x03: "MBC1+RAM+BATTERY",
    0x13: "MBC3+RAM+BATTERY",
    0x1B: "MBC5+RAM+BATTERY",
}


@dataclass(frozen=True)
class RomIdentity:
    path: str
    filename: str
    size_bytes: int
    sha1: str
    sha256: str
    header_title: str
    cartridge_type: str
    cartridge_type_code: int
    header_checksum: int
    header_checksum_valid: bool | None


def _header_checksum_ok(data: bytes) -> bool | None:
    if len(data) < HEADER_CHECKSUM + 1:
        return None
    checksum = 0
    for addr in range(0x0134, 0x014D):
        checksum = (checksum - data[addr] - 1) & 0xFF
    return checksum == data[HEADER_CHECKSUM]


def _title(data: bytes) -> str:
    raw = data[TITLE_START:TITLE_END]
    text = raw.split(b"\x00", 1)[0]
    return "".join(chr(b) if 32 <= b < 127 else "" for b in text).strip()


def inspect_rom(path: str | Path) -> RomIdentity:
    rom_path = Path(path)
    if not rom_path.exists():
        raise RomNotFoundError(f"ROM not found: {rom_path}")
    try:
        data = rom_path.read_bytes()
    except OSError as exc:
        raise RomUnreadableError(f"Cannot read ROM: {rom_path}") from exc
    if len(data) < 0x0150:
        raise RomUnreadableError(f"File too small to be a Game Boy ROM: {rom_path}")

    cart_code = data[CART_TYPE]
    return RomIdentity(
        path=str(rom_path.resolve()),
        filename=rom_path.name,
        size_bytes=len(data),
        sha1=hashlib.sha1(data).hexdigest(),
        sha256=hashlib.sha256(data).hexdigest(),
        header_title=_title(data),
        cartridge_type=CART_TYPES.get(cart_code, f"unknown(0x{cart_code:02X})"),
        cartridge_type_code=cart_code,
        header_checksum=data[HEADER_CHECKSUM],
        header_checksum_valid=_header_checksum_ok(data),
    )
