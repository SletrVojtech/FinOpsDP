<img src="https://fit.cvut.cz/static/images/fit-cvut-logo-en.svg" alt="FIT CTU logo" height="200">

This software was developed with the support of the **Faculty of Information Technology, Czech Technical University in Prague**.
For more information, visit [fit.cvut.cz](https://fit.cvut.cz).

# FinOpsDP

A FinOps platform for multi-cloud cost visibility, chargeback, and resource optimisation. Developed as a diploma thesis at the **Faculty of Information Technology, Czech Technical University in Prague**.

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Deploying with Helm](#deploying-with-helm)
- [Local Development (Docker Compose)](#local-development-docker-compose)
- [Running Tests](#running-tests)
- [Generating Documentation](#generating-documentation)
- [Configuration Reference](#configuration-reference)
- [License](#license)

---

## Overview

FinOpsDP ingests billing data from **Azure** and **AWS**, Kubernetes workload metrics via **Prometheus**, and VM performance telemetry. It provides:

| Feature | Description |
|---|---|
| **Chargeback dashboard** | Daily cost charts with forecast (AutoARIMA), budget tracking, and anomaly detection |
| **Allocation rules** | Redistribute a percentage of one scope's costs to another |
| **VM rightsizing** | Compares running instance telemetry against a hardware catalogue and recommends cheaper alternatives |
| **KRR integration** | Displays Robusta KRR Kubernetes resource recommendations per workload |
| **Scope explorer** | Hierarchical entity browser with tag-based filtering |
| **Metrics viewer** | Time-series charts for VM CPU, RAM, disk, and network metrics |

---

## Prerequisites

- Kubernetes cluster (tested on AKS) with `kubectl` configured
- Helm ≥ 3.10
- A TimescaleDB/PostgreSQL instance reachable from the cluster
- A RabbitMQ instance (included in the Helm chart)
- Azure SPN **and/or** AWS IAM user credentials with billing read access

---

## Deploying with Helm

The Helm chart lives in the `chart/` directory.

### 1. Prepare a secrets file

Copy the example and fill in real values (this file should **not** be committed):

```bash
cp chart/secrets.example.yml chart/secrets.yml
```

### 2. (Optional) Customise values

Edit `chart/values.yml` to change the image registry, tag, or feature flags:

```yaml
image:
  repository: finopsdp.azurecr.io
  tag: latest

```

### 3. Install / upgrade the release

```bash
helm upgrade --install finops ./chart \
  --namespace finops --create-namespace \
  -f chart/secrets.yml
```

### 4. Verify the rollout

```bash
kubectl -n finops get pods
kubectl -n finops logs -l app=webapp --tail=50
```

### 5. Uninstall

```bash
helm uninstall finops -n finops
```

---
## Configuration Reference

Detailed configuration schema for all YAML files (`accounts.yml`, `subscriptions.yml`, `cost_exports.yml`, `kube_clusters.yml`, `scheduler.yml`, `metrics.yml`, `db_config.yml`) and all `.env` files is documented in **[ConfDoc_cs.md](ConfDoc_cs.md)**.

Example configuration files for the Helm chart are provided in **[chart/conf_examples/](chart/conf_examples/)**.

---



## Local Development (Docker Compose)

For a quick local setup without Kubernetes:
Set up the environment variables file and fill in your own configuration. (see **[ConfDoc.md](ConfDoc_cs.md)**):


```bash
docker compose up --build -d
```

The webapp is then available at **http://localhost:8080**.

---

## Running Tests

Both the `webapp` and `data_collector` packages have independent test suites using **pytest**.

### Webapp tests

```bash
cd webapp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-tests.txt

# Run all tests
pytest tests/ -v

```

### Data collector tests

```bash
cd data_collector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-tests.txt

pytest tests/ -v
```

---

## Generating Documentation

The codebase uses **Google-style docstrings**. The recommended tool is **[pdoc](https://pdoc.dev)** - reads Google style docstrings and runs directly inside each package's existing venv.

Each package is documented independently from inside its own directory.

### Webapp

```bash
cd webapp
source .venv/bin/activate

PYTHONPATH=. pdoc services crud routers jobs 
    --docformat google
```

### Data Collector

```bash
cd data_collector
source .venv/bin/activate

PYTHONPATH=. pdoc cost_collector metrics_collector kube_collector krr_collector \
        catalog_collector db_loader \
    --docformat google
```


---

## License

Licensed under the **Apache License 2.0** — see [LICENSE.txt](LICENSE.txt) for the full text.

Copyright 2026 Vojtěch Šletr