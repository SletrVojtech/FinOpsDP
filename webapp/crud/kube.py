from datetime import date, timedelta
import calendar


def get_daily_metric_allocation(cursor, cluster_id: int, metric_name: str,
                                base_date: date = None,
                                start_date: date = None, end_date: date = None):
    """
    Queries average namespace reservations per day for the given cluster,
    returned as a fractional share of the cluster total for metric_name.
    """
    if base_date and not start_date:
        start_date = base_date.replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)

    if not start_date or not end_date:
        start_date = date.today().replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)

    query = """
        WITH DailyNamespaceMetric_Raw AS (
            SELECT 
                time_bucket_gapfill(
                    '1 day', 
                    m.Timestamp, 
                    %s::timestamptz, 
                    %s::timestamptz
                ) AS bucket,
                e.ResourceName AS namespace,
                COALESCE(AVG(m.Value), 0.0) AS daily_value
            FROM Entities e
            JOIN KubeMetrics m ON e.Id = m.EntityId
            WHERE e.ParentId = %s 
              AND m.MetricName = %s
              AND m.Timestamp >= %s::timestamptz
              AND m.Timestamp < %s::timestamptz
            GROUP BY bucket, e.ResourceName
        ),
        DailyNamespaceMetric AS (
            SELECT 
                bucket::date AS calc_date,
                namespace,
                daily_value
            FROM DailyNamespaceMetric_Raw
        ),
        DailyClusterMetric AS (
            SELECT calc_date, SUM(daily_value) AS total_daily_value
            FROM DailyNamespaceMetric
            GROUP BY calc_date
        )
        SELECT 
            n.calc_date,
            n.namespace,
            (n.daily_value / NULLIF(c.total_daily_value, 0)) AS daily_share
        FROM DailyNamespaceMetric n
        JOIN DailyClusterMetric c ON n.calc_date = c.calc_date
        ORDER BY n.calc_date, n.namespace;
    """

    cursor.execute(query, (start_date, end_date, cluster_id, metric_name, start_date, end_date))
    return [row for row in cursor.fetchall()]

def get_daily_cpu_allocation(cursor, cluster_id: int, base_date: date = None,
                             start_date: date = None, end_date: date = None):
    return get_daily_metric_allocation(cursor, cluster_id, 'cpu_requests_cores',
                                       base_date, start_date, end_date)


def get_daily_memory_allocation(cursor, cluster_id: int, base_date: date = None,
                                start_date: date = None, end_date: date = None):
    return get_daily_metric_allocation(cursor, cluster_id, 'memory_requests_bytes',
                                       base_date, start_date, end_date)