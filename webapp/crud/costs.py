import calendar
from datetime import date, timedelta
from crud import allocations
import json
from datetime import date


def _build_scope_cte(scope_id: int, tags_filter: dict):
    """Returns (sql_fragment, params) for the shared SubTree/FilteredEntities CTE."""
    tags_filter = tags_filter or {}
    params = [scope_id, scope_id]
    sql = """
        WITH RECURSIVE SubTree AS (
            SELECT Id, ParentId, Tags FROM Entities WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.ParentId, e.Tags FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
        ),
        BaseData AS (
            SELECT Id, Tags FROM SubTree WHERE Id != %s
        ),
        FilteredEntities AS ( SELECT Id FROM BaseData WHERE 1=1"""
    for key, value in tags_filter.items():
        sql += " AND Tags->>%s = %s"
        params.extend([key, value])
    sql += ")"
    return sql, params


def get_daily_costs(cursor, scope_id: int = 0, tags_filter: dict = None, target_date: date = None,
                    start_date: date = None, end_date: date = None, exchange_rate: float = 1.0):
    """
        Returns daily and accumulative data for given scope and tags for a time window.
        Based on https://focus.finops.org/use-cases/#forecast-amortized-costs-month-over-month-based-on-historical-trends-2
        but for daily aggregation and already scoped set of IDs.
        Uses TimescaleDB gap-filling function to ensure continuity of data.
    """
    # Backwards compability to get the current month
    if target_date and not start_date:
        start_date = target_date.replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)
        
    # Fallback for the actual month
    if not start_date or not end_date:
        start_date = date.today().replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)

    cte_sql, params = _build_scope_cte(scope_id, tags_filter)
    query = cte_sql + """
        , Gapfilled AS(
            SELECT 
            time_bucket_gapfill(
                '1 day', 
                c.ChargePeriodStart, 
                %s::timestamptz, 
                %s::timestamptz
            ) AS bucket,
            COALESCE(SUM(c.BilledCost * (CASE WHEN c.BillingCurrency = 'USD' THEN %s ELSE 1.0 END)), 0.0) AS daily_cost
        FROM Costs c
        JOIN FilteredEntities fe ON c.EntityId = fe.Id
        WHERE 
            c.ChargePeriodStart >= %s::timestamptz
            AND c.ChargePeriodStart < %s::timestamptz
        GROUP BY bucket)
        SELECT
            bucket::date AS cost_date,
            daily_cost
        FROM Gapfilled
        ORDER BY cost_date ASC;
    """
    params.extend([start_date, end_date, exchange_rate, start_date, end_date])
    cursor.execute(query, params)
    return [{"date": r[0].isoformat(), "cost": float(r[1])} for r in cursor.fetchall()]


def get_daily_costs_by_category(cursor, scope_id: int = 0, tags_filter: dict = None,
                                start_date: date = None, end_date: date = None, exchange_rate: float = 1.0):
    """Daily costs grouped by ServiceCategory. No gap-filling."""
    if not start_date or not end_date:
        start_date = date.today().replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)

    cte_sql, params = _build_scope_cte(scope_id, tags_filter)
    query = cte_sql + """
        SELECT c.ChargePeriodStart::date,
               COALESCE(c.ServiceCategory, 'Other'),
               SUM(c.BilledCost * (CASE WHEN c.BillingCurrency = 'USD' THEN %s ELSE 1.0 END))
        FROM Costs c
        JOIN FilteredEntities fe ON c.EntityId = fe.Id
        WHERE c.ChargePeriodStart >= %s::timestamptz
          AND c.ChargePeriodStart < %s::timestamptz
        GROUP BY 1, 2 ORDER BY 1, 2;
    """
    params.extend([exchange_rate, start_date, end_date])
    cursor.execute(query, params)
    return [{"date": r[0].isoformat(), "category": r[1], "cost": float(r[2])}
            for r in cursor.fetchall()]


