"""
YAML scenario loading, preview, and creation wizard.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import questionary
import yaml
from rich.panel import Panel
from rich.table import Table

from .config import FIELD_LABELS, SCENARIOS_DIR
from .console import console, custom_style, fatal


# ── Load existing scenario ────────────────────────────────────────────────────

def _preview_yaml(data: Dict[str, Any]) -> None:
    """Print a human-readable table summary of a YAML scenario config."""
    x = data.get("x_variable", {})
    y = data.get("y_variable", {})
    agg = data.get("batch_aggregation", {})

    table = Table(title=f"Cenário: {data.get('name', '?')}", border_style="dim")
    table.add_column("Campo", style="cyan", no_wrap=True)
    table.add_column("Valor")

    def _r(label: str, val: Any) -> None:
        table.add_row(label, str(val) if val is not None else "[dim]—[/]")

    _r("Variável X (parâmetro independente)", x.get("name", "?"))
    _r("  Filtro de entidade X", str(x.get("entity_selector", {})))
    _r("  Campo X", x.get("field_path", "?"))
    _r("  Agregação de frames X", x.get("frame_aggregation", "?"))
    _r("  Escopo X", x.get("scope", "?"))
    _r("Variável Y (métrica)", y.get("name", "?"))
    _r("  Filtro de entidade Y", str(y.get("entity_selector", {})))
    _r("  Campo Y", y.get("field_path", "?"))
    _r("  Agregação de frames Y", y.get("frame_aggregation", "?"))
    _r("  Escopo Y", y.get("scope", "?"))
    _r("Agregação do batch", agg.get("type", "?"))

    console.print()
    console.print(table)
    console.print()


def _load_existing_scenario(existing: List[Path]) -> Tuple[Path, Dict[str, Any]]:
    """Let the user pick one of the existing YAML scenario files."""
    choices = []
    for p in existing:
        try:
            with open(p, encoding="utf-8") as fh:
                data: Dict[str, Any] = yaml.safe_load(fh) or {}
            name = data.get("name", p.stem)
            desc = str(data.get("description", "")).strip().split("\n")[0][:50] + "..."
            label = f"{p.name}  — {name}"
            if desc:
                label += f" ({desc})"
        except Exception:
            data = {}
            label = p.name
        choices.append(questionary.Choice(title=label, value=(p, data)))

    result = questionary.select(
        "Selecione o arquivo de cenário:",
        choices=choices,
        style=custom_style,
        instruction="",
    ).ask()

    if result is None:
        sys.exit(0)

    yaml_path, yaml_data = result
    _preview_yaml(yaml_data)
    return yaml_path, yaml_data


# ── Wizard helpers ────────────────────────────────────────────────────────────

def _entity_choices_for_side(
    entities: Dict[Tuple[str, str], List[str]],
    side: str,
) -> List[questionary.Choice]:
    choices = []
    for (s, etype), fields in sorted(entities.items()):
        if s != side or etype == "unknown":
            continue
        choices.append(questionary.Choice(
            title=f"{etype}  ({len(fields)} campos)",
            value=etype,
        ))
    return choices


def _field_choices(
    entities: Dict[Tuple[str, str], List[str]],
    side: str,
    etype: str,
) -> List[questionary.Choice]:
    fields = entities.get((side, etype), [])
    choices = [
        questionary.Choice(
            title=FIELD_LABELS.get("frame", "frame — número do frame"),
            value="frame",
        )
    ]
    for field in sorted(fields):
        label = FIELD_LABELS.get(field, field)
        choices.append(questionary.Choice(title=label, value=field))
    return choices


def _validate_selector(
    entities: Dict[Tuple[str, str], List[str]],
    side: str,
    etype: str,
    field_path: str,
) -> None:
    """Warn (do not block) when the selector finds no match in the CSV sample."""
    matched = [(s, t) for (s, t) in entities if s == side and etype.lower() in t.lower()]
    if not matched:
        console.print(
            f"[yellow]⚠  Atenção: nenhuma entidade com lado='{side}' e tipo "
            f"contendo '{etype}' encontrada no CSV (amostra). "
            f"O processamento pode não gerar pontos.[/]"
        )
        return

    fields = entities.get((matched[0][0], matched[0][1]), [])
    if field_path != "frame" and field_path not in fields:
        console.print(
            f"[yellow]⚠  Atenção: campo '{field_path}' não encontrado para "
            f"'{side}/{etype}' na amostra.[/]"
        )


def _ask_variable(
    var_label: str,
    csv_info: Dict[str, Any],
    default_side: Optional[str] = None,
) -> Dict[str, Any]:
    """Wizard sub-flow to configure one variable (X or Y)."""
    entities = csv_info["entities"]
    available_sides = sorted({s for (s, _) in entities if s != "unknown"})

    if not available_sides:
        fatal("Nenhuma entidade foi detectada no CSV. Impossível configurar o cenário.")

    console.print(f"\n[bold cyan]── Variável {var_label} ──────────────────────────────[/]")

    default_s = default_side if default_side in available_sides else available_sides[0]
    side = questionary.select(
        f"Lado da entidade para {var_label}:",
        choices=available_sides,
        default=default_s,
        style=custom_style,
        instruction="",
    ).ask()
    if side is None:
        sys.exit(0)

    etype_choices = _entity_choices_for_side(entities, side)
    if not etype_choices:
        fatal(f"Nenhuma entidade do lado '{side}' encontrada no CSV.")

    etype = questionary.select(
        f"Tipo de entidade para {var_label}:",
        choices=etype_choices,
        style=custom_style,
        instruction="",
    ).ask()
    if etype is None:
        sys.exit(0)

    field_choices = _field_choices(entities, side, etype)
    field_path = questionary.select(
        f"Campo a extrair para {var_label}:",
        choices=field_choices,
        style=custom_style,
        instruction="",
    ).ask()
    if field_path is None:
        sys.exit(0)

    default_agg = "max" if field_path == "frame" else "last"
    frame_agg = questionary.select(
        f"Como agregar '{field_path}' ao longo dos frames para {var_label}?",
        choices=[
            questionary.Choice("max   — maior valor observado (ex: dano máximo)", "max"),
            questionary.Choice("min   — menor valor observado", "min"),
            questionary.Choice("last  — valor no último frame (ex: posição final)", "last"),
            questionary.Choice("first — valor no primeiro frame", "first"),
        ],
        default=default_agg,
        style=custom_style,
        instruction="",
    ).ask()
    if frame_agg is None:
        sys.exit(0)

    default_scope = "per_entity" if field_path == "frame" else "per_experiment"
    scope = questionary.select(
        f"Escopo de {var_label}:",
        choices=[
            questionary.Choice(
                "per_entity     — um valor por entidade por run",
                "per_entity",
            ),
            questionary.Choice(
                "per_experiment — um valor único por run",
                "per_experiment",
            ),
        ],
        default=default_scope,
        style=custom_style,
        instruction="",
    ).ask()
    if scope is None:
        sys.exit(0)

    last_field = field_path.split(".")[-1]
    auto_name = f"{side}_{etype.lower().replace('-', '_').replace(' ', '_')}_{last_field}_{frame_agg}"
    var_name = questionary.text(
        f"Nome da variável {var_label} (Enter para aceitar sugestão):",
        default=auto_name,
    ).ask()
    if var_name is None:
        sys.exit(0)
    var_name = var_name.strip() or auto_name

    _validate_selector(entities, side, etype, field_path)

    return {
        "name": var_name,
        "entity_selector": {"side": side, "type_contains": etype},
        "field_path": field_path,
        "frame_aggregation": frame_agg,
        "scope": scope,
    }


# ── YAML wizard ───────────────────────────────────────────────────────────────

def _run_yaml_wizard(csv_info: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
    """
    Guide the user through creating a new YAML scenario config.
    Y (metric) is asked before X (independent parameter) — more intuitive.
    """
    console.print(Panel(
        "[bold]Assistente de criação de cenário[/]\n\n"
        "Você vai configurar:\n"
        "  [cyan]Y[/] — o que você quer [bold]medir[/]\n"
        "  [yellow]X[/] — o que [bold]varia[/] entre os experimentos\n"
        "  Como [bold]combinar[/] X e Y de todos os experimentos",
        border_style="cyan",
        padding=(1, 2),
    ))

    analysis_name = questionary.text("Nome desta análise:", default="Minha Analise").ask()
    if analysis_name is None:
        sys.exit(0)

    description = questionary.text(
        "Descrição (opcional, Enter para pular):", default=""
    ).ask() or ""

    console.print("\n[bold]Primeiro, defina o que você quer medir[/] [dim](variável Y)[/]:")
    y_cfg = _ask_variable("Y (métrica)", csv_info)

    y_side = y_cfg["entity_selector"]["side"]
    opposite = "red" if y_side == "blue" else "blue"
    console.print(
        "\n[bold]Agora, defina o parâmetro que varia entre os experimentos[/] "
        "[dim](variável X)[/]:"
    )
    x_cfg = _ask_variable("X (parâmetro independente)", csv_info, default_side=opposite)

    console.print("\n[bold]Como combinar os resultados de todos os experimentos?[/]")
    batch_agg = questionary.select(
        "Função de agregação do batch:",
        choices=[
            questionary.Choice(
                "pearson_correlation — Correlação de Pearson entre X e Y (r ∈ [−1, +1])",
                "pearson_correlation",
            ),
            questionary.Choice(
                "scatter_only       — Apenas scatter plot X vs Y (sem valor numérico)",
                "scatter_only",
            ),
            questionary.Choice("mean_y             — Média de Y em todos os experimentos", "mean_y"),
            questionary.Choice("count_y            — Contagem total de observações Y", "count_y"),
        ],
        style=custom_style,
        instruction="",
    ).ask()
    if batch_agg is None:
        sys.exit(0)

    yaml_data: Dict[str, Any] = {
        "name": analysis_name,
        "description": description,
        "x_variable": x_cfg,
        "y_variable": y_cfg,
        "batch_aggregation": {"type": batch_agg},
    }
    _preview_yaml(yaml_data)

    safe = re.sub(r"[^a-z0-9_]+", "_", analysis_name.lower()).strip("_")
    default_filename = f"{safe or 'cenario'}.yaml"
    filename = questionary.text(
        "Nome do arquivo para salvar em scenarios/:", default=default_filename
    ).ask()
    if filename is None:
        sys.exit(0)

    if not filename.endswith((".yaml", ".yml")):
        filename += ".yaml"

    yaml_path = SCENARIOS_DIR / filename

    if yaml_path.exists():
        overwrite = questionary.confirm(
            f"'{filename}' já existe. Deseja sobrescrever?", default=False
        ).ask()
        if not overwrite:
            console.print("[yellow]Operação cancelada pelo usuário.[/]")
            sys.exit(0)

    with open(yaml_path, "w", encoding="utf-8") as fh:
        yaml.dump(yaml_data, fh, allow_unicode=True, sort_keys=False, indent=2)

    console.print(f"[green]✓ Cenário salvo em:[/] {yaml_path}")
    return yaml_path, yaml_data


# ── Public entry point ────────────────────────────────────────────────────────

def pick_or_create_scenario(csv_info: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
    """
    Offer the user a choice between loading an existing YAML scenario or
    creating a new one via the guided wizard.
    """
    console.print(Panel(
        "[bold]Configuração do cenário de análise[/]\n\n"
        "Um [bold]cenário[/] define:\n"
        "  • A [cyan]variável X[/] — o parâmetro que varia entre os experimentos\n"
        "  • A [cyan]variável Y[/] — a métrica de interesse a medir\n"
        "  • Como [cyan]combinar[/] X e Y de todos os experimentos em um valor agregado",
        border_style="blue",
    ))

    existing = sorted(SCENARIOS_DIR.glob("*.yaml")) + sorted(SCENARIOS_DIR.glob("*.yml"))

    mode_choices = [questionary.Choice("✨  Criar novo cenário (assistente guiado)", "new")]
    if existing:
        mode_choices.append(questionary.Choice("📂  Carregar cenário existente", "load"))

    mode = questionary.select(
        "Como deseja configurar o cenário?",
        choices=mode_choices,
        style=custom_style,
        instruction="",
    ).ask()

    if mode is None:
        sys.exit(0)

    if mode == "load":
        return _load_existing_scenario(existing)

    return _run_yaml_wizard(csv_info)
