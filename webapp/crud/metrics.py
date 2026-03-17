
def has_metrics(cursor, entity_id: int) -> bool:
    """Check if entity has metrics"""
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 
            FROM Metrics 
            WHERE EntityId = %s
        );
    """, (entity_id,))
    return cursor.fetchone()[0]

def get_available_metric_names(cursor, entity_id: int) -> list[str]:
    """List all available metric names for given entity"""
    cursor.execute("""
        SELECT DISTINCT MetricType
        FROM Metrics
        WHERE EntityId = %s
        ORDER BY MetricType;
    """, (entity_id,))
    return [row[0] for row in cursor.fetchall()]

def _resolve_data_source(cursor, granularity: str, time_range: str, data_type: str) -> tuple[str, bool]:
    """
    Choose the best fitting table fot the query.
    """
    cursor.execute("""
         SELECT TableName, IsCagg 
         FROM DataDictionary 
         WHERE Granularity <= %s::interval AND DataType = %s
         ORDER BY Granularity DESC
         LIMIT 1;
     """, (granularity, data_type))
    result = cursor.fetchone()
    if result: return result[0], result[1]
    return "Metrics", False


def get_metric_data(cursor, entity_id: int, metric_name: str, time_range: str = '7 days', granularity: str = '1 hour', data_type: str = 'metric'):
    """
    Get metric for given entity.
    """
    # Get the most fitting table
    table_name, is_cagg = _resolve_data_source(cursor, granularity, time_range, data_type)
    
    if is_cagg:
        # Read from an aggregate.
        query = f"""
            SELECT 
                bucket,
                avg_value,
                max_value,
                min_value,
                sum_value,
                count_value
            FROM {table_name}
            WHERE EntityId = %s 
              AND MetricType = %s
              AND bucket >= NOW() - %s::interval
            ORDER BY bucket ASC;
        """
        cursor.execute(query, (entity_id, metric_name, time_range))
        
    else:
        # Raw data read
        query = f"""
            SELECT 
                time_bucket(%s::interval, Timestamp) AS bucket,
                AVG(Value) as avg_value,
                MAX(Value) as max_value,
                MIN(Value) as min_value,
                SUM(Value) as sum_value,
                COUNT(*) as count_value
            FROM {table_name}
            WHERE EntityId = %s 
              AND MetricType = %s
              AND Timestamp >= NOW() - %s::interval
            GROUP BY bucket
            ORDER BY bucket ASC;
        """
        cursor.execute(query, (granularity, entity_id, metric_name, time_range))
    

    return [
        {
            "time": r[0].isoformat() if r[0] else None, 
            "avg": round(r[1], 2) if r[1] is not None else 0, 
            "max": round(r[2], 2) if r[2] is not None else 0,
            "min": round(r[3], 2) if r[3] is not None else 0,
            "sum": round(r[4], 2) if r[4] is not None else 0,
            "count": r[5] if r[5] is not None else 0
        } 
        for r in cursor.fetchall()
    ]
