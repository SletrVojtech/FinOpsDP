import pytest
from crud.krr import get_krr_clusters, get_krr_recommendations_for_cluster, get_cluster_name
from unittest.mock import MagicMock

def test_get_krr_clusters(mock_cursor):
    mock_cursor.description = [("Id",), ("ResourceName",), ("latest_scan",)]
    mock_cursor.fetchall.return_value = [(1, "Cluster 1", "2026-03-01")]
    
    clusters = get_krr_clusters(mock_cursor)
    
    assert len(clusters) == 1
    assert clusters[0]["ResourceName"] == "Cluster 1"
    assert "JOIN Entities e_ns" in mock_cursor.execute.call_args[0][0]

def test_get_krr_recommendations_for_cluster(mock_cursor):
    mock_cursor.description = [("namespace",), ("WorkloadType",), ("WorkloadName",)]
    mock_cursor.fetchall.return_value = [("ns1", "Deployment", "app")]
    
    recs = get_krr_recommendations_for_cluster(mock_cursor, 1)
    
    assert len(recs) == 1
    assert recs[0]["namespace"] == "ns1"
    assert "WITH LatestScan" in mock_cursor.execute.call_args[0][0]
    assert mock_cursor.execute.call_args[0][1] == (1, 1)

def test_get_cluster_name_found(mock_cursor):
    mock_cursor.fetchone.return_value = ("MyCluster",)
    
    name = get_cluster_name(mock_cursor, 1)
    
    assert name == "MyCluster"
    assert "WHERE Id = %s" in mock_cursor.execute.call_args[0][0]

def test_get_cluster_name_not_found(mock_cursor):
    mock_cursor.fetchone.return_value = None
    
    name = get_cluster_name(mock_cursor, 999)
    
    assert "Neznámý cluster" in name
