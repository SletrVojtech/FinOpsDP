import logging
from datetime import date

from crud import costs as costs_crud, allocations
from services import kube_chargeback, currency

logger = logging.getLogger(__name__)


def tags_match(current_tags: dict, rule_tags: dict) -> bool:
    """Check if current tags match rule tags"""
    if not rule_tags: 
        return False
    for k, v in rule_tags.items():
        if current_tags.get(k) != v:
            return False
    return True


def get_aggregated_daily_costs_k8s(cursor, scope_id: int, active_tags: dict,
                                start_date: date = None, end_date: date = None):
    """Aggregates daily costs for a given k8s."""
    exch_rate = currency.get_usd_to_eur_rate()
    raw_data = costs_crud.get_daily_costs(cursor, scope_id, active_tags,
                                           start_date=start_date, end_date=end_date, exchange_rate=exch_rate)
    cost_dict = {row["date"]: row["cost"] for row in raw_data}

    if not active_tags:
        return cost_dict
    
    target_namespaces = costs_crud.get_namespaces_for_tags(cursor, active_tags)
    if target_namespaces:
        # Get a set of clusters needed to be queried.
        cluster_map = {}
        for ns in target_namespaces:
            cluster_id = ns[1]
            ns_name = ns[2]
            if cluster_id not in cluster_map:
                cluster_map[cluster_id] = []
            cluster_map[cluster_id].append(ns_name)
        for cluster_id, ns_names in cluster_map.items():
            # Daily costs for given cluster
            cluster_raw_costs = costs_crud.get_daily_costs(cursor, cluster_id, {}, start_date=start_date, end_date=end_date, exchange_rate=exch_rate)
            cluster_cost_dict = {row["date"]: row["cost"] for row in cluster_raw_costs}
            namespace_costs = kube_chargeback.get_daily_namespace_allocation(
                cursor, 
                cluster_id,
                base_date=None,  
                daily_cluster_costs =cluster_cost_dict, 
                return_ui_format=False,
                start_date=start_date, 
                end_date=end_date

            )
            
            # Add the namespaces to the costs
            for ns_name in ns_names:
                if ns_name in namespace_costs:
                    for date_str, cost in namespace_costs[ns_name].items():
                        cost_dict[date_str] = cost_dict.get(date_str, 0.0) + cost
    
    all_rules = allocations.get_allocation_rules(cursor)
        
    # Get rules that affect current tag scope
    incoming_rules = [r for r in all_rules if tags_match(active_tags, r["target_tags"])]
    outgoing_rules = [r for r in all_rules if tags_match(active_tags, r["source_tags"])]
    
    applicable_rules = incoming_rules + outgoing_rules

    if applicable_rules:
        # Load all sources
        source_costs = {}
        existing_dates = set(cost_dict.keys())
        for rule in applicable_rules:
            if rule["id"] not in source_costs:
                s_data = costs_crud.get_daily_costs(cursor, 0, rule["source_tags"], start_date=start_date, end_date=end_date)
                s_dict = {row["date"]: row["cost"] for row in s_data}
                source_costs[rule["id"]] = s_dict
                existing_dates.update(s_dict.keys())

        # Update daily values
        for day in existing_dates:
            date_str = day
            
            # Base expense
            daily_total = cost_dict.get(date_str, 0.0)
            
            # Add costs for being the target
            for rule in incoming_rules:
                s_cost = source_costs[rule["id"]].get(date_str, 0.0)
                daily_total += s_cost * (rule["percentage"] / 100.0)
                
            # Deduct costs for being the source
            for rule in outgoing_rules:
                s_cost = source_costs[rule["id"]].get(date_str, 0.0)
                daily_total -= s_cost * (rule["percentage"] / 100.0)
                
            cost_dict[date_str] = daily_total

    return cost_dict


def get_aggregated_daily_costs(cursor, scope_id: int, active_tags: dict,
                                start_date: date = None, end_date: date = None):
    """Aggregates daily costs for a given scope and tags."""
    exch_rate = currency.get_usd_to_eur_rate()
    raw_data = costs_crud.get_daily_costs(cursor, scope_id, active_tags,
                                           start_date=start_date, end_date=end_date, exchange_rate=exch_rate)
    cost_dict = {row["date"]: row["cost"] for row in raw_data}

    if not active_tags:
        return cost_dict
    
    target_namespaces = costs_crud.get_namespaces_for_tags(cursor, active_tags)
    if target_namespaces:
        # Get a set of clusters needed to be queried.
        cluster_map = {}
        for ns in target_namespaces:
            cluster_id = ns[1]
            ns_name = ns[2]
            if cluster_id not in cluster_map:
                cluster_map[cluster_id] = []
            cluster_map[cluster_id].append(ns_name)
        for cluster_id, ns_names in cluster_map.items():
            # Daily costs for given cluster
            cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
            row = cursor.fetchone()
            cluster_name = row[0] if row else "Neznámý cluster"
            # Daily costs for given cluster
            cluster_cost_dict = get_aggregated_daily_costs_k8s(cursor, cluster_id, {"cluster": cluster_name}, start_date=start_date, end_date=end_date)
            namespace_costs = kube_chargeback.get_daily_namespace_allocation(
                cursor, 
                cluster_id,
                base_date=None,  
                daily_cluster_costs =cluster_cost_dict, 
                return_ui_format=False,
                start_date=start_date, 
                end_date=end_date

            )
            
            # Add the namespaces to the costs
            for ns_name in ns_names:
                if ns_name in namespace_costs:
                    for date_str, cost in namespace_costs[ns_name].items():
                        cost_dict[date_str] = cost_dict.get(date_str, 0.0) + cost
    
    all_rules = allocations.get_allocation_rules(cursor)
        
    # Get rules that affect current tag scope
    incoming_rules = [r for r in all_rules if tags_match(active_tags, r["target_tags"])]
    outgoing_rules = [r for r in all_rules if tags_match(active_tags, r["source_tags"])]
    
    applicable_rules = incoming_rules + outgoing_rules

    if applicable_rules:
        # Load all sources
        source_costs = {}
        existing_dates = set(cost_dict.keys())
        for rule in applicable_rules:
            if rule["id"] not in source_costs:
                s_data = costs_crud.get_daily_costs(cursor, 0, rule["source_tags"], start_date=start_date, end_date=end_date, exchange_rate=exch_rate)
                s_dict = {row["date"]: row["cost"] for row in s_data}
                source_costs[rule["id"]] = s_dict
                existing_dates.update(s_dict.keys())

        # Update daily values
        for day in existing_dates:
            date_str = day
            
            # Base expense
            daily_total = cost_dict.get(date_str, 0.0)
            
            # Add costs for being the target
            for rule in incoming_rules:
                s_cost = source_costs[rule["id"]].get(date_str, 0.0)
                daily_total += s_cost * (rule["percentage"] / 100.0)
                
            # Deduct costs for being the source
            for rule in outgoing_rules:
                s_cost = source_costs[rule["id"]].get(date_str, 0.0)
                daily_total -= s_cost * (rule["percentage"] / 100.0)
                
            cost_dict[date_str] = daily_total

    return cost_dict


