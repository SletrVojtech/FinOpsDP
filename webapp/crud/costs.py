# web_app/crud/costs.py
from datetime import date

def get_daily_costs(cursor, scope_id: int = None, tags_filter: dict = None, target_date: date = None):
    """
        Returns daily and accumulative data for given scope and tags in one month.
        Based on https://focus.finops.org/use-cases/#forecast-amortized-costs-month-over-month-based-on-historical-trends-2
        but for daily aggregation and already scoped set of IDs.
    """
    tags_filter = tags_filter or {}
    params = []

    # Scope
    if scope_id:
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
    else:
        base_sql = """
            WITH BaseData AS (
                SELECT Id, Tags FROM Entities
            )
        """

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