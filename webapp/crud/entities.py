"""
SQL queries for navigating the Entities hierarchy.
"""

from config import AppConfig

def get_roots(cursor):
    """Return roots of the hierarchy.(subscriptions)"""
    cursor.execute("""
        SELECT Id, ResourceName, ProviderName,
                    EXISTS(SELECT 1 FROM Entities child WHERE child.ParentId = e.Id) as has_children
        FROM Entities e
        WHERE ParentId = 0
        ORDER BY ProviderName, ResourceName;
    """)
    return [{"id": r[0], "name": r[1], "provider": r[2], "has_children": r[3]} for r in cursor.fetchall()]

def get_children(cursor, parent_id: int):
    """Returns children of given Id"""
    cursor.execute("""
        SELECT Id, ResourceName, ResourceType,
                   EXISTS(SELECT 1 FROM Entities child WHERE child.ParentId = e.Id) as has_children
        FROM Entities e
        WHERE ParentId = %s
        ORDER BY ResourceType, ResourceName;
    """, (parent_id,))
    return [{"id": r[0], "name": r[1], "type": r[2], "has_children": r[3]} for r in cursor.fetchall()]

def get_providers(cursor):
    """Return all compute providers - Azure/AWS/k8s"""
    cursor.execute("SELECT DISTINCT ProviderName FROM Entities WHERE ProviderName IS NOT NULL;")
    return [r[0] for r in cursor.fetchall()]

def get_top_tag_keys(cursor, limit: int = 15):
    """Find the most frequent tag keys in the database."""
    cursor.execute("""
        SELECT key, COUNT(*) as freq
        FROM Entities e, jsonb_object_keys(e.Tags) as key
        WHERE e.Tags IS NOT NULL
        GROUP BY key
        ORDER BY freq DESC
        LIMIT %s;
    """, (limit,))
    return [{"key": r[0], "count": r[1]} for r in cursor.fetchall()]

def get_number_of_entities(cursor):
    """Return the number of resources in the database."""
    cursor.execute("SELECT COUNT(*) FROM Entities;")
    return cursor.fetchone()[0]


def get_chain(cursor, current_node_id: int):
    """Bottom-Up recursion to find the path to root."""
    if current_node_id == 0:
        return []
        
    cursor.execute("""
        WITH RECURSIVE Path AS (
            -- actual node
            SELECT Id, ParentId, ResourceName, 1 AS depth
            FROM Entities WHERE Id = %s
            UNION ALL
            -- join with parent
            SELECT e.Id, e.ParentId, e.ResourceName, p.depth + 1
            FROM Entities e
            JOIN Path p ON e.Id = p.ParentId
        )
        SELECT Id, ResourceName FROM Path ORDER BY depth DESC;
    """, (current_node_id,))
    return [{"id": r[0], "name": r[1]} for r in cursor.fetchall()]

def get_scoped_top_tags(cursor, parent_id=None, limit=15):
    """Top-Down recursion to find the most frequent tags in the scope."""
    if parent_id is None:
        # Starting in the root
        parent_id = 0

    # Already scoped, recursively going down.
    cursor.execute("""
        WITH RECURSIVE SubTree AS (
            SELECT Id, Tags FROM Entities WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.Tags FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
        )
        SELECT key, COUNT(*) as freq
        FROM SubTree s, jsonb_object_keys(s.Tags) as key
        WHERE s.Tags IS NOT NULL
        GROUP BY key ORDER BY freq DESC LIMIT %s;
    """, (parent_id, limit))
        
    return [{"key": r[0], "count": r[1]} for r in cursor.fetchall()]

def get_scoped_items(cursor, parent_id=None):
    """Return entites in the scope - only one tier lower."""
    if parent_id is None:
        parent_id = 0
    cursor.execute("""
        SELECT Id, ResourceName, ResourceType as Type,
                EXISTS(SELECT 1 FROM Entities child WHERE child.ParentId = e.Id) as has_children
        FROM Entities e WHERE ParentId = %s ORDER BY ResourceType, ResourceName;
    """, (parent_id,))
    return [{"id": r[0], "name": r[1], "type": r[2], "has_children": r[3]} for r in cursor.fetchall()]

def get_dynamic_items(cursor, scope_id: int = None, tags_filter: dict = None):
    """Create a chained filter with scope and tag:value pairs"""
    tags_filter = tags_filter or {}
    params = []
    if not scope_id:
        scope_id = 0

    # Get the scope
    base_sql = """
        WITH RECURSIVE SubTree AS (
            SELECT Id, ParentId, ResourceName, ResourceType, Tags FROM Entities WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.ParentId, e.ResourceName, e.ResourceType, e.Tags FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
        ),
        BaseData AS (
            SELECT Id, ResourceName, ResourceType as Type, Tags, ParentId,
                    EXISTS(SELECT 1 FROM Entities c WHERE c.ParentId = SubTree.Id) as has_children
            FROM SubTree
            WHERE Id != %s
        )
    """
    params.extend([scope_id, scope_id])
    

    if AppConfig.ENABLE_METRICS:
            query = base_sql + """ 
        SELECT 
            b.Id, 
            b.ResourceName, 
            b.Type, 
            b.has_children, 
            b.ParentId,
            EXISTS(SELECT 1 FROM Metrics m WHERE m.EntityId = b.Id) as has_metrics 
        FROM BaseData b 
        WHERE 1=1
    """ 
    else:
        query = base_sql + " SELECT Id, ResourceName, Type, has_children, False as has_metrics FROM BaseData WHERE 1=1"

    # Query building with tags stored in JSONB, check if given entity has some measurements saved.
   
    for key, value in tags_filter.items():
        query += " AND Tags->>%s = %s"
        params.extend([key, value])

    query += " ORDER BY Type, ResourceName;"
    
    cursor.execute(query, params)
    return [{"id": r[0], "name": r[1], "type": r[2], "has_children": r[3], "parent_id": r[4], "has_metrics": r[5]} for r in cursor.fetchall()]

def get_scoped_tag_values(cursor, parent_id: int, tag_key: str):
    """
    Returns number (and names) of different key-values in current scope.
    """
    if parent_id is None:
        parent_id = 0

    cursor.execute("""
        WITH RECURSIVE SubTree AS (
            SELECT Id, Tags FROM Entities WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.Tags FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
        )
        SELECT Tags->>%s as tag_value, COUNT(*) as freq
        FROM SubTree
        WHERE Tags ? %s
        GROUP BY tag_value
        ORDER BY freq DESC;
    """, (parent_id, tag_key, tag_key))
        
    return [{"value": r[0] if r[0] is not None else "", "count": r[1]} for r in cursor.fetchall()]