# Backwards-compatibility shim.

from crud.costs.queries import (
    _build_scope_cte,
    get_daily_costs,
    get_daily_costs_by_category,
    get_daily_costs_by_tag_key,
    get_namespaces_for_tags,
    get_max_date,
)
from crud.costs.budgets import (
    get_budget,
    set_budget,
    get_active_budgets_scopes,
)
from crud.costs.forecasts import (
    save_forecast_snapshot,
    get_latest_forecast,
    get_forecast_quality,
)
from crud.costs.anomalies import (
    save_anomalies,
    get_anomalies_for_month,
    get_dashboard_anomalies,
    mark_anomaly_seen,
)

__all__ = [
    "_build_scope_cte",
    "get_daily_costs",
    "get_daily_costs_by_category",
    "get_daily_costs_by_tag_key",
    "get_namespaces_for_tags",
    "get_max_date",
    "get_budget",
    "set_budget",
    "get_active_budgets_scopes",
    "save_forecast_snapshot",
    "get_latest_forecast",
    "get_forecast_quality",
    "save_anomalies",
    "get_anomalies_for_month",
    "get_dashboard_anomalies",
    "mark_anomaly_seen",
]
