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

    # Assert - SQL queries called twice (normal + multiday)
    assert mock_con.execute.call_count == 2
    
    # Check the SQL parameters
    sql_query = mock_con.execute.call_args[0][0]
    assert "WHERE EffectiveCost != 0" in sql_query
    
    # 2 RMQ publish calls
    assert mock_rmq.publish.call_count == 2

def test_distribute_multiday_charges():
    # Arrange
    loader = CostDataLoader(rmq_client=MagicMock())
    
    # 3-day charge spanning from March 1 to March 4
    start_dt = datetime(2026, 3, 1, 0, 0, 0)
    end_dt = datetime(2026, 3, 4, 0, 0, 0)
    
    mock_multiday_dicts = [{
        'ProviderName': 'AWS', 
        'BillingAccountId': 'ba',
        'BillingAccountName': 'ban',
        'SubAccountId': '10', 
        'SubAccountName': 'san',
        'RegionId': 'eu-west-1',
        'resource_id': 'tax-res',
        'ServiceCategory': 'Tax',
        'ServiceName': 'AWS Tax',
        'SkuPriceId': 'skx',
        'BillingCurrency': 'USD',
        'ResourceName': 'n',
        'ResourceType': 't',
        'Tags': '{}',
        'charge_period_start': start_dt, 
        'charge_period_end': end_dt,
        'billed_cost': 30.0,
    }]
    
    # The pipeline started fetching data from March 2nd (March 1st is technically outside the main window)
    cutoff_date = "2026-03-02 00:00:00"

    # Act
    records = loader._distribute_multiday_charges(mock_multiday_dicts, cutoff_date)

    # Assert
    # 30 / 3 days = 10.0 daily cost
    # Since March 1st is < cutoff_date, we only retain the payloads for March 2nd & 3rd.
    assert len(records) == 2
    
    payload_1 = records[0]
    assert payload_1.charge_period_start == datetime(2026, 3, 2, 0, 0, 0) 
    assert payload_1.billed_cost == 10.0
    
    payload_2 = records[1]
    assert payload_2.charge_period_start == datetime(2026, 3, 3, 0, 0, 0) 
    assert payload_2.billed_cost == 10.0