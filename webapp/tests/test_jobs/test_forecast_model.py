import pytest
import pandas as pd
from datetime import date
from jobs.fbad_worker.forecast_model import ForecastModel
from unittest.mock import MagicMock

def test_forecast_model_insufficient_data():
    """Test behavior when data points are below minimum."""
    model = ForecastModel(min_data_points=10)
    # 5 data points
    df_data = [{"ds": date(2026, 3, i), "y": 10.0, "unique_id": "total"} for i in range(1, 6)]
    
    result = model.process(df_data, 5, date(2026, 3, 5))
    
    assert result["future_forecasts"] == {}
    assert result["anomalies"] == []

def test_forecast_model_process_success(mocker):
    """Test successful forecast and anomaly detection with mocked StatsForecast."""
    # Mocking StatsForecast inside ForecastModel
    mock_sf_class = mocker.patch("jobs.fbad_worker.forecast_model.StatsForecast")
    mock_sf_instance = mock_sf_class.return_value
    
    # 15 data points (to satisfy min_data_points=14)
    df_data = [{"ds": date(2026, 3, i), "y": 10.0, "unique_id": "total"} for i in range(1, 16)]
    
    # Mock forecast result
    forecast_df = pd.DataFrame({
        "ds": [pd.Timestamp(2026, 3, 16)],
        "AutoARIMA": [12.0],
        "unique_id": ["total"]
    })
    mock_sf_instance.forecast.return_value = forecast_df
    
    # Mock fitted values (anomaly detection)
    # Day 10 will be an anomaly: Actual 100.0 vs High-95 50.0
    fitted_df = pd.DataFrame({
        "ds": [pd.Timestamp(2026, 3, i) for i in range(1, 16)],
        "AutoARIMA": [10.0] * 15,
        "AutoARIMA-hi-95": [20.0] * 15,
        "unique_id": ["total"] * 15
    })
    fitted_df.loc[9, "AutoARIMA-hi-95"] = 50.0 # Day 10 threshold
    df_data[9]["y"] = 100.0 # Day 10 actual
    
    mock_sf_instance.forecast_fitted_values.return_value = fitted_df
    
    model = ForecastModel()
    result = model.process(df_data, 1, date(2026, 3, 15))
    
    # Future forecasts
    assert result["future_forecasts"]["2026-03-16"] == 12.0
    
    # Anomalies
    assert len(result["anomalies"]) == 1
    assert result["anomalies"][0]["date"] == "2026-03-10"
    assert result["anomalies"][0]["actual"] == 100.0
    assert result["anomalies"][0]["threshold"] == 50.0
    assert result["anomalies"][0]["delta"] == 90.0 # 100 - 10 (predicted)
