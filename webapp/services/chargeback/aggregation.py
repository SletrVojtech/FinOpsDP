"""
Chargeback Aggregation Module.

This module provides functions for computing aggregated daily cloud and
Kubernetes costs across a scoped entity hierarchy. It handles tag-based
filtering, K8s namespace cost attribution, and cost reallocation rules.
"""

import logging
from datetime import date
from typing import Optional

from crud import costs as costs_crud, allocations
from services import kube_chargeback, currency

logger = logging.getLogger(__name__)


def tags_match(current_tags: dict, rule_tags: dict) -> bool:
    """Check whether all key-value pairs in rule_tags are present in current_tags.

    Args:
        current_tags (dict): The active tag set of the current scope.
        rule_tags (dict): The tag set defined on the allocation rule side.

    Returns:
        bool: True if every key-value pair in rule_tags exists in current_tags,
            False otherwise (including when rule_tags is empty).
    """
    if not rule_tags:
        return False
    for k, v in rule_tags.items():
        if current_tags.get(k) != v:
            return False
    return True


def _apply_allocation_rules(
    cursor,
    active_tags: dict,
    cost_dict: dict,
    start_date: Optional[date],
    end_date: Optional[date],
    exch_rate: float,
) -> dict:
    """Apply incoming and outgoing allocation rules to a daily cost dictionary.

    Fetches all configured allocation rules, identifies rules that affect
    the given tag scope (as either source or target), loads source costs,
    and adjusts the daily totals accordingly.

    Args:
        cursor: Active database cursor.
        active_tags (dict): Current scope tag filter.
        cost_dict (dict): Mutable mapping of ISO date strings to daily costs.
            Modified in-place and also returned.
        start_date (date, optional): Start of the cost window.
        end_date (date, optional): End of the cost window (exclusive).
        exch_rate (float): USD-to-EUR exchange rate for source cost queries.

    Returns:
        dict: The updated cost_dict with allocation adjustments applied.
    """
    all_rules = allocations.get_allocation_rules(cursor)

    incoming_rules = [r for r in all_rules if tags_match(active_tags, r["target_tags"])]
    outgoing_rules = [r for r in all_rules if tags_match(active_tags, r["source_tags"])]

    applicable_rules = incoming_rules + outgoing_rules

    if not applicable_rules:
        return cost_dict

    source_costs = {}
    existing_dates = set(cost_dict.keys())
    for rule in applicable_rules:
        if rule["id"] not in source_costs:
            s_data = costs_crud.get_daily_costs(
                cursor, 0, rule["source_tags"],
                start_date=start_date, end_date=end_date,
                exchange_rate=exch_rate,
            )
            s_dict = {row["date"]: row["cost"] for row in s_data}
            source_costs[rule["id"]] = s_dict
            existing_dates.update(s_dict.keys())

    for date_str in existing_dates:
        daily_total = cost_dict.get(date_str, 0.0)

        for rule in incoming_rules:
            s_cost = source_costs[rule["id"]].get(date_str, 0.0)
            daily_total += s_cost * (rule["percentage"] / 100.0)

        for rule in outgoing_rules:
            s_cost = source_costs[rule["id"]].get(date_str, 0.0)
            daily_total -= s_cost * (rule["percentage"] / 100.0)

        cost_dict[date_str] = daily_total

    return cost_dict


