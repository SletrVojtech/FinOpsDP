from datetime import date, timedelta
import calendar
from collections import defaultdict
from crud import kube

def get_daily_namespace_allocation(cursor, cluster_id: int,
                                    base_date: date, daily_cluster_costs: dict,
                                    start_date: date = None, end_date: date = None,
                                   return_ui_format: bool = True):
    """Calculate daily costs of the cluster per namespace."""

    print(daily_cluster_costs)

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


    rows = kube.get_daily_cpu_allocation(cursor, cluster_id, base_date, start_date, end_date)
    raw_namespace_data = defaultdict(dict)

    # Reallocate the cost per namespace based on the cpu allocation
    for row in rows:
        calc_date = row[0]
        namespace = row[1]
        daily_share = row[2] or 0.0
        
        date_str = calc_date.isoformat()
        if date_str not in all_dates:
            continue
        
        # Multiply by the fraction
        cluster_cost_for_day = daily_cluster_costs.get(date_str, 0.0)
        #print(f"Date: {date_str} | K8s Share: {daily_share} | Cluster Cost: {cluster_cost_for_day}")
        allocated_cost = cluster_cost_for_day * float(daily_share)
        
        raw_namespace_data[namespace][date_str] = round(allocated_cost, 2)
    
    # gapfilling
    for ns in raw_namespace_data.keys():
        for d in all_dates:
            if d not in raw_namespace_data[ns]:
                raw_namespace_data[ns][d] = 0.0

    if not return_ui_format:
        # return just date:data
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