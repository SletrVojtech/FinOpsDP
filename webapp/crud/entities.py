"""
Entity Hierarchy Navigation Module.

Provides SQL queries for navigating and filtering the hierarchical
``Entities`` table. Supports top-down and bottom-up traversal,
tag-based filtering, and dynamic scope exploration for the UI.
"""

from config import AppConfig
from crud import rules
import re

def get_roots(cursor):
    """Return the root-level entities of the hierarchy.

    Args:
        cursor: Active database cursor.

    Returns:
        list: Dicts with keys ``id``, ``name``, ``provider``, and
            ``has_children``.
    """
    cursor.execute("""
        SELECT Id, ResourceName, ProviderName,
                    EXISTS(SELECT 1 FROM Entities child WHERE child.ParentId = e.Id) as has_children
        FROM Entities e
        WHERE ParentId = 0
        ORDER BY ProviderName, ResourceName;
    """)
    return [{"id": r[0], "name": r[1], "provider": r[2], "has_children": r[3]} for r in cursor.fetchall()]

def get_children(cursor, parent_id: int):
    """Return direct children of a given entity.

    Args:
        cursor: Active database cursor.
        parent_id (int): Entity ID of the parent node.

    Returns:
        list: Dicts with keys ``id``, ``name``, ``type``, and
            ``has_children``.
    """
    cursor.execute("""
        SELECT Id, ResourceName, ResourceType,
                   EXISTS(SELECT 1 FROM Entities child WHERE child.ParentId = e.Id) as has_children
        FROM Entities e
        WHERE ParentId = %s
        ORDER BY ResourceType, ResourceName;
    """, (parent_id,))
    return [{"id": r[0], "name": r[1], "type": r[2], "has_children": r[3]} for r in cursor.fetchall()]

def get_providers(cursor):
    """Return all distinct cloud provider names present in the Entities table.

    Args:
        cursor: Active database cursor.

    Returns:
        list[str]: Provider name strings.
    """
    cursor.execute("SELECT DISTINCT ProviderName FROM Entities WHERE ProviderName IS NOT NULL;")
    return [r[0] for r in cursor.fetchall()]

def get_top_tag_keys(cursor, limit: int = 15):
    """Return the most frequently used tag keys across all entities.

    Args:
        cursor: Active database cursor.
        limit (int, optional): Maximum number of keys to return. Defaults to 15.

    Returns:
        list: Dicts with keys ``key`` and ``count``.
    """
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
    """Return the total number of entity records in the database.

    Args:
        cursor: Active database cursor.

    Returns:
        int: Total entity count.
    """
    # ADD except subscriptions etc
    cursor.execute("SELECT COUNT(*) FROM Entities;")
    return cursor.fetchone()[0]


def get_chain(cursor, current_node_id: int):
    """Return the ancestor path from the root to a given entity node.

    Uses a recursive CTE that walks up the parent chain. Returns an
    empty list when ``current_node_id`` is 0 (the virtual root).

    Args:
        cursor: Active database cursor.
        current_node_id (int): Entity ID of the starting (leaf) node.

    Returns:
        list: Dicts with keys ``id`` and ``name``, ordered from root to
            current node.
    """
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
    """Return the most frequent tag keys within a scoped entity subtree.

    Performs a top-down recursive walk of the subtree rooted at
    ``parent_id``, restricts results to entities updated within the
    last 7 days, and excludes tag keys that match global tag-filter
    rules. Also returns the total entity count for quality metrics.

    Args:
        cursor: Active database cursor.
        parent_id (int, optional): Root entity ID of the scope.
            Defaults to 0 (global root).
        limit (int, optional): Maximum number of tag keys to return.
            Defaults to 15.

    Returns:
        list: Dicts with keys ``key``, ``count``, and ``total``.
    """
    if parent_id is None:
        # Starting in the root
        parent_id = 0
    
    tag_rules = rules.get_tag_filtering_rules(cursor)
    regex_filter = None
    if tag_rules:
        regex_parts = []
        for r in tag_rules:
            if r['pattern']:
                escaped = re.escape(r['pattern']).replace('\\*', '.*')
                regex_parts.append(f"({escaped})")
        if regex_parts:
            regex_filter = "^(" + "|".join(regex_parts) + ")$"

    where_clause = "WHERE s.Tags IS NOT NULL"
    params = [parent_id]
    if regex_filter:
        where_clause += " AND key !~ %s"
        params.append(regex_filter)
    params.append(limit)

    # Already scoped, recursively going down.
    # We calculate the total count of entities in the subtree to provide "tag quality" metrics.
    cursor.execute(f"""
        WITH RECURSIVE SubTree AS (
            SELECT Id, Tags FROM Entities 
            WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.Tags FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
            WHERE e.UpdatedAt >= NOW() - INTERVAL '7 days'
        ),
        Stats AS (
            SELECT COUNT(*) as total_count FROM SubTree
        )
        SELECT key, COUNT(*) as freq, (SELECT total_count FROM Stats) as total
        FROM SubTree s, jsonb_object_keys(s.Tags) as key
        {where_clause}
        GROUP BY key ORDER BY freq DESC LIMIT %s;
    """, tuple(params))
        
    return [{"key": r[0], "count": r[1], "total": r[2]} for r in cursor.fetchall()]

