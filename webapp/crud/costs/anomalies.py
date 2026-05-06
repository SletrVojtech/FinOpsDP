import json
from datetime import date


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
