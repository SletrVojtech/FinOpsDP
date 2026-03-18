import json
from pydantic import BaseModel
from typing import Dict

class AllocationRequest(BaseModel):
    rule_name: str
    source_tags: Dict[str, str]
    target_tags: Dict[str, str]
    percentage: float


def get_allocation_rules(cursor):
    """Returns all allocation rules"""
    cursor.execute("SELECT Id, RuleName, SourceTags, TargetTags, Percentage FROM AllocationRules ORDER BY Id;")
    rules = []
    for row in cursor.fetchall():
        rules.append({
            "id": row[0],
            "rule_name": row[1],
            "source_tags": row[2],
            "target_tags": row[3],
            "percentage": float(row[4])
        })
    return rules

def add_allocation_rule(cursor, rule_name: str, source_tags: dict, target_tags: dict, percentage: float):
    """Adds a new allocation rule"""
    cursor.execute("""
        INSERT INTO AllocationRules (RuleName, SourceTags, TargetTags, Percentage)
        VALUES (%s, %s::jsonb, %s::jsonb, %s);
    """, (rule_name, json.dumps(source_tags), json.dumps(target_tags), percentage))

def delete_allocation_rule(cursor, rule_id: int):
    """Delete rule by ID."""
    cursor.execute("DELETE FROM AllocationRules WHERE Id = %s;", (rule_id,))