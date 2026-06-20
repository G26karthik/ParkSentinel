"""CSV ingestion and DuckDB preprocessing for ParkSentinel."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from config import (
    CSV_PATH,
    DEFAULT_VEHICLE_SEVERITY,
    DEFAULT_VIOLATION_SEVERITY,
    DUCKDB_PATH,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    PEAK_HOURS,
    VEHICLE_SEVERITY,
)

logger = logging.getLogger(__name__)

PEAK_HOURS_SQL = ", ".join(str(h) for h in PEAK_HOURS)


def _parse_violation_list(raw: str) -> list[str]:
    """Parse violation_type column (Python-list-like string) into labels."""
    if not raw or raw == "NULL":
        return []
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed]
    except (ValueError, SyntaxError):
        pass
    return [raw.strip()]


def _build_severity_case(column: str, lookup: dict[str, float], default: float) -> str:
    """Build SQL CASE expression for severity lookup."""
    parts = [f"WHEN {column} = '{k}' THEN {v}" for k, v in lookup.items()]
    return f"CASE {' '.join(parts)} ELSE {default} END"


def _build_violation_tags(conn: duckdb.DuckDBPyConnection) -> None:
    """Parse violation_type lists and bulk-load violation_tags."""
    logger.info("Building violation_tags table...")
    raw_df = conn.execute("SELECT id, violation_type FROM violations_raw").df()

    tag_rows: list[dict[str, str]] = []
    for vid, vtype in zip(raw_df["id"], raw_df["violation_type"], strict=False):
        for label in _parse_violation_list(str(vtype)):
            tag_rows.append({"id": vid, "violation_label": label})

    tags_df = pd.DataFrame(tag_rows)
    conn.execute("CREATE OR REPLACE TABLE violation_tags (id VARCHAR, violation_label VARCHAR)")
    if not tags_df.empty:
        conn.register("_tags_tmp", tags_df)
        conn.execute("INSERT INTO violation_tags SELECT * FROM _tags_tmp")
        conn.unregister("_tags_tmp")

    tag_count = conn.execute("SELECT COUNT(*) FROM violation_tags").fetchone()[0]
    logger.info("Created violation_tags with %d rows", tag_count)


def load_csv_to_duckdb(
    csv_path: Path | None = None,
    db_path: Path | None = None,
    skip_tags: bool = False,
) -> duckdb.DuckDBPyConnection:
    """
    Load raw CSV into DuckDB, create violation_tags, and violations_clean view.
    Returns an open DuckDB connection.
    """
    csv_path = csv_path or CSV_PATH
    db_path = db_path or DUCKDB_PATH

    if not csv_path.exists():
        # #region agent log
        import json, time
        _log = {"sessionId": "d0259f", "hypothesisId": "H2-path", "location": "data_loader.py:load_csv_to_duckdb", "message": "CSV path missing", "data": {"csv_path": str(csv_path), "exists": False}, "timestamp": int(time.time() * 1000)}
        try:
            with open(Path(__file__).resolve().parent.parent / "debug-d0259f.log", "a", encoding="utf-8") as _f:
                _f.write(json.dumps(_log) + "\n")
        except Exception:
            pass
        # #endregion
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(db_path))

    # Skip reload if already populated
    existing = conn.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'violations_raw'"
    ).fetchone()[0]
    if existing:
        raw_count = conn.execute("SELECT COUNT(*) FROM violations_raw").fetchone()[0]
        if raw_count > 0:
            logger.info("Using existing DuckDB with %d raw records", raw_count)
            tag_exists = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'violation_tags'"
            ).fetchone()[0]
            if tag_exists == 0 and not skip_tags:
                _build_violation_tags(conn)
            _ensure_clean_view(conn)
            return conn

    logger.info("Loading CSV from %s", csv_path)
    conn.execute(
        """
        CREATE OR REPLACE TABLE violations_raw AS
        SELECT * FROM read_csv_auto(?, header=true, all_varchar=false)
        """,
        [str(csv_path)],
    )

    raw_count = conn.execute("SELECT COUNT(*) FROM violations_raw").fetchone()[0]
    logger.info("Loaded %d raw records into violations_raw", raw_count)

    if not skip_tags:
        _build_violation_tags(conn)

    _ensure_clean_view(conn)
    return conn


def _ensure_clean_view(conn: duckdb.DuckDBPyConnection) -> None:
    """Create or replace violations_clean view."""
    vehicle_case = _build_severity_case(
        "vehicle_type", VEHICLE_SEVERITY, DEFAULT_VEHICLE_SEVERITY
    )

    conn.execute(
        f"""
        CREATE OR REPLACE VIEW violations_clean AS
        SELECT
            id,
            latitude,
            longitude,
            location,
            vehicle_number,
            vehicle_type,
            violation_type,
            created_datetime::TIMESTAMP AS created_datetime,
            police_station,
            junction_name,
            validation_status,
            device_id,
            center_code,
            EXTRACT(HOUR FROM created_datetime::TIMESTAMP)::INTEGER AS hour_of_day,
            EXTRACT(DOW FROM created_datetime::TIMESTAMP)::INTEGER AS day_of_week,
            STRFTIME(created_datetime::TIMESTAMP, '%Y-%m') AS month_year,
            (junction_name IS NOT NULL AND junction_name != 'No Junction') AS is_junction,
            EXTRACT(HOUR FROM created_datetime::TIMESTAMP)::INTEGER IN ({PEAK_HOURS_SQL}) AS is_peak_hour,
            EXTRACT(DOW FROM created_datetime::TIMESTAMP)::INTEGER IN (5, 6) AS is_weekend,
            ({vehicle_case})::DOUBLE AS vehicle_severity_weight,
            DATE(created_datetime::TIMESTAMP) AS violation_date
        FROM violations_raw
        WHERE validation_status = 'approved'
          AND latitude BETWEEN {LAT_MIN} AND {LAT_MAX}
          AND longitude BETWEEN {LON_MIN} AND {LON_MAX}
        """
    )

    clean_count = conn.execute("SELECT COUNT(*) FROM violations_clean").fetchone()[0]
    logger.info("violations_clean view: %d approved records", clean_count)


def get_clean_violations_df(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return approved violations as a pandas DataFrame with severity weights."""
    df = conn.execute("SELECT * FROM violations_clean").df()

    tags_df = conn.execute(
        """
        SELECT vt.id, MAX(
            CASE vt.violation_label
                WHEN 'PARKING IN A MAIN ROAD' THEN 5.0
                WHEN 'DOUBLE PARKING' THEN 4.5
                WHEN 'PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS' THEN 4.5
                WHEN 'PARKING NEAR ROAD CROSSING' THEN 4.0
                WHEN 'PARKING ON FOOTPATH' THEN 3.5
                WHEN 'PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC' THEN 3.0
                WHEN 'PARKING OPPOSITE TO ANOTHER PARKED VEHICLE' THEN 3.0
                WHEN 'WRONG PARKING' THEN 2.0
                WHEN 'NO PARKING' THEN 1.5
                WHEN 'DEFECTIVE NUMBER PLATE' THEN 0.5
                ELSE 1.0
            END
        ) AS violation_severity_weight
        FROM violation_tags vt
        GROUP BY vt.id
        """
    ).df()

    df = df.merge(tags_df, on="id", how="left")
    df["violation_severity_weight"] = df["violation_severity_weight"].fillna(
        DEFAULT_VIOLATION_SEVERITY
    )
    df["combined_severity"] = (
        df["vehicle_severity_weight"] * df["violation_severity_weight"]
    )

    return df


