from datetime import date, timedelta
import calendar

def get_daily_cpu_allocation(cursor, cluster_id: int, base_date: date, 
                            start_date: date = None, end_date: date = None):
    """
    Queries for all the average namespace reservations per day for given cluster. 
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
        WITH DailyNamespaceCPU_Raw AS (
            SELECT 
                time_bucket_gapfill(
                    '1 day', 
                    m.Timestamp, 
                    %s::timestamptz, 
                    %s::timestamptz
                ) AS bucket,
                e.ResourceName AS namespace,
                COALESCE(AVG(m.Value), 0.0) AS daily_cpu
            FROM Entities e
            JOIN KubeMetrics m ON e.Id = m.EntityId
            WHERE e.ParentId = %s 
              AND m.MetricName = 'cpu_requests_cores'
              AND m.Timestamp >= %s::timestamptz
              AND m.Timestamp < %s::timestamptz
            GROUP BY bucket, e.ResourceName
        ),
        DailyNamespaceCPU AS (
            SELECT 
                bucket::date AS calc_date,
                namespace,
                daily_cpu
            FROM DailyNamespaceCPU_Raw
        ),
        DailyClusterCPU AS (
            SELECT calc_date, SUM(daily_cpu) AS total_daily_cpu
            FROM DailyNamespaceCPU
            GROUP BY calc_date
        )
        SELECT 
            n.calc_date,
            n.namespace,
            (n.daily_cpu / NULLIF(c.total_daily_cpu, 0)) AS daily_share
        FROM DailyNamespaceCPU n
        JOIN DailyClusterCPU c ON n.calc_date = c.calc_date
        ORDER BY n.calc_date, n.namespace;
    """
    
    cursor.execute(query, (start_date, end_date, cluster_id, start_date, end_date))
    
    return [row for row in cursor.fetchall()]