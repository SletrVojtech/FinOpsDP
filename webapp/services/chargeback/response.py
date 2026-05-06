"""
Chargeback Response Module.

This module provides helper functions for building the dashboard API
response payload from raw cost and forecast data. It handles anomaly
entry normalisation and service-category limiting.
"""

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def _make_anomaly_entry(date_str: str, daily_cost: float, thresh_data) -> dict:
    """Normalise anomaly threshold data into a unified anomaly object.

    Accepts either a dict (from a persisted ``CostAnomalies`` record) or
    a scalar upper bound (from AutoETS fitted values). Returns a plain
    no-anomaly object when no threshold data is available.

    Args:
        date_str (str): ISO date string for the entry.
        daily_cost (float): Actual observed daily cost in EUR.
        thresh_data: One of:
            - ``dict`` with keys ``actual``, ``threshold``, ``delta`` from a
              persisted anomaly record.
            - ``float`` scalar representing the AutoETS 95th-percentile upper bound.
            - ``None`` when no threshold is available.

    Returns:
        dict: Anomaly object with keys ``date``, ``is_anomaly``, ``actual``,
            ``threshold``, ``delta``, and optionally ``type``.
    """
    if isinstance(thresh_data, dict):          # from CostAnomalies DB record
        is_anom = thresh_data["actual"] > thresh_data["threshold"] and thresh_data["actual"] > 4.0
        return {
            "date": date_str,
            "is_anomaly": is_anom,
            "actual": round(thresh_data["actual"], 2),
            "threshold": round(thresh_data["threshold"], 2),
            "delta": round(thresh_data["delta"], 2),
            "type": "spike",
        }
    elif thresh_data is not None:              # scalar upper-bound from AutoETS fitted values
        thresh_f = float(thresh_data)
        is_anom = daily_cost > thresh_f and daily_cost > 4.0
        return {
            "date": date_str,
            "is_anomaly": is_anom,
            "actual": round(daily_cost, 2),
            "threshold": round(thresh_f, 2),
            "delta": round(max(0.0, daily_cost - thresh_f), 2),
            "type": "spike",
        }
    return {"date": date_str, "is_anomaly": False, "actual": round(daily_cost, 2), "threshold": None, "delta": 0.0}


def _limit_breakdown_categories(breakdown_dict: dict, top_n: int = 5) -> dict:
    """Reduce a category breakdown to the top N categories by total cost.

    All categories beyond the top N are merged into an ``'other'`` bucket.
    If ``'other'`` is already among the top N, the overflow costs are
    merged into it rather than creating a duplicate key.

    Args:
        breakdown_dict (dict): Nested mapping ``{category : {date_str : cost}}``.
        top_n (int, optional): Maximum number of distinct categories to keep.
            Defaults to 5.

    Returns:
        dict: Reduced breakdown with at most ``top_n + 1`` categories.
    """
    if len(breakdown_dict) <= top_n:
        return breakdown_dict

    totals = {cat: sum(daily_costs.values()) for cat, daily_costs in breakdown_dict.items()}
    sorted_cats = sorted(totals.keys(), key=lambda x: totals[x], reverse=True)

    top_cats_list = sorted_cats[:top_n]
    new_breakdown = {cat: breakdown_dict[cat] for cat in top_cats_list}

    other_combined: dict = {}
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
    base_date: date,
    num_days: int,
    cutoff_day: int,
    cost_dict: dict,
    future_forecasts: dict,
    budget_amount: Optional[float],
    projected_total: Optional[float],
    anomaly_thresholds: dict,
    breakdown_dict: dict,
) -> dict:
    """Assemble the final chargeback dashboard response dictionary.

    Iterates over every day in the month, filling ``actual_daily`` and
    ``actual_cumulative`` up to ``cutoff_day``, then switching to
    ``forecast_cumulative`` for remaining days. Anomaly entries are generated
    for each actual day using :func:`_make_anomaly_entry`.

    Args:
        base_date (date): First day of the target month.
        num_days (int): Number of days in the target month.
        cutoff_day (int): Day-of-month index of the last confirmed cost day
            (0 means no actual data exists for the month).
        cost_dict (dict): Mapping of ISO date strings to actual daily costs.
        future_forecasts (dict): Mapping of ISO date strings to forecast values.
        budget_amount (float, optional): Configured monthly budget in EUR.
        projected_total (float, optional): Pre-calculated projected total; when
            ``None`` the running cumulative sum is used instead.
        anomaly_thresholds (dict): Mapping of date strings to threshold values.
        breakdown_dict (dict): Nested ``{category : {date_str : cost}}``
            mapping used for the category breakdown chart.

    Returns:
        dict: Payload with keys ``month``, ``projected_total``, ``labels``,
            ``actual_daily``, ``actual_cumulative``, ``forecast_cumulative``,
            ``anomalies``, ``budget``, and ``breakdown_by_category``.
    """
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
