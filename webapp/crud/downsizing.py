"""
Downsizing CRUD Module.

Provides SQL queries for the VM rightsizing pipeline: hardware metadata
retrieval, performance telemetry aggregation, catalogue pricing lookup,
and candidate instance search.
"""

from typing import List, Dict, Any, Optional


def get_instance_metadata(db_cursor, resource_id: int) -> Optional[Dict[str, Any]]:
    """Fetch hardware metadata and class constraints for a VM instance entity.

    Joins the ``Entities`` table with ``HardwareCatalog`` using the
    ``instance_type`` JSON extra field. Returns ``None`` when the entity
    does not exist.

    Args:
        db_cursor: Active database cursor.
        resource_id (int): Primary key of the VM entity to look up.

    Returns:
        dict: Metadata dict with keys ``provider``, ``region``, ``os``,
            ``instance_type``, ``vcpu``, ``memory_gb``, ``architecture``,
            ``is_gpu``, ``is_confidential``, ``has_local_storage``, and
            ``supports_premium_storage``. Returns ``None`` if not found.
    """
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
    """Select the best metrics table for the given analysis window.

    Prefers Continuous Aggregate (CAGG) tables that cover at least
    ``analysis_days`` days to raw ``Metrics`` for performance.

    Args:
        db_cursor: Active database cursor.
        analysis_days (int): Number of historical days in the analysis window.

    Returns:
        tuple: 3-tuple of ``(table_name, val_col, time_col)`` where
            ``val_col`` is ``max_value`` for CAGGs or ``value`` for raw,
            and ``time_col`` is ``bucket`` for CAGGs or ``timestamp``
            for raw.
    """
    # Defaults
    table = "metrics"
    val_col = "value"
    time_col = "timestamp"
    
    # Prefer aggregates for longer timeframes
    db_cursor.execute("SELECT TableName, IsCAGG FROM DataDictionary WHERE DataType = 'metrics' AND retentionduration >= %s::interval ORDER BY Granularity ASC LIMIT 1", (f"{analysis_days} days",))
    row = db_cursor.fetchone()
    if row:
        table = row[0]
        is_cagg = row[1]
        val_col = "max_value" if is_cagg else "value"
        time_col = "bucket" if is_cagg else "timestamp"
    return table, val_col, time_col


def get_telemetry(db_cursor, resource_id: int, analysis_days: int) -> Dict[str, Optional[float]]:
    """Return aggregated performance telemetry for a VM over the analysis window.

    Queries CPU P95, max RAM usage, max disk IOPS, and max network throughput
    from the appropriate metrics table. All values may be ``None`` when the
    VM has not reported the corresponding metric.

    Args:
        db_cursor: Active database cursor.
        resource_id (int): Primary key of the VM entity.
        analysis_days (int): Number of days to look back.

    Returns:
        dict: Dict with keys ``cpu_p95``, ``ram_max``, ``disk_read_max``,
            ``disk_write_max``, ``net_in_max``, ``net_out_max``.
            Each value is a float or ``None``.
    """
    table, val_col, time_col  = _resolve_data_source(db_cursor, analysis_days)

    query = f"""
        WITH time_filtered AS (
            SELECT metrictype as metric_name, {val_col} as val
            FROM {table}
            WHERE entityid = %(resource_id)s
              AND "{time_col}" >= NOW() - (%(days)s * INTERVAL '1 day')
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

def get_actual_daily_cost(
    db_cursor,
    resource_id: str,
    analysis_days: int,
    exchange_rate: float = 1.0,
) -> float:
    """Return the average daily billing cost for a VM over the analysis window.

    Divides the total billed cost by ``analysis_days`` so the result is
    directly comparable to catalogue hourly prices.

    Args:
        db_cursor: Active database cursor.
        resource_id (str): Primary key of the VM entity.
        analysis_days (int): Number of days to average over.
        exchange_rate (float, optional): USD-to-EUR multiplier. Defaults to 1.0.

    Returns:
        float: Average daily cost in EUR.
    """
    query = """
        SELECT COALESCE(SUM(billedcost * (CASE WHEN billingcurrency = 'USD' THEN %(exchange_rate)s ELSE 1.0 END)), 0.0) / %(analysis_days)s
        FROM costs
        WHERE entityid = %(resource_id)s
          AND "chargeperiodstart" >= NOW() - (%(analysis_days)s * INTERVAL '1 day');
    """
    db_cursor.execute(query, {"resource_id": resource_id, "analysis_days": analysis_days, "exchange_rate": exchange_rate})
    return db_cursor.fetchone()[0]

def get_catalog_hourly_price(
    db_cursor,
    provider: str,
    region: str,
    os: str,
    instance_type: str,
    exchange_rate: float = 1.0,
) -> Optional[float]:
    """Return the listed hourly price for an instance type in EUR.

    Args:
        db_cursor: Active database cursor.
        provider (str): Cloud provider name (e.g. ``"azure"``).
        region (str): Region identifier.
        os (str): Normalised OS name.
        instance_type (str): Instance type string.
        exchange_rate (float, optional): USD-to-EUR multiplier. Defaults to 1.0.

    Returns:
        float: Hourly price in EUR, or ``None`` if not found in the catalogue.
    """
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


def get_suitable_candidates(
    db_cursor,
    provider: str,
    region: str,
    os: str,
    req_vcpu: float,
    req_ram: float,
    req_iops: float,
    req_net_mbps: float,
    sql_like_patterns: List[str],
    architecture: str = 'x86_64',
    is_gpu: bool = False,
    is_confidential: bool = False,
    has_local_storage: bool = False,
    current_supports_premium: bool = False,
    exchange_rate: float = 1.0,
) -> List[Dict[str, Any]]:
    """Query the hardware catalogue for cheaper instance types meeting all constraints.

    Hard constraints are applied directly in SQL:
    - ``is_gpu`` (must match exactly)
    - vCPU, RAM, IOPS, throughput (minimum thresholds)
    - Exclusion patterns via ``NOT LIKE ALL``

    Soft constraints (architecture, confidential, local storage, premium
    storage) are checked in Python and surfaced as ``warnings`` on each
    candidate so the service layer can present them to the user.

    Args:
        db_cursor: Active database cursor.
        provider (str): Cloud provider (e.g. ``"azure"``).
        region (str): Region identifier.
        os (str): Normalised OS name.
        req_vcpu (float): Minimum required vCPU count.
        req_ram (float): Minimum required RAM in GB.
        req_iops (float): Minimum required IOPS (0 means no constraint).
        req_net_mbps (float): Minimum required network throughput in Mbps.
        sql_like_patterns (list[str]): SQL ``LIKE`` patterns for exclusion
            (``%`` wildcards, not glob ``*``).
        architecture (str, optional): Preferred CPU architecture.
            Defaults to ``'x86_64'``.
        is_gpu (bool, optional): Whether a GPU instance is required.
        is_confidential (bool, optional): Whether confidential compute is needed.
        has_local_storage (bool, optional): Whether local NVMe/SSD is needed.
        current_supports_premium (bool, optional): Whether the current instance
            supports premium storage.
        exchange_rate (float, optional): USD-to-EUR multiplier.

    Returns:
        list: Candidate dicts ordered by ascending price, each with keys
            ``instance_type``, ``vcpu``, ``memory_gb``, ``hourly_price_usd``,
            ``architecture``, ``is_gpu``, ``is_confidential``,
            ``has_local_storage``, ``supports_premium_storage``, and
            ``warnings`` (list of user-visible constraint violation strings).
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