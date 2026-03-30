import pytest
from unittest.mock import MagicMock, patch
from db_loader.cost_processor import CostsProcessor

@pytest.fixture
def mock_db():
    db_conn = MagicMock()
    # fetchone for _upsert_single_parent returns ID=10
    db_conn.cursor.return_value.fetchone.return_value = [10]
    return db_conn

def test_cost_processor_process(mock_db):
    # Arrange
    envelope = MagicMock()
    envelope.payload = {"dummy": "data"}

    # Simulated Cost Record
    mock_record = MagicMock()
    mock_record.resource_id = "i-12345678"
    mock_record.provider = "aws"
    mock_record.account_id = "111122223333"
    mock_record.resource_name = "aws-ec2-test"
    mock_record.resource_type = "aws_ec2"
    mock_record.tags = {"env": "prod"}
    mock_record.region_id = "eu-central-1"
    
    # Cost insert row attributes
    mock_record.billed_cost = 15.5
    mock_record.billing_currency = "USD"
    mock_record.charge_period_start = "2024-01-01T00:00:00"
    mock_record.charge_period_end = "2024-01-02T00:00:00"
    mock_record.service_category = "Compute"
    mock_record.service_name = "AmazonEC2"
    mock_record.sku_price_id = "sku-123"

    processor = CostsProcessor(mock_db)

    # Act
    # Mock the Pydantic validation and return simulated data
    with patch('db_loader.cost_processor.CostBatchPayload.model_validate') as mock_validate:
        mock_validate.return_value.records = [mock_record]
        
        # Mock execute_values for _resolve_entities_bulk, returns list of (ID, ExternalId)
        def mock_execute_values(cursor, query, values, fetch=False):
            if fetch:
                return [(42, mock_record.resource_id.lower())]
            return None

        with patch('db_loader.cost_processor.execute_values', side_effect=mock_execute_values) as mock_exec:
            processor.process(envelope)

    # Assert
    # Check if AWS account (parent entity) was created
    cursor = mock_db.cursor.return_value
    assert cursor.execute.call_count == 1
    parent_args = cursor.execute.call_args[0][1]
    assert parent_args[0] == "111122223333" # Account ID
    assert parent_args[3] == "aws_account"  # type

    # Once for retrieving entities and Once for upserting costs
    assert mock_exec.call_count == 2
    
    # Check cost upserts
    cost_insert_args = mock_exec.call_args_list[1][0][2] # Values list
    assert len(cost_insert_args) == 1
    # Check the inserted row
    assert cost_insert_args[0][0] == 42 
    assert cost_insert_args[0][1] == 15.5