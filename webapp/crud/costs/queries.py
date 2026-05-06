"""
Cost Query Module.

Provides SQL queries against the ``Costs`` table, using a shared
``SubTree / FilteredEntities`` recursive CTE to scope results by entity
hierarchy and tag filters. Supports gap-filled daily totals, category
breakdowns, and tag-value breakdowns.
"""

import calendar
from datetime import date, timedelta
import json


def _build_scope_cte(scope_id: int, tags_filter: dict):
    """Build the shared ``SubTree / FilteredEntities`` CTE SQL fragment.

    Generates a recursive CTE that walks the entity hierarchy downward
    from ``scope_id`` and then filters descendant IDs by the supplied
    tag key-value pairs.

    Args:
        scope_id (int): Root entity ID for the subtree.
        tags_filter (dict): Tag key-value constraints. Empty dict means
            no additional tag filtering.

    Returns:
        tuple[str, list]: A 2-tuple of ``(sql_fragment, params)`` ready
            for use as a prefix CTE in a larger query.
    """
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


def get_daily_costs(
    cursor,
    scope_id: int = 0,
    tags_filter: dict = None,
    target_date: date = None,
    start_date: date = None,
    end_date: date = None,
    exchange_rate: float = 1.0,
) -> list:
    """Return gap-filled daily costs for a scoped entity subtree.

    Uses TimescaleDB ``time_bucket_gapfill`` to ensure every day in the
    window appears in the result even if no billing records exist.
    Based on the FOCUS cost allocation model.

    Args:
        cursor: Active database cursor.
        scope_id (int, optional): Root entity ID. Defaults to 0.
        tags_filter (dict, optional): Tag key-value constraints.
        target_date (date, optional): When provided and ``start_date`` is
            absent, the window defaults to the full calendar month
            containing ``target_date``.
        start_date (date, optional): Explicit window start.
        end_date (date, optional): Explicit window end (exclusive).
        exchange_rate (float, optional): USD-to-EUR multiplier.
            Defaults to 1.0.

    Returns:
        list: Dicts with keys ``date`` (ISO string) and ``cost`` (float).
    """
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


def get_daily_costs_by_category(
    cursor,
    scope_id: int = 0,
    tags_filter: dict = None,
    start_date: date = None,
    end_date: date = None,
    exchange_rate: float = 1.0,
) -> list:
    """Return daily costs grouped by ``ServiceCategory``, without gap-filling.

    Args:
        cursor: Active database cursor.
        scope_id (int, optional): Root entity ID. Defaults to 0.
        tags_filter (dict, optional): Tag key-value constraints.
        start_date (date, optional): Window start; defaults to first of
            current month.
        end_date (date, optional): Window end (exclusive).
        exchange_rate (float, optional): USD-to-EUR multiplier.

    Returns:
        list: Dicts with keys ``date``, ``category``, and ``cost``.
    """
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


def get_daily_costs_by_tag_key(
    cursor,
    scope_id: int = 0,
    tags_filter: dict = None,
    tag_key: str = None,
    start_date: date = None,
    end_date: date = None,
    exchange_rate: float = 1.0,
) -> list:
    """Return daily costs grouped by values of a given tag key.

    Resources that lack the tag are grouped as ``'Unrecognized'``.
    Returns an empty list when ``tag_key`` is ``None``.

    Args:
        cursor: Active database cursor.
        scope_id (int, optional): Root entity ID. Defaults to 0.
        tags_filter (dict, optional): Tag key-value constraints.
        tag_key (str, optional): Tag key to group by.
        start_date (date, optional): Window start.
        end_date (date, optional): Window end (exclusive).
        exchange_rate (float, optional): USD-to-EUR multiplier.

    Returns:
        list: Dicts with keys ``date``, ``tag_value``, and ``cost``.
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


def get_namespaces_for_tags(cursor, active_tags: dict) -> list:
    """Return Kubernetes namespace entities matching the given tags.

    Queries the ``Entities`` table for rows with
    ``ResourceType = 'kubernetes_namespace'`` and all tags in
    ``active_tags``.

    Args:
        cursor: Active database cursor.
        active_tags (dict): Tag key-value constraints.

    Returns:
        list: Raw DB rows of ``(Id, ParentId, ResourceName)``.
    """
    query_ns = "SELECT Id, ParentId, ResourceName FROM Entities WHERE ResourceType = 'kubernetes_namespace'"
    params_ns = []
    for k, v in active_tags.items():
        query_ns += " AND Tags->>%s = %s"
        params_ns.extend([k, v])
    cursor.execute(query_ns, params_ns)
    return cursor.fetchall()


def get_max_date(cursor, start_date: date, end_date: date):
    """Return the latest billing date within a given time window.

    Args:
        cursor: Active database cursor.
        start_date (date): Window start (inclusive).
        end_date (date): Window end (exclusive).

    Returns:
        tuple: A 1-tuple ``(max_date,)`` where ``max_date`` is a
            ``date`` object, or ``None`` when no records exist.
    """
    cursor.execute("""
        SELECT MAX(ChargePeriodStart)::date 
        FROM Costs 
        WHERE ChargePeriodStart >= %s AND ChargePeriodStart < %s
    """, (start_date, end_date))
    return cursor.fetchone()
