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
