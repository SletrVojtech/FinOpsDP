import pytest
from unittest.mock import MagicMock, patch
from rabbitmq.connector import RabbitMQClient

@patch('rabbitmq.connector.pika')
def test_rabbitmq_connect_and_close(mock_pika):
    # Arrange
    client = RabbitMQClient()
    mock_connection = MagicMock()
    mock_connection.is_closed = False
    mock_pika.BlockingConnection.return_value = mock_connection

    client.connect()

    # Assert for connection
    mock_pika.PlainCredentials.assert_called_once_with('finops', 'finops_password')
    mock_pika.BlockingConnection.assert_called_once()
    assert client.connection is not None
    assert client.channel is not None

    # Act disconnect
    client.close()

    # Assert disconnect
    mock_connection.close.assert_called_once()

@patch('rabbitmq.connector.pika')
def test_rabbitmq_context_manager(mock_pika):
    # Arrange
    mock_connection = MagicMock()
    mock_connection.is_closed = False
    mock_pika.BlockingConnection.return_value = mock_connection

    # Act
    with RabbitMQClient() as client:
        # Check for existing connection
        assert client.connection is not None
        assert client.channel is not None
        
    # Assert for called __exit__ and close
    mock_connection.close.assert_called_once()

@patch('rabbitmq.connector.pika')
def test_rabbitmq_publish_success(mock_pika):
    # Arrange
    mock_channel = MagicMock()
    
    with RabbitMQClient() as client:
        # Mock the channel
        client.channel = mock_channel
        
        # Act
        client.publish(queue_name="test_queue", message=b"hello_world")
        
        # Assert - declared queue
        mock_channel.queue_declare.assert_called_once_with(queue="test_queue", durable=True)
        # sent message
        mock_channel.basic_publish.assert_called_once()
        
        # Check parametrers of the publish call
        args, kwargs = mock_channel.basic_publish.call_args
        assert kwargs['routing_key'] == "test_queue"
        assert kwargs['body'] == b"hello_world"
        
        # Check for persistent message
        assert mock_pika.BasicProperties.call_args[1]['delivery_mode'] == 2

def test_rabbitmq_publish_without_connection_raises_exception():
    client = RabbitMQClient()
    # Call publish without establishing connection beforehand.
    
    with pytest.raises(Exception) as exc_info:
        client.publish(queue_name="test_queue", message="test")
        
    assert "Connection is not established" in str(exc_info.value)
    
def test_rabbitmq_consume_without_connection_raises_exception():
    client = RabbitMQClient()
    # Call consume without establishing the connection.
    
    with pytest.raises(Exception) as exc_info:
        def dummy_callback(ch, method, properties, body): pass
        client.consume(queue_name="test_queue", callback=dummy_callback)
        
    assert "Connection is not established" in str(exc_info.value)