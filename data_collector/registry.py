import importlib
import logging
from pathlib import Path

log = logging.getLogger("registry")

COLLECTOR_REGISTRY = {}

def register_collector(name, help_text=None, cli_args=None):
    """
    Decorator to register a collector module.
    """
    def decorator(func):
        COLLECTOR_REGISTRY[name] = {
            "func": func,
            "help": help_text or "",
            "cli_args": cli_args or []
        }
        return func
    return decorator

def load_collectors():
    """
    Dynamically loads all data collector modules to trigger decorators.
    """
    base_dir = Path(__file__).parent
    for d in base_dir.iterdir():
        if d.is_dir() and d.name.endswith("_collector") and d.name != "krr_collector":
            run_file = d / "run_collection.py"
            if run_file.exists():
                try:
                    importlib.import_module(f"{d.name}.run_collection")
                except ImportError as e:
                    log.error(f"Failed to load collector {d.name}: {e}")
