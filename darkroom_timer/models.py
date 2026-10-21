"""Core data types: process steps, agitation schemes and time parsing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

STEP_NAMES = ["Pre-rinse", "Developer", "Stop bath", "Fixer", "Wash", "Rinse aid"]

# Defaults for a typical Ilford-style process (seconds). 0 = step skipped.
DEFAULT_TIMES = {
    "Pre-rinse": 0,
    "Developer": 0,
    "Stop bath": 60,
    "Fixer": 300,
    "Wash": 600,
    "Rinse aid": 60,
}


@dataclass
class Agitation:
    """Agitate for `initial` s at the start, then for `duration` s every `interval` s.

    interval == 0 means no agitation after the initial period (stand development).
    continuous == True means agitate the whole time.
    """

    name: str
    initial: int = 0
    interval: int = 0
    duration: int = 0
    continuous: bool = False

    def describe(self) -> str:
        if self.continuous:
            return "continuous"
        parts = []
        if self.initial:
            parts.append(f"first {self.initial}s")
        if self.interval:
            parts.append(f"then {self.duration}s every {fmt_time(self.interval)}")
        return ", ".join(parts) or "none"

    def is_agitating(self, elapsed: float) -> bool:
        if self.continuous:
            return True
        if elapsed < self.initial:
            return True
        if self.interval and elapsed >= self.interval:
            return (elapsed % self.interval) < self.duration
        return False

    def next_agitation_in(self, elapsed: float) -> float | None:
        """Seconds until the next agitation window starts, or None if there is none."""
        if self.continuous or not self.interval:
            return None
        nxt = (int(elapsed // self.interval) + 1) * self.interval
        return nxt - elapsed


AGITATION_PRESETS: list[Agitation] = [
    Agitation("Ilford: 10s first, 10s every minute", 10, 60, 10),
    Agitation("Kodak: 30s first, 5s every 30s", 30, 30, 5),
    Agitation("30s first, 10s every minute", 30, 60, 10),
    Agitation("30s first, 10s every 2 minutes", 30, 120, 10),
    Agitation("Continuous (rotary / Jobo)", continuous=True),
    Agitation("Stand: 30s first, then none", 30, 0, 0),
    Agitation("Semi-stand: 30s first, 10s every 30 min", 30, 1800, 10),
    Agitation("None", 0, 0, 0),
]


def agitation_by_name(name: str) -> Agitation:
    for a in AGITATION_PRESETS:
        if a.name == name:
            return a
    return AGITATION_PRESETS[0]


@dataclass
class Step:
    name: str
    seconds: int
    agitation: Agitation | None = None


@dataclass
class Session:
    """One film development: what was planned, what actually happened, notes."""

    film: str = ""
    ei: str = ""
    developer: str = ""
    dilution: str = ""
    temperature: str = "20"
    rolls: str = "1"
    notes: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = "planned"  # planned | completed | aborted
    steps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def total_planned(self) -> int:
        return sum(s.get("planned", 0) for s in self.steps)


_TIME_RE = re.compile(r"^\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?\s*$", re.I)


def parse_time(text: str) -> int | None:
    """Parse a duration into seconds.

    Accepts "7:30", "7m30s", "45s", "7m", or a plain number of minutes ("7", "7.5").
    Empty input means 0 (step skipped). Returns None if the input is invalid.
    """
    text = text.strip().lower()
    if not text:
        return 0
    if ":" in text:
        mins, _, secs = text.partition(":")
        if mins.strip().isdigit() and secs.strip().isdigit() and int(secs) < 60:
            return int(mins) * 60 + int(secs)
        return None
    try:
        return round(float(text.replace(",", ".")) * 60)
    except ValueError:
        pass
    m = _TIME_RE.match(text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    return None


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
