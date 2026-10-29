"""
MapReduce aggregation logic: partition-level accumulation and global merge.

Design rationale — why mapPartitions?
--------------------------------------
Several Spark APIs could compute per-entity aggregates:

1. **DataFrame groupBy + agg**: Natural for SQL-style aggregations, but
   requires every column to be a Spark type.  The ``payload`` column is a raw
   Python-literal or JSON string that must be parsed (AST + JSON), which
   cannot be expressed as a native Spark SQL function.  Pushing that to a UDF
   introduces one Python↔JVM boundary crossing *per row* — prohibitively
   expensive for million-row CSVs.

2. **RDD.map (row-level UDF)**: One Python call per row.  Correct, but the
   per-call overhead dominates when payloads are complex nested dicts that
   require multi-step traversal.

3. **RDD.mapPartitions** ← chosen approach: A single Python generator is
   invoked *once per partition*, amortising the interpreter setup and
   dictionary allocation overhead across all rows in that partition.
   The partition-local accumulator dict (``x_local``, ``y_local``) avoids
   redundant object creation.  The config dicts are captured in a closure
   and serialised once per executor at dispatch time.

4. **foreachPartition / accumulators**: Could drive side-effects (e.g., write
   to HDFS per partition) but cannot return values; unsuitable for returning
   partial aggregates to the driver.

5. **Spark SQL window functions**: Require broadcasting the parsed payload as
   structured columns; parsing is still needed, and the string-based payload
   makes schema inference unreliable.

``mapPartitions`` is the minimal-overhead path for custom Python parsing of
opaque string columns with heterogeneous entity types, and it naturally
expresses the two-phase MapReduce pattern required here.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from .config import SIDES
from .payload import (
    _extract_field_value,
    _matches_entity_selector,
    _parse_row_payload,
)


def _update_agg(
    data: Dict,
    key: Any,
    frame: float,
    value: float,
    agg_type: str,
) -> None:
    """
    Update ``data[key]`` with a new ``(frame, value)`` observation.

    Supported agg_type values:
    - ``"max"``   – keep observation with the highest value
    - ``"min"``   – keep observation with the lowest value
    - ``"last"``  – keep observation at the highest frame
    - ``"first"`` – keep observation at the lowest frame
    """
    existing = data.get(key)
    if existing is None:
        data[key] = (frame, value)
        return

    e_frame, e_value = existing
    if agg_type == "max":
        if value > e_value:
            data[key] = (frame, value)
    elif agg_type == "min":
        if value < e_value:
            data[key] = (frame, value)
    elif agg_type == "first":
        if frame < e_frame:
            data[key] = (frame, value)
    else:  # "last" is the default
        if frame > e_frame:
            data[key] = (frame, value)


def _merge_agg(global_data: Dict, partial_data: Dict, agg_type: str) -> None:
    """Merge *partial_data* (from one Spark partition) into *global_data*."""
    for key, (frame, value) in partial_data.items():
        _update_agg(global_data, key, frame, value, agg_type)


def make_aggregate_partition_fn(
    x_cfg: Dict[str, Any], y_cfg: Dict[str, Any]
) -> Callable:
    """
    Return a ``mapPartitions``-compatible generator function that accumulates
    x and y variable observations from raw simulation rows.

    The config dicts are captured in a closure and serialised with the
    function when Spark distributes it to worker executors.

    Each call of the returned function processes one RDD partition and yields
    exactly two items: ``("x", x_local_dict)`` and ``("y", y_local_dict)``.
    """
    x_selector = x_cfg["entity_selector"]
    x_field = x_cfg["field_path"]
    x_agg = x_cfg.get("frame_aggregation", "last")
    x_scope = x_cfg.get("scope", "per_experiment")

    y_selector = y_cfg["entity_selector"]
    y_field = y_cfg["field_path"]
    y_agg = y_cfg.get("frame_aggregation", "max")
    y_scope = y_cfg.get("scope", "per_entity")

    def _aggregate_partition(rows):
        x_local: Dict = {}
        y_local: Dict = {}

        for row in rows:
            experiment = row["experiment"]
            frame = row["frame"]
            payload = row["payload"]

            if experiment is None or frame is None or payload is None:
                continue

            parsed, side, entity_key, entity_name, entity_type = _parse_row_payload(payload)
            if parsed is None or side not in SIDES:
                continue

            exp = int(experiment)
            frame_val = float(frame)

            if _matches_entity_selector(entity_name, entity_type, side, x_selector):
                field_val = _extract_field_value(parsed, x_field, frame_val)
                if field_val is not None:
                    x_key = exp if x_scope == "per_experiment" else (exp, entity_key or "")
                    _update_agg(x_local, x_key, frame_val, field_val, x_agg)

            if _matches_entity_selector(entity_name, entity_type, side, y_selector):
                field_val = _extract_field_value(parsed, y_field, frame_val)
                if field_val is not None:
                    y_key = exp if y_scope == "per_experiment" else (exp, entity_key or "")
                    _update_agg(y_local, y_key, frame_val, field_val, y_agg)

        yield ("x", x_local)
        yield ("y", y_local)

    return _aggregate_partition
