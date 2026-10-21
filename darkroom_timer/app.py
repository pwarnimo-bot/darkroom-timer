"""Darkroom timer TUI."""

from __future__ import annotations

import math
import shutil
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
    TextArea,
)

from . import storage
from .bigclock import BigClock
from .models import (
    AGITATION_PRESETS,
    DEFAULT_TIMES,
    STEP_NAMES,
    Agitation,
    Session,
    Step,
    agitation_by_name,
    fmt_time,
    parse_time,
)

CUSTOM = "Custom (set below)"

DEFAULT_AGITATION = {
    "Pre-rinse": "Continuous (rotary / Jobo)",
    "Developer": AGITATION_PRESETS[0].name,
    "Stop bath": "Continuous (rotary / Jobo)",
    "Fixer": AGITATION_PRESETS[0].name,
    "Wash": "None",
    "Rinse aid": "None",
}

DARKROOM_THEME = Theme(
    name="darkroom",
    primary="#d42a2a",
    secondary="#8a1c1c",
    accent="#ff4d4d",
    foreground="#e05050",
    background="#000000",
    surface="#0d0000",
    panel="#1a0505",
    warning="#ff8040",
    error="#ff2020",
    success="#c04040",
    dark=True,
)

BELL_SOUNDS = [
    "/usr/share/sounds/freedesktop/stereo/bell.oga",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
]


def mdc_url(film: str, developer: str = "") -> str:
    """Massive Dev Chart search URL (opened in the browser; the site blocks scripts)."""
    film = film.replace("Ilford ", "").replace("Kodak ", "").replace(" Plus", "")
    developer = developer.split("/")[0].replace("Ilford ", "").replace("Kodak ", "").strip()
    query = {"Film": film, "Developer": developer, "mdc": "Search", "TempUnits": "C", "TimeUnits": "D"}
    return "https://www.digitaltruth.com/devchart.php?" + urlencode(query)


def slug(name: str) -> str:
    return name.lower().replace(" ", "-")


# --------------------------------------------------------------------------
# Modal dialogs
# --------------------------------------------------------------------------


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("y", "yes", "Yes"), Binding("n,escape", "no", "No")]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question)
            with Horizontal(classes="buttons"):
                yield Button("Yes (y)", id="yes", variant="error")
                yield Button("No (n)", id="no", variant="primary")

    @on(Button.Pressed, "#yes")
    def action_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def action_no(self) -> None:
        self.dismiss(False)


