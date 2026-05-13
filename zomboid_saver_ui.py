"""Compatibility launcher for the packaged UI module.

This keeps legacy commands working while the implementation lives in
zomboid_saver.ui for packaging.
"""

from __future__ import annotations

from zomboid_saver.ui import main


if __name__ == "__main__":
    main()
