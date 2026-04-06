from typing import List, Dict, Any
from crud import downsizing as crud_downsizing


def evaluate_downsizing(
    db_cursor,
    resource_id: int,
    analysis_days: int = 30,
    target_cpu_util: float = 60.0,
    target_ram_util: float = 80.0,
    excluded_filters: List[str] = None,
) -> Dict[str, Any]:
    """
    Returns a rightsizing recommendation for the given instance.

    Class constraints (architecture, GPU, confidential, local storage) are
    enforced as hard filters — candidates that would break instance compatibility
    are never returned. Premium storage is a soft ordering hint only.
    """

    if target_cpu_util <= 0:
        target_cpu_util = 1.0 # fallback for zero target
    if target_ram_util <= 0:
        target_ram_util = 1.0

    if excluded_filters is None:
        excluded_filters = []


    # Get actual instance metadata
    current = crud_downsizing.get_instance_metadata(db_cursor, resource_id)
    if not current:
        return {"status": "error", "message": "Resource not found"}

    # Get current metrics
    tel = crud_downsizing.get_telemetry(db_cursor, resource_id, analysis_days)

    # Add a buffer to the measured needs, don't change the limits if metrics are missing
    if tel["cpu_p95"] is not None:
        target_vcpu = float(current["vcpu"]) * (tel["cpu_p95"] / target_cpu_util)
    else:
        target_vcpu = current["vcpu"]

    if tel["ram_max"] is not None:
        target_ram = float(current["memory_gb"]) * (tel["ram_max"] / target_ram_util)
    else:
        target_ram = current["memory_gb"]

    provider = current["provider"].lower()
    
    # Disk - sum of max read and write
    iops_max = (tel.get("disk_read_max") or 0) + (tel.get("disk_write_max") or 0)

    # Network - extract in Mbps
    net_in_mbps = (tel.get("net_in_max") or 0) / 1_000_000.0
    net_out_mbps = (tel.get("net_out_max") or 0) / 1_000_000.0

    if provider == "azure":
        # Azure limits only outbound traffic
        required_net_mbps = net_out_mbps
    else:
        # AWS full duplex - limit applies to each direction separately
        required_net_mbps = max(net_in_mbps, net_out_mbps)

    # Get class constraints from current instance
    constraints = {
        "architecture":     current["architecture"],
        "is_gpu":           current["is_gpu"],
        "is_confidential":  current["is_confidential"],
        "has_local_storage": current["has_local_storage"],
    }

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
        req_net_mbps=float(required_net_mbps),
        sql_like_patterns=sql_patterns,
        # Hard constraints
        architecture=current["architecture"],
        is_gpu=current["is_gpu"],
        is_confidential=current["is_confidential"],
        has_local_storage=current["has_local_storage"],
        # Soft ordering hint
        current_supports_premium=current["supports_premium_storage"],
    )

    if not candidates:
        return {
            "status": "success",
            "action": "none",
            "message": "No smaller instances fit the target workloads.",
            "constraints_applied": constraints,
            "current_instance": current["instance_type"]
        }

    # Get current costs
    actual_daily_cost = crud_downsizing.get_actual_daily_cost(
        db_cursor, resource_id, analysis_days
    )
    current_catalog_price = crud_downsizing.get_catalog_hourly_price(
        db_cursor, current["provider"], current["region"],
        current["os"], current["instance_type"],
    )

    # No catalog price — return best candidate without financials
    if not current_catalog_price or current_catalog_price <= 0:
        best_candidate = candidates[0]
        return {
            "status": "success",
            "action": "downsize_recommended",
            "current_instance": current["instance_type"],
            "recommended_instance": best_candidate["instance_type"],
            "constraints_applied": constraints,
            "warning": "Cost metrics unavailable for ratio calculation.",
        }

    # Pick the cheapest candidate that is cheaper than current
    best_candidate = None
    best_savings_ratio = 0.0

    for cand in candidates:
        if cand["hourly_price_usd"] < current_catalog_price:
            best_candidate = cand
            best_savings_ratio = (
                (current_catalog_price - cand["hourly_price_usd"]) / current_catalog_price
            )
            break

    if not best_candidate:
        return {
            "status": "success",
            "action": "none",
            "message": "Current instance is already the most cost-effective option.",
            "constraints_applied": constraints,
        }

    # Calculate financials
    projected_daily_cost = actual_daily_cost * float(1 - best_savings_ratio)
    monthly_savings_usd = (actual_daily_cost - projected_daily_cost) * 30

    return {
        "status": "success",
        "action": "downsize_recommended",
        "current_instance": current["instance_type"],
        "recommended_instance": best_candidate["instance_type"],
        "constraints_applied": constraints,
        "financials": {
            "current_actual_daily_cost_usd": round(actual_daily_cost, 2),
            "projected_daily_cost_usd": round(projected_daily_cost, 2),
            "estimated_monthly_savings_usd": round(monthly_savings_usd, 2),
            "savings_percentage": round(best_savings_ratio * 100, 2),
        },
        "telemetry_used": {
            "cpu_p95": round(tel["cpu_p95"], 2) if tel["cpu_p95"] else None,
            "ram_max": tel["ram_max"],
            "target_vcpu": round(target_vcpu, 2),
            "target_ram": round(target_ram, 2),
        },
    }