def get_daily_costs_by_tag_key(cursor, scope_id: int = 0, tags_filter: dict = None,
                               tag_key: str = None,
                               start_date: date = None, end_date: date = None, exchange_rate: float = 1.0):
    """Daily costs grouped by values of a given tag key.
    Resources without the tag are grouped as 'Unrecognized'.
    """
    if not start_date or not end_date:
        start_date = date.today().replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)

    if not tag_key:
        return []

    cte_sql, params = _build_scope_cte(scope_id, tags_filter)
    query = cte_sql + """
        SELECT c.ChargePeriodStart::date,
               COALESCE(e.Tags->>%s, 'Unrecognized'),
               SUM(c.BilledCost * (CASE WHEN c.BillingCurrency = 'USD' THEN %s ELSE 1.0 END))
        FROM Costs c
        JOIN Entities e ON c.EntityId = e.Id
        JOIN FilteredEntities fe ON e.Id = fe.Id
        WHERE c.ChargePeriodStart >= %s::timestamptz
          AND c.ChargePeriodStart < %s::timestamptz
        GROUP BY 1, 2 ORDER BY 1, 2;
    """
    params.extend([tag_key, exchange_rate, start_date, end_date])
    cursor.execute(query, params)
    return [{"date": r[0].isoformat(), "tag_value": r[1], "cost": float(r[2])}
            for r in cursor.fetchall()]


def get_budget(cursor, scope_id: int, tags_filter: dict, target_month: date) -> float:
    """Returns the newest existing budget for given scope and tags."""
    tags_json = json.dumps(tags_filter) if tags_filter else '{}'
    scope_id = scope_id if scope_id is not None else 0
    
    query = """
        SELECT LimitAmount FROM Budgets 
        WHERE ScopeId = %s 
          AND Tags::jsonb = %s::jsonb 
          AND PeriodMonth <= %s
        ORDER BY PeriodMonth DESC
        LIMIT 1;
    """
    cursor.execute(query, (scope_id, tags_json, target_month))
    result = cursor.fetchone()
    return float(result[0]) if result else None

def set_budget(cursor, scope_id: int, tags_filter: dict, target_month: date, amount: float):
    """UPSERTS a new budget for given scope and tags for the EXACT month."""
    tags_json = json.dumps(tags_filter) if tags_filter else '{}'
    scope_id = scope_id if scope_id is not None else 0

    # Check for current budget
    cursor.execute("""
        SELECT Id FROM Budgets 
        WHERE ScopeId = %s AND Tags::jsonb = %s::jsonb AND PeriodMonth = %s;
    """, (scope_id, tags_json, target_month))
    
    existing_row = cursor.fetchone()

    if existing_row:
        cursor.execute("""
            UPDATE Budgets SET LimitAmount = %s 
            WHERE ScopeId = %s AND Tags::jsonb = %s::jsonb AND PeriodMonth = %s;
        """, (amount, scope_id, tags_json, target_month))
    else:
        cursor.execute("""
            INSERT INTO Budgets (ScopeId, Tags, LimitAmount, PeriodMonth)
            VALUES (%s, %s::jsonb, %s, %s);
        """, (scope_id, tags_json, amount, target_month))

def save_forecast_snapshot(cursor, scope_id: int, tags_filter: dict, target_month: date, amount: float, daily_forecasts: dict = None):
    """Save the current forecast snapshot (and its daily curve) to history"""
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

def get_latest_forecast(cursor, scope_id: int, tags_filter: dict, target_month: date):
    """Returns the most recent calculated forecast under 24 hours old."""
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

def get_namespaces_for_tags(cursor, active_tags: dict):
    query_ns = "SELECT Id, ParentId, ResourceName FROM Entities WHERE ResourceType = 'kubernetes_namespace'"
    params_ns = []
    for k, v in active_tags.items():
        query_ns += " AND Tags->>%s = %s"
        params_ns.extend([k, v])
    
    cursor.execute(query_ns, params_ns)
    return cursor.fetchall()

def get_max_date(cursor, start_date: date, end_date: date):
    """Returns the latest available date of the costs for the given time window."""
    cursor.execute("""
        SELECT MAX(ChargePeriodStart)::date 
        FROM Costs 
        WHERE ChargePeriodStart >= %s AND ChargePeriodStart < %s
    """, (start_date, end_date))
    return cursor.fetchone()

def get_active_budgets_scopes(cursor, target_month: date):
    """Returns unique (scope_id, tags) combinations that have active budgets."""
    query = """
        SELECT DISTINCT ScopeId, Tags 
        FROM Budgets 
        WHERE PeriodMonth <= %s
    """
    cursor.execute(query, (target_month,))
    return [{"scope_id": r[0], "tags": r[1]} for r in cursor.fetchall()]

