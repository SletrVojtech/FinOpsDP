import calendar
import logging
from datetime import date, timedelta, datetime

import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoETS

from crud import costs as costs_crud
from services.chargeback.aggregation import (
    get_aggregated_daily_costs,
    get_aggregated_daily_costs_by_category,
    get_aggregated_daily_costs_by_tag_key,
)
from services.chargeback.response import _build_response_payload

logger = logging.getLogger(__name__)


def _prepare_dates_and_cutoff(cursor, target_month: str = None):
    """Prepare date interval and actual data cutoff for the given month"""
    SAFE_DAYS_TO_SUBTRACT = 1
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


def get_chargeback_dashboard_data(cursor, scope_id: int, active_tags: dict, 
                                  target_month: str = None, group_by_tag: str = None) -> dict:
    """
    Main entry point for UI. Attempt to load pre-calculated AutoARIMA data from DB.
    """
    base_date, start_date, end_date, num_days, cutoff_date_obj, cutoff_day = _prepare_dates_and_cutoff(cursor, target_month)
    
    latest = costs_crud.get_latest_forecast(cursor, scope_id, active_tags, base_date)

    if not latest or not latest.get('daily_forecasts'):
        return calculate_chargeback_forecast(cursor, scope_id, active_tags, target_month, group_by_tag)
        
    budget_amount = costs_crud.get_budget(cursor, scope_id, active_tags, base_date)
    cost_dict = get_aggregated_daily_costs(cursor, scope_id, active_tags, start_date=start_date, end_date=end_date)
    anomaly_thresholds = costs_crud.get_anomalies_for_month(cursor, scope_id, active_tags, start_date, end_date)
    
    if group_by_tag:
        breakdown_dict = get_aggregated_daily_costs_by_tag_key(cursor, scope_id, active_tags, group_by_tag, start_date=start_date, end_date=end_date)
    else:
        breakdown_dict = get_aggregated_daily_costs_by_category(cursor, scope_id, active_tags, start_date=start_date, end_date=end_date)

    return _build_response_payload(
        base_date=base_date,
        num_days=num_days,
        cutoff_day=cutoff_day,
        cost_dict=cost_dict,
        future_forecasts=latest.get('daily_forecasts', {}),
        budget_amount=budget_amount,
        projected_total=latest.get("projected_amount"),
        anomaly_thresholds=anomaly_thresholds,
        breakdown_dict=breakdown_dict
    )


def calculate_chargeback_forecast(cursor, scope_id: int, active_tags: dict, 
                                  target_month: str = None, group_by_tag: str = None) -> dict:
    """
    Calculates monthly spend and creates a forecast with StatsForecast.
    """
    base_date, start_date, end_date, num_days, cutoff_date_obj, cutoff_day = _prepare_dates_and_cutoff(cursor, target_month)

    # Get history
    history_start = start_date - timedelta(days=35)
    cost_dict = get_aggregated_daily_costs(cursor, scope_id, active_tags, start_date=history_start, end_date=end_date)
    if group_by_tag:
        breakdown_dict = get_aggregated_daily_costs_by_tag_key(cursor, scope_id, active_tags, group_by_tag, start_date=start_date, end_date=end_date)
    else:
        breakdown_dict = get_aggregated_daily_costs_by_category(cursor, scope_id, active_tags, start_date=start_date, end_date=end_date)

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
    future_forecasts = {}
    ml_success = False
    forecast_df = pd.DataFrame()
    fitted_df = pd.DataFrame()

    # Predict enough days to reach the end_date of the target month
    days_to_predict = (end_date - cutoff_date_obj).days if (cost_dict and cutoff_date_obj) else num_days

    try:
        sf = StatsForecast(

            models=[AutoETS(season_length=7)],
            freq='D'
        )

        if df.empty:
            raise ValueError("No data")
        sf.fit(df=df)
        
        ml_success = True
        
        # Always predict at least 1 day to force sf.forecast to cache fitted values
        h_val = max(1, days_to_predict)
        forecast_df = sf.forecast(df=df, h=h_val, level=[95], fitted=True)
        fitted_df = sf.forecast_fitted_values()
        
        # If prediction wasn't needed, drop the future forecast
        if days_to_predict <= 0:
            forecast_df = pd.DataFrame()
       
    except Exception as e:
        # Log the failure for StatsForecast
        logger.error("StatsForecast failed, using SMA fallback: %s", scope_id)
        ml_success = False
        forecast_df = pd.DataFrame()
        fitted_df = pd.DataFrame()
        
        # Manually create flat future forecasts as fallback
        if not df.empty and days_to_predict > 0:
            run_rate = df['y'].tail(7).mean()
            fallback_date = cutoff_date_obj + timedelta(days=1)
            for _ in range(days_to_predict):
                future_forecasts[fallback_date.strftime("%Y-%m-%d")] = run_rate
                fallback_date += timedelta(days=1)


    # Create dict mapping for upper bound of prediction interval
    anomaly_thresholds = {}
    if not fitted_df.empty:
        hi_cols = [c for c in fitted_df.columns if c.lower().endswith('-hi-95')]
        if hi_cols:
            hi_col = hi_cols[0]
            for _, row in fitted_df.iterrows():
                anomaly_thresholds[row['ds'].strftime("%Y-%m-%d")] = row[hi_col]

    # Map forecast values { ds_str: forecast_y }
    # Only map from forecast_df if no fallback was used
    if not future_forecasts:

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
        projected_total=None,
        anomaly_thresholds=anomaly_thresholds,
        breakdown_dict=breakdown_dict
    )