class PresetScreen(ModalScreen[dict | None]):
    """Pick a film/developer combination from bundled + user presets."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+o", "open_mdc", "Open Massive Dev Chart"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.presets = storage.load_presets()

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Label("[b]Film / developer presets[/b]  (type to filter, Enter to use)")
            yield Input(placeholder="filter e.g. hp5 ddx", id="filter")
            yield DataTable(cursor_type="row", id="preset-table")
            yield Static(
                "Datasheet times are starting points at 20°C - verify against the "
                "current datasheet. Ctrl+O opens the Massive Dev Chart for the "
                "highlighted film in your browser.",
                classes="hint",
            )

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Film", "EI", "Developer", "Dilution", "Time", "Temp", "Source")
        self.refresh_table("")

    def refresh_table(self, text: str) -> None:
        table = self.query_one(DataTable)
        table.clear()
        words = text.lower().split()
        for i, p in enumerate(self.presets):
            hay = " ".join(str(v) for v in p.values()).lower().replace("-", "")
            if all(w.replace("-", "") in hay for w in words):
                table.add_row(
                    p["film"], p.get("ei", ""), p["developer"], p.get("dilution", ""),
                    p["dev"], f"{p.get('temp', '20')}°C",
                    p.get("ref") if p["source"] != "mine" else "mine",
                    key=str(i),
                )

    @on(Input.Changed, "#filter")
    def filter_changed(self, event: Input.Changed) -> None:
        self.refresh_table(event.value)

    @on(Input.Submitted, "#filter")
    def filter_submitted(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count:
            self.dismiss(self.presets[int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)])

    def on_key(self, event) -> None:
        # Let arrow keys move the table even while typing in the filter.
        if event.key in ("up", "down") and self.focused is self.query_one("#filter"):
            table = self.query_one(DataTable)
            table.action_cursor_up() if event.key == "up" else table.action_cursor_down()
            event.stop()

    @on(DataTable.RowSelected)
    def row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(self.presets[int(event.row_key.value)])

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_open_mdc(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count:
            p = self.presets[int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)]
            webbrowser.open(mdc_url(p["film"], p["developer"]))
            self.notify("Opened Massive Dev Chart in your browser")


class NotesScreen(ModalScreen[Session | None]):
    """Shown after a development (or when editing a log entry): notes + save."""

    BINDINGS = [Binding("ctrl+s", "save", "Save"), Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: Session, title: str = "Development finished") -> None:
        super().__init__()
        self.session = session
        self.title_text = title

    def compose(self) -> ComposeResult:
        s = self.session
        lines = [
            f"[b]{self.title_text}[/b]  ({s.status})",
            f"{s.film} @ EI {s.ei} · {s.developer} {s.dilution} · {s.temperature}°C · {s.rolls} roll(s)",
            "",
        ]
        for step in s.steps:
            actual = step.get("actual")
            actual_txt = fmt_time(actual) if actual is not None else "--:--"
            lines.append(
                f"  {step['name']:<10} planned {fmt_time(step['planned'])}  "
                f"actual {actual_txt}   [dim]{step.get('agitation', '')}[/dim]"
            )
        with Vertical(classes="dialog wide"):
            yield Static("\n".join(lines))
            yield Label("Notes (contrast, density, chemistry age, scene...):")
            yield TextArea(s.notes, id="notes")
            with Horizontal(classes="buttons"):
                yield Button("Save to log (Ctrl+S)", id="save", variant="primary")
                yield Button("Don't save (Esc)", id="cancel")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        self.session.notes = self.query_one(TextArea).text.strip()
        self.dismiss(self.session)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------
# Log screen
# --------------------------------------------------------------------------


class LogScreen(Screen[dict | None]):
    """Browse past developments. Returns a setup dict when 'reuse' is chosen."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("enter", "edit", "View / edit notes", show=True),
        Binding("u", "reuse", "Reuse setup"),
        Binding("d", "delete", "Delete"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Log file: {storage.data_dir() / storage.LOG_FILE}", classes="hint")
        yield DataTable(cursor_type="row", id="log-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Date", "Film", "EI", "Developer", "Dil.", "Temp", "Dev", "Total", "Status", "Notes")
        self.reload()

    def reload(self) -> None:
        self.sessions = storage.load_log()
        table = self.query_one(DataTable)
        table.clear()
        for i, s in reversed(list(enumerate(self.sessions))):
            dev = next((st for st in s.steps if st["name"] == "Developer"), None)
            note = s.notes.replace("\n", " ")
            table.add_row(
                s.started_at[:16].replace("T", " "), s.film, s.ei, s.developer, s.dilution,
                f"{s.temperature}°C", fmt_time(dev["planned"]) if dev else "-",
                fmt_time(s.total_planned), s.status,
                note[:40] + ("…" if len(note) > 40 else ""),
                key=str(i),
            )
        if not self.sessions:
            self.notify("No developments logged yet.")

    def current(self) -> Session | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self.sessions[int(key)]

    @on(DataTable.RowSelected)
    def action_edit(self) -> None:
        s = self.current()
        if s is None:
            return

        def done(result: Session | None) -> None:
            if result is not None:
                storage.update_log_entry(result)
                self.reload()
                self.notify("Notes saved")

        self.app.push_screen(NotesScreen(s, title=s.started_at[:16].replace("T", " ")), done)

    def action_reuse(self) -> None:
        s = self.current()
        if s is None:
            return
        setup = {
            "film": s.film, "ei": s.ei, "developer": s.developer, "dilution": s.dilution,
            "temperature": s.temperature, "rolls": s.rolls,
            "times": {name: "" for name in STEP_NAMES},
            "agitation": {},
            "custom": {},
        }
        for st in s.steps:
            setup["times"][st["name"]] = fmt_time(st["planned"])
            ag = st.get("agitation_params") or {}
            if ag.get("name") and any(a.name == ag["name"] for a in AGITATION_PRESETS):
                setup["agitation"][st["name"]] = ag["name"]
            elif ag:
                setup["agitation"][st["name"]] = CUSTOM
                setup["custom"] = {k: ag.get(k, 0) for k in ("initial", "interval", "duration")}
        self.dismiss(setup)

    def action_delete(self) -> None:
        s = self.current()
        if s is None:
            return

        def done(yes: bool | None) -> None:
            if yes:
                storage.delete_log_entry(s.started_at)
                self.reload()

        self.app.push_screen(ConfirmScreen(f"Delete log entry from {s.started_at[:16]}?"), done)

    def action_back(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------
# Timer screen
# --------------------------------------------------------------------------


class TimerScreen(Screen[None]):
    BINDINGS = [
        Binding("space", "toggle", "Start / pause"),
        Binding("n", "next_step", "Finish step now"),
        Binding("r", "restart_step", "Restart step"),
        Binding("plus,equals_sign", "adjust(30)", "+30s"),
        Binding("minus", "adjust(-30)", "-30s"),
        Binding("a", "toggle_auto", "Auto-advance"),
        Binding("escape,q", "abort", "Abort"),
    ]

    def __init__(self, session: Session, steps: list[Step]) -> None:
        super().__init__()
        self.session = session
        self.steps = steps
        self.idx = 0
        self.state = "ready"  # ready | running | paused | finished
        self.step_elapsed = 0.0
        self.run_started: float | None = None
        self.first_start: float | None = None
        self.was_agitating = False
        self.warned = False
        self.auto_advance = False
        self.actuals: list[float | None] = [None] * len(steps)

    def compose(self) -> ComposeResult:
        yield Header()
        s = self.session
        yield Static(
            f"{s.film or 'Film'} @ EI {s.ei or '?'} · {s.developer or 'developer'} "
            f"{s.dilution} · {s.temperature}°C",
            id="film-line",
        )
        with Horizontal(id="timer-main"):
            with Vertical(id="clocks"):
                yield Label("", id="step-name")
                yield BigClock(id="step-digits")
                yield ProgressBar(show_eta=False, show_percentage=False, id="step-progress")
                yield Static("", id="agitation")
                yield Label("TOTAL REMAINING", classes="caption")
                yield BigClock(id="total-digits")
                yield Static("", id="status")
            yield Static("", id="step-list")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.1, self.tick)
        self.tick()

    # --- time helpers -----------------------------------------------------

    @property
    def step(self) -> Step:
        return self.steps[self.idx]

    def elapsed(self) -> float:
        e = self.step_elapsed
        if self.run_started is not None:
            e += time.monotonic() - self.run_started
        return e

    def remaining_total(self, step_remaining: float) -> float:
        return step_remaining + sum(s.seconds for s in self.steps[self.idx + 1:])

    def beep(self, times: int = 1) -> None:
        for _ in range(times):
            self.app.bell()
        sound = next((p for p in BELL_SOUNDS if Path(p).exists()), None)
        player = shutil.which("paplay") or shutil.which("pw-play")
        if sound and player:
            for i in range(times):
                self.set_timer(i * 0.35, lambda: subprocess.Popen(
                    [player, sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                ))

    # --- main loop ----------------------------------------------------------

    def tick(self) -> None:
        if self.state == "finished":
            return
        step = self.step
        e = self.elapsed()
        remaining = step.seconds - e

        if self.state == "running":
            if remaining <= 0:
                self.finish_step(step.seconds)
                return
            ag = step.agitation
            agitating = bool(ag and ag.is_agitating(e))
            if agitating != self.was_agitating and not (ag and ag.continuous):
                self.beep()
            self.was_agitating = agitating
            if remaining <= 10 and not self.warned and step.seconds > 20:
                self.warned = True
                self.beep(2)

        self.query_one("#step-name", Label).update(
            f"STEP {self.idx + 1}/{len(self.steps)}  ·  {step.name.upper()}"
        )
        self.query_one("#step-digits", BigClock).text = fmt_time(math.ceil(max(remaining, 0)))
        self.query_one("#total-digits", BigClock).text = fmt_time(
            math.ceil(self.remaining_total(max(remaining, 0)))
        )
        self.query_one("#step-progress", ProgressBar).update(total=step.seconds, progress=e)
        self.update_agitation(e)
        self.update_status()
        self.update_step_list()

    def update_agitation(self, e: float) -> None:
        widget = self.query_one("#agitation", Static)
        ag = self.step.agitation
        widget.remove_class("agitate")
        if not ag or ag.name == "None":
            widget.update("no agitation")
        elif self.state != "running":
            widget.update(f"agitation: {ag.describe()}")
        elif ag.is_agitating(e):
            widget.add_class("agitate")
            if ag.continuous:
                widget.update(">>> AGITATE (continuous) <<<")
            else:
                end = ag.initial if e < ag.initial else (e // ag.interval) * ag.interval + ag.duration
                widget.update(f">>> AGITATE <<<   {math.ceil(end - e)}s")
        else:
            nxt = ag.next_agitation_in(e)
            if nxt is None or nxt >= self.step.seconds - e:
                widget.update("rest - no more agitation this step")
            else:
                widget.update(f"rest - next agitation in {fmt_time(math.ceil(nxt))}")

    def update_status(self) -> None:
        wall = f"   ·   elapsed {fmt_time(time.monotonic() - self.first_start)}" if self.first_start else ""
        auto = "   ·   auto-advance ON" if self.auto_advance else ""
        msg = {
            "ready": f"Pour in {self.step.name.upper()} and press SPACE to start",
            "running": "running",
            "paused": "PAUSED - SPACE to resume",
        }[self.state]
        self.query_one("#status", Static).update(msg + wall + auto)

    def update_step_list(self) -> None:
        lines = ["[b]Process[/b]", ""]
        for i, s in enumerate(self.steps):
            if i < self.idx:
                mark, style = "✓", "dim"
            elif i == self.idx:
                mark, style = "▶", "b"
            else:
                mark, style = " ", ""
            line = f"{mark} {s.name:<10} {fmt_time(s.seconds)}"
            lines.append(f"[{style}]{line}[/{style}]" if style else line)
        self.query_one("#step-list", Static).update("\n".join(lines))

    # --- state changes ------------------------------------------------------

    def start_step(self) -> None:
        self.run_started = time.monotonic()
        if self.first_start is None:
            self.first_start = self.run_started
            self.session.started_at = datetime.now().isoformat(timespec="seconds")
        self.state = "running"
        self.was_agitating = bool(self.step.agitation and self.step.agitation.is_agitating(self.step_elapsed))

    def finish_step(self, actual: float) -> None:
        self.actuals[self.idx] = actual
        self.beep(3)
        self.idx += 1
        self.step_elapsed = 0.0
        self.run_started = None
        self.warned = False
        if self.idx >= len(self.steps):
            self.idx = len(self.steps) - 1
            self.complete("completed")
            return
        self.state = "ready"
        self.notify(f"Drain - next: {self.step.name}", timeout=8)
        if self.auto_advance:
            self.start_step()
        self.tick()

    def complete(self, status: str) -> None:
        self.state = "finished"
        s = self.session
        s.status = status
        s.finished_at = datetime.now().isoformat(timespec="seconds")
        if not s.started_at:
            s.started_at = s.finished_at
        s.steps = [
            {
                "name": st.name,
                "planned": st.seconds,
                "actual": None if a is None else round(a),
                "agitation": st.agitation.describe() if st.agitation else "none",
                "agitation_params": st.agitation.__dict__ if st.agitation else None,
            }
            for st, a in zip(self.steps, self.actuals)
        ]

        def saved(result: Session | None) -> None:
            if result is not None:
                storage.append_log(result)
                self.app.notify("Saved to log")
            self.dismiss(None)

        self.app.push_screen(NotesScreen(s, "Development finished" if status == "completed" else "Development aborted"), saved)

    # --- actions ------------------------------------------------------------

    def action_toggle(self) -> None:
        if self.state in ("ready", "paused"):
            self.start_step()
        elif self.state == "running":
            self.step_elapsed = self.elapsed()
            self.run_started = None
            self.state = "paused"
        self.tick()

    def action_next_step(self) -> None:
        if self.state != "finished":
            self.finish_step(self.elapsed())

    def action_restart_step(self) -> None:
        if self.state == "finished":
            return
        self.step_elapsed = 0.0
        self.run_started = time.monotonic() if self.state == "running" else None
        self.warned = False
        self.tick()

    def action_adjust(self, delta: int) -> None:
        if self.state == "finished":
            return
        new = self.step.seconds + delta
        if new <= self.elapsed() + 1:
            return
        self.step.seconds = new
        self.notify(f"{self.step.name}: now {fmt_time(new)}")
        self.tick()

    def action_toggle_auto(self) -> None:
        self.auto_advance = not self.auto_advance
        self.notify(f"Auto-advance {'on' if self.auto_advance else 'off'}")
        self.tick()

    def action_abort(self) -> None:
        if self.state == "finished":
            return

        def done(yes: bool | None) -> None:
            if not yes:
                return
            if self.state == "running" or self.step_elapsed:
                self.actuals[self.idx] = self.elapsed()
            self.run_started = None
            if self.first_start is None:
                self.dismiss(None)  # nothing happened yet, nothing to log
            else:
                self.complete("aborted")

        self.app.push_screen(ConfirmScreen("Abort this development?"), done)


# --------------------------------------------------------------------------
# Setup screen
# --------------------------------------------------------------------------


class SetupScreen(Screen[None]):
    BINDINGS = [
        Binding("f2", "presets", "Presets", priority=True),
        Binding("f3", "save_preset", "Save as preset", priority=True),
        Binding("f4", "log", "Log", priority=True),
        Binding("f5", "start", "START", priority=True),
        Binding("ctrl+o", "open_mdc", "Massive Dev Chart", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        ag_options = [(a.name, a.name) for a in AGITATION_PRESETS] + [(CUSTOM, CUSTOM)]
        with VerticalScroll(id="setup"):
            with Horizontal(classes="fields"):
                for fid, label, placeholder, cls in [
                    ("film", "Film", "e.g. Ilford HP5 Plus", "wide"),
                    ("ei", "EI / ISO", "400", ""),
                    ("developer", "Developer", "e.g. Ilford DD-X", "wide"),
                    ("dilution", "Dilution", "1+4", ""),
                    ("temperature", "Temp °C", "20", ""),
                    ("rolls", "Rolls", "1", ""),
                ]:
                    with Vertical(classes=f"field {cls}"):
                        yield Label(label)
                        yield Input(placeholder=placeholder, id=fid)

            yield Label("[b]Process steps[/b] · time as 7:30, 7m30s, 45s or minutes (7.5); empty or 0 = skip",
                        classes="section")
            with Grid(id="steps"):
                for name in STEP_NAMES:
                    yield Label(name, classes="step-label")
                    yield Input(placeholder="skip", id=f"time-{slug(name)}", classes="time")
                    yield Label("", id=f"hint-{slug(name)}", classes="time-hint")
                    yield Select(ag_options, allow_blank=False, value=DEFAULT_AGITATION[name],
                                 id=f"ag-{slug(name)}")

            with Horizontal(id="custom-row"):
                yield Label("Custom agitation:", classes="step-label")
                yield Label("first")
                yield Input("30", id="custom-initial", classes="small")
                yield Label("s, then for")
                yield Input("10", id="custom-duration", classes="small")
                yield Label("s every")
                yield Input("60", id="custom-interval", classes="small")
                yield Label("s  (every 0 = stand)")

            yield Static("", id="total")
            with Horizontal(classes="buttons"):
                yield Button("Presets (F2)", id="presets")
                yield Button("Save as preset (F3)", id="save-preset")
                yield Button("Log (F4)", id="log")
                yield Button("START (F5)", id="start", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        setup = storage.load_last_setup()
        if not setup:
            setup = {"temperature": "20", "rolls": "1",
                     "times": {k: fmt_time(v) if v else "" for k, v in DEFAULT_TIMES.items()}}
        self.apply_setup(setup)
        self.query_one("#film", Input).focus()

    # --- form <-> dict ------------------------------------------------------

    def apply_setup(self, setup: dict) -> None:
        for fid in ("film", "ei", "developer", "dilution", "temperature", "rolls"):
            if fid in setup:
                self.query_one(f"#{fid}", Input).value = str(setup[fid])
        for name, value in setup.get("times", {}).items():
            if name in STEP_NAMES:
                self.query_one(f"#time-{slug(name)}", Input).value = value
        for name, value in setup.get("agitation", {}).items():
            if name in STEP_NAMES:
                self.query_one(f"#ag-{slug(name)}", Select).value = value
        for key, value in setup.get("custom", {}).items():
            self.query_one(f"#custom-{key}", Input).value = str(value)
        self.update_hints()

    def collect_setup(self) -> dict:
        return {
            **{fid: self.query_one(f"#{fid}", Input).value.strip()
               for fid in ("film", "ei", "developer", "dilution", "temperature", "rolls")},
            "times": {n: self.query_one(f"#time-{slug(n)}", Input).value.strip() for n in STEP_NAMES},
            "agitation": {n: self.query_one(f"#ag-{slug(n)}", Select).value for n in STEP_NAMES},
            "custom": {k: self.query_one(f"#custom-{k}", Input).value.strip()
                       for k in ("initial", "duration", "interval")},
        }

    def custom_agitation(self) -> Agitation | None:
        try:
            vals = {k: int(self.query_one(f"#custom-{k}", Input).value or 0)
                    for k in ("initial", "duration", "interval")}
        except ValueError:
            return None
        if vals["interval"] and vals["duration"] >= vals["interval"]:
            return None
        return Agitation("Custom", **vals)

    def build_steps(self) -> list[Step] | None:
        steps = []
        for name in STEP_NAMES:
            secs = parse_time(self.query_one(f"#time-{slug(name)}", Input).value)
            if secs is None:
                self.notify(f"Invalid time for {name}", severity="error")
                return None
            if not secs:
                continue
            ag_name = self.query_one(f"#ag-{slug(name)}", Select).value
            if ag_name == CUSTOM:
                ag = self.custom_agitation()
                if ag is None:
                    self.notify("Invalid custom agitation (duration must be < interval)", severity="error")
                    return None
            else:
                ag = agitation_by_name(ag_name)
            steps.append(Step(name, secs, ag))
        return steps

    def update_hints(self) -> None:
        total = 0
        for name in STEP_NAMES:
            secs = parse_time(self.query_one(f"#time-{slug(name)}", Input).value)
            hint = self.query_one(f"#hint-{slug(name)}", Label)
            if secs is None:
                hint.update("[red]invalid[/red]")
            else:
                hint.update(fmt_time(secs) if secs else "[dim]skipped[/dim]")
                total += secs
        self.query_one("#total", Static).update(f"Total process time: [b]{fmt_time(total)}[/b]")

    @on(Input.Changed, ".time")
    def time_changed(self) -> None:
        self.update_hints()

    # --- actions ------------------------------------------------------------

    @on(Button.Pressed, "#presets")
    def action_presets(self) -> None:
        def chosen(p: dict | None) -> None:
            if not p:
                return
            setup = {
                "film": p["film"], "ei": p.get("ei", ""), "developer": p["developer"],
                "dilution": p.get("dilution", ""), "temperature": p.get("temp", "20"),
                "times": {"Developer": p["dev"]},
            }
            if p.get("agitation_custom"):
                setup["agitation"] = {"Developer": CUSTOM}
                setup["custom"] = p["agitation_custom"]
            elif p.get("agitation"):
                setup["agitation"] = {"Developer": p["agitation"]}
            self.apply_setup(setup)
            self.notify(f"Loaded {p['film']} in {p['developer']} {p.get('dilution', '')} - "
                        f"developer {p['dev']} ({p.get('ref', 'preset')})")

        self.app.push_screen(PresetScreen(), chosen)

    @on(Button.Pressed, "#save-preset")
    def action_save_preset(self) -> None:
        setup = self.collect_setup()
        dev = parse_time(setup["times"]["Developer"])
        if not setup["film"] or not setup["developer"] or not dev:
            self.notify("Need film, developer and a developer time to save a preset", severity="error")
            return
        preset = {
            "film": setup["film"], "ei": setup["ei"], "developer": setup["developer"],
            "dilution": setup["dilution"], "dev": fmt_time(dev), "temp": setup["temperature"] or "20",
            "agitation": setup["agitation"]["Developer"], "ref": "mine",
        }
        if preset["agitation"] == CUSTOM:
            preset["agitation_custom"] = setup["custom"]
        storage.save_user_preset(preset)
        self.notify(f"Saved preset: {preset['film']} / {preset['developer']} {preset['dilution']}")

    @on(Button.Pressed, "#log")
    def action_log(self) -> None:
        def back(setup: dict | None) -> None:
            if setup:
                self.apply_setup(setup)
                self.notify("Loaded setup from log")

        self.app.push_screen(LogScreen(), back)

    def action_open_mdc(self) -> None:
        film = self.query_one("#film", Input).value.strip()
        if not film:
            self.notify("Enter a film name first", severity="warning")
            return
        webbrowser.open(mdc_url(film, self.query_one("#developer", Input).value.strip()))
        self.notify("Opened Massive Dev Chart in your browser")

    @on(Button.Pressed, "#start")
    def action_start(self) -> None:
        steps = self.build_steps()
        if steps is None:
            return
        if not steps:
            self.notify("Enter at least one step time", severity="error")
            return
        setup = self.collect_setup()
        storage.save_last_setup(setup)
        session = Session(
            film=setup["film"], ei=setup["ei"], developer=setup["developer"],
            dilution=setup["dilution"], temperature=setup["temperature"] or "20",
            rolls=setup["rolls"] or "1",
        )
        self.app.push_screen(TimerScreen(session, steps))


# --------------------------------------------------------------------------


class DarkroomTimer(App):
    TITLE = "Darkroom Timer"
    CSS_PATH = "app.tcss"

    def on_mount(self) -> None:
        self.register_theme(DARKROOM_THEME)
        self.theme = "darkroom"
        self.push_screen(SetupScreen())


def main() -> None:
    DarkroomTimer().run()
