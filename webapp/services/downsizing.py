from typing import List, Dict, Any
from crud import downsizing as crud_downsizing

def evaluate_downsizing(db_cursor, resource_id: int, analysis_days: int = 30, 
                        target_cpu_util: float = 60.0, target_ram_util: float = 80.0,
                        excluded_filters: List[str] = None) -> Dict[str, Any]:
    """
    Returns a rightsizing recommendation for given instance.
    """
    
    if excluded_filters is None:
        excluded_filters = []
    # Get actual instance metadata
    current = crud_downsizing.get_instance_metadata(db_cursor, resource_id)
    if not current:
        return {"status": "error", "message": "Resource not found"}

    # Get current metrics
    tel = crud_downsizing.get_telemetry(db_cursor, resource_id, analysis_days)
    
    # Sum the in/out metrics (slightly pesimistic)
    iops_max = (tel["disk_read_max"] or 0) + (tel["disk_write_max"] or 0)
    net_max_bps = (tel["net_in_max"] or 0) + (tel["net_out_max"] or 0)
    net_max_mbps = net_max_bps / 1000000.0

    # Add a buffer to the measured needs, don't change the limits if metrics are missing
    if tel["cpu_p95"] is not None:
        target_vcpu = float(current["vcpu"]) * (tel["cpu_p95"] / target_cpu_util)
    else:
        target_vcpu = current["vcpu"]

    if tel["ram_max"] is not None:
        target_ram = float(current["memory_gb"]) * (tel["ram_max"] / target_ram_util)
    else:
        target_ram = current["memory_gb"]

    # Filter instances by pattern
    sql_patterns = [f.replace("*", "%") for f in excluded_filters]

    # Find new candidates
    candidates = crud_downsizing.get_suitable_candidates(
        db_cursor=db_cursor,
        provider=current["provider"],
        region=current["region"],
        os=current["os"],
        req_vcpu=max(1.0, target_vcpu),
        req_ram=max(1.0, target_ram),
        req_iops=float(iops_max),
        req_net_mbps=float(net_max_mbps),
        sql_like_patterns=sql_patterns
    )

    if not candidates:
        return {"status": "success", "action": "none", "message": "No smaller instances fit the target workloads."}

    # Calculate the price difference
    actual_daily_cost = crud_downsizing.get_actual_daily_cost(db_cursor, resource_id, analysis_days)
    current_catalog_price = crud_downsizing.get_catalog_hourly_price(
        db_cursor, current["provider"], current["region"], current["os"], current["instance_type"]
    )
    
    # Skip if the pricing catalog is incomplete
    if not current_catalog_price or current_catalog_price <= 0:
        best_candidate = candidates[0] # Get the cheapest one
        return {
            "status": "success", 
            "action": "downsize_recommended",
            "current_instance": current["instance_type"],
            "recommended_instance": best_candidate["instance_type"],
            "warning": "Cost metrics unavailable for ratio calculation."
        }

    # Choose the cheapest one
    best_candidate = None
    best_savings_ratio = 0.0

    for cand in candidates:
        if cand["hourly_price_usd"] < current_catalog_price:
            best_candidate = cand
            best_savings_ratio = (current_catalog_price - cand["hourly_price_usd"]) / current_catalog_price
            break 

    if not best_candidate:
         return {"status": "success", "action": "none", "message": "Current instance is already the most cost-effective option."}

    # Ecaluate new price - ratio from the difference of listed and paid price
    projected_daily_cost = actual_daily_cost * float((1 - best_savings_ratio))
    monthly_savings_usd = (actual_daily_cost - projected_daily_cost) * 30

    return {
        "status": "success",
        "action": "downsize_recommended",
        "current_instance": current["instance_type"],
        "recommended_instance": best_candidate["instance_type"],
        "financials": {
            "current_actual_daily_cost_usd": round(actual_daily_cost, 2),
            "projected_daily_cost_usd": round(projected_daily_cost, 2),
            "estimated_monthly_savings_usd": round(monthly_savings_usd, 2),
            "savings_percentage": round(best_savings_ratio * 100, 2)
        },
        "telemetry_used": {
            "cpu_p95": round(tel["cpu_p95"], 2) if tel["cpu_p95"] else None,
            "ram_max": tel["ram_max"],
            "target_vcpu": round(target_vcpu, 2),
            "target_ram": round(target_ram, 2)
        }
    }