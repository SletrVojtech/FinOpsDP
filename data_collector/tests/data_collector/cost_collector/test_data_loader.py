import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from cost_collector.data_loader import CostDataLoader

@patch('cost_collector.data_loader.duckdb.connect')
def test_process_and_publish_batches(mock_duckdb_connect):
    # Arrange
    mock_rmq = MagicMock()
    mock_con = MagicMock()
    mock_duckdb_connect.return_value = mock_con

    # Mock DuckDB with 3 returned rows
    mock_records = [
        {'ProviderName': 'AWS', 'SubAccountId': '1', 'resource_id': 'res1', 'charge_period_start': datetime.now(), 'charge_period_end': datetime.now()},
        {'ProviderName': 'AWS', 'SubAccountId': '2', 'resource_id': 'res2', 'charge_period_start': datetime.now(), 'charge_period_end': datetime.now()},
        {'ProviderName': 'AWS', 'SubAccountId': '3', 'resource_id': 'res3', 'charge_period_start': datetime.now(), 'charge_period_end': datetime.now()}
    ]
    
    # execute().fetchdf().to_dict('records')
    mock_execute = mock_con.execute.return_value
    mock_fetchdf = mock_execute.fetchdf.return_value
    mock_fetchdf.to_dict.return_value = mock_records

    # Create loader
    loader = CostDataLoader(rmq_client=mock_rmq)

    # Act: Try batch_size=2 -> 2 published messages
    loader.process_and_publish(export_folder_pattern="dummy_path/*.csv", batch_size=2)

    # Assert - SQL query called once
    mock_con.execute.assert_called_once()
    
    # Check the SQL parameters
    sql_query = mock_con.execute.call_args[0][0]
    assert "WHERE EffectiveCost != 0" in sql_query
    
    # 2 RMQ publish calls
    assert mock_rmq.publish.call_count == 2