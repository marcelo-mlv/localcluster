"""
Docker daemon and Spark cluster management helpers.

Compatible with:
  - Docker Desktop (Linux, macOS, Windows via WSL2)
  - docker.io Ubuntu package (`docker compose` CLI plugin, v2)
  - Legacy `docker-compose` standalone binary (v1), if still installed

The `_compose()` function detects the available Compose command at runtime so
callers never need to care which variant is installed.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from .config import HDFS_NAMENODE, HDFS_INPUTS_DIR, SCRIPT_DIR
from .console import console, fatal


# ── Compose command detection ─────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _compose_cmd() -> List[str]:
    """
    Return the Compose command prefix available on this system.

    Priority:
    1. `docker compose` — Compose v2 CLI plugin (Docker Desktop or docker.io ≥ 23)
    2. `docker-compose` — Compose v1 standalone binary (legacy)
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=8,
        )
        if result.returncode == 0:
            return ["docker", "compose"]
    except Exception:
        pass

    if shutil.which("docker-compose"):
        return ["docker-compose"]

    # Cannot find compose; will surface error when first called
    return ["docker", "compose"]  # default; error will propagate naturally


def _dc(*args: str) -> List[str]:
    """
    Build a Compose command targeting this project's compose file.
    Works with both `docker compose` (v2 plugin) and `docker-compose` (v1).
    """
    return _compose_cmd() + ["-f", str(SCRIPT_DIR / "docker-compose.yml")] + list(args)


# ── Docker daemon checks ──────────────────────────────────────────────────────

def docker_is_running() -> bool:
    """Return True if the Docker daemon is running and accessible."""
    try:
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_docker() -> None:
    """
    Verify Docker daemon is running. Exits with human-friendly guidance if not.

    Works with Docker Desktop, docker.io (Ubuntu), and Podman-docker shims.
    """
    if docker_is_running():
        console.print("[green]✓ Docker está rodando.[/]")
        return

    fatal(
        "Docker não está rodando ou não está acessível.\n\n"
        "[bold]Para iniciar o Docker:[/]\n"
        "  [yellow]sudo systemctl start docker[/]    "
        "[dim]# docker.io / Docker Engine[/]\n"
        "  [dim]Ou abra o Docker Desktop se estiver instalado.[/]\n\n"
        "Se o Docker nunca foi instalado:\n"
        "  [dim]https://docs.docker.com/engine/install/ubuntu/[/]"
    )


# ── Spark cluster management ──────────────────────────────────────────────────

