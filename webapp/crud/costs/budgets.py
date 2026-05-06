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


def get_active_budgets_scopes(cursor, target_month: date):
    """Returns unique (scope_id, tags) combinations that have active budgets."""
    query = """
        SELECT DISTINCT ScopeId, Tags 
        FROM Budgets 
        WHERE PeriodMonth <= %s
    """
    cursor.execute(query, (target_month,))
    return [{"scope_id": r[0], "tags": r[1]} for r in cursor.fetchall()]
