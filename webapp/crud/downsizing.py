from typing import List, Dict, Any, Optional


def get_instance_metadata(db_cursor, resource_id: int) -> Optional[Dict[str, Any]]:
    """Return current metadata about given instance, including instance class constraints."""
    query = """
        SELECT
            e.providername,
            e.regionid,
            e.extras->>'normalized_os'    AS os,
            h.instancetype,
            h.vcpu,
            h.memorygb,
            h.architecture,
            h.isgpu,
            h.isconfidential,
            h.haslocalstorage,
            h.supportspremiumstorage
        FROM Entities e
        LEFT JOIN hardwarecatalog h
          ON e.extras->>'instance_type' = h.instancetype
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


def _resolve_data_source(db_cursor, analysis_days: int) -> tuple:
    """Returns (table_name, value_column) based on DataDictionary lookup."""
    # Defaults
    table = "metrics"
    val_col = "value"

    if analysis_days > 14:
        # Prefer aggregates for longer timeframes
        db_cursor.execute("SELECT TableName FROM DataDictionary WHERE DataType = 'metric' AND Granularity >= '1 hour' ORDER BY Granularity ASC LIMIT 1")
        row = db_cursor.fetchone()
        if row:
            table = row[0]
            val_col = "max_value"
            
    return table, val_col


def get_telemetry(db_cursor, resource_id: int, analysis_days: int) -> Dict[str, Optional[float]]:
    """Queries for percentiles and aggregated max values."""
    table, val_col = _resolve_data_source(db_cursor, analysis_days)

    query = f"""
        WITH time_filtered AS (
            SELECT metrictype as metric_name, {val_col} as val
            FROM {table}
            WHERE entityid = %(resource_id)s
              AND "timestamp" >= NOW() - (%(days)s * INTERVAL '1 day')
        )
        SELECT
            (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY val) FROM time_filtered WHERE metric_name = 'cpu_usage_max') AS cpu_p95,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'mem_available_avg') AS ram_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'disk_read_ops_avg') AS disk_read_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'disk_write_ops_avg') AS disk_write_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'net_in_bps_avg') AS net_in_max,
            (SELECT MAX(val) FROM time_filtered WHERE metric_name = 'net_out_bps_avg') AS net_out_max;
    """
    db_cursor.execute(query, {"resource_id": resource_id, "days": analysis_days})
    row = db_cursor.fetchone()

    if not row:
        return {"cpu_p95": None, "ram_max": None, "disk_read_max": None, "disk_write_max": None, "net_in_max": None, "net_out_max": None}

    return {
        "cpu_p95": row[0], "ram_max": row[1],
        "disk_read_max": row[2], "disk_write_max": row[3],
        "net_in_max": row[4], "net_out_max": row[5]
    }

def get_actual_daily_cost(db_cursor, resource_id: str, analysis_days: int, exchange_rate: float = 1.0) -> float:
    """Get the current instance spend."""
    query = """
        SELECT COALESCE(SUM(billedcost * (CASE WHEN billingcurrency = 'USD' THEN %(exchange_rate)s ELSE 1.0 END)), 0.0) / %(analysis_days)s
        FROM costs
        WHERE entityid = %(resource_id)s
          AND "chargeperiodstart" >= NOW() - (%(analysis_days)s * INTERVAL '1 day');
    """
    db_cursor.execute(query, {"resource_id": resource_id, "analysis_days": analysis_days, "exchange_rate": exchange_rate})
    return db_cursor.fetchone()[0]

def get_catalog_hourly_price(db_cursor, provider: str, region: str, os: str, instance_type: str, exchange_rate: float = 1.0) -> Optional[float]:
    """Get listed price for given instance, converted to EUR."""
    query = """
        SELECT hourlypriceusd * %(exchange_rate)s FROM pricingcatalog
        WHERE cloud = %(provider)s AND region = %(region)s
          AND os = %(os)s AND instancetype = %(instance_type)s
        LIMIT 1;
    """
    db_cursor.execute(query, {
        "provider": provider, "region": region,
        "os": os, "instance_type": instance_type,
        "exchange_rate": exchange_rate,
    })
    row = db_cursor.fetchone()
    return row[0] if row else None


def get_suitable_candidates(db_cursor, provider: str, region: str, os: str,
                            req_vcpu: float, req_ram: float, req_iops: float, req_net_mbps: float, 
                            sql_like_patterns: List[str], architecture: str = 'x86_64',
                            is_gpu: bool = False, is_confidential: bool = False,
                            has_local_storage: bool = False, current_supports_premium: bool = False,
                            exchange_rate: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Query for viable downsizing candidates.

    Hard constraints in SQL:
      - isgpu

    Other constraints are checked in code and added as warnings:
      - architecture
      - isconfidential
      - haslocalstorage
      - supportspremiumstorage
    """
    filter_clause = ""
    if sql_like_patterns:
        filter_clause = "AND h.instancetype NOT LIKE ALL(%(patterns)s)"

    query = f"""
        SELECT
            h.instancetype,
            h.vcpu,
            h.memorygb,
            p.hourlypriceusd * %(exchange_rate)s,
            h.architecture,
            h.isgpu,
            h.isconfidential,
            h.haslocalstorage,
            h.supportspremiumstorage
        FROM hardwarecatalog h
        JOIN pricingcatalog p
          ON h.cloud = p.cloud AND h.instancetype = p.instancetype
        WHERE h.cloud          = %(provider)s
          AND p.region         = %(region)s
          AND p.os             = %(os)s
          AND h.vcpu           >= %(req_vcpu)s
          AND h.memorygb      >= %(req_ram)s
          AND (h.baselineiops IS NULL OR h.baselineiops >= %(req_iops)s)
          AND (h.baselinethroughputmbps IS NULL OR h.baselinethroughputmbps >= %(req_net_mbps)s)
          AND p.hourlypriceusd IS NOT NULL
          AND p.hourlypriceusd > 0
          -- Hard class constraint
          AND h.isgpu            = %(is_gpu)s
          {filter_clause}
        ORDER BY p.hourlypriceusd ASC;
    """
    db_cursor.execute(query, {
        "provider": provider,
        "region": region,
        "os": os,
        "req_vcpu": req_vcpu,
        "req_ram": req_ram,
        "req_iops": req_iops,
        "req_net_mbps": req_net_mbps,
        "is_gpu": is_gpu,
        "patterns": sql_like_patterns,
        "exchange_rate": exchange_rate,
    })

    candidates = []
    for r in db_cursor.fetchall():
        c_arch = r[4]
        c_gpu = r[5]
        c_conf = r[6]
        c_local = r[7]
        c_premium = r[8]
        
        warns = []
        if c_arch != architecture:
            warns.append("jiná architektura procesoru")
        if is_confidential and not c_conf:
            warns.append("není confidential")
        if has_local_storage and not c_local:
            warns.append("bez lokálního úložiště")
        if current_supports_premium and not c_premium:
            warns.append("nepodporuje prémiové úložiště")
            
        candidates.append({
            "instance_type": r[0],
            "vcpu": r[1],
            "memory_gb": r[2],
            "hourly_price_usd": r[3],
            "architecture": c_arch,
            "is_gpu": c_gpu,
            "is_confidential": c_conf,
            "has_local_storage": c_local,
            "supports_premium_storage": c_premium,
            "warnings": warns
        })

    return candidates