def get_aggregated_daily_costs_k8s(
    cursor,
    scope_id: int,
    active_tags: dict,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Aggregate daily costs for a Kubernetes cluster scope.

    Fetches raw billing costs for the cluster, optionally overlays namespace
    allocation costs derived from CPU/RAM reservation shares, and applies
    any configured allocation rules.

    Args:
        cursor: Active database cursor.
        scope_id (int): Entity ID of the Kubernetes cluster.
        active_tags (dict): Tag filter used to identify target namespaces.
        start_date (date, optional): Start of the cost window.
        end_date (date, optional): End of the cost window (exclusive).

    Returns:
        dict: Mapping of ISO date strings (``YYYY-MM-DD``) to aggregated
            daily costs in EUR.
    """
    exch_rate = currency.get_usd_to_eur_rate()
    raw_data = costs_crud.get_daily_costs(
        cursor, scope_id, active_tags,
        start_date=start_date, end_date=end_date, exchange_rate=exch_rate,
    )
    cost_dict = {row["date"]: row["cost"] for row in raw_data}

    if not active_tags:
        return cost_dict

    target_namespaces = costs_crud.get_namespaces_for_tags(cursor, active_tags)
    if target_namespaces:
        cluster_map: dict = {}
        for ns in target_namespaces:
            cluster_id = ns[1]
            ns_name = ns[2]
            cluster_map.setdefault(cluster_id, []).append(ns_name)

        for cluster_id, ns_names in cluster_map.items():
            cluster_raw_costs = costs_crud.get_daily_costs(
                cursor, cluster_id, {},
                start_date=start_date, end_date=end_date, exchange_rate=exch_rate,
            )
            cluster_cost_dict = {row["date"]: row["cost"] for row in cluster_raw_costs}
            namespace_costs = kube_chargeback.get_daily_namespace_allocation(
                cursor,
                cluster_id,
                base_date=None,
                daily_cluster_costs=cluster_cost_dict,
                return_ui_format=False,
                start_date=start_date,
                end_date=end_date,
            )
            for ns_name in ns_names:
                if ns_name in namespace_costs:
                    for date_str, cost in namespace_costs[ns_name].items():
                        cost_dict[date_str] = cost_dict.get(date_str, 0.0) + cost

    return _apply_allocation_rules(cursor, active_tags, cost_dict, start_date, end_date, exch_rate)


def get_aggregated_daily_costs(
    cursor,
    scope_id: int,
    active_tags: dict,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Aggregate daily costs for a general scope, including K8s namespace attribution.

    Fetches cloud billing costs for the scope hierarchy, resolves any K8s
    namespace costs by looking up the cluster name and delegating to
    :func:`get_aggregated_daily_costs_k8s`, and applies allocation rules.

    Args:
        cursor: Active database cursor.
        scope_id (int): Root entity ID for the subtree to aggregate.
        active_tags (dict): Tag filter applied to the entity subtree.
        start_date (date, optional): Start of the cost window.
        end_date (date, optional): End of the cost window (exclusive).

    Returns:
        dict: Mapping of ISO date strings (``YYYY-MM-DD``) to aggregated
            daily costs in EUR.
    """
    exch_rate = currency.get_usd_to_eur_rate()
    raw_data = costs_crud.get_daily_costs(
        cursor, scope_id, active_tags,
        start_date=start_date, end_date=end_date, exchange_rate=exch_rate,
    )
    cost_dict = {row["date"]: row["cost"] for row in raw_data}

    if not active_tags:
        return cost_dict

    target_namespaces = costs_crud.get_namespaces_for_tags(cursor, active_tags)
    if target_namespaces:
        cluster_map: dict = {}
        for ns in target_namespaces:
            cluster_id = ns[1]
            ns_name = ns[2]
            cluster_map.setdefault(cluster_id, []).append(ns_name)

        for cluster_id, ns_names in cluster_map.items():
            cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
            row = cursor.fetchone()
            cluster_name = row[0] if row else "Neznámý cluster"

            cluster_cost_dict = get_aggregated_daily_costs_k8s(
                cursor, cluster_id, {"cluster": cluster_name},
                start_date=start_date, end_date=end_date,
            )
            namespace_costs = kube_chargeback.get_daily_namespace_allocation(
                cursor,
                cluster_id,
                base_date=None,
                daily_cluster_costs=cluster_cost_dict,
                return_ui_format=False,
                start_date=start_date,
                end_date=end_date,
            )
            for ns_name in ns_names:
                if ns_name in namespace_costs:
                    for date_str, cost in namespace_costs[ns_name].items():
                        cost_dict[date_str] = cost_dict.get(date_str, 0.0) + cost

    return _apply_allocation_rules(cursor, active_tags, cost_dict, start_date, end_date, exch_rate)


def get_aggregated_daily_costs_by_category(
    cursor,
    scope_id: int,
    active_tags: dict,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Return daily costs broken down by service category, including K8s namespaces.

    Cloud billing costs are grouped by ``ServiceCategory``. Each matched
    Kubernetes namespace appears as an additional category keyed
    ``k8s:<namespace_name>``.

    Args:
        cursor: Active database cursor.
        scope_id (int): Root entity ID for the subtree to aggregate.
        active_tags (dict): Tag filter applied to the entity subtree.
        start_date (date, optional): Start of the cost window.
        end_date (date, optional): End of the cost window (exclusive).

    Returns:
        dict: Nested mapping ``{category : {date_str : cost_eur}}``.
    """
    cat_dict: dict[str, dict[str, float]] = {}
    exch_rate = currency.get_usd_to_eur_rate()
    for row in costs_crud.get_daily_costs_by_category(
        cursor, scope_id, active_tags,
        start_date=start_date, end_date=end_date, exchange_rate=exch_rate,
    ):
        d = cat_dict.setdefault(row["category"], {})
        d[row["date"]] = d.get(row["date"], 0.0) + row["cost"]

    if active_tags:
        ns_allocations = _get_shared_namespace_allocations(cursor, active_tags, start_date, end_date)
        for ns_id, ns_info in ns_allocations.items():
            cat_key = f"k8s:{ns_info['name']}"
            cat_dict.setdefault(cat_key, {}).update(ns_info["costs"])

    return cat_dict


def get_aggregated_daily_costs_by_tag_key(
    cursor,
    scope_id: int,
    active_tags: dict,
    tag_key: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Return daily costs grouped by values of a single tag key, including K8s costs.

    Cloud billing costs are grouped by the value of ``tag_key`` on each
    resource. K8s namespace costs are attributed to whichever tag value
    the namespace carries for that key (falling back to ``'Unrecognized'``).

    Args:
        cursor: Active database cursor.
        scope_id (int): Root entity ID for the subtree to aggregate.
        active_tags (dict): Tag filter applied to the entity subtree.
        tag_key (str): The tag key to group costs by.
        start_date (date, optional): Start of the cost window.
        end_date (date, optional): End of the cost window (exclusive).

    Returns:
        dict: Nested mapping ``{tag_value : {date_str : cost_eur}}``.
    """
    tag_dict: dict[str, dict[str, float]] = {}
    exch_rate = currency.get_usd_to_eur_rate()

    for row in costs_crud.get_daily_costs_by_tag_key(
        cursor, scope_id, active_tags, tag_key,
        start_date=start_date, end_date=end_date, exchange_rate=exch_rate,
    ):
        d = tag_dict.setdefault(row["tag_value"], {})
        d[row["date"]] = d.get(row["date"], 0.0) + row["cost"]

    if active_tags:
        ns_allocations = _get_shared_namespace_allocations(cursor, active_tags, start_date, end_date)
        for ns_id, ns_info in ns_allocations.items():
            tag_val = ns_info["tags"].get(tag_key, "Unrecognized")
            d = tag_dict.setdefault(tag_val, {})
            for date_str, cost in ns_info["costs"].items():
                d[date_str] = d.get(date_str, 0.0) + cost

    return tag_dict


def _get_shared_namespace_allocations(
    cursor,
    active_tags: dict,
    start_date: Optional[date],
    end_date: Optional[date],
) -> dict:
    """Resolve namespace allocations for all clusters matching active_tags.

    Queries all ``kubernetes_namespace`` entities whose tags match
    active_tags, groups them by parent cluster, fetches cluster-level
    costs via :func:`get_aggregated_daily_costs_k8s`, and derives each
    namespace's share via :func:`~services.kube_chargeback.get_daily_namespace_allocation`.

    Args:
        cursor: Active database cursor.
        active_tags (dict): Tag filter used to identify target namespaces.
        start_date (date, optional): Start of the cost window.
        end_date (date, optional): End of the cost window (exclusive).

    Returns:
        dict: Mapping of ``{ns_id -> {"name": str, "tags": dict, "costs": dict}}``.
    """
    query_ns = (
        "SELECT Id, ParentId, ResourceName, Tags "
        "FROM Entities WHERE ResourceType = 'kubernetes_namespace'"
    )
    params_ns: list = []
    for k, v in active_tags.items():
        query_ns += " AND Tags->>%s = %s"
        params_ns.extend([k, v])

    cursor.execute(query_ns, params_ns)
    ns_rows = cursor.fetchall()

    cluster_map: dict[int, list[tuple]] = {}
    for ns_id, cluster_id, ns_name, ns_tags in ns_rows:
        cluster_map.setdefault(cluster_id, []).append((ns_id, ns_name, ns_tags))

    results = {}
    for cluster_id, ns_list in cluster_map.items():
        # Get cluster name
        cursor.execute("SELECT ResourceName FROM Entities WHERE Id = %s", (cluster_id,))
        row = cursor.fetchone()
        cluster_name = row[0] if row else "Neznámý cluster"

        cluster_cost_dict = get_aggregated_daily_costs_k8s(
            cursor, cluster_id, {"cluster": cluster_name},
            start_date=start_date, end_date=end_date,
        )
        all_ns_allocations = kube_chargeback.get_daily_namespace_allocation(
            cursor, cluster_id, base_date=None,
            daily_cluster_costs=cluster_cost_dict, return_ui_format=False,
            start_date=start_date, end_date=end_date,
        )
        for ns_id, ns_name, ns_tags in ns_list:
            if ns_name in all_ns_allocations:
                results[ns_id] = {
                    "name": ns_name,
                    "tags": ns_tags if isinstance(ns_tags, dict) else {},
                    "costs": all_ns_allocations[ns_name],
                }
    return results
