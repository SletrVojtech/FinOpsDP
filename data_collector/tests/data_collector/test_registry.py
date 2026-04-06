import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import registry

@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure COLLECTOR_REGISTRY is empty before each test."""
    registry.COLLECTOR_REGISTRY.clear()
    yield

def test_register_collector_decorator():
    """Verify the registration decorator correctly populates the registry."""
    @registry.register_collector("test_col", help_text="Test Help", cli_args=["--foo"])
    def mock_func():
        return "success"
    
    assert "test_col" in registry.COLLECTOR_REGISTRY
    assert registry.COLLECTOR_REGISTRY["test_col"]["help"] == "Test Help"
    assert registry.COLLECTOR_REGISTRY["test_col"]["cli_args"] == ["--foo"]
    assert registry.COLLECTOR_REGISTRY["test_col"]["func"]() == "success"

@patch("registry.importlib.import_module")
@patch("registry.Path.iterdir")
def test_load_collectors_logic(mock_iterdir, mock_import):
    """Verify dynamic loading filters for *_collector directories."""
    # Setup mock file structure
    mock_dir = MagicMock(spec=Path)
    mock_dir.is_dir.return_value = True
    mock_dir.name = "my_collector"
    
    mock_run_file = mock_dir / "run_collection.py"
    mock_run_file.exists.return_value = True
    
    # Another dir that shouldn't match
    bad_dir = MagicMock(spec=Path)
    bad_dir.is_dir.return_value = False
    bad_dir.name = "random_file"
    
    mock_iterdir.return_value = [mock_dir, bad_dir]
    
    # Act
    registry.load_collectors()
    
    # Assert
    # Should attempt to import my_collector.run_collection
    mock_import.assert_called_with("my_collector.run_collection")
