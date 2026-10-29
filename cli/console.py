"""
Rich console singleton and shared UI helpers for the AeroSOuDA CLI.
"""
from __future__ import annotations

import sys

from questionary import Style
from rich.console import Console
from rich.panel import Panel

console = Console()

custom_style = Style([
    ("pointer", "bg:white fg:black bold"),
    ("highlighted", "bg:white fg:black bold"),
    ("selected", "bg:white fg:black bold"),
])


def fatal(message: str) -> None:
    """Print a red error panel and exit with code 1."""
    console.print()
    console.print(Panel(message, title="[bold red]❌ Erro[/]", border_style="red"))
    sys.exit(1)
