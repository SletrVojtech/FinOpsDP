# Documentation of configuration files

In this section, the recommended schemas of configuration files are described.

## Location and structure of configuration files

Current structure of configuration files and .env files for Docker Compose:


```yaml
FinOpsDP
    - data_collector
        - .conf
            - accounts.yml
            - subscriptions.yml
            - cost_exports.yml
            - kube_clusters.yml
            - scheduler.yml
        - conf 
            - metrics.yml
        - db_init
            - db_config.yml
        - .env.collector (Docker Compose)
    - webapp
        - .env.web (Docker Compose)
    .env
```
## Accounts.yml

File for defining AWS accounts. Defines a list of accounts and the role used to query the AWS API.
Required fields are account_id, name, role.


### Example template

```yaml
accounts:
- account_id: '0000000'
  name: AWSMain
  role: arn:aws:iam::00000:role/Reader
```

Role, that the specified IAM User assumes, requires a set of AmazonEC2ReadOnlyAccess policies (for collecting metrics)
and a set of permissions to load CUR

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "Statement1",
            "Effect": "Allow",
            "Action": [
                "bcm-data-exports:GetExport",
                "bcm-data-exports:ListExports",
                "cur:DescribeReportDefinitions",
                "sts:GetCallerIdentity",
                "ce:GetCostAndUsage",
                "ec2:DescribeInstanceTypes"
            ],
            "Resource": [
                "*"
            ]
        },
        {
            "Sid": "S3DataAccess",
            "Effect": "Allow",
            "Action": [
                "s3:Get*",
                "s3:List*"
            ],
            "Resource": [
                "arn:aws:s3:::<bucket-name>",
                "arn:aws:s3:::<bucket-name>/*"
            ]
        }
    ]
}

```



## Subscriptions.yml

File for defining Azure accounts. Defines a list of accounts used to query the Azure API.
Required fields are name and subscription_id.

### Example template

```yaml
subscriptions:
- name: Name
  subscription_id: 000-00-0000
```

Azure Service Pricipal requires these permissions:


    -  Reader - for querying API on metadata and metrics

    -  Cost Management Reader - querying the path to the last completed export

    -  Billing Account Reader - querying the path to the last completed export

    -  Storage Blob Data Reader - reading/downloading export from the specified storage

## Cost_exports.yml

Defines lists of accounts (AWS and Azure) from which the generated Cost Exports / CUR should be downloaded.
Required only for the cost_collector module (defined as 'costs' for scheduler execution).

In Azure, it is necessary to distinguish between the used API endpoint. Use ['billing_id', 'subscription_id'] and possible subgroups of these endpoints as part of the ID.

In the case of omitting the export name, the first found one is chosen.


### Example template

```yaml
aws:
  - account_id: '0000'
    export_name: "DailyExport"
azure:
  - billing_id: "0000-0000-000-0000-000"
    export_name: "CostExport"
  - subscription_id: "0000-0000-000-0000-000"
    export_name: "CostExport"
```

## Kube_clusters.yml

Defines a list of K8s clusters for collecting requests grouped by namespace. The cluster context must match the context provided in the kubeconfig.

Items provider, account_id, cluster_resource_id are used to create a hierarchy in the storage system.
Labels are optional, but without their definition, namespaces will be tagged with only the basic tags {'cluster': cluster_name, 'namespace': namespace}

When querying Prometheus with a specific configuration, it is possible to provide definitions of where to look for the metrics on the cluster.

### Example template

```yaml
clusters:
  - provider: "azure"
    account_id: "000000000"
    cluster_name: "aks"
    cluster_resource_id: "/subscriptions/00000000000/resourceGroups/RG/providers/Microsoft.ContainerService/managedClusters/aks"
    labels: ["department", "cost_center","team"]
    context: "aks"
    prometheus: # defaults
      namespace: "monitoring"
      service_name: "prometheus-kube-prometheus-prometheus"
      port: "9090"
```

## Scheduler.yml

This file is only used when running with Docker Compose and the built-in metric collection scheduler. It allows dynamic definition for metrics, costs, kube, and catalogs.

It distinguishes between 'interval' - every x units ['hours', 'minutes', 'days', 'weeks', 'months'] and 'time' - at a specific time [HH:MM]


### Example template

```yaml
schedules:
  metrics:
    interval: 2
    unit: hours
    
  costs:
    time: "3:00"
    
  kube:
     time: "1:00"
     kwargs: # default
       hours: 24   
    
  catalogs:
    unit: months
    day_of_month: 2
    at: "2:00"
```

## Metrics.yml

Defines the metrics to be collected. Run_frequency_hours affects the size of the time window to query.
Granularity is derived from the Azure API and translated for AWS: ['PT5M','PT15M', 'PT30M', 'PT1H', 'P1D']
Metric names are unified and their translations to the called API values are defined in metrics_definitions.yml.
Since some aggregations are not natively supported in the API, additional translation using transformation functions is defined in data_collector/policy_templates/metric_definition.py
By default, averaging (avg) is used.

### Example template

```yaml
run_frequency_hours: 2
granularity: "PT5M"
measure:
  - resource: aws.ec2
    measurement:
      - metric: cpu_usage
        aggregate: ["avg", "max"]
      - metric: net_in
```

## Db_config.yml

Sets the definitions of aggregation tables in TimeScaleDB (PostgreSQL) and the retention policy for data storage.
Aggregates are currently used only for metrics. For Cost Exports, the interval is based on the options of cloud providers, and Azure does not support lower aggregation than daily. KubeMetrics are queried in hourly time frames.

### Example template

```yaml
data_hierarchy:
  metrics:
    raw_table: "metrics"
    raw_interval: "5 minutes"
    raw_retention: "7 days"
    aggregates:
      - name: "metrics_hourly"
        interval: "1 hour"
        retention: "1 month"
        refresh_window: "2 days"
      - name: "metrics_daily"
        interval: "1 day"
        retention: "2 years"
        refresh_window: "14 days"
  kubemetrics:
    raw_table: "kubemetrics"
    raw_interval: "1 hour"
    raw_retention: "6 months"
  costs:
    raw_table: "costs"
    raw_interval: "1 day"
    raw_retention: "3 years"
```

## ENV.collector

Setting up Azure SPN:
subscription can be any valid one, it is used for downloading pricing catalogs

```yaml
AZURE_SUBSCRIPTION_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
AZURE_TENANT_ID=

#AWS user settings that then uses AssumeRole

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

#Connection settings for collectors to RabbitMQ

RMQ_HOST=
RMQ_PORT=
RMQ_USER=
RMQ_PASSWORD=

#External access to rabbitmq
RMQ_HOST_PORT=5672
RMQ_UI_PORT=15672
RMQ_HOST_LOCAL=localhost
```

## ENV.web

Preparation for the modular functionality of the web.

```yaml
ENABLE_METRICS=True
ENABLE_COSTS=True
```

## ENV

Shared environment variables for both collector and web modules. Mainly database connection settings and kubeconfig path.

```yaml
DB_HOST=timescaledb
DB_PORT=5432
DB_USER=
DB_PASSWORD=
DB_NAME=

DB_HOST_PORT=5432
#Need to substitute with the absolute path before building Docker Compose 
KUBECONFIG_PATH="~/.kube/config"
```