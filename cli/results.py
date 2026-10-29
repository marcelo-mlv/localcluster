"""
Results display: show the final aggregate value and output file paths.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from rich.panel import Panel
from rich.text import Text

from .config import OUTPUTS_DIR
from .console import console


def show_results(summary: Optional[Dict[str, Any]], csv_name: str) -> None:
    """Print the final results panel with aggregate value and output paths."""
    stem = Path(csv_name).stem + "_aggregated"
    out_csv = OUTPUTS_DIR / f"{stem}.csv"
    out_png = OUTPUTS_DIR / f"{stem}.png"
    out_json = OUTPUTS_DIR / f"{stem}_summary.json"

    if summary is None and out_json.exists():
        try:
            with open(out_json, encoding="utf-8") as fh:
                summary = json.load(fh)
        except Exception:
            pass

    if summary is None:
        console.print(Panel(
            "O processamento foi concluído mas não foi possível ler o sumário.\n\n"
            f"Verifique manualmente os arquivos em:\n  {OUTPUTS_DIR}",
            title="[bold yellow]⚠  Resultados parciais[/]",
            border_style="yellow",
        ))
        return

    batch = summary.get("batch_aggregates", {})
    agg_type = next((k for k in batch if k not in ("n_points", "reason")), None)
    agg_value = batch.get(agg_type)
    n_points = batch.get("n_points", 0)
    reason = batch.get("reason") or ""

    if isinstance(agg_value, float):
        agg_str = f"[bold green]{agg_value:.4f}[/]"
    elif agg_value is None:
        agg_str = "[yellow]N/A[/]" + (f" [dim]({reason})[/]" if reason else "")
    else:
        agg_str = f"[bold]{agg_value}[/]"

    files_exist = []
    for p in [out_csv, out_png, out_json]:
        marker = "[green]✓[/]" if p.exists() else "[dim]—[/]"
        files_exist.append(f"  {marker} {p}")

    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold green]Processamento distribuído finalizado![/]\n\n"
            f"[bold]Cenário:[/]         {summary.get('scenario', '?')}\n"
            f"[bold]Pontos gerados:[/]  {n_points}\n"
            f"[bold]{agg_type or 'Valor agregado'}:[/]  {agg_str}\n\n"
            "[bold]Arquivos de saída:[/]\n" + "\n".join(files_exist)
        ),
        title="[bold white]✅ Resultados[/]",
        border_style="green",
        padding=(1, 2),
    ))
