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

def humanize_memory(mem_str):
    if not mem_str or mem_str == "None":
        return "-"
    try:
        bytes_val = float(mem_str)
        if bytes_val >= 1024**3:
            return f"{bytes_val / (1024**3):.2f} Gi"
        elif bytes_val >= 1024**2:
            return f"{bytes_val / (1024**2):.0f} Mi"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.0f} Ki"
        else:
            return f"{bytes_val:.0f} B"
    except ValueError:
        return mem_str

def humanize_cpu(cpu_str):
    if not cpu_str or cpu_str == "None":
        return "-"
    try:
        # milicores
        cores = float(cpu_str)
        if cores < 1:
            return f"{cores * 1000:.0f}m"
        return f"{cores:.2f}"
    except ValueError:
        return cpu_str