def save_anomalies(cursor, scope_id: int, tags_filter: dict, anomalies_data: list):
    """Saves detected anomalies to CostAnomalies table."""
    tags_json = json.dumps(tags_filter) if tags_filter else '{}'
    scope_id = scope_id if scope_id is not None else 0
    
    for anomaly in anomalies_data:
        anomaly_type = anomaly.get("type", "cost")
        cursor.execute("""
            INSERT INTO CostAnomalies (ScopeId, Tags, AnomalyDate, AnomalyType, ActualCost, PredictedCost, UpperThreshold, Delta, DetectedAt)
            VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (ScopeId, Tags, AnomalyDate, AnomalyType) 
            DO UPDATE SET 
                ActualCost = EXCLUDED.ActualCost,
                PredictedCost = EXCLUDED.PredictedCost,
                UpperThreshold = EXCLUDED.UpperThreshold,
                Delta = EXCLUDED.Delta,
                DetectedAt = CURRENT_TIMESTAMP;
        """, (scope_id, tags_json, anomaly["date"], anomaly_type, anomaly["actual"], anomaly["predicted"], anomaly["threshold"], anomaly["delta"]))


def get_anomalies_for_month(cursor, scope_id: int, tags_filter: dict,
                            start_date: date, end_date: date) -> dict:
    """Returns persisted CostAnomalies for the given period."""
    tags_json = json.dumps(tags_filter) if tags_filter else '{}'
    scope_id = scope_id if scope_id is not None else 0
    cursor.execute("""
        SELECT AnomalyDate, ActualCost, PredictedCost, UpperThreshold, Delta, AnomalyType, IsSeen
        FROM CostAnomalies
        WHERE ScopeId = %s AND Tags::jsonb = %s::jsonb
          AND AnomalyDate >= %s AND AnomalyDate < %s
        ORDER BY AnomalyDate ASC;
    """, (scope_id, tags_json, start_date, end_date))
    return {
        row[0].isoformat(): {"actual": float(row[1]) if row[1] is not None else None, 
                             "predicted": float(row[2]) if row[2] is not None else None,
                             "threshold": float(row[3]) if row[3] is not None else None, 
                             "delta": float(row[4]) if row[4] is not None else None,
                             "type": row[5], "is_seen": row[6]}
        for row in cursor.fetchall()
    }

def get_dashboard_anomalies(cursor, start_date: date, end_date: date, only_unseen: bool = False):
    """Returns anomalies (both cost and budget) for the dashboard across all scopes."""
    query = """
        SELECT c.Id, c.ScopeId, e.ResourceName, c.Tags, c.AnomalyDate, c.AnomalyType, 
               c.ActualCost, c.PredictedCost, c.UpperThreshold, c.Delta, c.IsSeen, c.DetectedAt
        FROM CostAnomalies c
        LEFT JOIN Entities e ON c.ScopeId = e.Id
        WHERE c.AnomalyDate >= %s AND c.AnomalyDate <= %s
    """
    params = [start_date, end_date]
    if only_unseen:
        query += " AND c.IsSeen = FALSE "
        
    query += " ORDER BY c.DetectedAt DESC, c.AnomalyDate DESC;"
    cursor.execute(query, params)
    return [
       {
           "id": row[0],
           "scope_id": row[1],
           "scope_name": row[2] or f"Scope {row[1]}",
           "tags": row[3],
           "date": row[4].isoformat(),
           "type": row[5],
           "actual": float(row[6]) if row[6] is not None else None,
           "predicted": float(row[7]) if row[7] is not None else None,
           "threshold": float(row[8]) if row[8] is not None else None,
           "delta": float(row[9]) if row[9] is not None else None,
           "is_seen": row[10],
           "detected_at": row[11].isoformat() if row[11] else None
       }
       for row in cursor.fetchall()
    ]

def mark_anomaly_seen(cursor, anomaly_id: int):
    """Marks an anomaly as seen by its ID."""
    cursor.execute("""
        UPDATE CostAnomalies SET IsSeen = TRUE WHERE Id = %s;
    """, (anomaly_id,))