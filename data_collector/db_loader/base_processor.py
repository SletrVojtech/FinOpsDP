from abc import ABC, abstractmethod
import logging

log = logging.getLogger('base_processor')

PROCESSOR_REGISTRY = {}

def register_processor(source_module: str):
    """
    Decorator to register an entity processor for a specific source_module.
    """
    def decorator(cls):
        PROCESSOR_REGISTRY[source_module] = cls
        return cls
    return decorator

class BaseProcessor(ABC):
    """
    Base class for all DB processors.
    """
    def __init__(self, db_conn):
        self.db = db_conn
        self.cursor = self.db.cursor()

    @abstractmethod
    def process(self, envelope):
        """
        Process the incoming envelope and store into the database.
        """
        pass

    def upsert_basic_entity(self, ext_id, provider, res_name, res_type, parent_id=0, cache=None):
        """
        Basic entity UPSERT function shared across processors.
        If parent_id is 0, it will not be updated.
        """
        if cache is not None and ext_id.lower() in cache:
            return cache[ext_id.lower()]

        query = """
            INSERT INTO Entities (ExternalId, ProviderName, ResourceName, ResourceType, ParentId)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ExternalId) DO UPDATE 
            SET ParentId = CASE WHEN EXCLUDED.ParentId = 0 THEN Entities.ParentId ELSE EXCLUDED.ParentId END, 
                ResourceType = EXCLUDED.ResourceType
            RETURNING Id;
        """
        if not res_name or str(res_name).lower() == "none":
            res_name = ext_id
            
        self.cursor.execute(query, (ext_id.lower(), provider.lower(), str(res_name).lower(), res_type.lower(), parent_id))
        result = self.cursor.fetchone()
        
        if result:
            result_id = result[0]
        else:
            self.cursor.execute("SELECT Id FROM Entities WHERE ExternalId = %s;", (ext_id.lower(),))
            result_id = self.cursor.fetchone()[0]
        
        if cache is not None:
            cache[ext_id.lower()] = result_id
            
        return result_id

    def resolve_azure_hierarchy(self, resource_id, parent_id=0, cache=None, fallback_sub_id=None, fallback_sub_name=None):
        """
        Parses Azure Resource ID and creates Subscription and ResourceGroup entities.
        Returns the DB ID of the lowest created parent (ResourceGroup or Subscription).
        """
        parts = resource_id.split("/")
        # format: /subscriptions/{sub_id}/resourcegroups/{rg_name}/...
        if len(parts) > 4 and parts[1].lower() == 'subscriptions':
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

    def resolve_aws_hierarchy(self, account_id, account_name=None, parent_id=0, cache=None):
        """
        Creates AWS Account entity.
        Returns the DB ID of the account.
        """
        return self.upsert_basic_entity(account_id, "aws", account_name or account_id, "aws_account", parent_id, cache)


class ProcessorFactory:
    """
    Factory to retrieve the processor for a specific source_module.
    """
    @staticmethod
    def load_available():
        """
        Dynamically imports all modules in the db_loader directory to trigger @register_processor decorators.
        """
        import importlib
        from pathlib import Path
        
        current_dir = Path(__file__).parent
        for file in current_dir.glob("*_processor.py"):
            if file.name != "base_processor.py":
                importlib.import_module(f"db_loader.{file.stem}")

    @staticmethod
    def get_processor(source_module: str, db_conn):
        processor_class = PROCESSOR_REGISTRY.get(source_module)
        if not processor_class:
            return None
        return processor_class(db_conn)
