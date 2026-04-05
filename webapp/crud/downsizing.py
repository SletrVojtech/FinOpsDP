from typing import List, Dict, Any, Optional


def get_instance_metadata(db_cursor, resource_id: int) -> Optional[Dict[str, Any]]:
    """Return current metadata about given instance, including instance class constraints."""
    query = """
        SELECT
            e.providername,
            e.regionid,
            e.extras->>'normalized_os'    AS os,
            h.instance_type,
            h.vcpu,
            h.memory_gb,
            h.architecture,
            h.is_gpu,
            h.is_confidential,
            h.has_local_storage,
            h.supports_premium_storage
        FROM Entities e
        JOIN hardwarecatalog h
          ON e.extras->>'instance_type' = h.instance_type
        WHERE e.Id = %(resource_id)s
        LIMIT 1;
    """
    db_cursor.execute(query, {"resource_id": resource_id})
    row = db_cursor.fetchone()
    if not row:
        return None
    return {
        "provider": row[0],
        "region": row[1],
        "os": row[2],
        "instance_type": row[3],
        "vcpu": row[4],
        "memory_gb": row[5],
        "architecture": row[6],
        "is_gpu": row[7],
        "is_confidential": row[8],
        "has_local_storage": row[9],
        "supports_premium_storage": row[10],
    }


def get_telemetry(db_cursor, resource_id: int, analysis_days: int) -> Dict[str, Optional[float]]:
    """Queries for percentiles and aggregated max values."""
    # TODO get metric table from _resolve_data_source
    table = "metrics" if analysis_days <= 14 else "metrics_hourly"
    val_col = "value" if analysis_days <= 14 else "max_value"

    query = f"""
        WITH time_filtered AS (
            SELECT metrictype as metric_name, {val_col} as val
            FROM {table}
            WHERE entityid = %(resource_id)s
              AND "timestamp" >= NOW() - INTERVAL '{analysis_days} days'
        )
        SELECT
            (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY val) FROM time_filtered WHERE metric_name = 'cpu_usage_avg') AS cpu_p95,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'mem_available_avg') AS ram_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'disk_read_ops_avg') AS disk_read_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'disk_write_ops_avg') AS disk_write_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'net_in_bps_avg') AS net_in_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'net_out_bps_avg') AS net_out_max;
    """
    db_cursor.execute(query, {"resource_id": resource_id})
    row = db_cursor.fetchone()

    if not row:
        return {"cpu_p95": None, "ram_max": None, "disk_read_max": None, "disk_write_max": None, "net_in_max": None, "net_out_max": None}

    return {
        "cpu_p95": row[0], "ram_max": row[1],
        "disk_read_max": row[2], "disk_write_max": row[3],
        "net_in_max": row[4], "net_out_max": row[5]
    }

def get_actual_daily_cost(db_cursor, resource_id: str, analysis_days: int) -> float:
    """Get the current instance spend."""
    query = """
        SELECT COALESCE(AVG(billedcost), 0.0)
        FROM costs
        WHERE entityid = %(resource_id)s
          AND "chargeperiodstart" >= NOW() - INTERVAL '%(analysis_days)s days';
    """
    db_cursor.execute(query, {"resource_id": resource_id, "analysis_days": analysis_days})
    return db_cursor.fetchone()[0]

def get_catalog_hourly_price(db_cursor, provider: str, region: str, os: str, instance_type: str) -> Optional[float]:
    """Get listed price for given instance."""
    query = """
        SELECT hourly_price_usd FROM pricingcatalog
        WHERE cloud = %(provider)s AND region = %(region)s
          AND os = %(os)s AND instance_type = %(instance_type)s
        LIMIT 1;
    """
    db_cursor.execute(query, {
        "provider": provider, "region": region,
        "os": os, "instance_type": instance_type,
    })
    row = db_cursor.fetchone()
    return row[0] if row else None


def get_suitable_candidates(db_cursor, provider: str, region: str, os: str,
                            req_vcpu: float, req_ram: float, req_iops: float, req_net_mbps: float, 
                            sql_like_patterns: List[str], architecture: str = 'x86_64',
                            is_gpu: bool = False, is_confidential: bool = False,
                            has_local_storage: bool = False, current_supports_premium: bool = False,
) -> List[Dict[str, Any]]:
    """
    Query for viable downsizing candidates.

    Hard constraints:
      - architecture
      - is_gpu
      - is_confidential
      - has_local_storage

    Soft constraint (affects ordering):
      - supports_premium_storage: if the current instance uses premium storage,
        prefer premium-capable candidates first, but don't exclude non-premium ones.
    """
    filter_clause = ""
    if sql_like_patterns:
        filter_clause = "AND h.instance_type NOT LIKE ALL(%(patterns)s)"

    # Premium storage ordering: if current uses premium, rank premium-capable first.
    # If current doesn't use premium, order is irrelevant — price already sorts ASC.
    premium_order = (
        "h.supports_premium_storage DESC," if current_supports_premium else ""
    )

    query = f"""
        SELECT
            h.instance_type,
            h.vcpu,
            h.memory_gb,
            p.hourly_price_usd,
            h.architecture,
            h.is_gpu,
            h.is_confidential,
            h.has_local_storage,
            h.supports_premium_storage
        FROM hardwarecatalog h
        JOIN pricingcatalog p
          ON h.cloud = p.cloud AND h.instance_type = p.instance_type
        WHERE h.cloud          = %(provider)s
          AND p.region         = %(region)s
          AND p.os             = %(os)s
          AND h.vcpu           >= %(req_vcpu)s
          AND h.memory_gb      >= %(req_ram)s
          AND (h.baseline_iops IS NULL OR h.baseline_iops >= %(req_iops)s)
          AND (h.baseline_throughput_mbps IS NULL OR h.baseline_throughput_mbps >= %(req_net_mbps)s)
          AND p.hourly_price_usd IS NOT NULL
          AND p.hourly_price_usd > 0
          -- Hard class constraints
          AND h.architecture      = %(architecture)s
          AND h.is_gpu            = %(is_gpu)s
          AND h.is_confidential   = %(is_confidential)s
          AND h.has_local_storage = %(has_local_storage)s
          {filter_clause}
        ORDER BY {premium_order} p.hourly_price_usd ASC;
    """
    db_cursor.execute(query, {
        "provider": provider,
        "region": region,
        "os": os,
        "req_vcpu": req_vcpu,
        "req_ram": req_ram,
        "req_iops": req_iops,
        "req_net_mbps": req_net_mbps,
        "architecture": architecture,
        "is_gpu": is_gpu,
        "is_confidential": is_confidential,
        "has_local_storage": has_local_storage,
        "patterns": sql_like_patterns,
    })

    return [
        {
            "instance_type": r[0],
            "vcpu": r[1],
            "memory_gb": r[2],
            "hourly_price_usd": r[3],
            "architecture": r[4],
            "is_gpu": r[5],
            "is_confidential": r[6],
            "has_local_storage": r[7],
            "supports_premium_storage": r[8],
        }
        for r in db_cursor.fetchall()
    ]