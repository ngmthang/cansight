"""
Lightweight persistence for the review web app -- SQLite, since
that's proportionate for a single-user local tool (per
docs/PROJECT_STATUS.md Section 5/6, this is explicitly NOT a
multi-tenant production database; it just needs to survive a
process restart and hold more than one project at a time).

What's persisted per project:
  - the BuildingModel, serialized via BuildingModel.to_json()
  - the review queue's resolved-object-id set, separately -- NOT
    inferred from confidence values, because confidence alone can't
    distinguish "a human reviewed this" from "this object happened
    to score high" (see ReviewQueue.resolved_ids()'s docstring for
    the concrete failure case this avoids).
"""

from __future__ import annotations
import sqlite3
import json
import datetime
from dataclasses import dataclass

from building_model.schema import BuildingModel

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    building_id TEXT NOT NULL,
    model_json TEXT NOT NULL,
    resolved_ids_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


@dataclass
class ProjectSummary:
    project_id: str
    building_id: str
    updated_at: str


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_project(
    db_path: str,
    project_id: str,
    model: BuildingModel,
    resolved_ids: set[str],
) -> None:
    """Upsert: inserts a new project, or overwrites an existing one
    with the same project_id (called after every mutating operation
    in webapp/server.py, so a project is never more than one
    request stale)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        conn.execute(
            """
            INSERT INTO projects
                (project_id, building_id, model_json,
                 resolved_ids_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                building_id = excluded.building_id,
                model_json = excluded.model_json,
                resolved_ids_json = excluded.resolved_ids_json,
                updated_at = excluded.updated_at
            """,
            (
                project_id,
                model.building_id,
                model.to_json(),
                json.dumps(sorted(resolved_ids)),
                datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_project(
    db_path: str, project_id: str
) -> tuple[BuildingModel, set[str]] | None:
    """Returns (model, resolved_ids), or None if project_id doesn't
    exist."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        row = conn.execute(
            "SELECT model_json, resolved_ids_json FROM projects "
            "WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    model_json, resolved_ids_json = row
    model = BuildingModel.from_json(model_json)
    resolved_ids = set(json.loads(resolved_ids_json))
    return model, resolved_ids


def list_projects(db_path: str) -> list[ProjectSummary]:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        rows = conn.execute(
            "SELECT project_id, building_id, updated_at "
            "FROM projects ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()

    return [
        ProjectSummary(
            project_id=r[0], building_id=r[1], updated_at=r[2]
        )
        for r in rows
    ]


def delete_project(db_path: str, project_id: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_SCHEMA)
        conn.execute(
            "DELETE FROM projects WHERE project_id = ?", (project_id,)
        )
        conn.commit()
    finally:
        conn.close()