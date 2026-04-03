# web_app/services/cost_service.py
import calendar
from datetime import date, timedelta, datetime
import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoETS
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
            
    
    

def _prepare_dates_and_cutoff(cursor, target_month: str = None):
    """Prepare date interval and actual data cutoff for the given month"""
    SAFE_DAYS_TO_SUBTRACT = 3
    if target_month:
        year, month = map(int, target_month.split('-'))
        base_date = date(year, month, 1)
    else:
        base_date = date.today().replace(day=1)

    start_date = base_date.replace(day=1)
    _, last_day = calendar.monthrange(start_date.year, start_date.month)
    end_date = start_date + timedelta(days=last_day)
    num_days = last_day
    
    # Get the latest date with actual data
    max_date_row = costs_crud.get_max_date(cursor, start_date, end_date)
    if max_date_row and max_date_row[0]:
        cutoff_date_obj = max_date_row[0]
        if isinstance(cutoff_date_obj, datetime):
            cutoff_date_obj = cutoff_date_obj.date()
        # Skip a few latest days with incomplete data
        safe_max_date = date.today() - timedelta(days=SAFE_DAYS_TO_SUBTRACT)
        if cutoff_date_obj > safe_max_date:
            cutoff_date_obj = safe_max_date
        # If the cutoff date is not in the current month, set cutoff_day to 0
        if cutoff_date_obj.month != base_date.month:
            cutoff_day = 0
        else:
            cutoff_day = cutoff_date_obj.day
    else:
        cutoff_date_obj = date.today() - timedelta(days=SAFE_DAYS_TO_SUBTRACT)
        cutoff_day = 0
        
    return base_date, start_date, end_date, num_days, cutoff_date_obj, cutoff_day

def _build_response_payload(base_date, num_days, cutoff_day, cost_dict, future_forecasts, budget_amount, anomaly_thresholds=None, projected_total=None):
    """Build the response payload for the given month"""
    if anomaly_thresholds is None:
        anomaly_thresholds = {}

    labels, actual_daily, actual_cumulative, forecast_cumulative, anomalies = [], [], [], [], []
    cumulative_sum, actual_cumulative_sum = 0, 0

    for day in range(1, num_days + 1):
        current_date = date(base_date.year, base_date.month, day)
        date_str = current_date.isoformat()
        labels.append(date_str)
        # If the day is within the actual data range, use actual data
        if day <= cutoff_day:
            daily_cost = cost_dict.get(date_str, 0.0)
            actual_cumulative_sum += daily_cost
            cumulative_sum += daily_cost
            
            actual_daily.append(round(daily_cost, 2))
            actual_cumulative.append(round(actual_cumulative_sum, 2))
            forecast_cumulative.append(None) 
            
            thresh = anomaly_thresholds.get(date_str, float('inf'))
            anomalies.append(daily_cost > thresh and daily_cost > 10.0)
        # If the day is beyond the actual data range, use forecast data
        else:
            # If the forecast_cumulative is empty, fill it with the actual cumulative sum
            if cutoff_day > 0 and len(actual_cumulative) == cutoff_day and forecast_cumulative[-1] is None:
                forecast_cumulative[cutoff_day - 1] = round(cumulative_sum, 2)

            pred_val = float(max(0.0, future_forecasts.get(date_str, 0.0)))
            cumulative_sum += pred_val
            
            actual_daily.append(None)
            actual_cumulative.append(None)
            forecast_cumulative.append(round(cumulative_sum, 2))
            anomalies.append(False)
       
    return {
        "month": f"{base_date.year}-{base_date.month:02d}",
        "projected_total": projected_total if projected_total is not None else round(cumulative_sum, 2),
        "labels": labels,
        "actual_daily": actual_daily,
        "actual_cumulative": actual_cumulative,
        "forecast_cumulative": forecast_cumulative,
        "anomalies": anomalies,
        "budget": budget_amount
    }

def get_chargeback_dashboard_data(cursor, scope_id: int, active_tags: dict, target_month: str = None) -> dict:
    """
    Main entry point for UI. Attempt to load pre-calculated AutoARIMA data from DB.
    If not available (or older than 24h), fallback to fast AutoETS calculation.
    """
    base_date, start_date, end_date, num_days, cutoff_date_obj, cutoff_day = _prepare_dates_and_cutoff(cursor, target_month)
    
    latest = costs_crud.get_latest_forecast(cursor, scope_id, active_tags, base_date)
    print(latest)
    budget_amount = costs_crud.get_budget(cursor, scope_id, active_tags, base_date)
    
    if not latest or not latest.get('daily_forecasts'):
        return calculate_chargeback_forecast(cursor, scope_id, active_tags, target_month)
        
    cost_dict = get_aggregated_daily_costs(cursor, scope_id, active_tags, start_date=start_date, end_date=end_date)
    
    return _build_response_payload(
        base_date=base_date,
        num_days=num_days,
        cutoff_day=cutoff_day,
        cost_dict=cost_dict,
        future_forecasts=latest.get('daily_forecasts', {}),
        budget_amount=budget_amount,
        projected_total=latest.get("projected_amount")
    )
        


