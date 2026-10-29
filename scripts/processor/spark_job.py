"""
Spark job orchestrator for the distributed CSV processor.

Reads the input CSV, runs the MapReduce pipeline, computes the batch
aggregate, and writes three output artefacts: CSV, PNG, JSON summary.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from .aggregator import _merge_agg, make_aggregate_partition_fn
from .config import parse_args
from .output import (
    build_output_df,
    build_output_name,
    compute_batch_aggregate,
    corr_column_name,
    ensure_output_dir,
    generate_plot,
    validate_input_columns,
)
from .scenario import resolve_scenario_config


def main() -> None:
    args = parse_args()

    # Spark will raise a descriptive error if the HDFS path doesn't exist.
    is_hdfs = args.input_file.startswith("hdfs://") or args.input_file.startswith("s3://")
    if not is_hdfs and not os.path.exists(args.input_file):
        raise FileNotFoundError(f"Input CSV not found: {args.input_file}")

    # ── Scenario config ───────────────────────────────────────────────────────
    scenario = resolve_scenario_config(args.scenario_config)
    x_cfg = scenario["x_variable"]
    y_cfg = scenario["y_variable"]
    agg_cfg = scenario["batch_aggregation"]
    agg_type = agg_cfg["type"]
    x_name = x_cfg["name"]
    y_name = y_cfg["name"]

    print(f"INFO: Scenario: {scenario.get('name', 'unnamed')}", flush=True)
    print(
        f"INFO: X variable: {x_name}  Y variable: {y_name}  Aggregate: {agg_type}",
        flush=True,
    )

    # ── Output paths ──────────────────────────────────────────────────────────
    ensure_output_dir(args.output_path)
    output_stem = build_output_name(args.input_file)
    output_csv = os.path.join(args.output_path, f"{output_stem}.csv")
    output_png = os.path.join(args.output_path, f"{output_stem}.png")
    output_summary = os.path.join(args.output_path, f"{output_stem}_summary.json")

    # ── Spark session ─────────────────────────────────────────────────────────
    spark = (
        SparkSession.builder
        .appName(f"ASA Distributed Aggregator - {scenario.get('name', 'generic')}")
        .config("spark.sql.execution.arrow.pyspark.enabled", "false")
        .getOrCreate()
    )
    spark_stopped = False

    try:
        raw_df = (
            spark.read
            .option("header", True)
            .option("inferSchema", True)
            .option("multiLine", False)
            .option("quote", '"')
            .option("escape", '"')
            .option("mode", "PERMISSIVE")
            .csv(args.input_file)
        )

        raw_df = raw_df.coalesce(max(1, args.initial_partitions))
        validate_input_columns(list(raw_df.columns))

        base_df = raw_df.select(
            F.col("experiment").cast("long").alias("experiment"),
            F.col("frame").cast("double").alias("frame"),
            F.col("payload").cast("string").alias("payload"),
        ).where(F.col("experiment").isNotNull())

        if args.max_experiments is not None and args.max_experiments > 0:
            allowed = (
                base_df.select("experiment")
                .distinct()
                .orderBy("experiment")
                .limit(args.max_experiments)
            )
            base_df = base_df.join(allowed, on="experiment", how="inner")

        working_df = base_df.where(F.col("payload").isNotNull()).coalesce(
            max(1, args.agg_partitions)
        )

        # ── Distributed map phase ─────────────────────────────────────────────
        partition_fn = make_aggregate_partition_fn(x_cfg, y_cfg)
        partial_results = working_df.rdd.mapPartitions(partition_fn).collect()

        # ── Reduce phase (driver) ─────────────────────────────────────────────
        x_global: Dict = {}
        y_global: Dict = {}

        for kind, partial in partial_results:
            if kind == "x":
                _merge_agg(x_global, partial, x_cfg.get("frame_aggregation", "last"))
            else:
                _merge_agg(y_global, partial, y_cfg.get("frame_aggregation", "max"))

        spark.stop()
        spark_stopped = True

        # ── Build output DataFrame ────────────────────────────────────────────
        points_df = build_output_df(x_global, y_global, x_cfg, y_cfg)

        # ── Batch aggregate ───────────────────────────────────────────────────
        agg_value, agg_reason, n_points = compute_batch_aggregate(
            points_df, x_name, y_name, agg_type
        )

        if agg_type == "pearson_correlation":
            points_df[corr_column_name(y_name, x_name)] = agg_value

        points_df.to_csv(output_csv, index=False)

        # ── Plot ──────────────────────────────────────────────────────────────
        try:
            generate_plot(points_df, x_name, y_name, output_png)
        except Exception as exc:
            print(f"WARNING: Could not generate plot: {exc}", flush=True)

        # ── Summary JSON ──────────────────────────────────────────────────────
        summary: Dict[str, Any] = {
            "scenario": scenario.get("name", "unknown"),
            "input": args.input_file,
            "output_csv": output_csv,
            "output_png": output_png,
            "rows": int(len(points_df)),
            "columns": list(points_df.columns),
            "batch_aggregates": {
                agg_type: agg_value,
                "n_points": n_points,
                "reason": agg_reason,
            },
        }

        with open(output_summary, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)

        print(json.dumps(summary, indent=2))

    except Exception as exc:
        print(f"ERROR: {exc}", flush=True)
        raise
    finally:
        if not spark_stopped:
            try:
                spark.stop()
            except Exception:
                pass
