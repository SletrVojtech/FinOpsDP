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

def test_dashboard_status(client):
    """Test the main dashboard page."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

def test_get_scope_view(client, mock_cursor, override_db, mocker):
    """Test partial scope view rendering."""
    # Mocking entities calls
    mocker.patch("crud.entities.get_chain", return_value=[{"id": 1, "name": "Root"}])
    mocker.patch("crud.entities.get_scoped_top_tags", return_value=[])
    mocker.patch("crud.entities.get_dynamic_items", return_value=[])
    
    response = client.get("/ui/scope/1?tag_env=prod")
    
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_view_chargeback_dashboard(client, mock_cursor, override_db, mocker):
    """Test chargeback dashboard page."""
    mocker.patch("crud.entities.get_scoped_top_tags", return_value=[])
    
    response = client.get("/ui/chargeback?scope_id=1")
    
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

def test_cluster_cost_detail_json(client, mock_cursor, override_db, mocker):
    """Test cluster cost detail with AJAX JSON response."""
    # Mocking cluster name query
    mock_cursor.fetchone.return_value = ["MyCluster"]
    
    # Mocking services
    mocker.patch("routers.web_router.costs_service.calculate_chargeback_forecast", return_value={
        "labels": ["2026-03-01"],
        "actual_daily": [10.0]
    })
    mocker.patch("routers.web_router.get_daily_namespace_allocation", return_value={"data": "mocked"})
    
    # Requesting JSON via Accept header
    response = client.get("/ui/clusters/1/costs", headers={"Accept": "application/json"})
    
    assert response.status_code == 200
    assert response.json()["month"] is not None
    assert response.json()["chart_data"] == {"data": "mocked"}
