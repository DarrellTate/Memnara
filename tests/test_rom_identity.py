from pathlib import Path

import pytest

from memnara.emulators.exceptions import RomNotFoundError, RomUnreadableError
from memnara.rom_identity import inspect_rom


def _minimal_gb(title: bytes) -> bytes:
    data = bytearray(0x200)
    padded = title[:15].ljust(15, b"\x00")
    data[0x0134 : 0x0134 + len(padded)] = padded
    data[0x0147] = 0x13
    checksum = 0
    for addr in range(0x0134, 0x014D):
        checksum = (checksum - data[addr] - 1) & 0xFF
    data[0x014D] = checksum
    return bytes(data)


def test_inspect_missing(tmp_path: Path) -> None:
    with pytest.raises(RomNotFoundError):
        inspect_rom(tmp_path / "missing.gb")


def test_inspect_too_small(tmp_path: Path) -> None:
    p = tmp_path / "tiny.gb"
    p.write_bytes(b"nope")
    with pytest.raises(RomUnreadableError):
        inspect_rom(p)


def test_inspect_header_generic(tmp_path: Path) -> None:
    p = tmp_path / "fake.gb"
    p.write_bytes(_minimal_gb(b"TEST GAME"))
    ident = inspect_rom(p)
    assert ident.header_title == "TEST GAME"
    assert ident.header_checksum_valid is True
    assert ident.size_bytes == 0x200
    assert len(ident.sha1) == 40
    assert len(ident.sha256) == 64
