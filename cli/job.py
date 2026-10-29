"""
Spark job execution: YAML injection, HDFS CSV upload, progress monitoring,
and output retrieval.

HDFS is required. The pipeline exits with guidance if the namenode is not running.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import questionary
import yaml
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

from .config import (
    CONTAINER_SCENARIOS,
    CONTAINER_TMP_OUT,
    HDFS_INPUTS_DIR,
    HDFS_NAMENODE,
    OUTPUTS_DIR,
    SCRIPT_DIR,
    STAGE_RE,
)
from .console import console, custom_style, fatal
from .docker import _dc, hdfs_is_running, upload_to_hdfs


# ── Confirmation ──────────────────────────────────────────────────────────────

def confirm_run(
    csv_path: Path,
    yaml_path: Path,
    yaml_data: Dict[str, Any],
) -> None:
    """Show a summary panel and ask the user to confirm before running."""
    x = yaml_data.get("x_variable", {})
    y = yaml_data.get("y_variable", {})
    agg = yaml_data.get("batch_aggregation", {})
    x_sel = x.get("entity_selector", {})
    y_sel = y.get("entity_selector", {})

    console.print()
    console.print(Panel(
        Text.from_markup(
            f"[bold]Arquivo de entrada:[/]    {csv_path.name}\n"
            f"[bold]Cenário:[/]              {yaml_data.get('name', yaml_path.name)}\n\n"
            f"[bold]Parâmetro[/] (Variável X):\n"
            f"  Nome:      {x.get('name', '?')}\n"
            f"  Entidade:  lado={x_sel.get('side', '?')}, "
            f"tipo contém '{x_sel.get('type_contains', '?')}'\n"
            f"  Campo:     {x.get('field_path', '?')} ({x.get('frame_aggregation', '?')})\n"
            f"  Escopo:    {x.get('scope', '?')}\n\n"
            f"[bold]Métrica[/] (Variável Y):\n"
            f"  Nome:      {y.get('name', '?')}\n"
            f"  Entidade:  lado={y_sel.get('side', '?')}, "
            f"tipo contém '{y_sel.get('type_contains', '?')}'\n"
            f"  Campo:     {y.get('field_path', '?')} ({y.get('frame_aggregation', '?')})\n"
            f"  Escopo:    {y.get('scope', '?')}\n\n"
            f"[bold]Agregação do batch:[/]   {agg.get('type', '?')}\n\n"
            f"[bold]Saída em:[/]             {OUTPUTS_DIR.relative_to(SCRIPT_DIR)}"
        ),
        title="[bold white]Resumo da execução[/]",
        border_style="green",
    ))

    ok = questionary.confirm(
        "Iniciar o processamento distribuído agora?", default=True
    ).ask()
    if ok is None or not ok:
        console.print("[yellow]Abortado pelo usuário.[/]")
        sys.exit(0)


# ── HDFS CSV upload ───────────────────────────────────────────────────────────

def _upload_csv_to_hdfs(csv_path: Path) -> str:
    """
    Upload *csv_path* to HDFS and return the full HDFS URI.

    Exits with guidance if the HDFS namenode is not running.
    """
    if not hdfs_is_running():
        fatal(
            "O HDFS namenode não está rodando.\n\n"
            "O pipeline requer HDFS para distribuir os dados de entrada entre\n"
            "os workers Spark. Inicie o cluster completo antes de continuar:\n\n"
            "  [yellow]docker compose up -d[/]\n"
            "  [dim]docker compose ps   # aguarde 'healthy'[/]\n\n"
            "Web UI do HDFS: [link]http://localhost:9870[/]"
        )

    hdfs_dest = f"{HDFS_INPUTS_DIR}/{csv_path.name}"
    try:
        hdfs_uri = upload_to_hdfs(csv_path, hdfs_dest)
        console.print(f"[green]✓ CSV enviado para HDFS:[/] [dim]{hdfs_uri}[/]")
        return hdfs_uri
    except Exception as exc:
        fatal(
            f"Falha ao enviar CSV para HDFS:\n  {exc}\n\n"
            "Verifique se o namenode está saudável:\n"
            "  [yellow]docker compose ps[/]\n"
            "  [dim]http://localhost:9870[/]"
        )
        raise  # unreachable; satisfies type checker


# ── YAML injection ────────────────────────────────────────────────────────────

def _inject_yaml_into_container(yaml_path: Path, yaml_data: Dict[str, Any]) -> str:
    """
    Write the YAML scenario into spark-master via python stdin.
    Returns the container path where it was written.
    """
    container_yaml_path = f"/tmp/aerosouda_{yaml_path.stem}.yaml"
    yaml_content = yaml.dump(yaml_data, allow_unicode=True, sort_keys=False, indent=2)
    python_cmd = f"import sys; open('{container_yaml_path}', 'w').write(sys.stdin.read())"
    result = subprocess.run(
        _dc("exec", "-T", "spark-master", "python3", "-c", python_cmd),
        input=yaml_content, capture_output=True, text=True, cwd=SCRIPT_DIR, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to inject YAML into container: {result.stderr}")
    return container_yaml_path


# ── Output retrieval ──────────────────────────────────────────────────────────

def _pull_outputs_from_container(csv_stem: str) -> Optional[Dict[str, Any]]:
    """Copy output files from the container /tmp to the host outputs/ directory."""
    OUTPUTS_DIR.mkdir(exist_ok=True)
    console.print("[dim]Copiando resultados do container...[/]")
    result = subprocess.run(
        ["docker", "cp", f"spark-master:{CONTAINER_TMP_OUT}/.", str(OUTPUTS_DIR)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        console.print(
            f"[yellow]⚠  docker cp falhou (outputs em {CONTAINER_TMP_OUT}):[/]\n"
            f"[dim]{result.stderr}[/]"
        )
        return None

    stem = f"{csv_stem}_aggregated"
    summary_path = OUTPUTS_DIR / f"{stem}_summary.json"
    summary: Optional[Dict[str, Any]] = None
    if summary_path.exists():
        try:
            with open(summary_path, encoding="utf-8") as fh:
                summary = json.load(fh)
            if summary:
                summary["output_csv"] = str(OUTPUTS_DIR / f"{stem}.csv")
                summary["output_png"] = str(OUTPUTS_DIR / f"{stem}.png")
                with open(summary_path, "w", encoding="utf-8") as fh:
                    json.dump(summary, fh, indent=2)
        except Exception:
            pass

    console.print(f"[green]✓ Resultados salvos em:[/] {OUTPUTS_DIR}")
    return summary


# ── Job execution ─────────────────────────────────────────────────────────────

def run_job(
    csv_path: Path,
    yaml_path: Path,
    yaml_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Upload CSV to HDFS, submit the Spark job, stream progress, and return
    the parsed JSON summary (or None on job failure).
    """
    # Upload input CSV to HDFS — exits with guidance if namenode not running
    container_csv = _upload_csv_to_hdfs(csv_path)

    # Inject YAML scenario config into the container via stdin
    try:
        effective_yaml_data = yaml_data or {}
        if effective_yaml_data:
            container_yaml = _inject_yaml_into_container(yaml_path, effective_yaml_data)
        else:
            container_yaml = f"{CONTAINER_SCENARIOS}/{yaml_path.name}"
    except Exception as exc:
        console.print(f"[yellow]⚠  Falha ao injetar YAML: {exc}. Usando fallback interno.[/]")
        container_yaml = f"{CONTAINER_SCENARIOS}/{yaml_path.name}"

    cmd = _dc(
        "exec", "-T", "spark-master",
        "/opt/spark/scripts/run_csv_processor.sh",
        container_csv,
        CONTAINER_TMP_OUT,
        container_yaml,
    )

    console.print()
    console.print(f"[dim]$ {' '.join(cmd[4:])}[/]")
    console.print()

    proc = subprocess.Popen(
        cmd, cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )

    state: Dict[str, Any] = {
        "status": "Iniciando Spark...",
        "summary": None,
        "errors": [],
        "all_lines": [],
    }
    json_buf: List[str] = []
    in_json = False

    def _read(stream, label: str) -> None:
        nonlocal in_json
        for raw_line in stream:
            line = raw_line.rstrip("\n")
            state["all_lines"].append(f"[{label}] {line}")

            if label == "OUT":
                stripped = line.strip()
                if stripped == "{":
                    in_json = True
                    json_buf.clear()
                if in_json:
                    json_buf.append(line)
                    if stripped == "}":
                        in_json = False
                        try:
                            state["summary"] = json.loads("\n".join(json_buf))
                        except Exception:
                            pass
                    continue

            m = STAGE_RE.search(line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                pct = int(done / total * 100) if total else 0
                state["status"] = f"Processando... {pct}% ({done}/{total} tarefas)"
                continue

            if "INFO: Scenario:" in line:
                state["status"] = "Cenário carregado, iniciando MapReduce..."
            elif "INFO: X variable:" in line:
                state["status"] = "Fase Map: extraindo métricas por partição..."
            elif "ERROR:" in line:
                err = line.split("ERROR:", 1)[-1].strip()
                state["errors"].append(err)
                state["status"] = f"Erro: {err[:60]}"

    t_out = threading.Thread(target=_read, args=(proc.stdout, "OUT"), daemon=True)
    t_err = threading.Thread(target=_read, args=(proc.stderr, "ERR"), daemon=True)
    start = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(state["status"], total=None)
        t_out.start()
        t_err.start()
        while t_out.is_alive() or t_err.is_alive():
            progress.update(task, description=state["status"])
            time.sleep(0.25)
        t_out.join()
        t_err.join()
        progress.update(task, description=state["status"])

    proc.wait()
    elapsed = time.time() - start
    console.print()

    if proc.returncode != 0:
        last_lines = "\n".join(
            ln for ln in state["all_lines"][-25:]
            if not STAGE_RE.search(ln)
        )
        console.print(Panel(
            "[red]O job Spark terminou com erro.[/]\n\n"
            "[dim]Últimas linhas de log:[/]\n" + last_lines,
            title="[bold red]❌ Falha no processamento[/]",
            border_style="red",
        ))
        return None

    console.print(f"[green]✓ Processamento concluído em {elapsed:.1f}s.[/]")
    return state["summary"] or _pull_outputs_from_container(csv_path.stem)
