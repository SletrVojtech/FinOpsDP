# web_app/services/cost_service.py
import calendar
from datetime import date
from crud import costs as costs_crud

def calculate_chargeback_forecast(cursor, scope_id: int, active_tags: dict, target_month: str = None) -> dict:
    """
    Calculates monthly spend and creates a Run-Rate forcast with a 7 day window.
    Based on
    """
    # Get month
    if target_month:
        year, month = map(int, target_month.split('-'))
        base_date = date(year, month, 1)
    else:
        base_date = date.today().replace(day=1) 

    # Get daily data from DB
    raw_data = costs_crud.get_daily_costs(cursor, scope_id, active_tags, base_date)
    cost_dict = {row["date"]: row["cost"] for row in raw_data}

    _, num_days = calendar.monthrange(base_date.year, base_date.month)
    # How many days have to be forecasted
    if raw_data:
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

    return {
        "month": f"{base_date.year}-{base_date.month:02d}",
        "projected_total": round(cumulative_sum, 2),
        "labels": labels,
        "actual_daily": actual_daily,
        "actual_cumulative": actual_cumulative,
        "forecast_cumulative": forecast_cumulative
    }