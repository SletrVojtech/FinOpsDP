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
    """Adds a new allocation rule with a 100% limit check for the source tags."""
    # Normalize tags by sorting keys to ensure consistent JSON representation
    source_tags_json = json.dumps(source_tags, sort_keys=True)
    target_tags_json = json.dumps(target_tags, sort_keys=True)
    
    # Check current total percentage for this source
    cursor.execute("""
        SELECT COALESCE(SUM(Percentage), 0) 
        FROM AllocationRules 
        WHERE SourceTags::jsonb = %s::jsonb;
    """, (source_tags_json,))
    current_total = float(cursor.fetchone()[0])
    
    if current_total + percentage > 100.001: 
        raise ValueError(f"Alokace by přesáhla 100% (aktuální: {current_total}%, přidává se: {percentage}%)")

    cursor.execute("""
        INSERT INTO AllocationRules (RuleName, SourceTags, TargetTags, Percentage)
        VALUES (%s, %s::jsonb, %s::jsonb, %s);
    """, (rule_name, source_tags_json, target_tags_json, percentage))

def delete_allocation_rule(cursor, rule_id: int):
    """Delete rule by ID."""
    cursor.execute("DELETE FROM AllocationRules WHERE Id = %s;", (rule_id,))