"""
Kubernetes Prometheus Collector Module.

This module provides the KubePrometheusCollector class, which queries Prometheus
instances running inside Kubernetes clusters to collect resource usage metrics.
"""

import yaml
import logging
import time
from typing import List, Dict, Any, Optional
from kubernetes import client, config
from kube_collector.message import KubeMetricsPayload, Datapoint
from rabbitmq.message import IngestionMessage


log = logging.getLogger("kube_collector")

class KubePrometheusCollector:
    """
    Collector for Kubernetes metrics via Prometheus proxy.
    """
    def __init__(self, config_path: str, hours_back: int = 24):
        """
        Initialize the collector with configuration and time window.

        Args:
            config_path (str): Path to the clusters configuration YAML file.
            hours_back (int, optional): Number of hours of history to collect. Defaults to 24.
        """
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        self.hours_back = hours_back
        self.metrics_to_collect: List[Dict[str, Any]] = []

    def set_metrics(self, labels: List[str]):
        """
        Configure the list of metrics to collect based on namespace labels.

        Args:
            labels (List[str]): A list of namespace labels to include as tags.
        """
        list_of_labels = ",".join([f"label_{label}" for label in labels]) 

        self.metrics_to_collect = [
            {
                "resource": "cpu",
                "metric_name": "cpu_requests_cores",
                "query": '(sum by (namespace) (avg_over_time(kube_pod_container_resource_requests{resource="cpu"}[1h]))'
                ' unless on(namespace) kube_namespace_labels)'
                'or (sum by (namespace) (avg_over_time(kube_pod_container_resource_requests{resource="cpu"}[1h]))'
                f' * on(namespace) group_left({list_of_labels}) kube_namespace_labels)'
            },
            {
                "resource": "memory",
                "metric_name": "memory_requests_bytes",
                "query": '(sum by (namespace) (avg_over_time(kube_pod_container_resource_requests{resource="memory"}[1h]))'
                f' * on(namespace) group_left({list_of_labels}) kube_namespace_labels)'
                'or (sum by (namespace) (avg_over_time(kube_pod_container_resource_requests{resource="memory"}[1h]))'
                ' unless on(namespace) kube_namespace_labels)'
            }
        ]

    def collect_all(self) -> List[IngestionMessage]:
        """
        Iterates over all configured clusters and collects their metrics.

        Returns:
            List[IngestionMessage]: A list of all collected metric messages.
        """
        all_messages = []
        for cluster in self.config.get('clusters', []):
            try:
                cluster_messages = self._process_cluster(cluster)
                all_messages.extend(cluster_messages)
            except Exception as e:
                log.error(f"Error during processing cluster {cluster.get('cluster_name', 'unknown')}: {e}", exc_info=True)
                
        return all_messages

    def _process_cluster(self, cluster: Dict[str, Any]) -> List[IngestionMessage]:
        """
        Processes a single Kubernetes cluster to collect metrics.

        Args:
            cluster (Dict[str, Any]): The cluster configuration dictionary.

        Returns:
            List[IngestionMessage]: A list of messages collected from the cluster.
        """
        provider = cluster.get('provider')
        account_id = cluster.get('account_id')
        cluster_name = cluster.get('cluster_name')
        cluster_id = cluster.get('cluster_resource_id')
        context = cluster.get('context')

        if not all([provider, account_id, cluster_name, cluster_id, context]):
            log.error(f"Missing required fields for cluster: {cluster}")
            return []
        
        # Prometheus variables
        prom_conf = cluster.get('prometheus', {})
        namespace = prom_conf.get('namespace', 'monitoring')
        service = prom_conf.get('service_name', 'prometheus-kube-prometheus-prometheus')
        port = prom_conf.get('port', '9090')

        labels = cluster.get('labels', [])
        self.set_metrics(labels)
        
        log.info(f"Switching to context: {context}")
        try:
            api_client = config.new_client_from_config(context=context)
            v1 = client.CoreV1Api(api_client=api_client)
        except Exception as e:
            log.error(f"Failed to initialize Kubernetes client for context {context}: {e}")
            return []

        # Get the window
        end_time = int(time.time() // 3600) * 3600
        start_time = end_time - (self.hours_back * 3600)
        step = "1h"

        cluster_messages = []

        # Iterate over metrics
        for metric_def in self.metrics_to_collect:
            log.info(f"Downloading {metric_def['metric_name']} from {cluster_name}")
            name_with_port = f"http:{service}:{port}"
            query_params = [
                ('query', metric_def['query']),
                ('start', start_time),
                ('end', end_time),
                ('step', step)
            ]

            # Craft URL parameters
            path_params = {
                'name': name_with_port,
                'namespace': namespace,
                'path': 'api/v1/query_range'
            }
            auth_keys = list(api_client.configuration.auth_settings().keys())

            try:
                response = v1.api_client.call_api(
                    '/api/v1/namespaces/{namespace}/services/{name}/proxy/{path}', 
                    'GET',
                    path_params=path_params,
                    query_params=query_params,
                    auth_settings=auth_keys,
                    response_type='object',
                    _return_http_data_only=True
                )
                data = response
                messages = self._format_to_payload(
                    prom_data=data, 
                    provider=provider, 
                    account_id=account_id, 
                    cluster_name=cluster_name,
                    cluster_id=cluster_id,
                    metric_name=metric_def['metric_name']
                )
                cluster_messages.extend(messages)
            except client.exceptions.ApiException as api_err:
                log.error(f"K8s API error for {metric_def['metric_name']}: {api_err.status} - {api_err.reason}")
                log.error(api_err.body)

        return cluster_messages

    def _format_to_payload(self, prom_data: Dict[str, Any], provider: str, account_id: str, 
                           cluster_name: str, metric_name: str, cluster_id: str) -> List[IngestionMessage]:
        """
        Transforms Prometheus query results into a list of IngestionMessage objects.

        Args:
            prom_data (Dict[str, Any]): The raw data returned from Prometheus.
            provider (str): The cloud provider name.
            account_id (str): The cloud account ID.
            cluster_name (str): The name of the Kubernetes cluster.
            metric_name (str): The name of the metric being processed.
            cluster_id (str): The resource ID of the cluster.

        Returns:
            List[IngestionMessage]: A list of formatted ingestion messages.
        """
        messages = []
        cluster_urn = cluster_id

        for item in prom_data.get('data', {}).get('result', []):
            metric_labels = item.get('metric', {})
            ns = metric_labels.get('namespace')
            if not ns:
                continue
            # Add custom tags and merge with labels from Prometheus
            tags = {"cluster": cluster_name, "namespace": ns}
            for key, val in metric_labels.items():
                if key.startswith("label_"):
                    clean_key = key.replace("label_", "")
                    tags[clean_key] = val

            datapoint_objects = []
            for dp in item.get('values', []):
                datapoint_objects.append(
                    Datapoint(timestamp=dp[0], value=float(dp[1]))
                )
            
            if not datapoint_objects:
                continue

            namespace_urn = f"{cluster_urn}:namespace/{ns}"

            inner_payload = KubeMetricsPayload(
                cloud_provider=provider,
                account_id=account_id,
                resource_id=namespace_urn,
                resource_name=ns,
                metric_name=metric_name,
                metric_period=60,
                tags=tags,
                datapoints=datapoint_objects
            )

            envelope = IngestionMessage(
                source_module="kube_collector",
                payload=inner_payload.model_dump()
            )
            
            messages.append(envelope)
            
        return messages