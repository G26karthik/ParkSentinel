"""Natural-language query engine (Text-to-SQL) for ParkSentinel.

This module combines three engineering layers on top of an LLM:

* Context engineering  - a schema-grounded system prompt with the real table
  shapes, the 10 canonical violation labels, vehicle types, junction/station
  formats, the live date range, DuckDB-specific notes and few-shot examples,
  plus optional live DISTINCT values pulled once from the database.
* Memory engineering   - lightweight per-session conversation memory so that
  follow-up questions resolve against prior turns, plus a question->result
  cache to avoid duplicate LLM calls.
* Harness engineering  - a provider abstraction (see ``llm_provider``), a
  read-only SQL guardrail, automatic ``LIMIT`` injection, a retry-with-error
  loop that feeds DuckDB errors back to the model, request timeouts and
  structured logging.

Public, backward-compatible surface:
    run_nl_query(conn, question[, session_id]) -> {sql, answer, data, row_count}
"""

from __future__ import annotations

import collections
import json
import logging
import re
import time
from typing import Any, Deque

import duckdb

import llm_provider

logger = logging.getLogger(__name__)

# --- Tunables ----------------------------------------------------------------

MAX_GENERATIONS = 3            # 1 initial generation + up to 2 regenerations
DEFAULT_ROW_LIMIT = 50
MEMORY_TURNS = 4              # how many prior turns to feed back into the prompt
SESSION_MEMORY_CAP = 64      # max distinct sessions kept in memory


# --- Context engineering: schema-grounded system prompt ----------------------

