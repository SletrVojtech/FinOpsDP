import os

class AppConfig:
    # Prepared for implementing web modules 
    ENABLE_METRICS = os.getenv("ENABLE_METRICS", "True").lower() == "true"
    ENABLE_COSTS = os.getenv("ENABLE_COSTS", "False").lower() == "true"