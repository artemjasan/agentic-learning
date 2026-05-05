from rich.panel import Panel
from rich.text import Text

from pgvis.core import console

PREVIEW_COUNT = 3


class PanelBuilder:
    def __init__(self) -> None:
        self.lines: list[Text | str] = []

    def add(self, line: Text | str) -> None:
        self.lines.append(line)

    def blank(self) -> None:
        self.lines.append("")

    def print(
        self, *, title: str = "", subtitle: str = "",
        border_style: str = "blue", padding: tuple[int, int] = (1, 2),
    ) -> None:
        content = Text()
        for line in self.lines:
            if isinstance(line, Text):
                content.append_text(line)
            else:
                content.append(str(line))
            content.append("\n")

        panel = Panel(
            content,
            title=title or None,
            subtitle=subtitle or None,
            border_style=border_style,
            padding=padding,
        )
        console.print(panel)


def section_bar(offset: int, label: str, info: str, style: str) -> Text:
    line = Text()
    line.append(f"  0x{offset:04X}", style="dim italic")
    line.append("  ┃ ", style=f"bold {style}")
    line.append(f" {label} ", style=f"bold {style}")
    line.append(f" ({info})", style="dim")
    pad = max(0, 55 - len(label) - len(info))
    line.append(" " + "─" * pad, style="dim")
    return line


def ellipsis(count: int) -> Text:
    line = Text()
    line.append(f"  {'':>6}    ", style="dim")
    line.append(f"    ⋮  ({count} more)", style="dim italic")
    return line


def centered_dim(text: str) -> Text:
    return Text(f"  {'':>6}    {text}", style="dim")


def pick_preview(items: list) -> list:
    if len(items) <= PREVIEW_COUNT * 2 + 1:
        return items
    return items[:PREVIEW_COUNT] + [None] + items[-PREVIEW_COUNT:]


def fmt_cell(val) -> str:
    if val is None:
        return "∅"
    if isinstance(val, bool):
        return str(val).lower()
    return str(val)