SCHEMA_PROMPT = """\
You are an expert DuckDB SQL analyst for "ParkSentinel", a Bengaluru (India)
traffic / parking-violation analytics platform. You translate a user's natural
language question into ONE valid, read-only DuckDB SQL query.

# DATABASE SCHEMA

## Table: violations_clean  (one row per approved violation report)
Pre-cleaned, approved-only records (validation_status = 'approved').
Columns:
  id                       TEXT      - unique report id (join key)
  latitude                 DOUBLE    - WGS84 latitude  (~12.7..13.4)
  longitude                DOUBLE    - WGS84 longitude (~77.3..77.9)
  location                 TEXT      - free-text street address
  vehicle_type             TEXT      - UPPERCASE category (see list below)
  violation_type           TEXT      - raw JSON-list string of labels; DO NOT
                                       parse this. Use violation_tags instead.
  created_datetime         TIMESTAMP - when the violation was recorded
  police_station           TEXT      - one of 54 jurisdictions (see examples)
  junction_name            TEXT      - "BTP051 - Safina Plaza Junction" style,
                                       or the literal 'No Junction'
  hour_of_day              INTEGER   - 0..23, precomputed from created_datetime
  day_of_week              INTEGER   - DuckDB DOW: 0=Sunday .. 6=Saturday
  month_year               TEXT      - precomputed 'YYYY-MM' (e.g. '2024-03')
  is_junction              BOOLEAN   - TRUE when junction_name <> 'No Junction'
  is_peak_hour             BOOLEAN   - TRUE for peak hours (7-9, 17-20)
  is_weekend               BOOLEAN   - TRUE for Saturday/Sunday
  vehicle_severity_weight  DOUBLE    - heavier vehicles weigh more
  validation_status        TEXT      - always 'approved' in this view

## Table: violation_tags  (one row per (report, violation_label) pair)
A single report can carry MULTIPLE violation labels, so this table is the
exploded form. Join to violations_clean on id.
Columns:
  id               TEXT  - report id (FK -> violations_clean.id)
  violation_label  TEXT  - one canonical UPPERCASE label (see list below)

# CANONICAL VALUES (case-sensitive, always UPPERCASE)

violation_label is EXACTLY one of these 10 (match the spelling precisely):
  WRONG PARKING
  NO PARKING
  PARKING IN A MAIN ROAD
  DEFECTIVE NUMBER PLATE
  PARKING ON FOOTPATH
  PARKING NEAR BUSTOP/SCHOOL/HOSPITAL ETC
  DOUBLE PARKING
  PARKING NEAR ROAD CROSSING
  PARKING NEAR TRAFFIC LIGHT OR ZEBRA CROSS
  PARKING OPPOSITE TO ANOTHER PARKED VEHICLE

vehicle_type values include:
  SCOOTER, CAR, MOTOR CYCLE, PASSENGER AUTO, MAXI-CAB, LGV, GOODS AUTO, MOPED,
  PRIVATE BUS, VAN, TEMPO, BUS (BMTC/KSRTC), HGV, LORRY/GOODS VEHICLE

police_station examples (54 total):
  Upparpet, Shivajinagar, Malleshwaram, City Market, Madiwala, Bellandur, ...

Data covers approximately Nov 2023 - Mar 2024 (~115,400 approved rows).

# RULES
1. To filter or count by a specific VIOLATION TYPE, you MUST join
   violation_tags (vt) to violations_clean (vc) on id and filter
   vt.violation_label. For everything else, query violations_clean directly.
2. When joining violation_tags, COUNT(*) counts (report x label) pairs. If you
   need distinct reports, use COUNT(DISTINCT vc.id).
3. Labels and most categorical values are UPPERCASE and case-sensitive — match
   them exactly.
4. Prefer the precomputed columns: hour_of_day, day_of_week, month_year,
   is_weekend, is_peak_hour, is_junction.
5. For month filtering, use the precomputed text column, e.g.
   month_year = '2024-03'. For an explicit hour use hour_of_day, or
   EXTRACT(HOUR FROM created_datetime).
6. 'No Junction' is NOT a real junction — exclude it (or use is_junction = TRUE)
   for junction-level questions.
7. Always return at most 50 rows (add LIMIT 50) unless the user asks for a
   specific smaller top-N.

# OUTPUT FORMAT
Return ONLY the SQL query. No prose, no explanation, no markdown code fences.
The query MUST be a single read-only statement starting with SELECT or WITH.

# FEW-SHOT EXAMPLES

Q: Which junction has the most HGV violations?
SQL:
SELECT junction_name, COUNT(*) AS violation_count
FROM violations_clean
WHERE vehicle_type = 'HGV' AND is_junction = TRUE
GROUP BY junction_name
ORDER BY violation_count DESC
LIMIT 50;

Q: What is the peak violation hour on weekends?
SQL:
SELECT hour_of_day, COUNT(*) AS violation_count
FROM violations_clean
WHERE is_weekend = TRUE
GROUP BY hour_of_day
ORDER BY violation_count DESC
LIMIT 50;

Q: Which police station zone worsened most in March?
SQL:
SELECT police_station,
       COUNT(*) FILTER (WHERE month_year = '2024-03') AS march_count,
       COUNT(*) FILTER (WHERE month_year = '2024-02') AS february_count,
       COUNT(*) FILTER (WHERE month_year = '2024-03')
         - COUNT(*) FILTER (WHERE month_year = '2024-02') AS increase
FROM violations_clean
WHERE month_year IN ('2024-02', '2024-03')
GROUP BY police_station
ORDER BY increase DESC
LIMIT 50;

Q: How many scooters were caught parking on footpaths?
SQL:
SELECT COUNT(DISTINCT vc.id) AS violation_count
FROM violations_clean vc
JOIN violation_tags vt ON vc.id = vt.id
WHERE vc.vehicle_type = 'SCOOTER'
  AND vt.violation_label = 'PARKING ON FOOTPATH'
LIMIT 50;

Q: Show top 5 zones by double parking incidents
SQL:
SELECT vc.police_station, COUNT(*) AS double_parking_count
FROM violations_clean vc
JOIN violation_tags vt ON vc.id = vt.id
WHERE vt.violation_label = 'DOUBLE PARKING'
GROUP BY vc.police_station
ORDER BY double_parking_count DESC
LIMIT 5;

Q: What are the most common violation types overall?
SQL:
SELECT vt.violation_label, COUNT(*) AS violation_count
FROM violation_tags vt
JOIN violations_clean vc ON vc.id = vt.id
GROUP BY vt.violation_label
ORDER BY violation_count DESC
LIMIT 50;
"""