def get_data_stats(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Return summary statistics for health check."""
    stats = conn.execute(
        """
        SELECT
            COUNT(*) AS total_approved,
            COUNT(DISTINCT police_station) AS unique_stations,
            COUNT(DISTINCT CASE WHEN is_junction THEN junction_name END) AS unique_junctions,
            MIN(created_datetime) AS date_min,
            MAX(created_datetime) AS date_max
        FROM violations_clean
        """
    ).fetchone()

    peak_hour = conn.execute(
        """
        SELECT hour_of_day, COUNT(*) AS cnt
        FROM violations_clean
        GROUP BY hour_of_day
        ORDER BY cnt DESC
        LIMIT 1
        """
    ).fetchone()

    most_active = conn.execute(
        """
        SELECT police_station, COUNT(*) AS cnt
        FROM violations_clean
        GROUP BY police_station
        ORDER BY cnt DESC
        LIMIT 1
        """
    ).fetchone()

    return {
        "total_approved": stats[0],
        "unique_stations": stats[1],
        "unique_junctions": stats[2],
        "date_min": str(stats[3]) if stats[3] else None,
        "date_max": str(stats[4]) if stats[4] else None,
        "peak_hour_citywide": peak_hour[0] if peak_hour else None,
        "most_active_station": most_active[0] if most_active else None,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    conn = load_csv_to_duckdb()
    stats = get_data_stats(conn)
    print("Data load successful!")
    print(f"  Approved records: {stats['total_approved']:,}")
    print(f"  Date range: {stats['date_min']} to {stats['date_max']}")
    print(f"  Police stations: {stats['unique_stations']}")
    print(f"  Named junctions: {stats['unique_junctions']}")
    print(f"  Peak hour: {stats['peak_hour_citywide']}:00")
    print(f"  Most active station: {stats['most_active_station']}")
    conn.close()
