from datetime import date, timedelta
import calendar
from collections import defaultdict
from crud import kube

CPU_WEIGHT = 0.70   # fraction of cluster cost attributed to CPU requests
RAM_WEIGHT = 0.30   # fraction of cluster cost attributed to memory requests


def get_daily_namespace_allocation(cursor, cluster_id: int,
                                    base_date: date, daily_cluster_costs: dict,
                                    start_date: date = None, end_date: date = None,
                                   return_ui_format: bool = True):
    """
    Distributes daily cluster costs among namespaces based on their resource utilization.
        Fetch daily average CPU/RAM reservation shares (%) for each namespace from the DB.
        Combine these shares using a static weight (0.7 for CPU, 0.3 for RAM) to derive
        a single 'combined share' per namespace per day.
        Multiply the day's total cluster cost (derived from the cloud billing table) 
        by the combined share.
        Ensures all namespaces are gap-filled across the entire range.

        return_ui_format: If True, returns Chart.js-compatible dataset format.

    """

    if base_date and not start_date:
        start_date = base_date.replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)

    if not start_date or not end_date:
        start_date = date.today().replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)

    # list of days
    delta = end_date - start_date
    all_dates = [(start_date + timedelta(days=i)).isoformat() for i in range(delta.days)]

    # Get both resource shares from DB
    cpu_rows = kube.get_daily_cpu_allocation(cursor, cluster_id, start_date=start_date, end_date=end_date)
    ram_rows = kube.get_daily_memory_allocation(cursor, cluster_id, start_date=start_date, end_date=end_date)

    def _rows_to_lookup(rows):
        lk = defaultdict(dict)
        for row in rows:
            lk[row[0].isoformat()][row[1]] = float(row[2] or 0.0)
        return lk

    cpu_lookup = _rows_to_lookup(cpu_rows)
    ram_lookup = _rows_to_lookup(ram_rows)

    # Collect all namespaces seen across both metrics
    all_namespaces = set()
    for d in all_dates:
        all_namespaces.update(cpu_lookup.get(d, {}).keys())
        all_namespaces.update(ram_lookup.get(d, {}).keys())

    raw_namespace_data = defaultdict(dict)

    for date_str in all_dates:
        cluster_cost_for_day = daily_cluster_costs.get(date_str, 0.0)
        cpu_day = cpu_lookup.get(date_str, {})
        ram_day = ram_lookup.get(date_str, {})

        for namespace in all_namespaces:
            cpu_share = cpu_day.get(namespace, 0.0)
            ram_share = ram_day.get(namespace, 0.0)

            # Weighted combined share
            combined_share = CPU_WEIGHT * cpu_share + RAM_WEIGHT * ram_share
            allocated_cost = cluster_cost_for_day * combined_share
            raw_namespace_data[namespace][date_str] = round(allocated_cost, 2)

    # gap-filling: ensure every namespace has an entry for every date
    for ns in raw_namespace_data:
        for d in all_dates:
            raw_namespace_data[ns].setdefault(d, 0.0)

    if not return_ui_format:
        return dict(raw_namespace_data)

    datasets = []
    for ns_name, dates_dict in raw_namespace_data.items():
        data_array = [dates_dict[d] for d in all_dates]
        datasets.append({
            "label": ns_name,
            "data": data_array
        })

    return {
        "labels": all_dates,
        "datasets": datasets
    }