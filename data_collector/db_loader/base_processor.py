"""
Base Processor Module.

This module defines the abstract BaseProcessor class, which provides shared
functionality for all database processors (entity upserts, cloud hierarchy
resolution). It also includes a registration system for processors.
"""

from abc import ABC, abstractmethod
import logging
from typing import Dict, Any, Optional, Type, List, Callable

log = logging.getLogger('base_processor')

# Global registry of processor classes
PROCESSOR_REGISTRY: Dict[str, Type['BaseProcessor']] = {}


def register_processor(source_module: str) -> Callable:
    """
    Decorator to register an entity processor for a specific source_module.

    Args:
        source_module (str): The name of the source module ('custodian', 'kube').

    Returns:
        Callable: The decorator function.
    """
    def decorator(cls: Type['BaseProcessor']):
        PROCESSOR_REGISTRY[source_module] = cls
        return cls
    return decorator


class BaseProcessor(ABC):
    """
    Base class for all DB processors.
    """
    def __init__(self, db_conn):
        """
        Initialize the processor.

        Args:
            db_conn: A psycopg2 connection object.
        """
        self.db = db_conn
        self.cursor = self.db.cursor()

    @abstractmethod
    def process(self, envelope: Any):
        """
        Process the incoming message envelope and store data into the database.

        Args:
            envelope (Any): The message envelope containing payload and metadata.
        """
        pass

    def upsert_basic_entity(self, ext_id: str, provider: str, res_name: str, 
                           res_type: str, parent_id: int = 0, cache: Optional[Dict[str, int]] = None) -> int:
        """
        Standard entity UPSERT function shared across processors.

        Args:
            ext_id (str): The external unique identifier for the entity.
            provider (str): The cloud provider name (aws, azure, k8s).
            res_name (str): Human-readable resource name.
            res_type (str): The type of the resource (e.g., ec2, vm, subscription).
            parent_id (int, optional): The ID of the parent entity. Defaults to 0.
            cache (Optional[Dict[str, int]], optional): Local cache to speed up lookups. Defaults to None.

        Returns:
            int: The internal database ID of the entity.

        Raises:
            RuntimeError: If the entity cannot be found or created.
        """
        ext_id_lower = ext_id.lower()
        if cache is not None and ext_id_lower in cache:
            return cache[ext_id_lower]

        query = """
            INSERT INTO Entities (ExternalId, ProviderName, ResourceName, ResourceType, ParentId)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ExternalId) DO UPDATE 
            SET ParentId = CASE WHEN EXCLUDED.ParentId = 0 THEN Entities.ParentId ELSE EXCLUDED.ParentId END, 
                ResourceType = EXCLUDED.ResourceType, UpdatedAt = NOW()
            RETURNING Id;
        """
        
        # Use External ID as fallback for Resource Name
        final_res_name = ext_id if (not res_name or str(res_name).lower() == "none") else res_name
            
        self.cursor.execute(query, (ext_id_lower, provider.lower(), str(final_res_name).lower(), res_type.lower(), parent_id))
        result = self.cursor.fetchone()
        
        if result:
            result_id = result[0]
        else:
            # Fallback if RETURNING failed (shouldn't happen with ON CONFLICT)
            self.cursor.execute("SELECT Id FROM Entities WHERE ExternalId = %s;", (ext_id_lower,))
            res = self.cursor.fetchone()
            if not res:
                raise RuntimeError(f"Entity {ext_id} not found after UPSERT failure.")
            result_id = res[0]
        
        if cache is not None:
            cache[ext_id_lower] = result_id
            
        return result_id

    def resolve_azure_hierarchy(self, resource_id: str, parent_id: int = 0, 
                                 cache: Optional[Dict[str, int]] = None, 
                                 fallback_sub_id: Optional[str] = None, 
                                 fallback_sub_name: Optional[str] = None) -> int:
        """
        Parses an Azure Resource ID and ensures parent entities (Subscription, RG) exist.

        Args:
            resource_id (str): The full Azure Resource ID.
            parent_id (int, optional): The base parent ID. Defaults to 0.
            cache (Optional[Dict[str, int]], optional): Entity ID cache. Defaults to None.
            fallback_sub_id (Optional[str], optional): Fallback Subscription ID if not in resource_id.
            fallback_sub_name (Optional[str], optional): Fallback Subscription name.

        Returns:
            int: The DB ID of the immediate parent entity.
        """
        parts = resource_id.split("/")
        # format: /subscriptions/{sub_id}/resourcegroups/{rg_name}/...
        if len(parts) > 2 and parts[1].lower() == 'subscriptions':
            sub_id = parts[2]
            sub_ext_id = f"/subscriptions/{sub_id}"
            
            sub_db_id = self.upsert_basic_entity(sub_ext_id, "azure", sub_id, "subscription", parent_id, cache)
            
            if len(parts) > 4 and parts[3].lower() == 'resourcegroups':
                rg_name = parts[4]
                rg_ext_id = f"/subscriptions/{sub_id}/resourcegroups/{rg_name}"
                return self.upsert_basic_entity(rg_ext_id, "azure", rg_name, "resource_group", sub_db_id, cache)
                
            return sub_db_id

        if fallback_sub_id:
            fallback_ext = fallback_sub_id if fallback_sub_id.startswith('/') else f"/subscriptions/{fallback_sub_id}"
            return self.upsert_basic_entity(fallback_ext, "azure", fallback_sub_name or fallback_sub_id, "subscription", parent_id, cache)
            
        return parent_id

    def resolve_aws_hierarchy(self, account_id: str, account_name: Optional[str] = None, 
                              parent_id: int = 0, cache: Optional[Dict[str, int]] = None) -> int:
        """
        Ensures the AWS Account entity exists.

        Args:
            account_id (str): The AWS Account ID.
            account_name (Optional[str], optional): Human-readable account name.
            parent_id (int, optional): Parent ID. Defaults to 0.
            cache (Optional[Dict[str, int]], optional): Entity ID cache.

        Returns:
            int: The DB ID of the account.
        """
        return self.upsert_basic_entity(account_id, "aws", account_name or account_id, "aws_account", parent_id, cache)


class ProcessorFactory:
    """
    Factory to retrieve the appropriate processor instance for a source module.
    """
    @staticmethod
    def load_available():
        """
        Dynamically imports all modules in the db_loader directory to register processors.
        """
        import importlib
        from pathlib import Path
        
        current_dir = Path(__file__).parent
        for file in current_dir.glob("*_processor.py"):
            if file.name != "base_processor.py":
                importlib.import_module(f"db_loader.{file.stem}")

    @staticmethod
    def get_processor(source_module: str, db_conn) -> Optional[BaseProcessor]:
        """
        Retrieves a processor instance for the given source module.

        Args:
            source_module (str): The name of the source module.
            db_conn: Database connection object.

        Returns:
            Optional[BaseProcessor]: A processor instance or None if not found.
        """
        processor_class = PROCESSOR_REGISTRY.get(source_module)
        if not processor_class:
            return None
        return processor_class(db_conn)