# Cache of live DISTINCT values injected into the prompt (populated once).
_LIVE_VALUES_CACHE: dict[str, str] = {}


def _live_values_block(conn: duckdb.DuckDBPyConnection) -> str:
    """Pull DISTINCT vehicle_type / police_station once and cache the block."""
    if "block" in _LIVE_VALUES_CACHE:
        return _LIVE_VALUES_CACHE["block"]
    try:
        vehicles = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT vehicle_type FROM violations_clean "
                "WHERE vehicle_type IS NOT NULL ORDER BY 1"
            ).fetchall()
        ]
        stations = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT police_station FROM violations_clean "
                "WHERE police_station IS NOT NULL ORDER BY 1"
            ).fetchall()
        ]
        block = (
            "\n# LIVE DISTINCT VALUES (from the current database)\n"
            f"vehicle_type ({len(vehicles)}): {', '.join(vehicles)}\n"
            f"police_station ({len(stations)}): {', '.join(stations)}\n"
        )
    except Exception as e:  # never let prompt-enrichment break a query
        logger.warning("Could not inject live DISTINCT values: %s", e)
        block = ""
    _LIVE_VALUES_CACHE["block"] = block
    return block


def _build_system_instruction(conn: duckdb.DuckDBPyConnection | None) -> str:
    if conn is None:
        return SCHEMA_PROMPT
    return SCHEMA_PROMPT + _live_values_block(conn)


# --- Memory engineering ------------------------------------------------------

# Per-session ring buffer of {question, sql, summary}.
_SESSION_MEMORY: "collections.OrderedDict[str, Deque[dict[str, str]]]" = (
    collections.OrderedDict()
)
# Global question -> full result cache (avoids duplicate LLM calls / speeds repeats).
_QUERY_CACHE: dict[str, dict[str, Any]] = {}


def _normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def _get_session(session_id: str) -> Deque[dict[str, str]]:
    mem = _SESSION_MEMORY.get(session_id)
    if mem is None:
        mem = collections.deque(maxlen=MEMORY_TURNS)
        _SESSION_MEMORY[session_id] = mem
        # Evict oldest sessions if we exceed the cap.
        while len(_SESSION_MEMORY) > SESSION_MEMORY_CAP:
            _SESSION_MEMORY.popitem(last=False)
    else:
        _SESSION_MEMORY.move_to_end(session_id)
    return mem


def _memory_context(session_id: str) -> str:
    mem = _SESSION_MEMORY.get(session_id)
    if not mem:
        return ""
    lines = ["# RECENT CONVERSATION (most recent last) — resolve follow-ups against this:"]
    for i, turn in enumerate(mem, 1):
        lines.append(f"[turn {i}] Q: {turn['question']}")
        lines.append(f"         SQL: {turn['sql']}")
        if turn.get("summary"):
            lines.append(f"         RESULT: {turn['summary']}")
    return "\n".join(lines) + "\n\n"


def _remember(session_id: str, question: str, sql: str, summary: str) -> None:
    _get_session(session_id).append(
        {"question": question, "sql": sql, "summary": summary[:240]}
    )


def _short_result_summary(data: list[dict[str, Any]], row_count: int) -> str:
    if row_count == 0:
        return "0 rows"
    head = json.dumps(data[0], default=str)
    if len(head) > 160:
        head = head[:157] + "..."
    return f"{row_count} row(s); first row: {head}"


