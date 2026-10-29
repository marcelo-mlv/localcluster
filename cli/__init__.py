"""
AeroSOuDA CLI package.

Public API::

    from cli import main
    main()
"""
from __future__ import annotations

import sys

from rich.panel import Panel
from rich.text import Text

from .console import console
from .docker import check_cluster, check_docker, check_hdfs
from .csv_source import pick_or_generate_csv
from .inspector import inspect_csv
from .scenario import pick_or_create_scenario
from .job import confirm_run, run_job
from .results import show_results


def welcome() -> None:
    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold cyan][italic]Aerospace Simulation Output Distributed Architecture[/]\n\n"
            "Pipeline de análise distribuída ([bold]Apache Spark[/]) para saídas de\n"
            "simulação de cenários aeroespaciais do projeto [bold]ASA[/].\n\n"
            "Este assistente irá guiá-lo em todo o processo:\n"
            "  [green]1.[/] Origem dos dados — CSV já pronto [dim]ou[/] gerar via simulação ASA\n"
            "  [green]2.[/] Configuração do cenário de análise (YAML)\n"
            "  [green]3.[/] Processamento distribuído com Apache Spark\n"
            "  [green]4.[/] Exibição dos resultados\n\n"
        ),
        title="[bold white]Bem-vindo[/]",
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()


def main() -> None:
    try:
        console.clear()
        welcome()

        # 1. Docker daemon check
        check_docker()
        console.print()

        # 2. Spark cluster check (must be started: docker compose up -d)
        check_cluster()
        console.print()

        # 3. HDFS check — required, no fallback
        check_hdfs()
        console.print()

        # 4. CSV source: existing file or generate via ASA simulation
        csv_path = pick_or_generate_csv()
        console.print(f"\n[bold]Arquivo selecionado:[/] {csv_path.name}")

        # 5. CSV validation and entity inspection
        csv_info = inspect_csv(csv_path)

        # 6. Scenario selection or wizard
        yaml_path, yaml_data = pick_or_create_scenario(csv_info)

        # 7. Confirmation
        confirm_run(csv_path, yaml_path, yaml_data)

        # 8. Upload to HDFS and submit Spark job with live progress
        summary = run_job(csv_path, yaml_path, yaml_data)

        # 9. Display results
        show_results(summary, csv_path.name)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrompido pelo usuário (Ctrl+C).[/]")
        sys.exit(0)
