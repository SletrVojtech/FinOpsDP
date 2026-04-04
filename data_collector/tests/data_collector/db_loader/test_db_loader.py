from unittest.mock import MagicMock, patch
from db_loader.db_loader import DBLoader

def test_handle_message_success_custodian():
    # Arrange: Mock DB and RabbitMQ
    mock_db = MagicMock()
    mock_mq = MagicMock()
    loader = DBLoader(mock_db, mock_mq)
    
    mock_ch = MagicMock()
    mock_method = MagicMock()
    mock_method.delivery_tag = 1
    
    # IngestionMessage example 
    valid_json = """{
        "source_module": "custodian",
        "payload": {
            "provider": "aws", 
            "resource_id": "test", 
            "billing_account_id": "123", 
            "resource_name": "test", 
            "resource_type": "aws.ec2", 
            "metric_name": "cpu", 
            "metric_period": 5, 
            "tags": {}, 
            "extras": {}, 
            "datapoints": []
        }
    }"""

    # Act: patch blocks out using the real factory
    with patch('db_loader.db_loader.ProcessorFactory.get_processor') as mock_get_processor:
        loader.handle_message(mock_ch, mock_method, None, valid_json)

    # Assert: check the creation via factory and calling "process" once
    mock_get_processor.assert_called_once_with('custodian', mock_db)
    mock_get_processor.return_value.process.assert_called_once()
    
    # Assert: Check if sucessfuly commited and acknowledged
    mock_db.commit.assert_called_once()
    mock_ch.basic_ack.assert_called_once_with(delivery_tag=1)
    mock_db.rollback.assert_not_called()

def test_handle_message_exception_triggers_rollback():
    # Arrange
    mock_db = MagicMock()
    mock_mq = MagicMock()
    loader = DBLoader(mock_db, mock_mq)
    
    mock_ch = MagicMock()
    mock_method = MagicMock()
    mock_method.delivery_tag = 2
    
    # Invalid JSON should call IngestionMessage.model_validate_json
    invalid_json = "NOT A JSON"

    # Act
    loader.handle_message(mock_ch, mock_method, None, invalid_json)

    # Assert:On failure call rollback and NACK while deleting the message.
    mock_db.rollback.assert_called_once()
    mock_ch.basic_nack.assert_called_once_with(delivery_tag=2, requeue=False)
    mock_db.commit.assert_not_called()