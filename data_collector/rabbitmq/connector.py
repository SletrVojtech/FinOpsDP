import pika
import logging
from typing import Optional, Callable
import os

log = logging.getLogger("rabbitmq_client")

class RabbitMQClient:
    """
    Based on:
    https://github.com/pazfelipe/python-rabbitmq
    (Felipe Paz, 2024)
    with added methods for using the 'with' clause
    """
    def __init__(self):
        self.user = os.getenv('RMQ_USER', 'user')
        self.password = os.getenv('RMQ_PASSWORD', 'password')
        self.host = os.getenv('RMQ_HOST', 'localhost')
        self.port = int(os.getenv('RMQ_PORT', 5672))
        self.connection: Optional[pika.BlockingConnection] = None
        self.channel: Optional[pika.channel.Channel] = None

    def connect(self):
        """Establishes a connection to the RabbitMQ server and opens a channel."""
        if self.connection and self.connection.is_open:
            return
        credentials = pika.PlainCredentials(self.user, self.password)
        parameters = pika.ConnectionParameters(host=self.host,
                                                port=self.port,
                                                credentials=credentials)
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
        """Starts consuming messages from a specified queue."""
        if not self.channel:
            raise Exception("RabbitMQ Connection is not established.")
        self.channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=False)
        self.channel.start_consuming()

    def publish(self, queue_name: str, message: str) -> None:
        """
        Publishes a persistent message to a specified queue.
        Declares the queue if it doesn't exist.
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