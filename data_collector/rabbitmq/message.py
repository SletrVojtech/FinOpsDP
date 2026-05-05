from pydantic import BaseModel, Field
from typing import Any, Dict
from datetime import datetime, timezone
import uuid



class IngestionMessage(BaseModel):
    """
    Base class for RabbitMQ  messages.

    To deliver data to the DB collector, inherit from this class
    and load your module-specific data into the payload dictionary.
    This model ensures a unified data structure across all data collectors.

    Attributes:
        message_id (str): A unique identifier for the message, automatically 
                          generated as a UUID4 string.
        timestamp (datetime): The exact time the message was created, 
                              automatically set to current UTC time.
        source_module (str): The name of the collector module that generated 
                             the message.
        payload (Dict[str, Any]): A dictionary containing the actual collected 
                                  data specific to the source module.
    """
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_module: str 
    payload: Dict[str, Any]