import pytest
from pydantic import ValidationError
from rabbitmq.message import IngestionMessage
import uuid
from datetime import datetime

def test_ingestion_message_valid_creation():
    # Arrange & Act
    payload_data = {"metric": "cpu", "value": 42}
    msg = IngestionMessage(source_module="test_module", payload=payload_data)

    # Assert
    assert msg.source_module == "test_module"
    assert msg.payload == payload_data
    
    # Check default generators
    assert msg.message_id is not None
    assert isinstance(msg.timestamp, datetime)
    
    # Check UUID
    try:
        uuid_obj = uuid.UUID(msg.message_id, version=4)
        assert str(uuid_obj) == msg.message_id
    except ValueError:
        pytest.fail("Generated message_id is not a valid UUID4")

def test_ingestion_message_missing_fields():
    # Act & Assert: ValidationError for missing payload
    with pytest.raises(ValidationError) as exc_info:
        IngestionMessage(source_module="test_module")
        
    assert "payload" in str(exc_info.value)

    # Act & Assert: ValidationError for missing source_module
    with pytest.raises(ValidationError) as exc_info:
        IngestionMessage(payload={"data": "test"})
        
    assert "source_module" in str(exc_info.value)