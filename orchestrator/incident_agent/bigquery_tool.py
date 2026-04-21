"""
orchestrator/incident_agent/bigquery_tool.py

BigQuery data layer for the IGA incident analysis agent.
Reads from raw_incidents and analysis_result tables.

Config resolution: env var > hardcoded default.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# -- BigQuery coordinates (env var > hardcoded default) -----------------------
BQ_PROJECT      = os.getenv("BQ_PROJECT", "gsk-corp-ai-tech-ops-dev")
BQ_DATASET      = os.getenv("BQ_DATASET", "snow")
BQ_RAW_TABLE    = os.getenv("BQ_RAW_TABLE", "raw_incidents")
BQ_RESULT_TABLE = os.getenv("BQ_RESULT_TABLE", "analysis_result")

_FULL_RAW_TABLE    = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_RAW_TABLE}"
_FULL_RESULT_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_RESULT_TABLE}"

# -- Lazy singleton client ----------------------------------------------------
_client: bigquery.Client | None = None


def _get_client() -> bigquery.Client:
    """Return a cached BigQuery client (created on first call)."""
    global _client
    if _client is None:
        _client = bigquery.Client(project=BQ_PROJECT)
        logger.info("BigQuery client initialised (project=%s)", BQ_PROJECT)
    return _client


# -- Column mapping: BQ column -> internal snake_case key ---------------------
COLUMN_MAP = {
    "number":            "incident_number",
    "caller":            "caller",
    "short_description": "short_description",
    "description":       "description",
    "category":          "category",
    "priority":          "priority",
    "state":             "state",
    "assignment_group":  "assignment_group",
    "assigned_to":       "assigned_to",
    "opened_at":         "opened_at",
    "closed_at":         "closed_at",
    "ingested_at":       "ingested_at",
}


# =============================================================================
#  READ helpers
# =============================================================================

def get_incident_by_id(incident_id: str) -> Optional[dict]:
    """Fetch a single incident from raw_incidents by its number."""
    client = _get_client()
    query = f"""
        SELECT * FROM `{_FULL_RAW_TABLE}`
        WHERE UPPER(TRIM(number)) = @incident_id
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "incident_id", "STRING", incident_id.strip().upper()
            ),
        ]
    )
    df = client.query(query, job_config=job_config).to_dataframe()
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    return {
        k: ("" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v))
        for k, v in row.items()
    }


