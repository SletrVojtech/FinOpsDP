"""
Budget Management Module.

Provides CRUD operations for monthly cost budgets. Budgets are keyed
by ``(ScopeId, Tags, PeriodMonth)`` and support lookups that return
the latest budget at or before the target month.
"""

import json
from datetime import date


def get_budget(cursor, scope_id: int, tags_filter: dict, target_month: date) -> float:
    """Return the most recent budget limit for a scope, at or before the target month.

    Args:
        cursor: Active database cursor.
        scope_id (int): Scope entity ID (0 for global).
        tags_filter (dict): Tag key-value filter identifying the budget.
        target_month (date): Target month; any date within the month works.

    Returns:
        float: Budget limit in EUR, or ``None`` if no budget is configured.
    """
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
    """Upsert a monthly budget limit for a scope.

    Inserts a new record or updates the existing one for the exact
    ``(scope_id, tags_filter, target_month)`` key.

    Args:
        cursor: Active database cursor.
        scope_id (int): Scope entity ID (0 for global).
        tags_filter (dict): Tag key-value filter identifying the budget.
        target_month (date): The exact month the budget applies to.
        amount (float): Budget limit in EUR.
    """
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


def get_active_budgets_scopes(cursor, target_month: date) -> list:
    """Return distinct (scope_id, tags) combinations with an active budget.

    Args:
        cursor: Active database cursor.
        target_month (date): Include budgets valid at or before this month.

    Returns:
        list: Dicts with keys ``scope_id`` and ``tags``.
    """
    query = """
        SELECT DISTINCT ScopeId, Tags 
        FROM Budgets 
        WHERE PeriodMonth <= %s
    """
    cursor.execute(query, (target_month,))
    return [{"scope_id": r[0], "tags": r[1]} for r in cursor.fetchall()]
