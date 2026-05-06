# Dokumentace pro nastavení konfiguračních souborů

V této sekci jsou popsána doporučená schemata konfiguračních souborů

## Rozmístění

Aktuální struktura konfiguračních souborů a .env souborů pro Docker Compose:

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

Soubor pro definici AWS účtů. Definuje seznam účtů, a roli pomocí které se dotazuje na AWS API.
Povinná pole jsou account_id, name, role.

### Ukázkový template

```yaml
accounts:
- account_id: '0000000'
  name: AWSMain
  role: arn:aws:iam::00000:role/Reader
```

Role na kterou se přihlašuje zadaný IAM User vyžaduje sadu politik AmazonEC2ReadOnlyAccess (pro sběr metrik)
a sadu oprávnění pro načtení CUR 

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

Soubor pro definici Azure účtů. Definuje seznam, povinné parametry jsou name a subscriptionID

### Ukázkový template

```yaml
subscriptions:
- name: Name
  subscription_id: 000-00-0000
```

Azure Service Pricipal vyžaduje tato oprávnění:

    -  Reader - pro dotazování API na metadata a metriky

    -  Cost Management Reader - dotazování na cestu k poslednímu proběhlému exportu

    -  Billing Account Reader - dotazování na cestu k poslednímu proběhlému exportu

    -  Storage Blob Data Reader - čtení/stahování exportu z daného úložiště

## Cost_exports.yml

Definuje seznamy účtů (AWS i Azure), ze kterých má proběhnout stahování vygenerovaných Cost Exports / CUR.
Potřebný pouze pro cost_collector module (definován jako 'costs' pro spuštění schedulerem).

U Azure je třeba rozlišovat mezi použitým endpointem api. Využívejte ['billing_id', 'subscription_id'] a případné podskupiny těchto endpointů jako součást ID.

V případě vynechání názvu exportu, je volen pvní nalezený.

### Ukázkový template

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

Definuje seznam K8s clusterů pro sběr požadavků seskupených dle namespace. Kontext clusteru musí odpovídat kontextu poskytnutém v kubeconfigu.

Položky provider, account_id, cluster_resource_id jsou využívány pro vytvoření hierarchie v úložném systému.
Labels jsou volitelné, ovšem bez jejich definice budou namespaces opatřeny pouze záklladními tagy {'cluster': cluster_name, 'namespace': namespace}

Při dotazování se Promethea se specifickým nastavením, je možné dodat definice, kde jej na clusteru hledat.

### Ukázkový template

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

Tento soubor je využíván pouze při spouštění pomocí Docker Compose s vestavěným plánovačem sběru metrik. Lze dynamicky definovat pro metrics, costs, kube, catalogs.

Rozlišuje mezi 'interval' - každých x jednotek ['hours', 'minutes', 'days', 'weeks', 'months'] a 'time' - v konkrétní čas [HH:MM]


### Ukázkový template

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

Slouží k nastavení sbíraných metrik. Run_frequency_hours ovlivňuje jak velké časové okno se má dotazovat.
Granularita vychází z Azure API a je překládána pro AWS: ['PT5M','PT15M', 'PT30M', 'PT1H', 'P1D']
Názvy metrik jsou unifikované a jejich překlady na volané API hodnoty jsou zadefinovány v metrics_definitions.yml.
Jelikož některé agregace nejsou v základu podporovány v API, dodatečný překlad pomocí aplikace transformačních funkcí je definován v data_collector/policy_templates/metric_definition.py
V základu je používáno průměrováni (avg)


### Ukázkový template

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

Nastavuje definice agregačních tabulek v TimeScaleDB (PostgreSQL) a retenční politiky uchování dat.
Agregáty jsou v tuto chvíli využívány pouze pro metrics. Pro Cost Exports vychází interval z možností cloud providerů a Azure nepodporuje nižší agregaci než hodinovou. KubeMetrics jsou dotazovány po hodinových oblastech.

### Ukázkový template

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

Nastavení Azure SPN:
subcription může být jakékoliv platné, je využíváno pro stahování ceníkových katalogů

```yaml
AZURE_SUBSCRIPTION_ID=
AZURE_CLIENT_ID=
AZURE_CLIENT_SECRET=
AZURE_TENANT_ID=

#Nastavení AWS usera který následně používá AssumeRole

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

#Připojení kolektorů k RabbitMQ

RMQ_HOST=
RMQ_PORT=
RMQ_USER=
RMQ_PASSWORD=

#Venkovní přístup k rabbitmq
RMQ_HOST_PORT=5672
RMQ_UI_PORT=15672
RMQ_HOST_LOCAL=localhost
```

## ENV.web

Příprava na modulární funkcionalitu webu.

```yaml
ENABLE_METRICS=True
ENABLE_COSTS=True
```

## ENV

Sdílené připojení k DB

```yaml
DB_HOST=timescaledb
DB_PORT=5432
DB_USER=
DB_PASSWORD=
DB_NAME=

DB_HOST_PORT=5432
#Potřeba dosadit za absolutní cestu před sestavením Docker Compose 
KUBECONFIG_PATH="~/.kube/config"
```