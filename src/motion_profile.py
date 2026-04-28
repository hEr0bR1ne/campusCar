#!/usr/bin/env python3
"""Shared motion shaping for campusCar manual and UE controls."""
from __future__ import annotations

import math
import os
import shlex
from pathlib import Path


def _load_project_env() -> None:
    env_file = Path(__file__).resolve().parents[1] / "config" / "robot.env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not parts or "=" not in parts[0]:
            continue
        key, value = parts[0].split("=", 1)
        if not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        if key in os.environ or "$(" in value or "${" in value:
            continue
        os.environ[key] = value


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


_load_project_env()

TANK_TURN_MODE = _env_str("TANK_TURN_MODE", "angular").strip().lower()
TANK_TURN_SIDE_SPEED_SCALE = max(0.0, _env_float(
    "TANK_TURN_SIDE_SPEED_SCALE",
    _env_float("PIVOT_TURN_LINEAR_SCALE", 1.0),
))
TANK_TURN_MIN_SIDE_SPEED = max(0.0, _env_float(
    "TANK_TURN_MIN_SIDE_SPEED",
    _env_float("PIVOT_TURN_MIN_LINEAR", 0.10),
))
TANK_TURN_MAX_SIDE_SPEED = max(0.0, _env_float(
    "TANK_TURN_MAX_SIDE_SPEED",
    _env_float("PIVOT_TURN_MAX_LINEAR", 1.0),
))
_EPSILON = 1e-6


def shape_twist_for_base(linear: float, angular: float) -> tuple[float, float]:
    """Shape pure yaw commands without changing travelling-turn commands."""
    linear = float(linear)
    angular = float(angular)
    if abs(linear) > _EPSILON or abs(angular) <= _EPSILON:
        return linear, angular
    if TANK_TURN_MODE in ("angular", "pure_angular", "cmd_vel"):
        return 0.0, angular
    if TANK_TURN_SIDE_SPEED_SCALE <= 0.0 or TANK_TURN_MAX_SIDE_SPEED <= 0.0:
        return 0.0, angular

    side_speed = abs(angular) * TANK_TURN_SIDE_SPEED_SCALE
    if TANK_TURN_MIN_SIDE_SPEED > 0.0:
        side_speed = max(TANK_TURN_MIN_SIDE_SPEED, side_speed)
    side_speed = min(TANK_TURN_MAX_SIDE_SPEED, side_speed)

    if TANK_TURN_MODE in ("xz_opposite", "experimental_xz"):
        return -math.copysign(side_speed, angular), math.copysign(side_speed, angular)
    if TANK_TURN_MODE in ("xz_same", "experimental_xz_same"):
        return math.copysign(side_speed, angular), math.copysign(side_speed, angular)
    if TANK_TURN_MODE in ("yz_opposite", "experimental_yz"):
        return 0.0, math.copysign(side_speed, angular)
    return 0.0, angular