def get_scoped_items(cursor, parent_id=None):
    """Return direct children of the given scope entity.

    Fetches entities one tier below ``parent_id`` that have been
    updated within the last 7 days.

    Args:
        cursor: Active database cursor.
        parent_id (int, optional): Parent entity ID. Defaults to 0.

    Returns:
        list: Dicts with keys ``id``, ``name``, ``type``, and
            ``has_children``.
    """
    if parent_id is None:
        parent_id = 0
    cursor.execute("""
        SELECT Id, ResourceName, ResourceType as Type,
                EXISTS(SELECT 1 FROM Entities child WHERE child.ParentId = e.Id) as has_children
        FROM Entities e WHERE ParentId = %s AND (UpdatedAt >= NOW() - INTERVAL '7 days' OR Id = 0) ORDER BY ResourceType, ResourceName;
    """, (parent_id,))
    return [{"id": r[0], "name": r[1], "type": r[2], "has_children": r[3]} for r in cursor.fetchall()]

def get_dynamic_items(cursor, scope_id: int = None, tags_filter: dict = None):
    """Return all entities visible under a scope with optional tag-chain filtering.

    Builds a recursive CTE that walks the entire subtree under
    ``scope_id``, filters leaf nodes by ``tags_filter``, and back-traces
    ancestor paths so that intermediate nodes required for navigation are
    also returned. Optionally flags entities that have recent Metrics data
    when ``AppConfig.ENABLE_METRICS`` is set.

    Args:
        cursor: Active database cursor.
        scope_id (int, optional): Root entity ID. Defaults to 0.
        tags_filter (dict, optional): Key-value tag constraints.

    Returns:
        list: Dicts with keys ``id``, ``name``, ``type``,
            ``has_children``, ``parent_id``, and ``has_metrics``.
    """
    tags_filter = tags_filter or {}
    params = []
    if not scope_id:
        scope_id = 0

    # Get the scope
    base_sql = """
        WITH RECURSIVE SubTree AS (
            SELECT Id, ParentId, ResourceName, ResourceType, Tags, ARRAY[Id] as path
            FROM Entities WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.ParentId, e.ResourceName, e.ResourceType, e.Tags, s.path || e.Id
            FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
            WHERE e.UpdatedAt >= NOW() - INTERVAL '7 days'
        ),
        Paths AS (
            SELECT path
            FROM SubTree
            WHERE 1=1
    """
    params.append(scope_id)
    
    # Filter by tags
    for key, value in tags_filter.items():
        base_sql += " AND Tags->>%s = %s"
        params.extend([key, value])
    base_sql += " ),"

    # Bottom up

    base_sql +="""
        ValidIds AS (
            SELECT DISTINCT unnest(path) as valid_id
            FROM Paths
        ),
        UniqueNodes AS (
            SELECT s.Id, s.ParentId, s.ResourceName, s.ResourceType as Type
            FROM SubTree s
            JOIN ValidIds v ON s.Id = v.valid_id
            WHERE s.Id != %s
        )   
    """
    params.append(scope_id)
    # Check if metrics are enabled and if the entity is a direct child of the scope
    if getattr(AppConfig, 'ENABLE_METRICS', False):
        has_metrics_sql = """
            CASE 
                WHEN u.ParentId = %s THEN 
                    EXISTS(SELECT 1 FROM Metrics m WHERE m.EntityId = u.Id AND m.Timestamp >= NOW() - INTERVAL '7 DAYS')
                ELSE False 
            END
        """
        params.append(scope_id)
    else:
        has_metrics_sql = "False"
    # finalize data with has_children, has_metrics
    base_sql += """
        SELECT 
            u.Id, 
            u.ResourceName, 
            u.Type, 
            -- Check for children after the filter.
            EXISTS(SELECT 1 FROM UniqueNodes c WHERE c.ParentId = u.Id) as has_children, 
            u.ParentId,
            """+has_metrics_sql +""" as has_metrics
        FROM UniqueNodes u
        ORDER BY has_children DESC, has_metrics DESC, u.Type, u.ResourceName;
    """
    
    cursor.execute(base_sql, params)
    return [{"id": r[0], "name": r[1], "type": r[2], "has_children": r[3], "parent_id": r[4], "has_metrics": r[5]} for r in cursor.fetchall()]

def get_scoped_tag_values(cursor, parent_id: int, tag_key: str):
    """Return distinct values and their frequencies for a tag key in a scope.

    Walks the entity subtree under ``parent_id`` and aggregates all
    distinct values of ``tag_key``, limited to recently updated entities.

    Args:
        cursor: Active database cursor.
        parent_id (int): Root entity ID for the scope.
        tag_key (str): The tag key to aggregate values for.

    Returns:
        list: Dicts with keys ``value`` and ``count``, ordered by
            frequency descending.
    """
    if parent_id is None:
        parent_id = 0

    cursor.execute("""
        WITH RECURSIVE SubTree AS (
            SELECT Id, Tags FROM Entities WHERE Id = %s
            UNION ALL
            SELECT e.Id, e.Tags FROM Entities e
            JOIN SubTree s ON e.ParentId = s.Id
            WHERE e.UpdatedAt >= NOW() - INTERVAL '7 days'
        )
        SELECT Tags->>%s as tag_value, COUNT(*) as freq
        FROM SubTree
        WHERE Tags ? %s
        GROUP BY tag_value
        ORDER BY freq DESC;
    """, (parent_id, tag_key, tag_key))
        
    return [{"value": r[0] if r[0] is not None else "", "count": r[1]} for r in cursor.fetchall()]