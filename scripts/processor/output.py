"""
Output construction: DataFrame assembly, batch aggregation, plot generation,
and file I/O helpers.
"""
from __future__ import annotations

import glob
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


# ── DataFrame assembly ────────────────────────────────────────────────────────

def build_output_df(
    x_data: Dict,
    y_data: Dict,
    x_cfg: Dict[str, Any],
    y_cfg: Dict[str, Any],
) -> pd.DataFrame:
    """
    Join x and y aggregated data into a tidy scatter DataFrame.

    Join strategy:
    - y scope = per_entity, x scope = per_experiment  → join on experiment
    - y scope = per_entity, x scope = per_entity       → join on (experiment, entity_key)
    - y scope = per_experiment, x scope = *            → join on experiment
    """
    x_scope = x_cfg.get("scope", "per_experiment")
    y_scope = y_cfg.get("scope", "per_entity")
    x_name = x_cfg["name"]
    y_name = y_cfg["name"]

    rows: List[Dict] = []

    for y_key, (_, y_value) in y_data.items():
        if y_scope == "per_entity":
            exp, entity_key = y_key
        else:
            exp = y_key
            entity_key = None

        if x_scope == "per_entity" and y_scope == "per_entity":
            x_entry = x_data.get((exp, entity_key or ""))
        else:
            x_entry = x_data.get(exp)

        if x_entry is None:
            continue

        _, x_value = x_entry
        row: Dict[str, Any] = {"experiment": exp, x_name: x_value, y_name: y_value}
        if entity_key is not None:
            row["entity_key"] = entity_key
        rows.append(row)

    if not rows:
        base_cols = ["experiment"]
        if y_scope == "per_entity":
            base_cols.append("entity_key")
        base_cols.extend([x_name, y_name])
        return pd.DataFrame(columns=base_cols)

    df = pd.DataFrame(rows)
    df["experiment"] = pd.to_numeric(df["experiment"], errors="coerce")
    df[x_name] = pd.to_numeric(df[x_name], errors="coerce")
    df[y_name] = pd.to_numeric(df[y_name], errors="coerce")
    df = df.dropna(subset=["experiment", x_name, y_name])

    sort_cols = ["experiment"]
    if "entity_key" in df.columns:
        sort_cols.append("entity_key")
    return df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


# ── Batch aggregation ─────────────────────────────────────────────────────────

def compute_batch_aggregate(
    df: pd.DataFrame,
    x_name: str,
    y_name: str,
    agg_type: str,
) -> Tuple[Optional[float], Optional[str], int]:
    """
    Compute the batch-level aggregate value.

    Returns ``(value, reason, n_points)`` where *reason* is non-empty only
    when *value* is None.

    Supported *agg_type* values:
    - ``"pearson_correlation"`` - Pearson r between x and y (driver-side pandas)
    - ``"scatter_only"``        - no numeric aggregate
    - ``"mean_y"``              - arithmetic mean of y
    - ``"count_y"``             - count of y observations
    """
    n_points = len(df)

    if agg_type == "pearson_correlation":
        if n_points >= 2:
            corr = df[y_name].corr(df[x_name])
            if pd.isna(corr):
                return None, "correlation undefined (constant series or invalid variance)", n_points
            return float(corr), None, n_points
        return None, "insufficient points for correlation", n_points

    if agg_type == "scatter_only":
        return None, "scatter_only (no numeric aggregate)", n_points

    if agg_type == "mean_y":
        if n_points > 0:
            return float(df[y_name].mean()), None, n_points
        return None, "no data", n_points

    if agg_type == "count_y":
        return float(n_points), None, n_points

    return None, f"unknown aggregation type: {agg_type}", n_points


def corr_column_name(y_name: str, x_name: str) -> str:
    return f"pearson_corr_{y_name}_vs_{x_name}"


# ── Plot generation ───────────────────────────────────────────────────────────

def generate_plot(df: pd.DataFrame, x_col: str, y_col: str, output_png: str) -> None:
    if df.empty:
        return
    plt.figure(figsize=(10, 6))
    plt.scatter(df[x_col], df[y_col], s=24)
    plt.xlabel(x_col)
    plt.ylabel(y_col)
    plt.title(f"{y_col} vs {x_col}")
    plt.tight_layout()
    plt.savefig(output_png, dpi=150)
    plt.close()


# ── File I/O helpers ──────────────────────────────────────────────────────────

def ensure_output_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def build_output_name(input_path: str) -> str:
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    return f"{base_name}_aggregated"


def consolidate_spark_csv(temp_dir: str, output_csv: str) -> pd.DataFrame:
    part_files = sorted(glob.glob(os.path.join(temp_dir, "**", "part-*.csv"), recursive=True))
    if not part_files:
        raise RuntimeError(f"No Spark CSV part files found under: {temp_dir}")
    frames = [pd.read_csv(fp) for fp in part_files]
    result = pd.concat(frames, ignore_index=True)
    result.to_csv(output_csv, index=False)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return result


def validate_input_columns(input_columns: list) -> None:
    from .config import INPUT_EXPECTED_COLUMNS
    missing = [c for c in INPUT_EXPECTED_COLUMNS if c not in input_columns]
    if missing:
        raise ValueError(
            "Input CSV is missing required columns: " + ", ".join(sorted(missing))
        )
    if set(input_columns) != set(INPUT_EXPECTED_COLUMNS):
        unexpected = sorted(set(input_columns) - set(INPUT_EXPECTED_COLUMNS))
        missing2 = sorted(set(INPUT_EXPECTED_COLUMNS) - set(input_columns))
        details = []
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        if missing2:
            details.append("missing: " + ", ".join(missing2))
        raise ValueError(
            "Input CSV does not match required template (" + "; ".join(details) + ")"
        )
