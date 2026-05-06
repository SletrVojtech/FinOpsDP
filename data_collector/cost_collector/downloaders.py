"""
Cost Downloaders Module.

This module contains worker processes for downloading cost and usage
reports from AWS (CUR) and Azure (Cost Exports).
"""

import os
import json
import logging
import requests
from botocore.exceptions import ClientError
from c7n_org.cli import get_session
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient


def run_aws_worker_process(account: dict, export_name: str, region: str, output_dir: str):
    """
    Wrapper function to initialize and run the AWS export worker.

    Args:
        account (dict): The AWS account configuration dictionary.
        export_name (str): The name of the AWS export to download.
        region (str): The AWS region where the export is configured.
        output_dir (str): The target directory to store downloaded files.

    Returns:
        tuple: A tuple containing the list of downloaded file paths and a boolean indicating success.
    """
    worker = AwsExportWorker(account, export_name, region, output_dir)
    return worker.run()

def run_azure_worker_process(scope_type: str, scope_id: str, output_dir: str, export_name: str = None):
    """
    Wrapper function to initialize and run the Azure export worker.

    Args:
        scope_type (str): The type of the Azure scope ('billing' or 'subscription').
        scope_id (str): The ID of the Azure scope.
        output_dir (str): The target directory to store downloaded files.
        export_name (str, optional): The name of the Azure export to download.

    Returns:
        tuple: A tuple containing the list of downloaded file paths and a boolean indicating success.
    """
    worker = AzureExportWorker(scope_type, scope_id, output_dir, export_name)
    return worker.run()


class AwsExportWorker:
    """
    Worker for finding a CUR export for a given AWS account,
    searching for the latest run, and downloading the files.
    """

    def __init__(self, account: dict, export_name: str, region: str, output_dir: str):
        """
        Initialize the AWS export worker.

        Args:
            account (dict): The AWS account configuration dictionary.
            export_name (str): The name of the AWS export to download.
            region (str): The AWS region where the export is configured.
            output_dir (str): The target directory to store downloaded files.
        """
        self.account = account
        self.export_name = export_name
        self.region = region
        self.output_dir = output_dir
        self.account_name = account.get('name', 'unknown')
        self.account_id = account.get('account_id')
        self.short_id = self.account_id[:8]
        self.log = logging.getLogger("cost_download_worker")

    def _get_export(self) -> tuple[str, str]:
        """
        Find configured CUR among all available exports.

        Returns:
            tuple: A tuple containing the S3 bucket name and S3 prefix.

        Raises:
            ValueError: If the export is not found.
        """
        target_arn = None
        self.session = get_session(self.account, 'custodian', self.region)
        bcm = self.session.client('bcm-data-exports')
        # iterate through all available exports
        paginator = bcm.get_paginator('list_exports')
        for page in paginator.paginate():
            for exp in page.get('Exports', []):
                if exp.get('ExportName') == self.export_name:
                    target_arn = exp.get('ExportArn')
                    break
            if target_arn:
                break
        
        if not target_arn:
            raise ValueError(f"Export '{self.export_name}' not found.")
        # Based on https://docs.aws.amazon.com/boto3/latest/reference/services/bcm-data-exports/client/get_export.html
        full_export = bcm.get_export(ExportArn=target_arn)
        dest = full_export['Export']['DestinationConfigurations']['S3Destination']
        return dest['S3Bucket'], dest['S3Prefix']
    
    def _find_newest_Manifest(self) -> str | None:
        """
        From the latest run of the export, find the manifest with locations of the data files.

        Returns:
            str: The S3 key of the newest manifest file, or None if not found.
        """
        # Based on https://docs.aws.amazon.com/boto3/latest/reference/services/s3/paginator/ListObjectsV2.html
        manifest_prefix = f"{self.prefix}/{self.export_name}/metadata/"
        paginator = self.s3.get_paginator('list_objects_v2')
        latest_manifest_key, latest_time = None, None
        # iterate over the existing manifests.
        for page in paginator.paginate(Bucket=self.bucket, Prefix=manifest_prefix):
            for obj in page.get('Contents', []):
                if obj['Key'].endswith('.json') and 'Manifest.json' in obj['Key']:
                    if not latest_time or obj['LastModified'] > latest_time:
                        latest_time, latest_manifest_key = obj['LastModified'], obj['Key']

        if not latest_manifest_key:
            self.log.warning(f"[{self.account_name}] Manifest not found in s3://{self.bucket}/{manifest_prefix}")
            return None

        return latest_manifest_key
    
    def _download_files(self, latest_manifest_key: str) -> list[str]:
        """
        Download the data files and temporarily save them.

        Args:
            latest_manifest_key (str): The S3 key to the manifest file.

        Returns:
            list: A list of local file paths where the data files were saved.
        """
        downloaded_files = []
        manifest_obj = self.s3.get_object(Bucket=self.bucket, Key=latest_manifest_key)
        manifest_data = json.loads(manifest_obj['Body'].read().decode('utf-8'))
        for s3_key in manifest_data.get('dataFiles', manifest_data.get('dataKeys', [])):
            file_name = s3_key.split('/')[-1]
            target_path = os.path.join(self.target_folder, file_name)
            if s3_key.startswith("s3://"):
                s3_key = s3_key.split('/',3)[-1]
            self.s3.download_file(self.bucket, s3_key, target_path)
            downloaded_files.append(target_path)
        return downloaded_files


    def run(self) -> tuple[list[str], bool]:
        """
        Execute the download workflow for the AWS account.

        Returns:
            tuple: A tuple of (list of downloaded files, success boolean).
        """
        self.log.info(f"[{self.account_name}] Begin download cost export: {self.export_name}")
        try:
            self.bucket, self.prefix = self._get_export()
            self.s3 = self.session.client('s3')
            latest_manifest_key = self._find_newest_Manifest()
            if not latest_manifest_key:
                return [], True
            self.target_folder = os.path.join(self.output_dir, f"aws_{self.short_id}_{self.export_name}")
            os.makedirs(self.target_folder, exist_ok=True)
            downloaded_files = self._download_files(latest_manifest_key)
            self.log.info(f"[{self.account_name}] Successfully downloaded {len(downloaded_files)} files.")
            return downloaded_files, True
        except Exception as e:
            self.log.error(f"[{self.account_name}] Error during AWS data download: {e}")
            return [], False




