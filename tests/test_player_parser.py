from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

from zomboid_saver.player_parser import (
    ZomboidBinaryParser,
    format_player_info,
    get_player_info,
)


def _build_blob() -> bytes:
    payload = bytearray()

    def add_string(key: str, value: str) -> None:
        payload.append(0x02)
        payload.extend(len(key).to_bytes(2, "big"))
        payload.extend(key.encode("utf-8"))
        payload.append(0x02)
        payload.extend(len(value).to_bytes(2, "big"))
        payload.extend(value.encode("utf-8"))

    add_string("trait1", "Brave")
    add_string("name", "Alice")
    add_string("surname", "Survivor")

    payload.append(0x02)
    payload.extend(len("hour").to_bytes(2, "big"))
    payload.extend(b"hour")
    payload.append(0x01)
    payload.extend(struct.pack(">d", 42.0))

    payload.append(0x02)
    payload.extend(len("zombieKills").to_bytes(2, "big"))
    payload.extend(b"zombieKills")
    payload.append(0x04)

    return bytes(payload)


def test_binary_parser_primitives() -> None:
    data = bytes([0xAB]) + (5).to_bytes(2, "big") + (7).to_bytes(4, "big") + struct.pack(">d", 1.5)
    parser = ZomboidBinaryParser(data)

    assert parser.read_byte() == 0xAB
    assert parser.read_short() == 5
    assert parser.read_int() == 7
    assert parser.read_double() == 1.5


def test_parse_character_data_extracts_keywords() -> None:
    parser = ZomboidBinaryParser(_build_blob())
    info = parser.parse_character_data()

    assert info["trait1"] == "Brave"
    assert info["name"] == "Alice"
    assert "zombieKills" in info


def test_get_player_info_reads_local_players(tmp_path: Path) -> None:
    save_path = tmp_path / "Sandbox" / "Alpha"
    save_path.mkdir(parents=True)
    db_path = save_path / "players.db"

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE localPlayers (name TEXT, data BLOB)")
    conn.execute("CREATE TABLE survivors (hours REAL, zombiekills INTEGER)")
    conn.execute(
        "INSERT INTO localPlayers (name, data) VALUES (?, ?)",
        ("Alice", _build_blob()),
    )
    conn.execute(
        "INSERT INTO survivors (hours, zombiekills) VALUES (?, ?)",
        (12.5, 99),
    )
    conn.commit()
    conn.close()

    info = get_player_info(save_path)

    assert info is not None
    assert info["character_name"] == "Alice"
    assert info["hours_survived"] == 12.5
    assert info["zombies_killed"] == 99
    assert "Brave" in info["traits"]


def test_get_player_info_missing_database(tmp_path: Path) -> None:
    save_path = tmp_path / "Sandbox" / "Missing"
    save_path.mkdir(parents=True)

    assert get_player_info(save_path) is None


def test_format_player_info_includes_traits() -> None:
    info = {
        "character_name": "Alice",
        "hours_survived": 8.5,
        "zombies_killed": 44,
        "traits": ["Brave", "Strong"],
    }

    formatted = format_player_info(info)

    assert "Alice" in formatted
    assert "Hours Survived" in formatted
    assert "Traits" in formatted