def cluster_is_running() -> bool:
    """Return True if spark-master container is in running state."""
    try:
        result = subprocess.run(
            ["docker", "ps",
             "--filter", "name=spark-master",
             "--filter", "status=running",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        return "spark-master" in result.stdout
    except Exception:
        return False


def restart_cluster() -> bool:
    """
    Stop and restart the Spark cluster (down → up).

    A full cycle resets both master and workers, preventing the
    'unregistered worker' heartbeat problem.
    """
    console.print("[yellow]⚙  Parando cluster (compose down)...[/]")
    try:
        subprocess.run(
            _dc("down"),
            cwd=SCRIPT_DIR, capture_output=True, text=True, timeout=120,
        )
    except Exception:
        pass

    console.print("[yellow]⚙  Iniciando cluster Spark (compose up -d)...[/]")
    try:
        result = subprocess.run(
            _dc("up", "-d"),
            cwd=SCRIPT_DIR, capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            console.print(f"[red]❌ Falha ao iniciar cluster:\n{result.stderr.strip()}[/]")
            return False
    except subprocess.TimeoutExpired:
        console.print("[red]❌ Timeout ao iniciar cluster.[/]")
        return False

    console.print("[yellow]⏳ Aguardando spark-master registrar workers...[/]")
    for _ in range(60):
        time.sleep(2)
        if cluster_is_running():
            time.sleep(5)
            console.print("[green]✓ Cluster reiniciado com estado limpo.[/]")
            return True

    console.print("[red]❌ O cluster não ficou pronto dentro do tempo esperado.[/]")
    return False


def check_cluster() -> None:
    """
    Verify the Spark cluster is running. Exits with guidance if not.

    The cluster must be started manually before running the CLI:
        docker compose up -d
    """
    if cluster_is_running():
        console.print("[green]✓ Cluster Spark está rodando.[/]")
        return

    compose_cmd = " ".join(_compose_cmd())
    fatal(
        "O cluster Spark não está rodando.\n\n"
        "[bold]Para iniciar o cluster (na pasta localcluster/):[/]\n"
        f"  [yellow]{compose_cmd} up -d[/]\n\n"
        "Aguarde todos os containers ficarem saudáveis:\n"
        f"  [dim]{compose_cmd} ps[/]\n\n"
        "Em seguida, execute o CLI novamente.\n\n"
    )


# ── HDFS helpers ──────────────────────────────────────────────────────────────

def hdfs_is_running() -> bool:
    """Return True if the HDFS namenode container is running."""
    try:
        result = subprocess.run(
            ["docker", "ps",
             "--filter", "name=namenode",
             "--filter", "status=running",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        return "namenode" in result.stdout
    except Exception:
        return False


def check_hdfs() -> None:
    """
    Verify the HDFS namenode is running AND has at least one live datanode.
    Exits with guidance if not.
    """
    if not hdfs_is_running():
        compose_cmd = " ".join(_compose_cmd())
        fatal(
            "O HDFS namenode não está rodando.\n\n"
            "[bold]Para iniciar o cluster completo (Spark + HDFS):[/]\n"
            f"  [yellow]{compose_cmd} up -d[/]\n\n"
            "Verifique os containers:\n"
            f"  [dim]{compose_cmd} ps[/]\n\n"
            "Web UI do HDFS: http://localhost:9870"
        )

    # Also check that at least one DataNode is registered
    try:
        report = subprocess.run(
            ["docker", "exec", "namenode", "hdfs", "dfsadmin", "-report"],
            capture_output=True, text=True, timeout=30,
        )
        if "Live datanodes (0)" in report.stdout or "Configured Capacity: 0" in report.stdout:
            fatal(
                "O HDFS namenode está rodando mas sem DataNodes registrados.\n\n"
                "Isso ocorre após deletar ou recriar o volume do namenode enquanto\n"
                "o datanode ainda tem o cluster ID antigo (split-brain).\n\n"
                "[bold]Solução: reinicie o cluster apagando os volumes:[/]\n"
                "  [yellow]docker compose down -v[/]\n"
                "  [yellow]docker compose up -d[/]\n\n"
                "[dim]Nota: isso apaga os dados do HDFS. Os CSVs em inputs/ não são afetados.[/]"
            )
    except Exception:
        pass

    usage = hdfs_usage()
    usage_str = f" [dim](uso atual: {usage})[/]" if usage and usage != "0" else ""
    console.print(f"[green]✓ HDFS namenode está rodando com DataNodes registrados.{usage_str}[/]")


def hdfs_usage() -> Optional[str]:
    """Return human-readable HDFS usage string, or None on failure."""
    try:
        result = subprocess.run(
            ["docker", "exec", "namenode", "hdfs", "dfs", "-du", "-s", "-h", "/"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()[0]
    except Exception:
        pass
    return None


def hdfs_mkdir(path: str) -> bool:
    """Create a directory in HDFS via the namenode container."""
    try:
        result = subprocess.run(
            ["docker", "exec", "namenode", "hdfs", "dfs", "-mkdir", "-p", path],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def upload_to_hdfs(local_path, hdfs_path: str) -> str:
    """
    Upload a local file to HDFS.

    Uses ``-put -f`` which overwrites any existing file at *hdfs_path*,
    so repeated uploads of the same file do NOT accumulate disk usage.

    1. ``docker cp`` the file into the namenode container.
    2. ``hdfs dfs -put -f`` to place it at *hdfs_path*.
    3. Clean up the temp copy inside the container.

    Returns the full HDFS URI (hdfs://namenode:9000/<hdfs_path>).
    """
    local_path = Path(local_path)
    tmp_container = f"/tmp/{local_path.name}"

    cp = subprocess.run(
        ["docker", "cp", str(local_path), f"namenode:{tmp_container}"],
        capture_output=True, text=True, timeout=300,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"docker cp to namenode failed: {cp.stderr.strip()}")

    hdfs_dir = hdfs_path.rsplit("/", 1)[0] if "/" in hdfs_path else "/"
    hdfs_mkdir(hdfs_dir)

    put = subprocess.run(
        ["docker", "exec", "namenode",
         "hdfs", "dfs", "-put", "-f", tmp_container, hdfs_path],
        capture_output=True, text=True, timeout=300,
    )
    if put.returncode != 0:
        raise RuntimeError(f"hdfs dfs -put failed: {put.stderr.strip()}")

    subprocess.run(
        ["docker", "exec", "namenode", "rm", "-f", tmp_container],
        capture_output=True, timeout=10,
    )

    return f"{HDFS_NAMENODE}{hdfs_path}"