def get_aggregated_daily_costs_by_category(
    cursor, scope_id: int, active_tags: dict,
    start_date: date = None, end_date: date = None
) -> dict:
    """Cloud costs by ServiceCategory + each matched K8s namespace as 'k8s:<name>'."""
    cat_dict: dict[str, dict[str, float]] = {}
    exch_rate = currency.get_usd_to_eur_rate()
    for row in costs_crud.get_daily_costs_by_category(cursor, scope_id, active_tags,
                                                       start_date=start_date, end_date=end_date, exchange_rate=exch_rate):
        d = cat_dict.setdefault(row["category"], {})
        d[row["date"]] = d.get(row["date"], 0.0) + row["cost"]

    if active_tags:
        ns_allocations = _get_shared_namespace_allocations(cursor, active_tags, start_date, end_date)
        for ns_id, ns_info in ns_allocations.items():
            cat_key = f"k8s:{ns_info['name']}"
            cat_dict.setdefault(cat_key, {}).update(ns_info["costs"])

    return cat_dict


def get_aggregated_daily_costs_by_tag_key(
    cursor, scope_id: int, active_tags: dict, tag_key: str,
    start_date: date = None, end_date: date = None
) -> dict:
    """Cloud costs grouped by values of a given tag key + K8s namespace costs attributed to their own tag values."""
    tag_dict: dict[str, dict[str, float]] = {}
    
    exch_rate = currency.get_usd_to_eur_rate()
    # Get raw cloud costs grouped by tag value
    for row in costs_crud.get_daily_costs_by_tag_key(cursor, scope_id, active_tags, tag_key,
                                                     start_date=start_date, end_date=end_date, exchange_rate=exch_rate):
        d = tag_dict.setdefault(row["tag_value"], {})
        d[row["date"]] = d.get(row["date"], 0.0) + row["cost"]

    # Add K8s namespace costs
    if active_tags:
        ns_allocations = _get_shared_namespace_allocations(cursor, active_tags, start_date, end_date)
        for ns_id, ns_info in ns_allocations.items():
            tag_val = ns_info["tags"].get(tag_key, "Unrecognized")
            d = tag_dict.setdefault(tag_val, {})
            for date_str, cost in ns_info["costs"].items():
                d[date_str] = d.get(date_str, 0.0) + cost

    return tag_dict


def _get_shared_namespace_allocations(cursor, active_tags: dict, start_date: date, end_date: date) -> dict:
    """Helper to find namespaces and calculate their allocations once."""
    query_ns = "SELECT Id, ParentId, ResourceName, Tags FROM Entities WHERE ResourceType = 'kubernetes_namespace'"
    params_ns = []
    for k, v in active_tags.items():
        query_ns += " AND Tags->>%s = %s"
        params_ns.extend([k, v])
    
    cursor.execute(query_ns, params_ns)
    ns_rows = cursor.fetchall()
    
    # cluster_id -> list of (ns_id, ns_name, ns_tags)
    cluster_map: dict[int, list[tuple[int, str, dict]]] = {}
    for ns_id, cluster_id, ns_name, ns_tags in ns_rows:
        cluster_map.setdefault(cluster_id, []).append((ns_id, ns_name, ns_tags))

    results = {}
    for cluster_id, ns_list in cluster_map.items():
        # Get cluster name
        cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
        row = cursor.fetchone()
        cluster_name = row[0] if row else "Neznámý cluster"
        # Daily costs for given cluster
        cluster_cost_dict = get_aggregated_daily_costs_k8s(cursor, cluster_id, {"cluster": cluster_name}, start_date=start_date, end_date=end_date)
        # Batch attribution for all namespaces in this cluster
        all_ns_allocations = kube_chargeback.get_daily_namespace_allocation(
            cursor, cluster_id, base_date=None,
            daily_cluster_costs=cluster_cost_dict, return_ui_format=False,
            start_date=start_date, end_date=end_date)
        for ns_id, ns_name, ns_tags in ns_list:
            if ns_name in all_ns_allocations:
                results[ns_id] = {
                    "name": ns_name,
                    "tags": ns_tags if isinstance(ns_tags, dict) else {},
                    "costs": all_ns_allocations[ns_name]
                }
    return results
