def get_krr_clusters(db_cursor):
    """Return list of clusters with available reccomendations."""
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
    """Return set of the newest recommendations for given cluster."""
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
    """Return name of the cluster.""" 
    cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
    cluster_row = cursor.fetchone()
    return cluster_row[0] if cluster_row else f"Neznámý cluster ({cluster_id})"