"""
CSV source selection: use an existing file or generate via ASA simulation.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import questionary
from rich.panel import Panel

from .config import (
    ASA_SERVER_DEFAULT,
    ASAPY_CONDA_CANDIDATES,
    INPUTS_DIR,
    JUPYTERHUB_DIR,
    REQUIRED_COLUMNS,
    SIM_GENERATOR_SCRIPT,
)
from .console import console, custom_style, fatal


def _human_size(path: Path) -> str:
    size_kb = path.stat().st_size / 1024
    if size_kb < 1024:
        return f"{size_kb:.0f} KB"
    return f"{size_kb / 1024:.1f} MB"


def _find_asapy_python() -> Optional[str]:
    """
    Return the path to a Python interpreter that has asapy + asaclient.
    Checks the current interpreter first, then well-known conda locations.
    """
    try:
        import asapy as _a  # noqa: F401
        import asaclient as _b  # noqa: F401
        return sys.executable
    except ImportError:
        pass

    for candidate in ASAPY_CONDA_CANDIDATES:
        if Path(candidate).exists():
            try:
                result = subprocess.run(
                    [candidate, "-c", "import asapy, asaclient; print('ok')"],
                    capture_output=True, text=True, timeout=15,
                )
                if "ok" in result.stdout:
                    return candidate
            except Exception:
                pass

    return None


def _pick_json_scenario() -> Path:
    """Interactive file picker for simulation JSON scenario files."""
    json_files = sorted(JUPYTERHUB_DIR.glob("*.json")) if JUPYTERHUB_DIR.exists() else []

    choices: List[questionary.Choice] = []
    for f in json_files:
        choices.append(questionary.Choice(title=f"📄  {f.name}", value=f))
    choices.append(questionary.Choice(title="📁  Especificar outro caminho...", value="custom"))

    selection = questionary.select(
        "Arquivo JSON do cenário de simulação:",
        choices=choices,
        style=custom_style,
        instruction="",
    ).ask()

    if selection is None:
        sys.exit(0)

    if selection != "custom":
        return selection  # type: ignore[return-value]

    path_str = questionary.text(
        "Caminho completo do arquivo JSON:",
        validate=lambda t: Path(t).exists() and t.endswith(".json") or "Arquivo não encontrado",
    ).ask()
    if path_str is None:
        sys.exit(0)
    return Path(path_str)


def _run_simulation_batch_subprocess(
    asapy_python: str, json_path: Path, server_url: str
) -> Path:
    """
    Run the simulation generator as a subprocess so the user can interact
    with it even when asapy lives in a different Python environment.
    """
    if not SIM_GENERATOR_SCRIPT.exists():
        fatal(
            f"Script de geração não encontrado:\n  {SIM_GENERATOR_SCRIPT}\n\n"
            "Verifique se scripts/generate_simulation_csv.py existe."
        )

    INPUTS_DIR.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        "[bold]Iniciando geração de CSV via simulação ASA[/]\n\n"
        "O processo interativo será controlado pelo assistente de simulação.\n"
        "Uma janela do navegador será aberta para autenticação.\n\n"
        "[dim]Pressione Ctrl+C para cancelar a qualquer momento.[/]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    proc = subprocess.run(
        [asapy_python, str(SIM_GENERATOR_SCRIPT),
         str(json_path), str(INPUTS_DIR), "--server", server_url],
    )

    if proc.returncode != 0:
        fatal(
            "A geração de CSV via simulação terminou com erro.\n\n"
            "Verifique:\n"
            "  • Conectividade com o servidor ASA\n"
            "  • Autenticação (login)\n"
            "  • Logs acima para detalhes do erro"
        )

    # Discover the generated CSV
    expected = INPUTS_DIR / f"results_{json_path.stem}.csv"
    if expected.exists():
        console.print(f"\n[green]✓ CSV gerado:[/] {expected.name}")
        return expected

    csv_files = sorted(INPUTS_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if csv_files:
        console.print(f"\n[green]✓ Usando CSV mais recente:[/] {csv_files[0].name}")
        return csv_files[0]

    fatal("CSV gerado não encontrado em inputs/. Verifique o log acima.")
    raise RuntimeError("unreachable")


def pick_csv() -> Path:
    """List CSV files in inputs/ and let the user pick one."""
    csv_files = sorted(f for f in INPUTS_DIR.glob("*.csv") if not f.name.startswith("."))

    if not csv_files:
        console.print(Panel(
            "[yellow]A pasta [bold]inputs/[/] não contém nenhum arquivo CSV.\n\n"
            "Copie pelo menos um arquivo CSV de saída de simulação ASA para:\n"
            f"  [bold]{INPUTS_DIR}[/]\n\n"
            "O arquivo deve conter exatamente estas colunas:\n"
            f"  [dim]{', '.join(REQUIRED_COLUMNS)}[/]",
            title="[bold red]Pasta de entrada vazia[/]",
            border_style="red",
        ))
        sys.exit(1)

    console.print(Panel(
        "[bold]Seleção do arquivo de entrada[/]\n"
        "[dim]Arquivos CSV disponíveis em inputs/[/]",
        border_style="blue",
    ))

    choices = [
        questionary.Choice(title=f"{f.name}  ({_human_size(f)})", value=f)
        for f in csv_files
    ]

    selected: Optional[Path] = questionary.select(
        "Arquivo CSV de entrada:",
        choices=choices,
        use_shortcuts=False,
        style=custom_style,
        instruction="",
    ).ask()

    if selected is None:
        sys.exit(0)
    return selected


def pick_or_generate_csv() -> Path:
    """
    Entry point for CSV acquisition.
    Asks whether to use an existing CSV or generate one via ASA simulation.
    """
    console.print(Panel(
        "[bold]Origem dos dados de entrada[/]\n\n"
        "O processamento distribuído requer um arquivo CSV com resultados de\n"
        "simulações ASA. Você pode usar um arquivo já pronto ou gerar um novo\n"
        "executando um batch de simulações no servidor ASA.",
        border_style="blue",
        padding=(1, 2),
    ))

    csv_files = sorted(f for f in INPUTS_DIR.glob("*.csv") if not f.name.startswith("."))

    choices: List[questionary.Choice] = []
    if csv_files:
        label = f"📂  Usar CSV já pronto  ({len(csv_files)} arquivo(s) em inputs/)"
        choices.append(questionary.Choice(title=label, value="existing"))

    choices.append(questionary.Choice(
        title="🚀  Gerar novo CSV rodando simulações no servidor ASA",
        value="generate",
    ))

    if not csv_files:
        choices.append(questionary.Choice(
            title="📂  Usar CSV já pronto  (pasta inputs/ — atualmente vazia)",
            value="existing",
        ))

    source = questionary.select(
        "Como deseja obter os dados de entrada?",
        choices=choices,
        style=custom_style,
        instruction="",
    ).ask()

    if source is None:
        sys.exit(0)

    if source == "existing":
        return pick_csv()

    # ── Simulation generation path ──────────────────────────────────────────
    asapy_python = _find_asapy_python()

    if asapy_python is None:
        console.print(Panel(
            "[red]❌ Bibliotecas asapy/asa-client não encontradas.[/]\n\n"
            "Para gerar CSVs via simulação, ative o ambiente conda com asapy:\n\n"
            "  [bold]conda activate asapy[/]\n"
            "  [bold]python cli.py[/]\n\n"
            "Depois escolha novamente \"Gerar novo CSV\".\n\n"
            "[dim]Alternativamente, copie um CSV de saída ASA para inputs/ e escolha\n"
            "\"Usar CSV já pronto\".[/]",
            title="[yellow]⚠️ Dependência não encontrada",
            border_style="yellow",
            padding=(1, 2),
        ))
        fatal("asapy/asa-client não disponíveis neste ambiente Python.")

    if asapy_python != sys.executable:
        console.print(f"[dim]ℹ  asapy encontrado em ambiente conda:\n   {asapy_python}[/]")

    console.print()
    json_path = _pick_json_scenario()
    console.print(f"[green]✓[/] Cenário: [bold]{json_path.name}[/]")

    server_url = questionary.text(
        "URL do servidor ASA:",
        default=ASA_SERVER_DEFAULT,
    ).ask()
    if server_url is None:
        sys.exit(0)

    return _run_simulation_batch_subprocess(asapy_python, json_path, server_url)