def calculate_chargeback_forecast(cursor, scope_id: int, active_tags: dict, target_month: str = None) -> dict:
    """
    Calculates monthly spend and creates an ML forecast with StatsForecast.
    Includes on-the-fly anomaly detection based on prediction intervals.
    """
    base_date, start_date, end_date, num_days, cutoff_date_obj, cutoff_day = _prepare_dates_and_cutoff(cursor, target_month)

    # Get history - 35 days before the month + the target month
    history_start = start_date - timedelta(days=35)
    cost_dict = get_aggregated_daily_costs(cursor, scope_id, active_tags, start_date=history_start, end_date=end_date)

    # Transform to DataFrame for the model,
    # fill gaps for all days from history_start to cutoff_date.
    df_data = []
    first_nonzero_date = history_start
    # Find the actual boundaries of present data in cost_dict
    if cost_dict:
        sorted_dates = sorted(cost_dict.keys())
        for d_str in sorted_dates:
            if cost_dict[d_str] > 0.0:
                first_nonzero_date = date.fromisoformat(d_str)
                break
                
    curr_date = max(history_start, first_nonzero_date)

    print(f"Cutoff date object: {cutoff_date_obj}")
        
    while curr_date <= cutoff_date_obj:
        d_str = curr_date.isoformat()
        df_data.append({"ds": curr_date,
                        "y": cost_dict.get(d_str, 0.0), 
                        "unique_id": "cost"})
        curr_date += timedelta(days=1)
        
    df = pd.DataFrame(df_data)
    if not df.empty:
        df['ds'] = pd.to_datetime(df['ds'])

    # Get StatsForecast and predictions
    sf = StatsForecast(
        models=[AutoETS(season_length=7)],
        freq='D'
    )
    
    # Predict enough days to reach the end_date of the target month
    days_to_predict = (end_date - cutoff_date_obj).days if cost_dict else num_days
    
    try:
        if df.empty:
            raise ValueError("No data to train on")
            
        # Always predict at least 1 day to force sf.forecast to cache fitted values
        h_val = max(1, days_to_predict)
        forecast_df = sf.forecast(df=df, h=h_val, level=[95], fitted=True)
        fitted_df = sf.forecast_fitted_values()
        
        # If prediction wasn't needed, drop the future forecast
        if days_to_predict <= 0:
            forecast_df = pd.DataFrame()
    except Exception as e:
        # Fallback in case of StatsForecast error (tiny datasets < 14 days)
        forecast_df = pd.DataFrame()
        fitted_df = pd.DataFrame()
        
        # Manually create flat future forecasts as fallback
        future_forecasts = {}
        if not df.empty and days_to_predict > 0:
            run_rate = df['y'].tail(7).mean()
            fallback_date = cutoff_date_obj + timedelta(days=1)
            for _ in range(days_to_predict):
                future_forecasts[fallback_date.strftime("%Y-%m-%d")] = run_rate
                fallback_date += timedelta(days=1)

    # Create dict mapping for upper bound of prediction interval
    anomaly_thresholds = {}
    if not fitted_df.empty:
        hi_cols = [c for c in fitted_df.columns if c.endswith('-hi-95')]
        if hi_cols:
            hi_col = hi_cols[0]
            for _, row in fitted_df.iterrows():
                anomaly_thresholds[row['ds'].strftime("%Y-%m-%d")] = row[hi_col]

    # Map forecast values { ds_str: forecast_y }
    # Only map from forecast_df if no fallback was used
    if 'future_forecasts' not in locals() or not future_forecasts:
        future_forecasts = {}
        if not forecast_df.empty:
            pred_cols = [c for c in forecast_df.columns if 'AutoETS' in c and not '-' in c]
            if pred_cols:
                pred_col = pred_cols[0]
                for _, row in forecast_df.iterrows():
                    future_forecasts[row['ds'].strftime("%Y-%m-%d")] = row[pred_col]
            
    budget_amount = costs_crud.get_budget(cursor, scope_id, active_tags, base_date)

    return _build_response_payload(
        base_date=base_date,
        num_days=num_days,
        cutoff_day=cutoff_day,
        cost_dict=cost_dict,
        future_forecasts=future_forecasts,
        budget_amount=budget_amount,
        anomaly_thresholds=anomaly_thresholds
    )

