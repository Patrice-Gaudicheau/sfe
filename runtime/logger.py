"""Minimal SQLite logger for sfe experimental runs."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "logs/sfe_runs.sqlite"

METADATA_COLUMNS = {
    "router": "TEXT",
    "executor": "TEXT",
    "router_model": "TEXT",
    "executor_model": "TEXT",
    "router_latency_ms": "INTEGER",
    "router_input_tokens": "INTEGER",
    "router_output_tokens": "INTEGER",
    "router_total_tokens": "INTEGER",
    "router_error": "TEXT",
    "prompt_style": "TEXT",
    "task_label": "TEXT",
    "error": "TEXT",
}

REQUIRED_INPUT_FIELDS = (
    "task_type",
    "mode",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "success",
)


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create the run log database and runs table if needed."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                task_type TEXT NOT NULL,
                mode TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                success INTEGER NOT NULL,
                structural_consistency REAL,
                router TEXT,
                executor TEXT,
                router_model TEXT,
                executor_model TEXT,
                router_latency_ms INTEGER,
                router_input_tokens INTEGER,
                router_output_tokens INTEGER,
                router_total_tokens INTEGER,
                router_error TEXT,
                prompt_style TEXT,
                task_label TEXT,
                error TEXT,
                notes TEXT
            )
            """
        )
        _migrate_runs_table(connection)


def log_run(run_data: dict, db_path: str = DEFAULT_DB_PATH) -> str:
    """Append one experimental run to SQLite and return its run_id."""
    data = dict(run_data)

    _validate_required_fields(data, REQUIRED_INPUT_FIELDS)

    data.setdefault("run_id", uuid.uuid4().hex)
    data.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))

    if "total_tokens" not in data or data["total_tokens"] is None:
        data["total_tokens"] = int(data["input_tokens"]) + int(data["output_tokens"])

    _validate_required_fields(
        data,
        (
            "run_id",
            "timestamp",
            "task_type",
            "mode",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "latency_ms",
            "success",
        ),
    )

    row = {
        "run_id": str(data["run_id"]),
        "timestamp": str(data["timestamp"]),
        "task_type": str(data["task_type"]),
        "mode": str(data["mode"]),
        "provider": str(data["provider"]),
        "model": str(data["model"]),
        "input_tokens": int(data["input_tokens"]),
        "output_tokens": int(data["output_tokens"]),
        "total_tokens": int(data["total_tokens"]),
        "latency_ms": int(data["latency_ms"]),
        "success": int(data["success"]),
        "structural_consistency": _optional_float(data.get("structural_consistency")),
        "router": data.get("router"),
        "executor": data.get("executor"),
        "router_model": data.get("router_model"),
        "executor_model": data.get("executor_model"),
        "router_latency_ms": _optional_int(data.get("router_latency_ms")),
        "router_input_tokens": _optional_int(data.get("router_input_tokens")),
        "router_output_tokens": _optional_int(data.get("router_output_tokens")),
        "router_total_tokens": _optional_int(data.get("router_total_tokens")),
        "router_error": data.get("router_error"),
        "prompt_style": data.get("prompt_style"),
        "task_label": data.get("task_label"),
        "error": data.get("error"),
        "notes": data.get("notes"),
    }

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                run_id,
                timestamp,
                task_type,
                mode,
                provider,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                latency_ms,
                success,
                structural_consistency,
                router,
                executor,
                router_model,
                executor_model,
                router_latency_ms,
                router_input_tokens,
                router_output_tokens,
                router_total_tokens,
                router_error,
                prompt_style,
                task_label,
                error,
                notes
            )
            VALUES (
                :run_id,
                :timestamp,
                :task_type,
                :mode,
                :provider,
                :model,
                :input_tokens,
                :output_tokens,
                :total_tokens,
                :latency_ms,
                :success,
                :structural_consistency,
                :router,
                :executor,
                :router_model,
                :executor_model,
                :router_latency_ms,
                :router_input_tokens,
                :router_output_tokens,
                :router_total_tokens,
                :router_error,
                :prompt_style,
                :task_label,
                :error,
                :notes
            )
            """,
            row,
        )

    return row["run_id"]


def list_runs(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return all runs ordered by newest timestamp first."""
    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                run_id,
                timestamp,
                task_type,
                mode,
                provider,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                latency_ms,
                success,
                structural_consistency,
                router,
                executor,
                router_model,
                executor_model,
                router_latency_ms,
                router_input_tokens,
                router_output_tokens,
                router_total_tokens,
                router_error,
                prompt_style,
                task_label,
                error,
                notes
            FROM runs
            ORDER BY timestamp DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def _migrate_runs_table(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
    }

    for column, column_type in METADATA_COLUMNS.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE runs ADD COLUMN {column} {column_type}")


def _validate_required_fields(data: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in data or data[field] is None]
    if missing:
        raise ValueError(f"Missing required run field(s): {', '.join(missing)}")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
