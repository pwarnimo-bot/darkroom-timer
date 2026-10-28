"""Regenerate the SVG screenshots in docs/screenshots/.

Runs the app headlessly against a throwaway data directory so your own log
and presets are never touched:

    .venv/bin/python scripts/screenshots.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
SIZE = (120, 40)

SAMPLE_LOG = [
    {
        "film": "Ilford HP5 Plus", "ei": "400", "developer": "Ilford ID-11", "dilution": "stock",
        "temperature": "20", "rolls": "2", "notes": "Good density, slightly flat in the shadows.",
        "started_at": "2026-10-12T19:04:10", "finished_at": "2026-10-12T19:21:40",
        "status": "completed",
        "steps": [{"name": "Developer", "planned": 450, "actual": 450}, {"name": "Fixer", "planned": 300, "actual": 300}],
    },
    {
        "film": "Kodak Tri-X 400", "ei": "1600", "developer": "Kodak HC-110", "dilution": "B",
        "temperature": "20", "rolls": "1", "notes": "Pushed two stops, night street.",
        "started_at": "2026-10-20T21:12:03", "finished_at": "2026-10-20T21:31:55",
        "status": "completed",
        "steps": [{"name": "Developer", "planned": 780, "actual": 780}, {"name": "Fixer", "planned": 300, "actual": 300}],
    },
]

SETUP = {
    "film": "Ilford HP5 Plus", "ei": "400", "developer": "Ilford ID-11", "dilution": "stock",
    "temperature": "20", "rolls": "2",
    "times": {"Pre-rinse": "1:00", "Developer": "7:30", "Stop bath": "1:00",
              "Fixer": "5:00", "Wash": "10:00", "Rinse aid": "1:00"},
}


async def main() -> None:
    data = Path(tempfile.mkdtemp(prefix="darkroom-shots-"))
    os.environ["XDG_DATA_HOME"] = str(data)
    (data / "darkroom-timer").mkdir()
    (data / "darkroom-timer" / "log.json").write_text(json.dumps(SAMPLE_LOG))
    (data / "darkroom-timer" / "last_setup.json").write_text(json.dumps(SETUP))

    sys.path.insert(0, str(ROOT))
    from darkroom_timer.app import DarkroomTimer, TimerScreen

    OUT.mkdir(parents=True, exist_ok=True)
    app = DarkroomTimer()
    async with app.run_test(size=SIZE) as pilot:
        def shot(name: str) -> None:
            path = Path(app.save_screenshot(filename=f"{name}.svg", path=str(OUT)))
            # Show the real default location rather than the temp dir.
            path.write_text(path.read_text().replace(str(data), "~/.local/share"))

        await pilot.pause()
        shot("setup")

        await pilot.press("f2")
        await pilot.pause()
        await pilot.press(*"hp5")
        await pilot.pause()
        shot("presets")
        await pilot.press("escape")

        await pilot.press("f4")
        await pilot.pause()
        shot("log")
        await pilot.press("escape")

        await pilot.press("f5")
        await pilot.pause()
        # Jump to the developer step, 1:03 in, so the agitation banner is showing.
        timer = app.screen
        assert isinstance(timer, TimerScreen)
        timer.idx, timer.actuals[0] = 1, 60
        timer.state = "running"
        timer.run_started = time.monotonic() - 63
        timer.first_start = timer.run_started
        timer.was_agitating = True
        timer.tick()
        await pilot.pause()
        shot("timer")


if __name__ == "__main__":
    asyncio.run(main())
