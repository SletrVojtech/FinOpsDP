"""
Forecast Model Module.

This module provides the ForecastModel class, which uses AutoARIMA to generate
cost forecasts and detect anomalies in historical cost data.
"""

import logging
from datetime import date
from typing import List, Dict, Any, Tuple

import pandas as pd
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA

logger = logging.getLogger(__name__)


class ForecastModel:
    """
    Wrapper for AutoARIMA calculations to compute forecasts and detect anomalies.

    Uses the StatsForecast library to fit a seasonal ARIMA model to daily 
    cost data and identify deviations that exceed the 95% confidence interval.
    """
    def __init__(self, season_length: int = 7, min_data_points: int = 14):
        """
        Initialize the forecast model.

        Args:
            season_length (int, optional): The expected seasonality period (e.g., 7 for weekly). 
                Defaults to 7.
            min_data_points (int, optional): Minimum historical points required for fitting. 
                Defaults to 14.
        """
        self.season_length = season_length
        self.min_data_points = min_data_points
        self.model = StatsForecast(
            models=[AutoARIMA(season_length=self.season_length)],
            freq='D'
        )

    def process(self, df_data: List[Dict[str, Any]], days_to_predict: int, cutoff_date: date) -> Dict[str, Any]:
        """
        Runs the AutoARIMA forecast and evaluates anomalies on historical fitted data.

        Args:
            df_data (List[Dict[str, Any]]): Historical cost data (must contain 'ds', 'y', 'unique_id').
            days_to_predict (int): Number of future days to forecast.
            cutoff_date (date): The end date of actual historical data.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - future_forecasts (Dict[str, float]): Map of date strings to forecasted values.
                - anomalies (List[Dict[str, Any]]): List of detected anomalies with delta and threshold.
        """
        df = pd.DataFrame(df_data)
        
        # Check if we have enough data to produce a reliable model
        if df.empty or len(df) < self.min_data_points:
            logger.warning(
                f"Not enough data for AutoARIMA (found {len(df)}, required {self.min_data_points}). "
                "Skipping calculation."
            )
            return {
                "future_forecasts": {},
                "anomalies": [],
            }

        df['ds'] = pd.to_datetime(df['ds'])

        # Ensure we predict at least 1 day
        h_val = max(1, days_to_predict)
        
        try:
            # Fit model and generate forecasts with 95% confidence intervals
            forecast_df = self.model.forecast(df=df, h=h_val, level=[95], fitted=True)
            fitted_df = self.model.forecast_fitted_values()
        except Exception as e:
            logger.error(f"AutoARIMA calculation failed: {str(e)}", exc_info=True)
            return {"future_forecasts": {}, "anomalies": []}

        # Identify anomalies from historical fitted data
        anomalies = []
        if not fitted_df.empty:
            # Dynamic column identification for StatsForecast output
            hi_cols = [c for c in fitted_df.columns if c.endswith('-hi-95')]
            fitted_cols = [c for c in fitted_df.columns if 'AutoARIMA' in c and not '-' in c]
            
            if hi_cols and fitted_cols:
                hi_col = hi_cols[0]
                pred_col = fitted_cols[0]
                
                # Merge original values with fitted values to find deviations
                merged = df.merge(
                    fitted_df.drop(columns=['y'], errors='ignore'), 
                    on=['unique_id', 'ds'], 
                    how='inner'
                )
                
                for _, row in merged.iterrows():
                    actual = row['y']
                    predicted = max(0.0, row[pred_col])
                    thresh = row[hi_col]
                    
                    delta = actual - predicted
                    
                    # Anomaly defined as actual > 95th percentile AND a significant absolute delta
                    if actual > thresh and delta > 5.0:
                        anomalies.append({
                            "date": row['ds'].strftime("%Y-%m-%d"),
                            "actual": float(actual),
                            "predicted": float(predicted),
                            "threshold": float(thresh),
                            "delta": float(delta)
                        })

        # Format future forecasts for the consumer
        future_forecasts = {}
        if days_to_predict > 0 and not forecast_df.empty:
            pred_cols = [c for c in forecast_df.columns if 'AutoARIMA' in c and not '-' in c]
            if pred_cols:
                pred_col = pred_cols[0]
                for _, row in forecast_df.iterrows():
                    future_forecasts[row['ds'].strftime("%Y-%m-%d")] = float(row[pred_col])
                    
        return {
            "future_forecasts": future_forecasts,
            "anomalies": anomalies
        }
