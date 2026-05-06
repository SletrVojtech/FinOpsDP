"""
Kubernetes Metrics Allocation Module.

Queries daily namespace-level CPU and memory reservation shares
from KubeMetrics, expressed as a fraction of the cluster total.
Used by the chargeback service to apportion cluster billing costs.
"""

from datetime import date, timedelta
import calendar


def get_daily_metric_allocation(
    cursor,
    cluster_id: int,
    metric_name: str,
    base_date: date = None,
    start_date: date = None,
    end_date: date = None,
):
    """Return daily namespace reservation shares as a fraction of the cluster total.

    Uses ``time_bucket_gapfill`` to ensure continuity. The returned share
    is computed as each namespace's daily average divided by the cluster's
    daily sum for the same metric.

    If only ``base_date`` is provided, the window defaults to the full
    calendar month containing that date.

    Args:
        cursor: Active database cursor.
        cluster_id (int): Entity ID of the Kubernetes cluster.
        metric_name (str): KubeMetrics metric name (e.g.
            ``'cpu_requests_cores'``).
        base_date (date, optional): Reference date used to derive the
            window when ``start_date`` is not provided.
        start_date (date, optional): Explicit window start.
        end_date (date, optional): Explicit window end (exclusive).

    Returns:
        list: Raw DB rows of ``(calc_date, namespace, daily_share)``.
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

def get_daily_cpu_allocation(
    cursor,
    cluster_id: int,
    base_date: date = None,
    start_date: date = None,
    end_date: date = None,
):
    """Return daily CPU request share per namespace for a cluster.

    Thin wrapper around :func:`get_daily_metric_allocation` for
    the ``cpu_requests_cores`` metric.

    Args:
        cursor: Active database cursor.
        cluster_id (int): Entity ID of the Kubernetes cluster.
        base_date (date, optional): Reference date for implicit window.
        start_date (date, optional): Explicit window start.
        end_date (date, optional): Explicit window end (exclusive).

    Returns:
        list: Raw rows of ``(calc_date, namespace, daily_share)``.
    """
    return get_daily_metric_allocation(cursor, cluster_id, 'cpu_requests_cores',
                                       base_date, start_date, end_date)


def get_daily_memory_allocation(
    cursor,
    cluster_id: int,
    base_date: date = None,
    start_date: date = None,
    end_date: date = None,
):
    """Return daily memory request share per namespace for a cluster.

    Thin wrapper around :func:`get_daily_metric_allocation` for
    the ``memory_requests_bytes`` metric.

    Args:
        cursor: Active database cursor.
        cluster_id (int): Entity ID of the Kubernetes cluster.
        base_date (date, optional): Reference date for implicit window.
        start_date (date, optional): Explicit window start.
        end_date (date, optional): Explicit window end (exclusive).

    Returns:
        list: Raw rows of ``(calc_date, namespace, daily_share)``.
    """
    return get_daily_metric_allocation(cursor, cluster_id, 'memory_requests_bytes',
                                       base_date, start_date, end_date)