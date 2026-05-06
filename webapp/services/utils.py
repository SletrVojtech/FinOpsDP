"""
Shared Service Utilities Module.

Provides small helper functions used across the service and router layers:
tag extraction from HTTP requests and human-readable formatting of
Kubernetes CPU and memory values.
"""

import calendar
from datetime import date, timedelta
from fastapi import Request


def extract_active_tags(request: Request) -> dict:
    """Extract tag filters from an HTTP request's query parameters.

    Collects all query parameters whose name starts with ``tag_`` and
    returns them as a plain dict with the ``tag_`` prefix stripped.

    Args:
        request (Request): The incoming FastAPI request object.

    Returns:
        dict: Mapping of tag keys to their values, e.g.
            ``{"env": "prod", "team": "data"}``.
    """
    active_tags = {}
    for param_name, param_value in request.query_params.items():
        if param_name.startswith("tag_") and param_value:
            active_tags[param_name[4:]] = param_value
    return active_tags


def humanize_memory(mem_str: str) -> str:
    """Format a raw byte count string into a human-readable memory value.

    Args:
        mem_str (str): Raw byte count as a string (e.g. ``"1073741824"``).
            Accepts ``None`` or ``"None"`` as sentinel values.

    Returns:
        str: Formatted string with unit suffix (``Gi``, ``Mi``, ``Ki``, ``B``),
            or ``"-"`` for missing/invalid input.
    """
    if not mem_str or mem_str == "None":
        return "-"
    try:
        bytes_val = float(mem_str)
        if bytes_val >= 1024**3:
            return f"{bytes_val / (1024**3):.2f} Gi"
        elif bytes_val >= 1024**2:
            return f"{bytes_val / (1024**2):.0f} Mi"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.0f} Ki"
        else:
            return f"{bytes_val:.0f} B"
    except ValueError:
        return mem_str


def humanize_cpu(cpu_str: str) -> str:
    """Format a raw CPU core count string into a human-readable value.

    Fractional cores are expressed in millicores (``m`` suffix); whole
    cores are shown with two decimal places.

    Args:
        cpu_str (str): CPU core count as a string (e.g. ``"0.25"``).
            Accepts ``None`` or ``"None"`` as sentinel values.

    Returns:
        str: Formatted string (e.g. ``"250m"`` or ``"2.00"``),
            or ``"-"`` for missing/invalid input.
    """
    if not cpu_str or cpu_str == "None":
        return "-"
    try:
        cores = float(cpu_str)
        if cores < 1:
            return f"{cores * 1000:.0f}m"
        return f"{cores:.2f}"
    except ValueError:
        return cpu_str