def get_ai_analysis_by_incident_id(incident_id: str) -> dict:
    """Fetch the latest AI analysis for a given incident from analysis_result."""
    client = _get_client()
    query = f"""
        SELECT
            incident_type,
            ai_analysis,
            summary,
            recommended_actions,
            noise_reason,
            confidence_score,
            kb_article_title,
            kb_article_url,
            rca_reason,
            lookalike_incidents,
            analyzed_at
        FROM `{_FULL_RESULT_TABLE}`
        WHERE UPPER(TRIM(number)) = @incident_id
        ORDER BY analyzed_at DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "incident_id", "STRING", incident_id.strip().upper()
            ),
        ]
    )
    try:
        df = client.query(query, job_config=job_config).to_dataframe()
    except Exception as exc:
        logger.warning("get_ai_analysis_by_incident_id query failed: %s", exc)
        return {"status": "error", "incident_id": incident_id, "error": str(exc)}

    if df.empty:
        return {"status": "not_found", "incident_id": incident_id}

    def _safe_str(val) -> str:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        return str(val).strip()

    def _safe_float(val) -> float | None:
        try:
            return float(val) if val is not None and str(val) != "" else None
        except (ValueError, TypeError):
            return None

    row = df.iloc[0]
    return {
        "status":              "success",
        "incident_id":         incident_id,
        "incident_type":       _safe_str(row.get("incident_type")),
        "ai_analysis":         _safe_str(row.get("ai_analysis")),
        "summary":             _safe_str(row.get("summary")),
        "recommended_actions": _safe_str(row.get("recommended_actions")),
        "noise_reason":        _safe_str(row.get("noise_reason")),
        "confidence_score":    _safe_float(row.get("confidence_score")),
        "kb_article_title":    _safe_str(row.get("kb_article_title")),
        "kb_article_url":      _safe_str(row.get("kb_article_url")),
        "rca_reason":          _safe_str(row.get("rca_reason")),
        "lookalike_incidents": _safe_str(row.get("lookalike_incidents")),
        "analyzed_at":         _safe_str(row.get("analyzed_at")),
    }


def get_column_names() -> list[str]:
    """Return column names of the raw_incidents table."""
    return list(COLUMN_MAP.keys())


def fetch_incidents_by_date(
    start_date: str,
    end_date: str = None,
    incident_type: str = None,
) -> dict:
    """Fetch incidents within a date range, optionally filtered by type."""
    try:
        client = _get_client()
        end_date = end_date or start_date

        type_filter_sql = ""
        params = [
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date",   "DATE", end_date),
        ]

        if incident_type and incident_type.strip():
            type_filter_sql = "AND UPPER(TRIM(a.incident_type)) = @incident_type"
            params.append(
                bigquery.ScalarQueryParameter(
                    "incident_type", "STRING", incident_type.strip().upper()
                )
            )

        query = f"""
            SELECT
                r.number,
                a.incident_type,
                a.confidence_score,
                a.lookalike_incidents,
                r.short_description,
                r.opened_at
            FROM (
                SELECT
                    number,
                    incident_type,
                    confidence_score,
                    lookalike_incidents,
                    ROW_NUMBER() OVER (PARTITION BY number ORDER BY number) AS rn
                FROM `{_FULL_RESULT_TABLE}`
            ) a
            JOIN `{_FULL_RAW_TABLE}` r
                ON UPPER(TRIM(a.number)) = UPPER(TRIM(r.number))
            WHERE a.rn = 1
              AND COALESCE(
                    DATE(SAFE_CAST(r.opened_at AS TIMESTAMP)),
                    SAFE.PARSE_DATE('%d-%b-%Y', SUBSTR(CAST(r.opened_at AS STRING), 1, 11)),
                    SAFE.PARSE_DATE('%Y-%m-%d', SUBSTR(CAST(r.opened_at AS STRING), 1, 10)),
                    DATE(SAFE.PARSE_DATETIME('%Y-%m-%d %H:%M:%S', CAST(r.opened_at AS STRING))),
                    DATE(SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez', CAST(r.opened_at AS STRING)))
                  ) BETWEEN @start_date AND @end_date
              {type_filter_sql}
            ORDER BY COALESCE(
                SAFE_CAST(r.opened_at AS TIMESTAMP),
                SAFE.PARSE_TIMESTAMP('%d-%b-%Y %H:%M:%S', CAST(r.opened_at AS STRING)),
                SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', CAST(r.opened_at AS STRING)),
                SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez', CAST(r.opened_at AS STRING))
            ) DESC
        """

        job_config = bigquery.QueryJobConfig(query_parameters=params)
        df = client.query(query, job_config=job_config).to_dataframe()

        if df.empty:
            type_msg = f" of type '{incident_type}'" if incident_type else ""
            return {
                "status": "no_incidents",
                "message": f"No incidents{type_msg} found between {start_date} and {end_date}.",
            }

        incidents = []
        for _, row in df.iterrows():
            raw_conf = row.get("confidence_score")
            try:
                confidence_val = float(raw_conf) if raw_conf is not None and str(raw_conf) != "" else None
            except (TypeError, ValueError):
                confidence_val = None

            raw_lookalikes = str(row.get("lookalike_incidents", "") or "")
            similar_count = 0
            if raw_lookalikes.strip():
                for token in [t.strip() for t in re.split(r"[\n,;]+", raw_lookalikes) if t.strip()]:
                    similar_count += 1

            incidents.append({
                "incident_id":             str(row["number"]),
                "incident_type":           str(row.get("incident_type", "N/A")).strip() or "N/A",
                "short_description":       str(row.get("short_description", "")),
                "opened":                  str(row.get("opened_at", "")),
                "confidence_score":        confidence_val,
                "similar_incidents_count": similar_count,
            })

        return {
            "status": "success",
            "count": len(incidents),
            "date_range": f"{start_date} to {end_date}",
            "incident_type_filter": incident_type if incident_type else "All",
            "incidents": incidents,
        }
    except Exception as e:
        logger.error("fetch_incidents_by_date failed: %s", e)
        return {
            "status": "error",
            "message": f"BigQuery query failed: {e}",
        }


def build_triage_dashboard(
    start_date: str,
    end_date: str = None,
    incident_type: str = None,
) -> dict:
    """Build triage dashboard from fetch_incidents_by_date results."""
    result = fetch_incidents_by_date(
        start_date=start_date,
        end_date=end_date,
        incident_type=incident_type,
    )

    if result.get("status") != "success":
        return result

    incidents = result.get("incidents", []) or []

    def _enterprise_classification(raw_type: str) -> str:
        t = (raw_type or "").strip().upper()
        if t == "NOISE":
            return "NOISE - AUTO CLOSE CANDIDATE"
        if t == "KB FOUND":
            return "KB RESOLUTION AVAILABLE"
        if t == "RCA REQUIRED":
            return "INVESTIGATION REQUIRED"
        return "INVESTIGATION REQUIRED"

    def _next_action_label(raw_type: str) -> str:
        t = (raw_type or "").strip().upper()
        if t == "NOISE":
            return "Close after validation"
        if t == "KB FOUND":
            return "Apply KB resolution"
        return "Perform targeted investigation using AI report"

    def _effort_saved_minutes(raw_type: str) -> int:
        t = (raw_type or "").strip().upper()
        if t == "NOISE":
            return 15
        if t == "KB FOUND":
            return 25
        return 10

    dashboard_incidents: list[dict] = []
    noise_auto_close_count = 0
    kb_resolution_count = 0
    investigation_required_count = 0
    estimated_effort_saved_minutes = 0

    for inc in incidents:
        raw_type = str(inc.get("incident_type", "") or "")
        t = raw_type.strip().upper()

        if t == "NOISE":
            noise_auto_close_count += 1
        elif t == "KB FOUND":
            kb_resolution_count += 1
        else:
            investigation_required_count += 1

        effort_saved = _effort_saved_minutes(t)
        estimated_effort_saved_minutes += effort_saved

        dashboard_incidents.append({
            "incident_id":          str(inc.get("incident_id", "")),
            "classification":       _enterprise_classification(t),
            "next_action":          _next_action_label(t),
            "confidence":           inc.get("confidence_score"),
            "similar_incidents":    int(inc.get("similar_incidents_count", 0) or 0),
            "effort_saved_minutes": effort_saved,
            "short_description":    str(inc.get("short_description", "") or ""),
            "opened":               str(inc.get("opened", "") or ""),
            "incident_type":        t or "N/A",
        })

    return {
        "status": "success",
        "start_date": start_date,
        "end_date": end_date or start_date,
        "incident_type_filter": incident_type if incident_type else "All",
        "total_incidents": len(dashboard_incidents),
        "noise_auto_close_count": noise_auto_close_count,
        "kb_resolution_count": kb_resolution_count,
        "investigation_required_count": investigation_required_count,
        "estimated_effort_saved_minutes": estimated_effort_saved_minutes,
        "incidents": dashboard_incidents,
    }
