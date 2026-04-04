import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def mock_cursor():
    """Fixture to mock a database cursor."""
    cursor = MagicMock()
    # Mock common cursor methods
    cursor.execute.return_value = None
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    return cursor

@pytest.fixture
def client():
    """Fixture to provide a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c
