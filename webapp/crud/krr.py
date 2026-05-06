"""
Kubernetes Resource Recommender (KRR) Module.

Provides queries for reading KubeRecommendations records produced by
Robusta's KRR scanner. Each recommendation contains optimal CPU/memory
request values per container workload.
"""


def get_krr_clusters(db_cursor):
    """Return clusters that have available KRR recommendation records.

    Args:
        db_cursor: Active database cursor.

    Returns:
        list: Dicts with keys ``cluster_id``, ``cluster_name``, and
            ``latest_scan`` (timestamp of the most recent scan).
    """
    query = """
        SELECT 
            e_clust.Id AS cluster_id,
            e_clust.ResourceName AS cluster_name,
            MAX(kr.Timestamp) AS latest_scan
        FROM KubeRecommendations kr
        JOIN Entities e_ns ON kr.EntityId = e_ns.Id
        JOIN Entities e_clust ON e_ns.ParentId = e_clust.Id
        GROUP BY e_clust.Id, e_clust.ResourceName
        ORDER BY cluster_name;
    """
    db_cursor.execute(query)
    columns = [desc[0] for desc in db_cursor.description]
    return [dict(zip(columns, row)) for row in db_cursor.fetchall()]

def get_krr_recommendations_for_cluster(db_cursor, cluster_id: int):
    """Return the latest KRR recommendations for all workloads in a cluster.

    Args:
        db_cursor: Active database cursor.
        cluster_id (int): Entity ID of the Kubernetes cluster.

    Returns:
        list: Dicts with workload recommendation details including
            ``namespace``, ``workloadtype``, ``workloadname``,
            ``containername``, CPU/memory current and recommended values,
            and ``timestamp``.
    """
    query = """
        WITH LatestScan AS (
            SELECT MAX(kr.Timestamp) as max_ts
            FROM KubeRecommendations kr
            JOIN Entities e_ns ON kr.EntityId = e_ns.Id
            WHERE e_ns.ParentId = %s
        )
        SELECT 
            e_ns.ResourceName AS namespace,
            kr.WorkloadType,
            kr.WorkloadName,
            kr.ContainerName,
            kr.CurrentCpuRequest,
            kr.RecommendedCpuRequest,
            kr.CurrentMemoryRequest,
            kr.RecommendedMemoryRequest,
            kr.Timestamp
        FROM KubeRecommendations kr
        JOIN Entities e_ns ON kr.EntityId = e_ns.Id
        CROSS JOIN LatestScan ls
        WHERE e_ns.ParentId = %s
          AND kr.Timestamp = ls.max_ts
        ORDER BY namespace, kr.WorkloadType, kr.WorkloadName;
    """
    db_cursor.execute(query, (cluster_id, cluster_id))
    columns = [desc[0] for desc in db_cursor.description]
    return [dict(zip(columns, row)) for row in db_cursor.fetchall()]

def get_cluster_name(cursor, cluster_id: int):
    """Return the display name of a Kubernetes cluster entity.

    Args:
        cursor: Active database cursor.
        cluster_id (int): Entity ID of the cluster.

    Returns:
        str: Cluster resource name, or a fallback string containing
            the ID when the entity is not found.
    """
    cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
    cluster_row = cursor.fetchone()
    return cluster_row[0] if cluster_row else f"Neznámý cluster ({cluster_id})"