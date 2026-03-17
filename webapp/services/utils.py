from fastapi import Request

def extract_active_tags(request: Request) -> dict:
    """
    Loads parameters from incoming requests and strips the 'tag_' prefix.
    """
    active_tags = {}
    for param_name, param_value in request.query_params.items():
        if param_name.startswith("tag_") and param_value:
            active_tags[param_name[4:]] = param_value
            
    return active_tags