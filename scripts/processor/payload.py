"""
Payload parsing and entity extraction for ASA simulation rows.
"""
from __future__ import annotations

import ast
import json
from typing import Any, Dict, Optional, Tuple

from .config import SIDES


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _extract_side(parsed: Dict[str, Any]) -> Optional[str]:
    """Extract entity side ('blue'/'red') from a parsed payload dict."""
    side = None
    if isinstance(parsed.get("attributes"), dict):
        side = parsed["attributes"].get("side")
    if side is None and isinstance(parsed.get("id"), dict):
        side = parsed["id"].get("side")
    if side is None:
        side = parsed.get("side")
    return str(side).lower() if side is not None else None


# ── Legacy QR-specific helpers (kept for backward compatibility) ──────────────

def _is_blue_fighter(
    entity_name: Optional[str], entity_type: Optional[str], side: Optional[str]
) -> bool:
    if side != "blue":
        return False
    combined = f"{entity_name or ''} {entity_type or ''}".lower()
    return "fighter" in combined


def _is_red_radar(
    entity_name: Optional[str], entity_type: Optional[str], side: Optional[str]
) -> bool:
    if side != "red":
        return False
    combined = f"{entity_name or ''} {entity_type or ''}".lower()
    return "radar" in combined


def parse_payload(payload: Optional[str]) -> Tuple[
    Optional[str], Optional[str], Optional[float], Optional[float], Optional[float]
]:
    """Parse a payload string and return QR-specific fields (legacy, kept for compatibility)."""
    if payload is None or payload == "":
        return None, None, None, None, None

    parsed: Any = None
    try:
        parsed = ast.literal_eval(payload)
    except Exception:
        try:
            parsed = json.loads(payload)
        except Exception:
            return None, None, None, None, None

    if not isinstance(parsed, dict):
        return None, None, None, None, None

    side = _extract_side(parsed)
    entity_info = parsed.get("id") if isinstance(parsed.get("id"), dict) else {}
    entity_id = entity_info.get("id")
    entity_name = entity_info.get("name")
    entity_type = entity_info.get("type")

    entity_key = str(entity_id) if entity_id is not None else (
        str(entity_name) if entity_name is not None else None
    )

    is_bf = 1.0 if _is_blue_fighter(
        str(entity_name) if entity_name is not None else None,
        str(entity_type) if entity_type is not None else None,
        side,
    ) else 0.0

    is_rr = 1.0 if _is_red_radar(
        str(entity_name) if entity_name is not None else None,
        str(entity_type) if entity_type is not None else None,
        side,
    ) else 0.0

    state = parsed.get("state") if isinstance(parsed.get("state"), dict) else {}
    geo_pos = state.get("geo_pos") if isinstance(state.get("geo_pos"), dict) else {}
    radar_longitude = _to_float(geo_pos.get("longitude"))

    return side, entity_key, is_bf, is_rr, radar_longitude


# ── Generic entity/field helpers ─────────────────────────────────────────────

def _matches_entity_selector(
    entity_name: Optional[str],
    entity_type: Optional[str],
    side: Optional[str],
    selector: Dict[str, Any],
) -> bool:
    """Return True if the entity matches ALL constraints in *selector*."""
    required_side = selector.get("side")
    if required_side and side != required_side:
        return False

    type_contains = selector.get("type_contains")
    if type_contains:
        combined = f"{entity_name or ''} {entity_type or ''}".lower()
        if type_contains.lower() not in combined:
            return False

    name_contains = selector.get("name_contains")
    if name_contains and name_contains.lower() not in (entity_name or "").lower():
        return False

    exact_type = selector.get("exact_type")
    if exact_type and entity_type != exact_type:
        return False

    return True


def _extract_nested_value(obj: Any, field_path: str) -> Any:
    """Traverse a nested dict using dot-notation path and return the leaf value."""
    current: Any = obj
    for part in field_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _extract_field_value(parsed: Dict[str, Any], field_path: str, frame: float) -> Optional[float]:
    """
    Extract a numeric value from *parsed* using *field_path*.
    The special path ``"frame"`` returns the CSV frame number directly
    (used to compute survival time via ``max`` aggregation).
    """
    if field_path == "frame":
        return frame
    return _to_float(_extract_nested_value(parsed, field_path))


def _parse_row_payload(
    payload: Optional[str],
) -> Tuple[Optional[Dict], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Parse a raw payload string.
    Returns ``(parsed_dict, side, entity_key, entity_name, entity_type)``.
    Returns ``(None, …)`` on failure.
    """
    if payload is None or payload == "":
        return None, None, None, None, None

    parsed: Any = None
    try:
        parsed = ast.literal_eval(payload)
    except Exception:
        try:
            parsed = json.loads(payload)
        except Exception:
            return None, None, None, None, None

    if not isinstance(parsed, dict):
        return None, None, None, None, None

    side = _extract_side(parsed)
    entity_info = parsed.get("id") if isinstance(parsed.get("id"), dict) else {}
    entity_id = entity_info.get("id")
    entity_name = entity_info.get("name")
    entity_type = entity_info.get("type")

    entity_key = str(entity_id) if entity_id is not None else (
        str(entity_name) if entity_name is not None else None
    )

    return (
        parsed,
        str(side).lower() if side is not None else None,
        entity_key,
        str(entity_name) if entity_name is not None else None,
        str(entity_type) if entity_type is not None else None,
    )
