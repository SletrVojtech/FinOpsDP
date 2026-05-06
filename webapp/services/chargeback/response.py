import logging
from datetime import date

logger = logging.getLogger(__name__)


def _make_anomaly_entry(date_str: str, daily_cost: float, thresh_data) -> dict:
    """Normalises anomaly threshold data into a unified anomaly object."""
    if isinstance(thresh_data, dict):          # from CostAnomalies DB record
        is_anom = thresh_data["actual"] > thresh_data["threshold"] and thresh_data["actual"] > 4.0
        return {"date": date_str, "is_anomaly": is_anom,
                "actual": round(thresh_data["actual"], 2),
                "threshold": round(thresh_data["threshold"], 2),
                "delta": round(thresh_data["delta"], 2),
                "type": "spike"}
    elif thresh_data is not None:              # scalar upper-bound from AutoETS fitted values
        thresh_f = float(thresh_data)
        is_anom = daily_cost > thresh_f and daily_cost > 4.0
        return {"date": date_str, "is_anomaly": is_anom,
                "actual": round(daily_cost, 2),
                "threshold": round(thresh_f, 2),
                "delta": round(max(0.0, daily_cost - thresh_f), 2),
                "type": "spike"}
    return {"date": date_str, "is_anomaly": False,
            "actual": round(daily_cost, 2), "threshold": None, "delta": 0.0}


def _limit_breakdown_categories(breakdown_dict: dict, top_n: int = 5) -> dict:
    """ Groups all but top N categories into 'other'. """
    # If there are already few enough categories, just return
    if len(breakdown_dict) <= top_n:
        return breakdown_dict
    
    # Calculate total cost for each category for sorting
    totals = {}
    for cat, daily_costs in breakdown_dict.items():
        totals[cat] = sum(daily_costs.values())
        
    # Sort categories by total cost descending
    sorted_cats = sorted(totals.keys(), key=lambda x: totals[x], reverse=True)
    
    top_cats_list = sorted_cats[:top_n]
    
    new_breakdown = {cat: breakdown_dict[cat] for cat in top_cats_list}
    
    other_combined = {}
    for cat in sorted_cats[top_n:]:
        for d_str, cost in breakdown_dict[cat].items():
            other_combined[d_str] = other_combined.get(d_str, 0.0) + cost
            
    if other_combined:
        if "other" in new_breakdown:
            # If 'other' was already in top N, merge the rest into it
            existing_other = new_breakdown["other"].copy()
            for d_str, cost in other_combined.items():
                existing_other[d_str] = existing_other.get(d_str, 0.0) + cost
            new_breakdown["other"] = existing_other
        else:
            new_breakdown["other"] = other_combined
            
    return new_breakdown


def _build_response_payload(
    base_date, num_days, cutoff_day, cost_dict, future_forecasts, budget_amount, projected_total, anomaly_thresholds, breakdown_dict
) -> dict:
    """Consolidates cost and forecast data into a response dictionary for the UI."""
    # Limit to top 5 categories to decrease cluttering
    breakdown_dict = _limit_breakdown_categories(breakdown_dict, top_n=5)
    
    breakdown_arrays: dict[str, list] = {cat: [] for cat in breakdown_dict}

    labels, actual_daily, actual_cumulative, forecast_cumulative, anomalies = [], [], [], [], []
    cumulative_sum, actual_cumulative_sum = 0, 0

    for day in range(1, num_days + 1):
        current_date = date(base_date.year, base_date.month, day)
        date_str = current_date.isoformat()
        labels.append(date_str)
        for cat, arr in breakdown_arrays.items():
            arr.append(round(breakdown_dict[cat].get(date_str, 0.0), 2) if day <= cutoff_day else None)
        # If the day is within the actual data range, use actual data
        if day <= cutoff_day:
            daily_cost = cost_dict.get(date_str, 0.0)
            actual_cumulative_sum += daily_cost
            cumulative_sum += daily_cost
            actual_daily.append(round(daily_cost, 2))
            actual_cumulative.append(round(actual_cumulative_sum, 2))
            forecast_cumulative.append(None)
            anomalies.append(_make_anomaly_entry(date_str, daily_cost,
                                                 anomaly_thresholds.get(date_str)))
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
            anomalies.append({"date": date_str, "is_anomaly": False,
                               "actual": None, "threshold": None, "delta": 0.0})

    return {
        "month": f"{base_date.year}-{base_date.month:02d}",
        "projected_total": projected_total if projected_total is not None else round(cumulative_sum, 2),
        "labels": labels,
        "actual_daily": actual_daily,
        "actual_cumulative": actual_cumulative,
        "forecast_cumulative": forecast_cumulative,
        "anomalies": anomalies,
        "budget": budget_amount,
        "breakdown_by_category": breakdown_arrays,
    }
