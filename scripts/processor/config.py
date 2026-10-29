"""
Constants and argument parsing for the distributed CSV processor.
"""
from __future__ import annotations

import argparse
from typing import List

from pyspark.sql.types import DoubleType, StringType, StructField, StructType


# ── Schema / column definitions ───────────────────────────────────────────────

PAYLOAD_SCHEMA = StructType([
    StructField("side", StringType(), True),
    StructField("entity_key", StringType(), True),
    StructField("is_blue_fighter", DoubleType(), True),
    StructField("is_red_radar", DoubleType(), True),
    StructField("radar_longitude", DoubleType(), True),
])

INPUT_EXPECTED_COLUMNS: List[str] = [
    "id", "frame", "execution_id", "mixr_type", "asa_type",
    "asa_custom_type", "payload", "sim_time", "utc_time",
    "execution_uuid", "batch_id", "experiment",
]

SIDES = ("blue", "red")

DEFAULT_SCENARIO_CONFIG = "/opt/spark/scenarios/qr_correlation.yaml"


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Distributed ASA simulation output aggregation processor"
    )
    parser.add_argument("--input-file", default="./inputs/input.csv")
    parser.add_argument("--output-path", default="./outputs")
    parser.add_argument(
        "--scenario-config", default=None,
        help=(
            "Path to a YAML scenario config. "
            f"Falls back to {DEFAULT_SCENARIO_CONFIG} or built-in QR defaults."
        ),
    )
    parser.add_argument("--initial-partitions", type=int, default=16)
    parser.add_argument("--agg-partitions", type=int, default=16)
    parser.add_argument("--max-experiments", type=int, default=None)
    parser.add_argument("--experiment-buckets", type=int, default=8)
    return parser.parse_args()
