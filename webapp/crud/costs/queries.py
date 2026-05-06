import calendar
from datetime import date, timedelta
import json


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
