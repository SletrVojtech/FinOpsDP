# web_app/services/cost_service.py
import calendar
from datetime import date, timedelta
from crud import costs as costs_crud, allocations
from services import kube_chargeback



def tags_match(current_tags: dict, rule_tags: dict) -> bool:
    """Check if current tags match rule tags"""
    if not rule_tags: 
        return False
    for k, v in rule_tags.items():
        if current_tags.get(k) != v:
            return False
    return True

def get_aggregated_daily_costs(cursor, scope_id: int, active_tags: dict,
                                start_date: date = None, end_date: date = None):
    raw_data = costs_crud.get_daily_costs(cursor, scope_id, active_tags,
                                           start_date=start_date, end_date=end_date)
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
            cluster_raw_costs = costs_crud.get_daily_costs(cursor, cluster_id, {}, start_date=start_date, end_date=end_date)
            cluster_cost_dict = {row["date"]: row["cost"] for row in cluster_raw_costs}
            
            namespace_costs = kube_chargeback.get_daily_namespace_allocation(
                cursor, 
                cluster_id,  
                cluster_cost_dict =cluster_cost_dict, 
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
            
    
    

def calculate_chargeback_forecast(cursor, scope_id: int, active_tags: dict, target_month: str = None) -> dict:
    """
    Calculates monthly spend and creates a Run-Rate forcast with a 7 day window.
    Based on
    """
    # Get month
    if target_month:
        year, month = map(int, target_month.split('-'))
        base_date = date(year, month, 1)
        start_date = base_date.replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)
    else:
        start_date = date.today().replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date + timedelta(days=last_day)


    # Get daily data from DB
    cost_dict = get_aggregated_daily_costs(cursor, scope_id, active_tags, start_date=start_date, end_date=end_date)

    _, num_days = calendar.monthrange(base_date.year, base_date.month)
    # How many days have to be forecasted
    if cost_dict:
        last_data_date = date.fromisoformat(max(cost_dict.keys()))
        cutoff_day = last_data_date.day
    else:
        cutoff_day = 0 

    labels = []
    actual_daily = []
    actual_cumulative = []
    forecast_cumulative = []

    cumulative_sum = 0
    last_7_days_costs = []

    # Computation with 7 day moving average
    for day in range(1, num_days + 1):
        current_date = date(base_date.year, base_date.month, day)
        date_str = current_date.isoformat()
        labels.append(date_str)
        
        # Use existing data
        if day <= cutoff_day:
            daily_cost = cost_dict.get(date_str, 0.0)
            cumulative_sum += daily_cost
            
            actual_daily.append(round(daily_cost, 2))
            actual_cumulative.append(round(cumulative_sum, 2))
            forecast_cumulative.append(None) 
            
            last_7_days_costs.append(daily_cost)
            if len(last_7_days_costs) > 7:
                last_7_days_costs.pop(0)
                
        else:
            # Forecast from the previous
            if cutoff_day > 0 and len(actual_cumulative) == cutoff_day and forecast_cumulative[-1] is None:
                forecast_cumulative[cutoff_day - 1] = round(cumulative_sum, 2)

            run_rate = sum(last_7_days_costs) / len(last_7_days_costs) if last_7_days_costs else 0
            cumulative_sum += run_rate
            
            actual_daily.append(None)
            actual_cumulative.append(None)
            forecast_cumulative.append(round(cumulative_sum, 2))
    costs_crud.save_forecast_snapshot(cursor, scope_id, active_tags, base_date, round(cumulative_sum, 2))
    cursor.connection.commit()
    budget_amount = costs_crud.get_budget(cursor, scope_id, active_tags, base_date)

    return {
        "month": f"{base_date.year}-{base_date.month:02d}",
        "projected_total": round(cumulative_sum, 2),
        "labels": labels,
        "actual_daily": actual_daily,
        "actual_cumulative": actual_cumulative,
        "forecast_cumulative": forecast_cumulative,
        "budget": budget_amount
    }

