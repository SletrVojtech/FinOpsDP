import pika
import logging
from typing import Optional, Callable
import os

log = logging.getLogger("rabbitmq_client")

class RabbitMQClient:
    """
    A client for interacting with RabbitMQ, supporting context management.
    This client allows publishing and consuming persistent messages

    Based on:
    https://github.com/pazfelipe/python-rabbitmq
    (Felipe Paz, 2024)
    """
    def __init__(self):
        """
        Initializes the RabbitMQ client with environment-based configuration.

        Reads RMQ_USER, RMQ_PASSWORD, RMQ_HOST, and RMQ_PORT.

        Raises:
            ValueError: If the required RMQ_USER or RMQ_PASSWORD are not set.
        """
        self.user = os.getenv('RMQ_USER')
        self.password = os.getenv('RMQ_PASSWORD')
        self.host = os.getenv('RMQ_HOST', 'localhost')
        self.port = int(os.getenv('RMQ_PORT', 5672))
        
        if not self.user or not self.password:
            raise ValueError("RabbitMQ environment variables RMQ_USER and RMQ_PASSWORD are required but not provided.")

        self.connection: Optional[pika.BlockingConnection] = None

        self.channel: Optional[pika.channel.Channel] = None

    def connect(self):
        """
        Establishes a blocking connection to the RabbitMQ server and opens a channel.
        Does nothing if the connection is already open.
        Sets the connection heartbeat to 600 seconds.
        """
        if self.connection and self.connection.is_open:
            return
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(host=self.host,
                                                port=self.port,
                                                credentials=credentials,
                                                heartbeat=600)
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        log.debug("Connected to RabbitMQ")


    def close(self):
        """Closes the connection to the RabbitMQ server if it is open."""
        if self.connection and not self.connection.is_closed:
            self.connection.close()
        log.debug("Connection to RabbitMQ closed")
    
    def __enter__(self):
        """Context manager entry point, connects to RabbitMQ."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Context manager exit point: closes the connection."""
        self.close()


    def consume(self, queue_name, callback) -> None:
        """
        Starts consuming messages from a specified queue.
        
        Ensures the queue exists before starting.

        Args:
            queue_name (str): The name of the queue to consume from.
            callback (Callable): The function to execute for each message.

        Raises:
            Exception: If the channel or connection is not established.
        """
        if not self.channel:
            raise Exception("RabbitMQ Connection is not established.")
        self.channel.queue_declare(queue=queue_name, durable=True)
        self.channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=False)
        self.channel.start_consuming()

    def publish(self, queue_name: str, message: str) -> None:
        """
        Publishes a persistent message to a specified queue.
        
        Declares the queue if it doesn't exist.

        Args:
            queue_name (str): The destination queue name.
            message (str): The text message payload to send.

        Raises:
            Exception: If the channel or connection is not established.
        """
        if not self.channel:
            raise Exception("Rabbit MQ Connection is not established.")
        self.channel.queue_declare(queue=queue_name, durable=True)
        self.channel.basic_publish(exchange='',
                                   routing_key=queue_name,
                                   body=message,
                                   properties=pika.BasicProperties(
                                       delivery_mode=2,  # make message persistent
                                   ))
        log.debug(f"Sent message to queue {queue_name}")