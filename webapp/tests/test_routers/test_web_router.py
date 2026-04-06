import pytest
from main import app
from db.database import get_db_cursor
from datetime import datetime
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

def test_view_tag_values(client, mock_cursor, override_db, mocker):
    """Test /ui/tag_values endpoint for dynamic filter buttons."""
    mocker.patch("crud.entities.get_scoped_tag_values", return_value=[{"value": "val1", "count": 10}, {"value": "val2", "count": 5}])
    response = client.get("/ui/tag_values?scope_id=1&tag_key=env")
    assert response.status_code == 200
    assert "val1" in response.text
    assert "val2" in response.text

def test_view_krr_dashboard(client, mock_cursor, override_db, mocker):
    """Test /ui/krr endpoint."""
    mocker.patch("crud.krr.get_krr_clusters", return_value=[{"cluster_id": 1, "cluster_name": "Cluster1", "latest_scan": datetime(2024, 1, 1)}])
    response = client.get("/ui/krr")
    assert response.status_code == 200
    assert "Cluster1" in response.text

def test_view_krr_detail(client, mock_cursor, override_db, mocker):
    """Test /ui/krr/{cluster_id} endpoint."""
    mocker.patch("crud.krr.get_cluster_name", return_value="Cluster1")
    mocker.patch("crud.krr.get_krr_recommendations_for_cluster", return_value=[
        {"namespace": "ns1", "currentcpurequest": 1000, "recommendedcpurequest": 500,
         "currentmemoryrequest": 1024, "recommendedmemoryrequest": 512}
    ])
    response = client.get("/ui/krr/1")
    assert response.status_code == 200
    assert "Cluster1" in response.text
    assert "ns1" in response.text

def test_view_metrics_dashboard_404(client, mock_cursor, override_db):
    """Entity not found returns 404."""
    mock_cursor.fetchone.return_value = None
    response = client.get("/ui/metrics/999")
    assert response.status_code == 404
    assert "Entity not found" in response.json()["detail"]

def test_list_clusters(client, mock_cursor, override_db):
    """Test /ui/clusters endpoint."""
    mock_cursor.fetchall.return_value = [[1, "Cluster1"]]
    response = client.get("/ui/clusters")
    assert response.status_code == 200
    assert "Cluster1" in response.text

