

SCHEMA_DEFINITIONS = {
    # DataDictionary should be first to exist.
    "datadictionary":"""
    CREATE TABLE DataDictionary (
        TableName VARCHAR(100) PRIMARY KEY,
        DataType VARCHAR(50),      -- 'metric', 'cost', 'kube'
        IsCagg BOOLEAN,
        Granularity INTERVAL,
        RetentionDuration INTERVAL
    );
    """,
    "entities": """
    CREATE TABLE Entities (
        Id SERIAL PRIMARY KEY,
        ExternalId VARCHAR(255) UNIQUE,
        ResourceName VARCHAR(255),
        ResourceType VARCHAR(50),
        RegionId VARCHAR(20),                   -- 'account', 'group', 'resource'
        ParentId INTEGER REFERENCES Entities(Id),
        ProviderName VARCHAR(20),          -- AWS, Azure, K8s
        MetaHash VARCHAR(32),
        Tags JSONB,
        Extras JSONB
    );
    """,
    "costs": """
    CREATE TABLE Costs (
        Id BIGSERIAL,
        EntityId INTEGER REFERENCES Entities(Id),
        BilledCost DOUBLE PRECISION,
        BillingCurrency VARCHAR(3) DEFAULT 'EUR',
        ChargePeriodStart TIMESTAMP WITH TIME ZONE,
        ChargePeriodEnd TIMESTAMP WITH TIME ZONE,
        ServiceCategory VARCHAR(255),
        ServiceName VARCHAR(255),
        SkuPriceId VARCHAR(255),

        -- for fast UPSERTS, some data needs to be pre-aggregated.
        PRIMARY KEY(EntityId, ChargePeriodStart, ServiceName, SkuPriceId)
    )WITH(
        tsdb.hypertable,
        tsdb.segmentby = 'EntityId'
    );
    """,
    "metrics": """
    CREATE TABLE Metrics (
        Id BIGSERIAL,
        Timestamp TIMESTAMP WITH TIME ZONE,
        EntityId INTEGER REFERENCES Entities(Id),
        IntervalMinutes INTEGER,
        MetricType VARCHAR,
        Value DOUBLE PRECISION,

        PRIMARY KEY (EntityId, MetricType, Timestamp)
    )WITH(
        tsdb.hypertable,
        tsdb.segmentby='EntityId'
    );
    """,
    "kubemetrics": """
    CREATE TABLE KubeMetrics (
        EntityId INTEGER REFERENCES Entities(Id),
        Timestamp TIMESTAMP WITH TIME ZONE,
        MetricName VARCHAR(50),      -- 'cpu_requests', 'memory_requests'
        Value DOUBLE PRECISION,
        PointInTimeTags JSONB,

        PRIMARY KEY(EntityId, Timestamp, MetricName)
    ) WITH(
        tsdb.hypertable,
        tsdb.segmentby = 'EntityId'
    );
    """,
    "budgets":"""
    CREATE TABLE Budgets (
        Id SERIAL PRIMARY KEY,
        ScopeId INTEGER REFERENCES Entities(Id),
        Tags JSONB,                           
        LimitAmount DECIMAL(18, 4),
        PeriodMonth DATE                        
    );
    """,
    "forecasthistory":"""
    CREATE TABLE ForecastHistory (
        Id SERIAL PRIMARY KEY,
        ScopeId INTEGER REFERENCES Entities(Id),
        Tags JSONB,
        TargetMonth DATE,
        ForecastDate DATE,
        ProjectedAmount DECIMAL(18, 4),
        CalculatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(ScopeId, Tags, TargetMonth, ForecastDate)
    );""",
    "allocationrules":"""
    CREATE TABLE AllocationRules (
        Id SERIAL PRIMARY KEY,
        RuleName VARCHAR(100),
        SourceTags JSONB NOT NULL,
        TargetTags JSONB NOT NULL,
        Percentage DECIMAL(5,2) NOT NULL CHECK (Percentage > 0 AND Percentage <= 100)
    );
    """,
    "kuberecommendations":"""
    CREATE TABLE KubeRecommendations (
         Id SERIAL PRIMARY KEY,
         EntityId INTEGER REFERENCES Entities(Id), -- points to a namespace
         Timestamp TIMESTAMP WITH TIME ZONE,
         WorkloadType VARCHAR(50),     -- Deployment, StatefulSet...
         WorkloadName VARCHAR(255),
         ContainerName VARCHAR(255),

         CurrentCpuRequest VARCHAR(50),
         RecommendedCpuRequest VARCHAR(50),
         CurrentMemoryRequest VARCHAR(50),
         RecommendedMemoryRequest VARCHAR(50),

         UNIQUE(EntityId, WorkloadType, WorkloadName, ContainerName)
    );
    """,
    "hardwarecatalog":"""
    CREATE TABLE HardwareCatalog (
        cloud VARCHAR(50) NOT NULL,
        instance_type VARCHAR(100) NOT NULL,
        instance_family VARCHAR(100),
        vcpu INTEGER,
        memory_gb NUMERIC(10, 2),
        baseline_iops INTEGER,
        baseline_throughput_mbps NUMERIC(15, 2),
        network_performance VARCHAR(100),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (cloud, instance_type)
    );
    """,
    "pricingcatalog":"""
    CREATE TABLE pricingcatalog (
        cloud VARCHAR(50) NOT NULL,
        instance_type VARCHAR(100) NOT NULL,
        region VARCHAR(100) NOT NULL,
        os VARCHAR(50) NOT NULL,
        hourly_price_usd NUMERIC(15, 6) NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (cloud, instance_type, region, os)
    );
    """
}

def cagg_first_metrics(name:str, interval:str):
    return f"""
    CREATE MATERIALIZED VIEW {name}
            WITH (timescaledb.continuous) AS
    SELECT
        time_bucket('{interval}', Timestamp) AS Bucket,
        EntityId,
        MetricType,
        AVG(Value) AS avg_value,
        MAX(Value) AS max_value,
        MIN(Value) AS min_value,
        SUM(Value) AS sum_value,
        COUNT(Value) AS count_value
    FROM Metrics
    GROUP BY 1, 2, 3;
    """

def cagg_next_metrics(name:str, interval:str, source:str):
    return f"""
    CREATE MATERIALIZED VIEW {name}
                WITH (timescaledb.continuous) AS
    SELECT
        time_bucket('{interval}', Bucket) AS Bucket,
        EntityId,
        MetricType,
        SUM(sum_value) / NULLIF(SUM(count_value), 0) AS avg_value,
        MAX(max_value) AS max_value,
        MIN(min_value) AS min_value,
        SUM(sum_value) AS sum_value,
        SUM(count_value) AS count_value -- sum of aggregated counts
    FROM {source}
    GROUP BY 1, 2, 3;
    """