def clear_memory(session_id: str | None = None) -> None:
    """Test/util helper: clear one session or all conversation memory + cache."""
    if session_id is None:
        _SESSION_MEMORY.clear()
        _QUERY_CACHE.clear()
    else:
        _SESSION_MEMORY.pop(session_id, None)


# --- Harness engineering: read-only SQL guardrail ----------------------------

class SQLGuardrailError(ValueError):
    """Raised when generated SQL is not a safe, single read-only statement."""


_FORBIDDEN_KEYWORDS = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|UPSERT|"
    r"ATTACH|DETACH|COPY|PRAGMA|INSTALL|LOAD|EXPORT|IMPORT|"
    r"SET|RESET|CALL|VACUUM|GRANT|REVOKE"
    r")\b",
    re.IGNORECASE,
)


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)            # line comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)  # block comments
    return sql


def _strip_string_literals(sql: str) -> str:
    """Blank out quoted strings/identifiers so keyword checks ignore them."""
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)        # single-quoted strings
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)        # double-quoted identifiers
    return sql


def _clean_sql(raw: str) -> str:
    """Strip markdown fences and surrounding whitespace from LLM output."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def validate_sql_readonly(sql: str) -> str:
    """Validate that ``sql`` is a single read-only SELECT/WITH statement.

    Returns the cleaned SQL (markdown stripped, trailing semicolon removed).
    Raises :class:`SQLGuardrailError` otherwise.
    """
    cleaned = _clean_sql(sql)
    if not cleaned:
        raise SQLGuardrailError("empty query")

    # Analyse a comment-free, string-free copy so literals can't smuggle keywords.
    probe = _strip_string_literals(_strip_sql_comments(cleaned)).strip()
    probe_no_trailing = probe.rstrip().rstrip(";").strip()

    if ";" in probe_no_trailing:
        raise SQLGuardrailError("multiple statements are not allowed")

    if not re.match(r"(?is)^\s*(WITH|SELECT)\b", probe_no_trailing):
        raise SQLGuardrailError("only SELECT / WITH...SELECT queries are allowed")

    match = _FORBIDDEN_KEYWORDS.search(probe_no_trailing)
    if match:
        raise SQLGuardrailError(
            f"forbidden keyword '{match.group(1).upper()}' detected"
        )

    return cleaned.rstrip().rstrip(";").strip()


def ensure_limit(sql: str, limit: int = DEFAULT_ROW_LIMIT) -> str:
    """Append ``LIMIT n`` if the (outermost) query has no LIMIT clause."""
    probe = _strip_string_literals(_strip_sql_comments(sql))
    if re.search(r"(?is)\blimit\b", probe):
        return sql
    return f"{sql.rstrip().rstrip(';').rstrip()}\nLIMIT {limit}"


# --- LLM calls ---------------------------------------------------------------

def generate_sql(
    question: str,
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
    error_context: str | None = None,
    memory_context: str = "",
) -> str:
    """Generate (raw, unvalidated) DuckDB SQL for a question."""
    system = _build_system_instruction(conn)
    parts = []
    if memory_context:
        parts.append(memory_context)
    parts.append(f"Question: {question}")
    if error_context:
        parts.append(
            "\nYour previous SQL was invalid. Error:\n"
            f"{error_context}\n"
            "Return a corrected single read-only SELECT/WITH query that fixes this."
        )
    raw = llm_provider.complete(system, "\n".join(parts), temperature=0.0)
    return _clean_sql(raw)


def execute_query(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    """Execute SQL and return rows as a list of JSON-safe dicts."""
    result = conn.execute(sql).fetchdf()
    return json.loads(result.to_json(orient="records", date_format="iso"))


def summarize_results(
    question: str, sql: str, data: list[dict[str, Any]]
) -> str:
    """Summarize query results in plain language for a traffic officer."""
    prompt = (
        f"Question: {question}\n"
        f"SQL run: {sql}\n"
        f"Result rows (up to 20 shown): {json.dumps(data[:20], default=str)}\n\n"
        "Answer the question in 2-3 clear sentences for a Bengaluru Traffic "
        "Police officer. Use concrete numbers from the result. If the result "
        "is empty, say so plainly."
    )
    try:
        return llm_provider.complete(
            "You summarize Bengaluru parking-violation query results concisely "
            "and accurately for traffic police officers.",
            prompt,
            temperature=0.2,
        ).strip()
    except Exception as e:
        logger.warning("Summarization failed, falling back to row count: %s", e)
        return f"Query returned {len(data)} row(s)."


# --- Public pipeline ---------------------------------------------------------

def run_nl_query(
    conn: duckdb.DuckDBPyConnection,
    question: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Full Text-to-SQL pipeline.

    Backward compatible: callable as ``run_nl_query(conn, question)`` and always
    returns ``{sql, answer, data, row_count}``. ``session_id`` is optional and
    enables per-session conversation memory; when omitted a shared "default"
    session is used so the existing POST /query path still benefits from memory.
    """
    started = time.perf_counter()
    sid = session_id or "default"
    norm = _normalize_question(question)

    # Memory: question -> result cache (skips both SQL-gen and summary LLM calls).
    cached = _QUERY_CACHE.get(norm)
    if cached is not None:
        logger.info("query.cache_hit session=%s q=%r", sid, question)
        _remember(sid, question, cached["sql"], _short_result_summary(
            cached["data"], cached["row_count"]))
        return json.loads(json.dumps(cached))  # defensive copy

    memory_context = _memory_context(sid)

    sql = ""
    data: list[dict[str, Any]] = []
    error: str | None = None
    last_was_guardrail = False

    for attempt in range(MAX_GENERATIONS):
        try:
            raw = generate_sql(
                question,
                conn=conn,
                error_context=error,
                memory_context=memory_context,
            )
        except llm_provider.LLMError as e:
            logger.error("query.llm_unavailable: %s", e)
            return {
                "sql": "",
                "answer": f"The language model is unavailable: {e}",
                "data": [],
                "row_count": 0,
            }

        # Guardrail: must be a single read-only SELECT/WITH.
        try:
            validated = validate_sql_readonly(raw)
            last_was_guardrail = False
        except SQLGuardrailError as g:
            sql = raw
            error = (
                f"Query rejected by read-only guardrail: {g}. You MUST return a "
                "single read-only SELECT or WITH...SELECT query that only reads data."
            )
            last_was_guardrail = True
            logger.warning(
                "query.guardrail_reject attempt=%d reason=%s sql=%r",
                attempt + 1, g, raw,
            )
            continue

        sql = ensure_limit(validated)
        try:
            data = execute_query(conn, sql)
            latency_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "query.success session=%s attempt=%d latency_ms=%.0f rows=%d sql=%r",
                sid, attempt + 1, latency_ms, len(data), sql,
            )
            break
        except Exception as e:
            error = str(e)
            logger.warning(
                "query.exec_fail attempt=%d err=%s sql=%r", attempt + 1, error, sql
            )
    else:
        # All attempts exhausted without a successful execution.
        if last_was_guardrail:
            answer = (
                "That request was blocked: I can only run read-only analytical "
                "queries (SELECT) over the violations data, not commands that "
                "modify or manage the database."
            )
        else:
            answer = (
                f"I couldn't build a valid query for that question (last error: "
                f"{error}). Please try rephrasing it."
            )
        logger.info("query.failed session=%s guardrail=%s", sid, last_was_guardrail)
        return {"sql": sql, "answer": answer, "data": [], "row_count": 0}

    answer = summarize_results(question, sql, data)
    result = {"sql": sql, "answer": answer, "data": data, "row_count": len(data)}

    _QUERY_CACHE[norm] = json.loads(json.dumps(result))
    _remember(sid, question, sql, _short_result_summary(data, len(data)))
    return result
