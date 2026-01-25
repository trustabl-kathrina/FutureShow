from agents.lifecycle import RunHooks
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box
import json
from typing import Optional

try:
    from futureshow.utils.batch_progress import BatchProgressManager  # type: ignore
except Exception:
    BatchProgressManager = None  # type: ignore


class Logs(RunHooks):
    def __init__(
        self,
        debug: bool,
        max_steps: int | None = None,
        label: str = "",
        progress_mgr: Optional["BatchProgressManager"] = None,
    ):
        super().__init__()
        self.debug = debug
        self.max_steps = max_steps
        self.label = label
        self.step = 0
        self.console = Console(highlight=True)
        self.progress_mgr = progress_mgr

    def set_label(self, label: str):
        self.label = label or ""

    async def on_agent_start(self, ctx, agent):
        self.step = 0
        if self.debug:
            self.console.print(
                Panel(
                    Text(f"Agent start: {agent.name}", style="bold magenta"),
                    box=box.ROUNDED,
                    border_style="magenta",
                )
            )

    async def on_llm_start(self, ctx, agent, system_prompt, input_items):
        self.step += 1
        bar = ""
        if self.max_steps:
            width = 18
            frac = min(1.0, max(0.0, self.step / self.max_steps))
            filled = int(width * frac)
            bar = "[" + "#" * filled + "-" * (width - filled) + f"] {self.step}/{self.max_steps}"
        # always update progress manager if provided
        if self.progress_mgr:
            try:
                status = f"Step {self.step}"
                if self.max_steps:
                    status = f"Step {self.step}/{self.max_steps}"
                self.progress_mgr.update_event(self.label or "event", status)
            except Exception:
                pass
        if not self.debug:
            return
        self.console.print(
            Panel(
                Text(
                    f"{self.label + ' ' if self.label else ''}LLM call {self.step}{' ' + bar if bar else ''} → requests={ctx.usage.requests}  total_tokens={ctx.usage.total_tokens}",
                    style="bold cyan",
                ),
                box=box.SQUARE,
                border_style="cyan",
            )
        )

    async def on_tool_start(self, ctx, agent, tool):
        if not self.debug:
            return
        args_preview = ""
        try:
            raw_args = getattr(ctx, "tool_arguments", None)
            if raw_args:
                if isinstance(raw_args, (bytes, bytearray)):
                    raw_args = raw_args.decode("utf-8", errors="ignore")
                if isinstance(raw_args, str):
                    try:
                        parsed = json.loads(raw_args)
                        raw_args = json.dumps(parsed, ensure_ascii=False)
                    except Exception:
                        pass
                args_text = str(raw_args)
                args_preview = args_text[:200] + ("..." if len(args_text) > 200 else "")
        except Exception:
            args_preview = ""

        content = f"▶ Tool → {tool.name}"
        if args_preview:
            content = f"{content}\nargs: {args_preview}"

        self.console.print(
            Panel(Text(content, style="bold yellow"), box=box.MINIMAL, border_style="yellow")
        )

    async def on_tool_end(self, ctx, agent, tool, result: str):
        if not self.debug:
            return
        preview = (result or "")
        if isinstance(preview, str) is False:
            preview = str(preview)

        preview = preview[:200] + ("..." if len(preview) > 200 else "")
        self.console.print(
            Panel(
                Text(f"{tool.name} output:\n{preview}", style="green"),
                box=box.MINIMAL,
                border_style="green",
            )
        )
