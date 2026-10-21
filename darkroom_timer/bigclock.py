"""Large block-digit clock that scales to the space it is given."""

from __future__ import annotations

from rich.segment import Segment
from textual.reactive import reactive
from textual.strip import Strip
from textual.widget import Widget

FONT = {
    "0": ["█████", "█   █", "█   █", "█   █", "█████"],
    "1": ["  █  ", " ██  ", "  █  ", "  █  ", "█████"],
    "2": ["█████", "    █", "█████", "█    ", "█████"],
    "3": ["█████", "    █", " ████", "    █", "█████"],
    "4": ["█   █", "█   █", "█████", "    █", "    █"],
    "5": ["█████", "█    ", "█████", "    █", "█████"],
    "6": ["█████", "█    ", "█████", "█   █", "█████"],
    "7": ["█████", "    █", "   █ ", "  █  ", "  █  "],
    "8": ["█████", "█   █", "█████", "█   █", "█████"],
    "9": ["█████", "█   █", "█████", "    █", "█████"],
    ":": ["   ", " █ ", "   ", " █ ", "   "],
}
ROWS = 5


class BigClock(Widget):
    text: reactive[str] = reactive("00:00")

    def _rows(self, sx: int, sy: int) -> list[str]:
        rows = []
        for r in range(ROWS):
            line = (" " * sx).join(
                "".join(ch * sx for ch in FONT[c][r]) for c in self.text if c in FONT
            )
            rows.extend([line] * sy)
        return rows

    def _layout(self) -> list[str]:
        width, height = self.size
        base = len(self._rows(1, 1)[0])
        rows = [self.text]
        # Terminal cells are ~twice as tall as wide, so prefer sx ≈ 2*sy.
        for sy in range(max(1, height // ROWS), 0, -1):
            fitting = [sx for sx in range(2 * sy, sy - 1, -1)
                       if base * sx + (len(self.text) - 1) * (sx - 1) <= width]
            if fitting:
                rows = self._rows(fitting[0], sy)
                break
        top = max(0, (height - len(rows)) // 2)
        left = max(0, (width - len(rows[0])) // 2)
        return [""] * top + [" " * left + r for r in rows]

    def render_line(self, y: int) -> Strip:
        if y == 0 or not hasattr(self, "_lines"):
            self._lines = self._layout()
        line = self._lines[y] if y < len(self._lines) else ""
        return Strip([Segment(line.ljust(self.size.width), self.rich_style)])
