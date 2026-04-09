import pytest
from main import app
from db.database import get_db_cursor
from unittest.mock import MagicMock

@pytest.fixture
def override_db(mock_cursor):
    """Override the DB dependency to use the mock_cursor fixture."""
    app.dependency_overrides[get_db_cursor] = lambda: mock_cursor
    yield
    app.dependency_overrides.clear()

def test_get_roots(client, mock_cursor, override_db, mocker):
    """Test /api/v1/roots endpoint."""
    # Mocking entities.get_roots
    mock_get_roots = mocker.patch("crud.entities.get_roots")
    mock_get_roots.return_value = [{"id": 1, "name": "Root"}]
    
    response = client.get("/api/v1/roots")
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["data"] == [{"id": 1, "name": "Root"}]
    mock_get_roots.assert_called_once_with(mock_cursor)

def test_get_chargeback_data(client, mock_cursor, override_db, mocker):
    """Test /api/v1/costs/chargeback endpoint."""
    # Mocking cost_service.get_chargeback_dashboard_data
    mock_get_data = mocker.patch("services.cost_service.get_chargeback_dashboard_data")
    mock_get_data.return_value = {"month": "2026-03", "projected_total": 500.0}
    
    mocker.patch("routers.api_router.extract_active_tags", return_value={})
    
    response = client.get("/api/v1/costs/chargeback?scope_id=1&target_month=2026-03")
    
    assert response.status_code == 200
    assert response.json()["month"] == "2026-03"
    assert response.json()["projected_total"] == 500.0
    mock_get_data.assert_called_once_with(mock_cursor, 1, {}, "2026-03", None)

def test_set_budget(client, mock_cursor, override_db, mocker):
    """Test /api/v1/costs/budget endpoint."""
    # Mocking cost.set_budget
    mock_set_budget = mocker.patch("crud.costs.set_budget")
    mocker.patch("routers.api_router.extract_active_tags", return_value={})
    
    payload = {"amount": 1000.0}
    response = client.post("/api/v1/costs/budget?scope_id=1&target_month=2026-03", json=payload)
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["amount"] == 1000.0
    # verify commit was called on mock_cursor.connection
    mock_cursor.connection.commit.assert_called_once()

def test_api_get_children(client, mock_cursor, override_db, mocker):
    """Test /api/v1/children/{parent_id} endpoint."""
    mock_get_children = mocker.patch("crud.entities.get_children", return_value=[{"id": 2, "name": "Child"}])
    response = client.get("/api/v1/children/1")
    assert response.status_code == 200
    assert response.json()["data"][0]["name"] == "Child"

def test_api_get_available_metrics(client, mock_cursor, override_db, mocker):
    """Test /api/v1/metrics/{entity_id}/available endpoint."""
    mock_get_metrics = mocker.patch("crud.metrics.get_available_metric_names", return_value=["cpu", "mem"])
    response = client.get("/api/v1/metrics/1/available")
    assert response.status_code == 200
    assert "cpu" in response.json()["available_metrics"]

def test_api_get_metric_data(client, mock_cursor, override_db, mocker):
    """Test /api/v1/metrics/{entity_id}/data endpoint."""
    mock_data = [{"timestamp": "2024-01-01T00:00:00", "value": 50.0}]
    mock_get_data = mocker.patch("crud.metrics.get_metric_data", return_value=mock_data)
    
    response = client.get("/api/v1/metrics/1/data?metric_name=cpu&time_range=24 hours&granularity=1 hour")
    
    assert response.status_code == 200
    assert response.json()["data_points"] == mock_data
    mock_get_data.assert_called_once_with(mock_cursor, 1, "cpu", "24 hours", "1 hour")

def test_api_add_allocation(client, mock_cursor, override_db, mocker):
    """Test POST /api/v1/allocations endpoint."""
    mock_add = mocker.patch("crud.allocations.add_allocation_rule")
    payload = {
        "rule_name": "Test Rule",
        "source_tags": {"env": "prod"},
        "target_tags": {"team": "data"},
        "percentage": 50.0
    }
    response = client.post("/api/v1/allocations", json=payload)
    assert response.status_code == 200
    mock_add.assert_called_once()
    mock_cursor.connection.commit.assert_called_once()

def test_api_delete_allocation(client, mock_cursor, override_db, mocker):
    """Test DELETE /api/v1/allocations/{rule_id} endpoint."""
    mock_delete = mocker.patch("crud.allocations.delete_allocation_rule")
    response = client.delete("/api/v1/allocations/10")
    assert response.status_code == 200
    mock_delete.assert_called_once_with(mock_cursor, 10)

def test_api_get_downsizing_recommendation(client, mock_cursor, override_db, mocker):
    """Test /api/v1/downsizing/{entity_id} endpoint."""
    mock_eval = mocker.patch("services.downsizing.evaluate_downsizing", return_value={"status": "success", "action": "none"})
    response = client.get("/api/v1/downsizing/1?analysis_days=7&target_cpu=50.0")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_eval.assert_called_once()


def test_api_get_anomalies(client, mock_cursor, override_db, mocker):
    """Test GET /api/v1/anomalies endpoint."""
    mock_data = [{"id": 1, "type": "cost", "date": "2024-04-01"}]
    mock_get = mocker.patch("crud.costs.get_dashboard_anomalies", return_value=mock_data)
    
    response = client.get("/api/v1/anomalies?only_unseen=true")
    
    assert response.status_code == 200
    assert response.json()["data"] == mock_data
    mock_get.assert_called_once()

def test_api_mark_anomaly_seen(client, mock_cursor, override_db, mocker):
    """Test POST /api/v1/anomalies/{id}/seen endpoint."""
    mock_mark = mocker.patch("crud.costs.mark_anomaly_seen")
    
    response = client.post("/api/v1/anomalies/123/seen")
    
    assert response.status_code == 200
    mock_mark.assert_called_once_with(mock_cursor, 123)
    mock_cursor.connection.commit.assert_called_once()


