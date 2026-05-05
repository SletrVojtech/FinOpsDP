from operator import call
import importlib
import logging
from pathlib import Path

log = logging.getLogger("registry")

COLLECTOR_REGISTRY = {}

def register_collector(name, help_text=None, cli_args=None) -> callable:
    """
    Decorator to register a collector module into the global registry.

    This decorator adds the decorated function and its metadata to the 
    `COLLECTOR_REGISTRY` dictionary, allowing it to be dynamically discovered 
    and executed by the CLI or the job scheduler.

    Args:
        name (str): The unique name of the collector used as a CLI command.
        help_text (str, optional): The description shown in the CLI help menu. Defaults to None.
        cli_args (list, optional): A list of tuples containing argument names and kwargs 
                                   for the argparse parser. Defaults to None.

    Returns:
        callable: The original, unmodified function.
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

    Iterates through the directory containing this file, looking for subdirectories
    that end with the suffix '_collector'. If a 'run_collection.py' file exists 
    within the directory, it imports the module, which triggers the module's 
    `@register_collector` decorators.

    The 'krr_collector' directory is explicitly ignored.
    """
    base_dir = Path(__file__).parent
    for d in base_dir.iterdir():
        if d.is_dir() and d.name.endswith("_collector") and d.name != "krr_collector":
            run_file = d / "run_collection.py"
            if run_file.exists():
                try:
                    importlib.import_module(f"{d.name}.run_collection")
                except Exception as e:
                    log.error(f"Failed to load collector {d.name}: {e}")
