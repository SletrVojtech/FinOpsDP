from datetime import date, timedelta

def get_daily_cpu_allocation(cursor, cluster_id: int, base_date: date):
    """
    Queries for all the average namespace reservations per day for given cluster. 
    """
    start_time = base_date
    end_time = (base_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    query = """
        WITH DailyNamespaceCPU AS (
            SELECT 
                DATE(m.Timestamp) AS calc_date,
                e.ResourceName AS namespace,
                AVG(m.Value) AS daily_cpu
            FROM Entities e
            JOIN KubeMetrics m ON e.Id = m.EntityId
            WHERE e.ParentId = %s 
              AND m.MetricName = 'cpu_requests_cores'
              AND m.Timestamp >= %s 
              AND m.Timestamp < %s
            GROUP BY DATE(m.Timestamp), e.ResourceName
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
    
    cursor.execute(query, (cluster_id, start_time, end_time))
    
    return [row for row in cursor.fetchall()]