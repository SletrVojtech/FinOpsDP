import pytest
from fastapi import Request
from services.utils import extract_active_tags, humanize_memory, humanize_cpu
from unittest.mock import MagicMock

def test_extract_active_tags():
    # Mocking FastAPI Request
    mock_request = MagicMock(spec=Request)
    mock_request.query_params = {
        "tag_env": "production",
        "tag_team": "billing",
        "other_param": "value",
        "tag_empty": ""
    }
    
    tags = extract_active_tags(mock_request)
    
    assert tags == {"env": "production", "team": "billing"}
    assert "other_param" not in tags
    assert "empty" not in tags

def test_humanize_memory():
    assert humanize_memory(None) == "-"
    assert humanize_memory("None") == "-"
    assert humanize_memory("1024") == "1 Ki"
    assert humanize_memory(str(1024**2)) == "1 Mi"
    assert humanize_memory(str(1024**3)) == "1.00 Gi"
    assert humanize_memory("500") == "500 B"
    assert humanize_memory("invalid") == "invalid"

def test_humanize_cpu():
    assert humanize_cpu(None) == "-"
    assert humanize_cpu("None") == "-"
    assert humanize_cpu("0.5") == "500m"
    assert humanize_cpu("2.0") == "2.00"
    assert humanize_cpu("0.001") == "1m"
    assert humanize_cpu("invalid") == "invalid"
