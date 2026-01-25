import time
from datetime import timedelta
from typing import Dict, Optional

from rich.console import Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)


class BatchProgressManager:
    """Minimal progress manager for concurrent event processing."""

    def __init__(self, total: int):
        self.total = max(1, total)
        self._start_ts = time.time()
        self._overall = Progress(
            SpinnerColumn(spinner_name="dots2"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("{task.fields[eta]}"),
        )
        self._detail = Progress(
            SpinnerColumn(spinner_name="dots2"),
            TextColumn("{task.fields[label]}"),
            TextColumn("{task.fields[status]}"),
            TimeElapsedColumn(),
        )
        self._overall_task: TaskID = self._overall.add_task("Overall", total=self.total, eta="")
        self._task_map: Dict[str, TaskID] = {}
        self.renderable = Group(self._detail, self._overall)

    def _eta_text(self, completed: int) -> str:
        try:
            elapsed = time.time() - self._start_ts
            remaining = elapsed / max(1, completed) * max(0, self.total - completed)
            return f"eta: {timedelta(seconds=int(remaining))}"
        except Exception:
            return ""

    def start_event(self, label: str):
        if label in self._task_map:
            return
        self._task_map[label] = self._detail.add_task(
            description=f"Task {label}",
            status="init",
            total=None,
            label=label,
        )

    def update_event(self, label: str, status: str):
        tid = self._task_map.get(label)
        if tid is None:
            return
        self._detail.update(tid, status=status)

    def end_event(self, label: str, status: Optional[str] = None):
        tid = self._task_map.get(label)
        if tid is not None:
            try:
                self._detail.remove_task(tid)
            except Exception:
                pass
        completed = min(self.total, self._overall.tasks[0].completed + 1)  # type: ignore[index]
        self._overall.update(self._overall_task, advance=1, eta=self._eta_text(completed), description=status or "Overall")

    def live(self) -> Live:
        return Live(self.renderable, refresh_per_second=4, transient=False)
