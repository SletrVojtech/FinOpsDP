
from datetime import date
from crud import allocations



def get_daily_costs(cursor, scope_id: int = 0, tags_filter: dict = None, target_date: date = None):
    """
        Returns daily and accumulative data for given scope and tags in one month.
        Based on https://focus.finops.org/use-cases/#forecast-amortized-costs-month-over-month-based-on-historical-trends-2
        but for daily aggregation and already scoped set of IDs.
    """
    tags_filter = tags_filter or {}
    params = []

    # Scope
    base_sql = """
        WITH RECURSIVE SubTree AS (
            SELECT Id, ParentId, Tags FROM Entities WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.ParentId, e.Tags FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
        ),
        BaseData AS (
            SELECT Id, Tags FROM SubTree WHERE Id != %s
        )
    """
    params.extend([scope_id, scope_id])

    # Filter by tags
    filter_sql = " , FilteredEntities AS ( SELECT Id FROM BaseData WHERE 1=1 "
    for key, value in tags_filter.items():
        filter_sql += " AND Tags->>%s = %s"
        params.extend([key, value])
    filter_sql += " )"

    # Join on costs, start on the first day of given month.
    query = base_sql + filter_sql + """
        SELECT 
            DATE(c.ChargePeriodStart) AS cost_date,
            SUM(c.BilledCost) AS daily_cost
        FROM Costs c
        JOIN FilteredEntities fe ON c.EntityId = fe.Id
        WHERE 
            c.ChargePeriodStart >= DATE_TRUNC('month', %s::date)
            AND c.ChargePeriodStart < DATE_TRUNC('month', %s::date) + INTERVAL '1 month'
        GROUP BY DATE(c.ChargePeriodStart)
        ORDER BY cost_date ASC;
    """
    
    target = target_date or date.today()
    params.extend([target, target])

    cursor.execute(query, params)
    
    return [{"date": r[0].isoformat(), "cost": float(r[1])} for r in cursor.fetchall()]

import json
from datetime import date

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

def save_forecast_snapshot(cursor, scope_id: int, tags_filter: dict, target_month: date, amount: float):
    """Save the current forecast snapshot to history"""
    tags_json = json.dumps(tags_filter) if tags_filter else '{}'
    scope_id = scope_id if scope_id is not None else 0
    today = date.today()

    cursor.execute("""
        INSERT INTO ForecastHistory (ScopeId, Tags, TargetMonth, ForecastDate, ProjectedAmount, CalculatedAt)
        VALUES (%s, %s::jsonb, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (ScopeId, Tags, TargetMonth, ForecastDate) 
        DO UPDATE SET 
            ProjectedAmount = EXCLUDED.ProjectedAmount,
            CalculatedAt = CURRENT_TIMESTAMP;
    """, (scope_id, tags_json, target_month, today, amount))