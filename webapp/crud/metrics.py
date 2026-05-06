"""
Metrics Query Module.

Provides functions for querying time-series metric data from raw and
aggregated (TimescaleDB Continuous Aggregate) tables. The best-fit
table for a given granularity and time range is resolved dynamically
via the ``DataDictionary`` catalogue.
"""

def has_metrics(cursor, entity_id: int) -> bool:
    """Check whether an entity has any recorded metrics.

    Args:
        cursor: Active database cursor.
        entity_id (int): Entity ID to check.

    Returns:
        bool: True if at least one metric record exists for the entity.
    """
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 
            FROM Metrics 
            WHERE EntityId = %s
        );
    """, (entity_id,))
    return cursor.fetchone()[0]

def get_available_metric_names(cursor, entity_id: int) -> list[str]:
    """Return distinct metric type names available for an entity.

    Args:
        cursor: Active database cursor.
        entity_id (int): Entity ID to query.

    Returns:
        list[str]: Sorted list of metric type name strings.
    """
    cursor.execute("""
        SELECT DISTINCT MetricType
        FROM Metrics
        WHERE EntityId = %s
        ORDER BY MetricType;
    """, (entity_id,))
    return [row[0] for row in cursor.fetchall()]

def _resolve_data_source(cursor, granularity: str, time_range: str, data_type: str) -> tuple[str, bool]:
    """Choose the best-fit metrics table for a given query granularity.

    Queries the ``DataDictionary`` catalogue for the coarsest table whose
    own granularity is still finer than or equal to the requested one.
    Falls back to the raw ``Metrics`` table when no match is found.

    Args:
        cursor: Active database cursor.
        granularity (str): Desired bucket interval (e.g. ``"1 hour"``).
        time_range (str): Full time window (e.g. ``"7 days"``).
        data_type (str): Data type identifier (e.g. ``"metrics"``).

    Returns:
        tuple[str, bool]: A 2-tuple of ``(table_name, is_cagg)``.
            ``is_cagg`` is True when the table is a Continuous Aggregate
            and uses pre-bucketed column names.
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


def get_metric_data(
    cursor,
    entity_id: int,
    metric_name: str,
    time_range: str = '7 days',
    granularity: str = '1 hour',
    data_type: str = 'metric',
) -> list:
    """Return time-bucketed metric data for an entity.

    Selects the appropriate storage table via :func:`_resolve_data_source`
    and builds the corresponding query — either reading directly from a
    Continuous Aggregate or applying ``time_bucket`` on the raw table.

    Args:
        cursor: Active database cursor.
        entity_id (int): Entity whose metrics to fetch.
        metric_name (str): Metric type name (e.g. ``"cpu_usage_avg"``).
        time_range (str, optional): Time window length (e.g. ``"7 days"``).
        granularity (str, optional): Bucket size for aggregation (e.g. ``"1 hour"``).
        data_type (str, optional): Data type identifier passed to the table resolver (e.g. ``'metric'``).

    Returns:
        list: Dicts with keys ``time``, ``avg``, ``max``, ``min``,
            ``sum``, and ``count`` for each time bucket.
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
