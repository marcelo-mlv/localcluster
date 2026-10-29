"""
Shared constants and path configuration for the AeroSOuDA CLI.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

# ── Repository layout ─────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.parent.resolve()   # localcluster/
INPUTS_DIR = SCRIPT_DIR / "inputs"
OUTPUTS_DIR = SCRIPT_DIR / "outputs"
SCENARIOS_DIR = SCRIPT_DIR / "scenarios"

# jupyterhub sibling directory — contains JSON scenario files for simulation gen
JUPYTERHUB_DIR = SCRIPT_DIR.parent / "jupyterhub"

# Simulation generation helper script
SIM_GENERATOR_SCRIPT = SCRIPT_DIR / "scripts" / "generate_simulation_csv.py"

# ASA server default
ASA_SERVER_DEFAULT = "https://service.asa.dcta.mil.br"

# Well-known conda env paths that may have asapy installed
ASAPY_CONDA_CANDIDATES: List[str] = [
    str(Path.home() / "miniconda3/envs/asapy/bin/python"),
    str(Path.home() / "anaconda3/envs/asapy/bin/python"),
    "/opt/conda/envs/asapy/bin/python",
]

# ── Container paths (inside spark-master) ────────────────────────────────────
CONTAINER_INPUTS = "/opt/spark/inputs"
CONTAINER_OUTPUTS = "/opt/spark/outputs"
CONTAINER_SCENARIOS = "/opt/spark/scenarios"
CONTAINER_TMP_OUT = "/tmp/aerosouda-outputs"

SPARK_ALL_CONTAINERS: List[str] = [
    "spark-master",
    "spark-worker-1",
    "spark-worker-2",
    "spark-worker-3",
    "spark-worker-4",
]

# ── CSV schema ────────────────────────────────────────────────────────────────
REQUIRED_COLUMNS: List[str] = [
    "id", "frame", "execution_id", "mixr_type", "asa_type",
    "asa_custom_type", "payload", "sim_time", "utc_time",
    "execution_uuid", "batch_id", "experiment",
]

# ── Payload inspection ────────────────────────────────────────────────────────
SKIP_FIELD_FRAGMENTS = {"ecef", "_body", "height", "id."}

FIELD_LABELS: Dict[str, str] = {
    "frame":                    "frame — número do frame (use max → tempo de sobrevivência)",
    "state.damage":             "state.damage — dano acumulado sofrido",
    "state.geo_pos.longitude":  "state.geo_pos.longitude — longitude geográfica",
    "state.geo_pos.latitude":   "state.geo_pos.latitude — latitude geográfica",
    "state.geo_pos.altitude":   "state.geo_pos.altitude — altitude",
    "mach":                     "mach — velocidade em Mach",
    "fuel":                     "fuel — combustível restante",
    "thrust":                   "thrust — empuxo do motor",
    "gload":                    "gload — fator de carga (G)",
    "gross_weight":             "gross_weight — peso bruto total",
    "fuel_flow":                "fuel_flow — consumo de combustível",
    "state.heading":            "state.heading — direção (heading)",
    "state.pitch":              "state.pitch — arfagem (pitch)",
    "state.roll":               "state.roll — rolamento (roll)",
}

# Regex to parse Spark's stage-progress lines from stderr
# Example: [Stage 0:==========>          (5 + 2) / 16]
STAGE_RE = re.compile(
    r"\[Stage\s+\d+:\s*[=>. ]+\s*\(\s*(\d+)\s*\+\s*\d+\s*\)\s*/\s*(\d+)\]"
)

# ── HDFS paths ────────────────────────────────────────────────────────────────
HDFS_NAMENODE = "hdfs://namenode:9000"
HDFS_INPUTS_DIR = "/inputs"
HDFS_OUTPUTS_DIR = "/outputs"
