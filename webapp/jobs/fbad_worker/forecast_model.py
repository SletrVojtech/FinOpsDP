import logging
import pandas as pd
from datetime import date, timedelta
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA

logger = logging.getLogger(__name__)

class ForecastModel:
    """
    Wrapper for AutoARIMA calculations.
    Computing forecasts and anomalies.
    """
    def __init__(self, season_length: int = 7, min_data_points: int = 14):
        self.season_length = season_length
        self.min_data_points = min_data_points
        self.model = StatsForecast(
            models=[AutoARIMA(season_length=self.season_length)],
            freq='D'
        )

    def process(self, df_data: list, days_to_predict: int, cutoff_date: date) -> dict:
        """
        Runs the AutoARIMA forecast and evaluates anomalies on historical fitted data.
        Returns a dictionary with future forecasted daily sums and actual detected anomalies.
        """
        df = pd.DataFrame(df_data)
        
        if df.empty or len(df) < self.min_data_points:
            logger.warning(f"Not enough data for AutoARIMA (found {len(df)}, required {self.min_data_points}). Skipping ML calculation.")
            return {
                "future_forecasts": {},
                "anomalies": [],
                "target_projected_total": 0.0
            }

        df['ds'] = pd.to_datetime(df['ds'])

        h_val = max(1, days_to_predict)
        
        try:
            forecast_df = self.model.forecast(df=df, h=h_val, level=[95], fitted=True)
            fitted_df = self.model.forecast_fitted_values()
        except Exception as e:
            logger.error(f"AutoARIMA calculation failed: {str(e)}")
            return {"future_forecasts": {}, "anomalies": [], "target_projected_total": 0.0}

        # Analyze anomalies from fitted bounds
        anomalies = []
        if not fitted_df.empty:
            hi_cols = [c for c in fitted_df.columns if c.endswith('-hi-95')]
            fitted_cols = [c for c in fitted_df.columns if 'AutoARIMA' in c and not '-' in c]
            
            if hi_cols and fitted_cols:
                hi_col = hi_cols[0]
                pred_col = fitted_cols[0]
                
                # Merge original DF with fitted DF to compare Actual vs Expected
                # Drop 'y' from fitted_df if it exists to avoid overlapping columns
                merged = df.merge(fitted_df.drop(columns=['y'], errors='ignore'), on=['unique_id', 'ds'], how='inner')
                
                for _, row in merged.iterrows():
                    actual = row['y']
                    predicted = max(0.0, row[pred_col])
                    thresh = row[hi_col]
                    
                    delta = actual - predicted
                    
                    # Detect significant deviations
                    if actual > thresh and delta > 10.0:
                        anomalies.append({
                            "date": row['ds'].strftime("%Y-%m-%d"),
                            "actual": float(actual),
                            "predicted": float(predicted),
                            "threshold": float(thresh),
                            "delta": float(delta)
                        })

        # Process future forecasts
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
