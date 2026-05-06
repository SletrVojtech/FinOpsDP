"""
Database Loader Module.

This module provides the DBLoader class, which consumes messages from RabbitMQ
and dispatches them to the appropriate database processor based on the
source module metadata.
"""

import logging
from typing import Any
from rabbitmq.message import IngestionMessage
from db_loader.base_processor import ProcessorFactory

# Dynamically load all processors to trigger their @register_processor decorators
ProcessorFactory.load_available()
log = logging.getLogger('db_loader')


class DBLoader:
    """
    Consumer class for loading ingested data into the database.
    """
    def __init__(self, db_conn, mq_channel):
        """
        Initialize the DB loader.

        Args:
            db_conn: A psycopg2 connection object.
            mq_channel: A RabbitMQ channel object.
        """
        self.db = db_conn
        self.mq = mq_channel

    def start_consuming(self, queue_name: str = "data_ingestion"):
        """
        Starts the RabbitMQ consumer loop.

        Args:
            queue_name (str, optional): The name of the queue to consume from. 
                Defaults to "data_ingestion".
        """
        log.info(f"Starting database loader consumer on queue: {queue_name}")
        self.mq.basic_qos(prefetch_count=5)
        self.mq.basic_consume(
            queue=queue_name, 
            on_message_callback=self.handle_message, 
            auto_ack=False
        )
        self.mq.start_consuming()

    def handle_message(self, ch: Any, method: Any, properties: Any, body: bytes):
        """
        Callback function to handle individual RabbitMQ messages.

        Args:
            ch (Any): The channel object.
            method (Any): Delivery method details.
            properties (Any): Message properties.
            body (bytes): The raw message body (JSON).
        """
        try:
            # Parse the ingestion envelope
            envelope = IngestionMessage.model_validate_json(body)
            
            # Dispatch to the appropriate processor
            processor = ProcessorFactory.get_processor(envelope.source_module, self.db)
            if processor:
                processor.process(envelope)
                # Persist changes to the database
                self.db.commit() 
                ch.basic_ack(delivery_tag=method.delivery_tag)
                log.debug(f"Successfully processed message from {envelope.source_module}")
            else:
                log.warning(f"No processor found for module: {envelope.source_module}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        except Exception as e:
            # Rollback database transaction on failure
            self.db.rollback()
            log.error(f"Failed to process message: {e}", exc_info=True)
            # Send NACK and do not requeue to avoid infinite loops on malformed data
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)