class AzureExportWorker:
    """
    Worker for downloading Azure Cost Management exports based on billing or subscription scope.
    """
    def __init__(self, scope_type: str, scope_id: str, output_dir: str, export_name: str):
        """
        Initialize the Azure export worker.

        Args:
            scope_type (str): The scope type ('billing' or 'subscription').
            scope_id (str): The ID of the billing account or subscription.
            output_dir (str): The target directory to store downloaded files.
            export_name (str): The name of the Azure export to download.
        """
        if scope_type == 'billing':
            self.scope = f"/providers/Microsoft.Billing/billingAccounts/{scope_id}"
        elif scope_type == 'subscription':
            self.scope = f"/subscriptions/{scope_id}"
        else:
            self.scope =  None
        self.short_id = scope_id[:8]
        self.scope_id = scope_id
        self.output_dir = output_dir
        self.export_name = export_name
        self.api_version = "2025-03-01"
        self.log = logging.getLogger("azure_cost_worker")


    def _get_token(self) -> None:
        """
        Acquire an Azure access token for the management API.
        """
        self.credential = DefaultAzureCredential()
        token = self.credential.get_token("https://management.azure.com/.default")
        self.headers = {'Authorization': f'Bearer {token.token}'}

    def _get_export_name(self) -> str | None:
        """
        Load existing Cost exports for different scopes and match if a name was given.
        
        Returns:
            str: The name of the export, or None if not found.
        """
        # Based on https://learn.microsoft.com/en-us/rest/api/cost-management/exports/get?view=rest-cost-management-2023-11-01&tabs=HTTP
        export_url = f"https://management.azure.com{self.scope}/providers/Microsoft.CostManagement/exports?api-version={self.api_version}"
        resp = requests.get(export_url, headers=self.headers)
        resp.raise_for_status()
        exports = resp.json().get('value', [])

        if not exports:
            self.log.warning(f"[Azure-{self.short_id}] No exports found for  {self.scope}.")
            return None

        if self.export_name:
            target_export = next((e for e in exports if e['name'] == self.export_name), None)
            if not target_export:
                self.log.warning(f"[Azure-{self.short_id}] No export named '{self.export_name}' found.")
                return None
            
            return target_export['name']
        else:
            return exports[0]['name']
    
    def _get_history(self, actual_export_name: str) -> list[dict]:
        """
        Extract information from the newest successful cost export runs.
        
        Args:
            actual_export_name (str): The name of the export to fetch history for.

        Returns:
            list: A list of run properties for the latest completed runs.
        """
        # Based on https://learn.microsoft.com/en-us/rest/api/cost-management/exports/get-execution-history?view=rest-cost-management-2025-03-01&tabs=HTTP
        history_url = f"https://management.azure.com{self.scope}/providers/Microsoft.CostManagement/exports/{actual_export_name}/runHistory?api-version={self.api_version}"
        history_resp = requests.get(history_url, headers=self.headers)
        history_resp.raise_for_status()
        runs = history_resp.json().get('value', [])

        completed_runs = [r.get('properties', {}) for r in runs if r.get('properties', {}).get('status') == 'Completed']
        
        if not completed_runs:
            self.log.warning(f"[Azure-{self.short_id}] No completed runs found.")
            return []

        latest_run = completed_runs[0]
        latest_date = latest_run.get('processingEndTime', latest_run.get('submittedTime', ''))[:10]
        
        target_runs = [latest_run]
        
        if len(completed_runs) > 1:
            next_run = completed_runs[1]
            next_date = next_run.get('processingEndTime', next_run.get('submittedTime', ''))[:10]
            if latest_date and latest_date == next_date:
                target_runs.append(next_run)

        return target_runs
    
    def _get_manifest(self, props: dict) -> list[dict] | None:
        """
        Extract the location of the Manifest file from the latest export run and download it.
        
        Args:
            props (dict): The properties of the export run.

        Returns:
            list: A list of blob dictionaries contained in the manifest, or None if failed.
        """
        manifest_path = props.get('manifestFile')
        if not manifest_path:
            self.log.error(f"[Azure-{self.short_id}] RunHistory doesn't contain manifestFile).")
            return None

        delivery_dest = props.get('runSettings', {}).get('deliveryInfo', {}).get('destination', {})
        resource_id = delivery_dest.get('resourceId', '')
        container_name = delivery_dest.get('container', '')
        
        if not resource_id or not container_name:
            self.log.error(f"[Azure-{self.short_id}] missing resourceId or container in runSettings.")
            return None

        storage_account_name = resource_id.split('/')[-1]

        # Needs to be a json file
        if not manifest_path.endswith('.json'):
            manifest_path = f"{manifest_path}/manifest.json"
        self.log.info(manifest_path)
        # Assemble the URL
        self.base_url = f"https://{storage_account_name}.blob.core.windows.net/{container_name}/"
        manifest_url = f"{self.base_url}{manifest_path}"
        
        self.log.info(f"[Azure-{self.short_id}] Manifest URL {manifest_url}")

        # Download the Manifest file and extract the blobs
        # Based on https://learn.microsoft.com/en-us/python/api/overview/azure/storage-blob-readme?view=azure-python
        blob_client = BlobClient.from_blob_url(manifest_url, credential=self.credential)
        manifest_content = json.loads(blob_client.download_blob().readall())
        return manifest_content.get('blobs', [])

    def download(self, blobs: list[dict]) -> list[str]:
        """
        Download the data blobs to the local filesystem.

        Args:
            blobs (list): A list of dictionaries describing the blobs to download.

        Returns:
            list: A list of local paths where the blobs were downloaded.
        """
        downloaded_files = []
        for blob_info in blobs:
            blob_path = blob_info.get('blobName',None)
            if not blob_path:
                continue
            file_name = blob_path.split('/')[-1]
            data_url = f"{self.base_url}{blob_path}"
            target_path = os.path.join(self.target_folder, file_name)
            
            self.log.info(f"[Azure-{self.short_id}] Downloading: {file_name}")
            data_client = BlobClient.from_blob_url(data_url, credential=self.credential)
            
            with open(target_path, "wb") as f:
                f.write(data_client.download_blob().readall())
                
            downloaded_files.append(target_path)
        return downloaded_files
    
    def run(self) -> tuple[list[str], bool]:
        """
        Execute the download workflow for the Azure scope.

        Returns:
            tuple: A tuple of (list of downloaded files, success boolean).
        """
        self.log.info(f"[Azure-{self.short_id}] Downloading exports.")
        try:
            if not self.scope:
                return [], False
            self._get_token()
            actual_export_name = self._get_export_name()
            if not actual_export_name:
                return [], True
            target_runs = self._get_history(actual_export_name)
            if not target_runs:
                return [], True
            self.target_folder = os.path.join(self.output_dir, f"azure_{self.short_id}_{actual_export_name}")
            os.makedirs(self.target_folder, exist_ok=True)
            
            all_downloaded_files = []
            for props in target_runs:
                blobs = self._get_manifest(props)
                if not blobs:
                    continue
                downloaded_files = self.download(blobs)
                all_downloaded_files.extend(downloaded_files)

            self.log.info(f"[Azure-{self.short_id}] Successfully downloaded {len(all_downloaded_files)} files.")
            return all_downloaded_files, True

        except requests.exceptions.HTTPError as he:
            self.log.error(f"[Azure-{self.short_id}] API Management error: {he.response.text}")
            return [], False
        except Exception as e:
            self.log.error(f"[Azure-{self.short_id}] Error during Azure data download: {e}", exc_info=True)
            return [], False

        
