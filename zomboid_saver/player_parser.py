"""Lightweight helpers for extracting high-level player information.

The binary payload stored in ``players.db`` is largely undocumented.  The
helpers in this module perform opportunistic parsing so the UI can display a
few friendly details (name, traits, etc.) while tolerating format changes.
"""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional


class ZomboidBinaryParser:
    """Very small binary reader used to spot human-readable fields."""

    def __init__(self, binary_data: bytes) -> None:
        self.data: bytes = binary_data
        self.position: int = 0

    def read_byte(self) -> int:
        """Read a single byte"""
        if self.position >= len(self.data):
            return 0
        byte = self.data[self.position]
        self.position += 1
        return byte

    def read_short(self) -> int:
        """Read a 2-byte short integer"""
        if self.position + 2 > len(self.data):
            return 0
        value = struct.unpack(">H", self.data[self.position : self.position + 2])[0]
        self.position += 2
        return value

    def read_int(self) -> int:
        """Read a 4-byte integer"""
        if self.position + 4 > len(self.data):
            return 0
        value = struct.unpack(">I", self.data[self.position : self.position + 4])[0]
        self.position += 4
        return value

    def read_double(self) -> float:
        """Read an 8-byte double"""
        if self.position + 8 > len(self.data):
            return 0.0
        value = struct.unpack(">d", self.data[self.position : self.position + 8])[0]
        self.position += 8
        return value

    def read_string(self) -> str:
        """Read a length-prefixed string"""
        length = self.read_short()
        if length == 0 or self.position + length > len(self.data):
            return ""
        string_bytes = self.data[self.position : self.position + length]
        self.position += length
        try:
            return string_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return string_bytes.decode("latin-1", errors="ignore")

    def read_value_by_type(self, value_type: int) -> Any:
        """Read a value based on its type identifier"""
        if value_type == 0x00:
            return None
        elif value_type == 0x01:
            return self.read_double()
        elif value_type == 0x02:
            return self.read_string()
        elif value_type == 0x03:
            return None
        elif value_type == 0x04:
            return True
        elif value_type == 0x05:
            return False
        else:
            return None

    def parse_character_data(self) -> Dict[str, Any]:
        """Parse character data from binary format"""
        character_info: Dict[str, Any] = {}

        self.position = 0

        while self.position < len(self.data) - 10:
            byte = self.read_byte()

            if byte != 0x02:
                continue

            length = self.read_short()
            if not (1 < length < 200 and self.position + length <= len(self.data)):
                continue

            string_bytes = self.data[self.position : self.position + length]
            self.position += length

            try:
                key = string_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue

            value_type = self.read_byte()
            value = self.read_value_by_type(value_type)

            keyword_targets = (
                "trait",
                "profession",
                "name",
                "surname",
                "forename",
                "hour",
                "zombie",
                "kill",
                "strength",
                "fitness",
            )
            if any(keyword in key.lower() for keyword in keyword_targets):
                character_info[key] = value

        return character_info


def get_player_info(save_path: Path) -> Optional[Dict[str, Any]]:
    """
    Extract player information from a Project Zomboid save.

    Args:
        save_path: Path to the save folder

    Returns:
        Dictionary with player information or None if not found
    """
    db_path = save_path / "players.db"

    if not db_path.exists():
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT name, data FROM localPlayers LIMIT 1")
        row = cursor.fetchone()

        if row:
            character_name = row[0]
            binary_data = row[1]

            parser = ZomboidBinaryParser(binary_data)
            parsed_data = parser.parse_character_data()

            traits: List[str] = []
            for key, value in parsed_data.items():
                if "trait" in key.lower() and value:
                    traits.append(value)

            hours = 0
            zombies = 0
            try:
                cursor.execute("SELECT hours, zombiekills FROM survivors LIMIT 1")
                survivor_row = cursor.fetchone()
                if survivor_row:
                    hours = survivor_row[0] if survivor_row[0] else 0
                    zombies = survivor_row[1] if survivor_row[1] else 0
            except sqlite3.Error:
                pass

            conn.close()

            return {
                "character_name": character_name,
                "hours_survived": hours,
                "zombies_killed": zombies,
                "traits": traits,
                "extra_data": parsed_data,
            }

        cursor.execute("SELECT hours, zombiekills FROM survivors LIMIT 1")
        row = cursor.fetchone()
        if row:
            conn.close()
            return {
                "character_name": "Unknown",
                "hours_survived": row[0] if row[0] else 0,
                "zombies_killed": row[1] if row[1] else 0,
                "traits": [],
            }

        conn.close()
        return None

    except Exception as exc:
        print(f"Error reading player data: {exc}")
        return None


def format_player_info(info: Dict[str, Any]) -> str:
    """Format player info for display"""
    if not info:
        return "No player data available"

    lines = [
        f"Character: {info.get('character_name', 'Unknown')}",
        f"Hours Survived: {info.get('hours_survived', 0):.1f}",
        f"Zombies Killed: {info.get('zombies_killed', 0)}",
    ]

    traits = info.get("traits", [])
    if traits:
        lines.append(f"Traits: {', '.join(str(t) for t in traits)}")

    return "\n".join(lines)


def _main() -> None:
    import os

    save_path = Path(os.path.expanduser(r"~\Zomboid\Saves\Sandbox\2024-12-29_14-37-29"))
    info = get_player_info(save_path)
    if info:
        print(format_player_info(info))
        print("\nExtra data found:", info.get("extra_data", {}))


if __name__ == "__main__":
    _main()
