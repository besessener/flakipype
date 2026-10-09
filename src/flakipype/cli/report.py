from rich.console import Console
from rich.table import Table
from rich.text import Text

from flakipype.setup.doctor import Check, CheckStatus

_MARKS = {
    CheckStatus.OK: Text("✔", style="bold green"),
    CheckStatus.WARNING: Text("!", style="bold yellow"),
    CheckStatus.FAILED: Text("✘", style="bold red"),
}


def checks_table(checks: list[Check]) -> Table:
    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column(width=1)
    table.add_column(style="bold", no_wrap=True)
    table.add_column(overflow="fold")
    for check in checks:
        detail = Text(check.detail)
        if check.next_step:
            detail.append(f"\n→ {check.next_step}", style="cyan")
        table.add_row(_MARKS[check.status], check.name, detail)
    return table


def print_checks(console: Console, checks: list[Check]) -> bool:
    """Print the checks; True when none failed."""
    console.print(checks_table(checks))
    return all(check.status is not CheckStatus.FAILED for check in checks)
