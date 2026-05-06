"""
Forecast History Module.

Stores and retrieves AutoARIMA forecast snapshots from the
``ForecastHistory`` table, and computes forecast quality
metrics by comparing stored projections to actual billed costs.
"""

import json
import calendar
from datetime import date, timedelta
from collections import defaultdict

from crud.costs.queries import get_daily_costs


def save_forecast_snapshot(
    cursor,
    scope_id: int,
    tags_filter: dict,
    target_month: date,
    amount: float,
    daily_forecasts: dict = None,
):
    """Persist a daily forecast snapshot to ``ForecastHistory``.

    Uses ``ON CONFLICT … DO UPDATE`` so multiple daily runs are safe and
    the table always reflects the latest forecast for the day.

    Args:
        cursor: Active database cursor.
        scope_id (int): Scope entity ID (0 for global).
        tags_filter (dict): Tag key-value filter identifying the scope.
        target_month (date): The month this forecast is for.
        amount (float): Projected monthly total in EUR.
        daily_forecasts (dict, optional): Mapping of ISO date strings to
            per-day forecast values.
    """
    tags_json = json.dumps(tags_filter) if tags_filter else '{}'
    daily_json = json.dumps(daily_forecasts) if daily_forecasts else '{}'
    scope_id = scope_id if scope_id is not None else 0
    today = date.today()

    cursor.execute("""
        INSERT INTO ForecastHistory (ScopeId, Tags, TargetMonth, ForecastDate, ProjectedAmount, DailyForecasts, CalculatedAt)
        VALUES (%s, %s::jsonb, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        ON CONFLICT (ScopeId, Tags, TargetMonth, ForecastDate) 
        DO UPDATE SET 
            ProjectedAmount = EXCLUDED.ProjectedAmount,
            DailyForecasts = EXCLUDED.DailyForecasts,
            CalculatedAt = CURRENT_TIMESTAMP;
    """, (scope_id, tags_json, target_month, today, amount, daily_json))


def get_latest_forecast(
    cursor,
    scope_id: int,
    tags_filter: dict,
    target_month: date,
) -> dict:
    """Return the most recent forecast calculated within the last 24 hours.

    Args:
        cursor: Active database cursor.
        scope_id (int): Scope entity ID.
        tags_filter (dict): Tag key-value filter.
        target_month (date): The month to retrieve the forecast for.

    Returns:
        dict: Dict with keys ``projected_amount`` and ``daily_forecasts``,
            or ``None`` if no recent forecast exists.
    """
    tags_json = json.dumps(tags_filter) if tags_filter else '{}'
    scope_id = scope_id if scope_id is not None else 0
    
    cursor.execute("""
        SELECT ProjectedAmount, DailyForecasts 
        FROM ForecastHistory 
        WHERE ScopeId = %s 
          AND Tags::jsonb = %s::jsonb 
          AND TargetMonth = %s
          AND CalculatedAt >= NOW() - INTERVAL '24 HOURS'
        ORDER BY CalculatedAt DESC
        LIMIT 1;
    """, (scope_id, tags_json, target_month))
    
    row = cursor.fetchone()
    if row:
        return {
            "projected_amount": float(row[0]),
            "daily_forecasts": row[1] if isinstance(row[1], dict) else {}
        }
    return None


def get_forecast_quality(cursor, target_month: date) -> list:
    """Compute post-hoc forecast accuracy metrics for all scopes in a target month.

    Fetches all ``ForecastHistory`` records for the month, groups them by
    scope and tags, computes the average projection across all saved
    snapshots (representing the prediction), and compares it to the most
    recent snapshot (representing the final actual projection). Fetches
    historical daily actuals for comparison plotting.

    Args:
        cursor: Active database cursor.
        target_month (date): Any date within the month to evaluate.

    Returns:
        list: Dicts per scope with keys ``scope_id``, ``scope_name``,
            ``tags``, ``projected_amount``, ``actual_amount``,
            ``variance``, ``accuracy`` (0–100 %), ``daily_forecasts``,
            and ``daily_actuals``.
    """
    query = """
        SELECT fh.ScopeId, e.ResourceName, fh.Tags, fh.ForecastDate, 
               fh.ProjectedAmount, fh.DailyForecasts, fh.CalculatedAt
        FROM ForecastHistory fh
        LEFT JOIN Entities e ON fh.ScopeId = e.Id
        WHERE fh.TargetMonth = %s AND fh.DailyForecasts IS NOT NULL
        ORDER BY fh.ScopeId NULLS FIRST, fh.CalculatedAt ASC;
    """
    cursor.execute(query, (target_month,))
    forecast_rows = cursor.fetchall()
    
    grouped = defaultdict(list)
    
    for row in forecast_rows:
        scope_id = row[0] if row[0] is not None else 0
        scope_name = row[1] or "Globální (Vše)"
        tags_dict = row[2] or {}
        # Serialize tags to string for consistent grouping
        tags_str = json.dumps(tags_dict, sort_keys=True)
        
        grouped[f"{scope_id}|{scope_name}|{tags_str}"].append({
            "tags": tags_dict,
            "forecast_date": row[3],
            "projected_amount": float(row[4]) if row[4] is not None else 0.0,
            "daily_forecasts": row[5] or {},
            "calculated_at": row[6]
        })
        
    results = []
    
    for group_key, forecasts in grouped.items():
        parts = group_key.split("|", 2)
        scope_id = int(parts[0])
        scope_name = parts[1]
        tags = forecasts[0]["tags"]
        
        # The latest forecast represents the actual projected status at the end of the month
        latest_forecast = forecasts[-1]
        latest_amount = latest_forecast["projected_amount"]
        
        # Aggregate all forecasts to represent the prediction
        total_amount = sum(f["projected_amount"] for f in forecasts)
        avg_amount = total_amount / len(forecasts) if forecasts else 0.0
        
        avg_daily = {}
        all_keys = set(k for f in forecasts for k in f["daily_forecasts"].keys())
        for k in all_keys:
            vals = [float(f["daily_forecasts"].get(k, 0.0)) for f in forecasts]
            avg_daily[k] = sum(vals) / len(vals)
            
        variance = latest_amount - avg_amount
        if avg_amount > 0:
            accuracy = 100.0 - min(100.0, abs(variance) / avg_amount * 100.0)
        else:
            accuracy = 100.0 if latest_amount == 0 else 0.0

        start_date = target_month.replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)
        
        # Fetch the historical actuals for plotting
        daily_actuals_data = get_daily_costs(cursor, scope_id=scope_id, tags_filter=tags, 
                                             target_date=target_month, start_date=start_date, end_date=end_date)
        daily_actuals_dict = {d["date"]: d["cost"] for d in daily_actuals_data}
            
        results.append({
            "scope_id": scope_id,
            "scope_name": scope_name,
            "tags": tags,
            "forecast_date": latest_forecast["forecast_date"].isoformat() if latest_forecast["forecast_date"] else None,
            "projected_amount": avg_amount,
            "actual_amount": latest_amount,
            "variance": variance,
            "accuracy": accuracy,
            "daily_forecasts": avg_daily,
            "daily_actuals": daily_actuals_dict
        })
        
    return results
