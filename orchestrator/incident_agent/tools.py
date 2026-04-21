"""
orchestrator/incident_agent/tools.py

ADK-compatible tool functions for the IGA Incident Analysis Agent.
Each function wraps the BigQuery data layer with guardrail validation.
These are registered in TOOL_REGISTRY by agent_from_manifest.py.
"""
from typing import Optional
from .bigquery_tool import (
    get_ai_analysis_by_incident_id,
    get_incident_by_id,
    get_column_names,
    fetch_incidents_by_date as bq_fetch_incidents_by_date,
    build_triage_dashboard as bq_build_triage_dashboard,
)
from .llm_policy_guardrail import validate_tool_call


def _guard_or_block(tool_name: str, args: dict) -> dict | None:
    """Run LLM policy guardrail. Returns block payload if denied, None if allowed."""
    allowed, reason = validate_tool_call(tool_name, args)
    if allowed:
        return None
    return {
        "status": "blocked",
        "tool": tool_name,
        "reason": reason,
    }


def fetch_ai_analysis(incident_id: str) -> dict:
    """
    Fetches the AI analysis for a given incident ID from BigQuery.

    Args:
        incident_id: The incident ID to look up (e.g. 'INC0012345').

    Returns:
        dict with 'status' and 'ai_analysis' keys.
    """
    blocked = _guard_or_block("fetch_ai_analysis", {"incident_id": incident_id})
    if blocked:
        return blocked
    try:
        analysis = get_ai_analysis_by_incident_id(incident_id)
        return {"status": "success", "incident_id": incident_id, "ai_analysis": analysis}
    except Exception as e:
        return {"status": "error", "incident_id": incident_id, "error": str(e)}


def fetch_incident_details(incident_id: str) -> dict:
    """
    Fetches the full incident details for a given incident ID from BigQuery.

    Args:
        incident_id: The incident ID to look up (e.g. 'INC0012345').

    Returns:
        dict with 'status' and full incident data.
    """
    blocked = _guard_or_block("fetch_incident_details", {"incident_id": incident_id})
    if blocked:
        return blocked
    try:
        incident = get_incident_by_id(incident_id)
        if incident is None:
            return {"status": "not_found", "incident_id": incident_id}
        return {"status": "success", "incident_id": incident_id, "data": incident}
    except Exception as e:
        return {"status": "error", "incident_id": incident_id, "error": str(e)}


def list_columns() -> dict:
    """
    Lists all available column names in the raw_incidents table.

    Returns:
        dict with 'status' and list of column names.
    """
    blocked = _guard_or_block("list_columns", {})
    if blocked:
        return blocked
    try:
        columns = get_column_names()
        return {"status": "success", "columns": columns}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def fetch_incidents_by_date(
    start_date: str,
    end_date: Optional[str] = None,
    incident_type: Optional[str] = None,
) -> dict:
    """
    Fetches incidents within a date range, optionally filtered by incident type.

    Args:
        start_date: Start date in 'YYYY-MM-DD' format.
        end_date: End date in 'YYYY-MM-DD' format (defaults to start_date).
        incident_type: Optional filter - 'NOISE', 'KB FOUND', or 'RCA REQUIRED'.

    Returns:
        dict with list of incidents found.
    """
    blocked = _guard_or_block(
        "fetch_incidents_by_date",
        {"start_date": start_date, "end_date": end_date, "incident_type": incident_type},
    )
    if blocked:
        return blocked
    return bq_fetch_incidents_by_date(
        start_date=start_date,
        end_date=end_date,
        incident_type=incident_type,
    )


def build_triage_dashboard(
    start_date: str,
    end_date: Optional[str] = None,
    incident_type: Optional[str] = None,
) -> dict:
    """
    Builds a triage dashboard for incidents in a date range.

    Args:
        start_date: Start date in 'YYYY-MM-DD' format.
        end_date: End date in 'YYYY-MM-DD' format (defaults to start_date).
        incident_type: Optional filter - 'NOISE', 'KB FOUND', or 'RCA REQUIRED'.

    Returns:
        dict with dashboard summary and list of classified incidents.
    """
    blocked = _guard_or_block(
        "build_triage_dashboard",
        {"start_date": start_date, "end_date": end_date, "incident_type": incident_type},
    )
    if blocked:
        return blocked
    return bq_build_triage_dashboard(
        start_date=start_date,
        end_date=end_date,
        incident_type=incident_type,
    )
