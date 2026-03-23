from datetime import date, timedelta
import calendar
from collections import defaultdict
from crud import kube

def get_daily_namespace_allocation(cursor, cluster_id: int,
                                    base_date: date, daily_cluster_costs: dict):
    """Calculate daily costs of the cluster per namespace."""

    _, num_days = calendar.monthrange(base_date.year, base_date.month)

    rows = kube.get_daily_cpu_allocation(cursor, cluster_id, base_date)
    
    # Load labels
    labels = [date(base_date.year, base_date.month, day).isoformat() for day in range(1, num_days + 1)]
    
    # Default values
    namespace_data = defaultdict(lambda: [0.0] * num_days)

    # Reallocate the cost per namespace based on the cpu allocation
    for row in rows:
        calc_date = row[0]
        namespace = row[1]
        daily_share = row[2] or 0.0
        
        date_str = calc_date.isoformat()
        
        day_index = calc_date.day - 1
        
        # Multiply by the fraction
        cluster_cost_for_day = daily_cluster_costs.get(date_str, 0.0)
        allocated_cost = cluster_cost_for_day * float(daily_share)
        
        namespace_data[namespace][day_index] = round(allocated_cost, 2)

    datasets = []
    for ns_name, data_array in namespace_data.items():
        datasets.append({
            "label": ns_name,
            "data": data_array
        })

    return {
        "labels": labels,
        "datasets": datasets
    }