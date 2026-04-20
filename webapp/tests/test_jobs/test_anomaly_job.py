import pytest
from jobs.fbad_worker.anomaly_job import run_anomaly_job
from unittest.mock import MagicMock, patch
from datetime import date

@patch("jobs.fbad_worker.anomaly_job.get_db_cursor")
@patch("jobs.fbad_worker.anomaly_job.costs_crud.get_active_budgets_scopes")
@patch("jobs.fbad_worker.anomaly_job.ForecastModel")
@patch("jobs.fbad_worker.anomaly_job.cost_service.get_aggregated_daily_costs")
@patch("jobs.fbad_worker.anomaly_job.costs_crud.save_forecast_snapshot")
@patch("jobs.fbad_worker.anomaly_job.costs_crud.save_anomalies")
@patch("jobs.fbad_worker.anomaly_job.costs_crud.get_max_date")
@patch("jobs.fbad_worker.anomaly_job.costs_crud.get_budget")
def test_run_anomaly_job(
    mock_get_budget,
    mock_get_max_date,
    mock_save_anomalies, 
    mock_save_forecast, 
    mock_get_costs, 
    mock_model_class, 
    mock_get_scopes, 
    mock_get_db
):
    """Test the anomaly job orchestration with mocked components."""
    # Setup DB mock
    mock_cursor = MagicMock()
    mock_get_db.return_value = iter([mock_cursor])
    
    # Setup Scopes
    mock_get_scopes.return_value = [{"scope_id": 1, "tags": {"team": "it"}}]
    
    # Setup Max Date
    mock_get_max_date.return_value = [date(2026, 3, 15)]
    
    # Setup Model
    mock_model_instance = mock_model_class.return_value
    mock_model_instance.process.return_value = {
        "future_forecasts": {"2026-03-31": 150.0},
        "anomalies": [{"date": "2026-03-10", "actual": 100.0, "predicted": 50.0, "threshold": 80.0, "delta": 50.0}]
    }
    
    # Setup Costs
    mock_get_costs.return_value = {"2026-03-01": 10.0}
    
    # Setup Budget
    mock_get_budget.return_value = 50.0  # Threshold
    
    
    # Act
    run_anomaly_job()
    
    # Assert
    # Check that model was called
    assert mock_model_instance.process.called
    # Check that results were saved
    assert mock_save_forecast.called
    assert mock_save_anomalies.called
    
    # Verify budget anomaly was generated and passed to save_anomalies
    saved_anomalies = mock_save_anomalies.call_args[0][3]
    budget_anomalies = [a for a in saved_anomalies if a.get("type") == "budget"]
    # 2 anomalies, one as end of month and one for when the overrun happened.
    assert len(budget_anomalies) == 2
    assert budget_anomalies[0]["date"] == "2026-03-31"
    
    # Check that commit was called
    assert mock_cursor.connection.commit.called

@patch("jobs.fbad_worker.anomaly_job.get_db_cursor")
@patch("jobs.fbad_worker.anomaly_job.costs_crud.get_active_budgets_scopes")
def test_run_anomaly_job_no_scopes(mock_get_scopes, mock_get_db):
    """Test job exit when no scopes are found."""
    mock_cursor = MagicMock()
    mock_get_db.return_value = iter([mock_cursor])
    mock_get_scopes.return_value = []
    
    run_anomaly_job()
    
    assert mock_cursor.execute.called is False # Should not proceed beyond scope check
