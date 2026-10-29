"""
CSV inspection: validate required columns and discover entity types + fields.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import pandas as pd
from rich.table import Table

from .config import REQUIRED_COLUMNS, SKIP_FIELD_FRAGMENTS
from .console import console, fatal


def _extract_leaf_paths(obj: Any, prefix: str = "") -> Iterator[str]:
    """Recursively yield dot-notation leaf paths from a nested dict."""
    if not isinstance(obj, dict):
        return
    for k, v in obj.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from _extract_leaf_paths(v, full)
        elif isinstance(v, (int, float, str)) and v is not None:
            yield full


def _parse_payload(raw: str) -> Optional[Dict[str, Any]]:
    """Parse a payload string (Python literal or JSON). Returns None on failure."""
    raw = str(raw).strip()
    if len(raw) < 3:
        return None
    try:
        parsed = ast.literal_eval(raw)
    except Exception:
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
    return parsed if isinstance(parsed, dict) else None


def _show_entity_table(
    entities: Dict[Tuple[str, str], List[str]],
    entity_names: Dict[Tuple[str, str], List[str]],
) -> None:
    table = Table(title="Entidades detectadas no CSV", border_style="dim", show_lines=False)
    table.add_column("Lado", style="cyan", no_wrap=True)
    table.add_column("Tipo", style="yellow")
    table.add_column("Exemplos de nomes", style="dim")
    table.add_column("Campos disponíveis", style="green")

    for (side, etype), fields in sorted(entities.items()):
        if side == "unknown" and etype == "unknown":
            continue
        names = entity_names.get((side, etype), [])
        name_sample = ", ".join(names[:2]) + ("…" if len(names) > 2 else "")
        useful = [f for f in fields if not any(x in f for x in ["pitch", "roll", "heading", "vel"])]
        field_str = ", ".join(useful[:5]) + ("…" if len(useful) > 5 else "")
        table.add_row(side, etype, name_sample or "[dim]—[/]", field_str or "[dim]—[/]")

    console.print()
    console.print(table)
    console.print()


def inspect_csv(path: Path) -> Dict[str, Any]:
    """
    Sample the CSV, validate required columns, and discover entity types
    with their available payload field paths.

    Returns a dict with keys:
      path, columns, row_count, n_experiments, entities, entity_names
    """
    console.print(f"\n[dim]Inspecionando {path.name}...[/]")

    try:
        sample = pd.read_csv(path, nrows=10000, low_memory=False)
    except Exception as exc:
        fatal(f"Não foi possível ler o CSV:\n{exc}")

    cols = list(sample.columns)
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    extra = [c for c in cols if c not in REQUIRED_COLUMNS]

    if missing:
        detail = f"[red]Colunas faltando:[/] {', '.join(missing)}"
        if extra:
            detail += f"\n[yellow]Colunas não reconhecidas:[/] {', '.join(extra)}"
        fatal(
            "O arquivo CSV não é compatível com o formato de saída do ASA.\n\n"
            + detail
        )

    if extra:
        console.print(f"[yellow]⚠  Colunas extras ignoradas: {', '.join(extra)}[/]")

    entities: Dict[Tuple[str, str], Set[str]] = {}
    entity_names: Dict[Tuple[str, str], List[str]] = {}

    for raw in sample["payload"].dropna():
        parsed = _parse_payload(str(raw))
        if parsed is None:
            continue

        info = parsed.get("id", {})
        if not isinstance(info, dict):
            continue

        side = str(info.get("side", "")).lower().strip() or "unknown"
        etype = str(info.get("type", "")).strip() or "unknown"
        name = str(info.get("name", "")).strip()

        key = (side, etype)
        entities.setdefault(key, set())
        entity_names.setdefault(key, [])

        if name and name not in entity_names[key]:
            entity_names[key].append(name)

        for field in _extract_leaf_paths(parsed):
            if any(frag in field for frag in SKIP_FIELD_FRAGMENTS):
                continue
            entities[key].add(field)

    entities_sorted: Dict[Tuple[str, str], List[str]] = {
        k: sorted(v) for k, v in entities.items()
    }

    n_experiments = (
        int(sample["experiment"].nunique()) if "experiment" in sample.columns else 0
    )

    console.print(
        f"[green]✓[/] CSV válido — "
        f"[bold]{len(sample):,}[/] linhas (amostra), "
        f"[bold]{n_experiments}[/] experimentos, "
        f"[bold]{len(entities_sorted)}[/] tipos de entidade."
    )

    if entities_sorted:
        _show_entity_table(entities_sorted, entity_names)

    return {
        "path": path,
        "columns": cols,
        "row_count": len(sample),
        "n_experiments": n_experiments,
        "entities": entities_sorted,
        "entity_names": entity_names,
    }
