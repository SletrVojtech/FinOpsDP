import pytest
from unittest.mock import MagicMock, patch
from cost_collector.downloaders import AwsExportWorker, AzureExportWorker

@patch('cost_collector.downloaders.get_session')
@patch('cost_collector.downloaders.os.makedirs')
def test_aws_export_worker_success(mock_makedirs, mock_get_session):
    # Arrange
    account = {'name': 'Prod Account', 'account_id': '111122223333'}
    worker = AwsExportWorker(account, 'DailyExport', 'eu-central-1', '/tmp')

    mock_session = MagicMock()
    mock_get_session.return_value = mock_session
    mock_bcm_client = MagicMock()
    mock_s3_client = MagicMock()
    
    # get_session().client() should return client based on the name
    def mock_client(service_name):
        if service_name == 'bcm-data-exports': return mock_bcm_client
        if service_name == 's3': return mock_s3_client
    mock_session.client.side_effect = mock_client

    # Mocked Paginator for BCM
    mock_bcm_paginator = MagicMock()
    mock_bcm_paginator.paginate.return_value = [{'Exports': [{'ExportName': 'DailyExport', 'ExportArn': 'arn:aws:bcm:'}]}]
    mock_bcm_client.get_paginator.return_value = mock_bcm_paginator
    
    # Mocked get_export - returns bucket and prefix
    mock_bcm_client.get_export.return_value = {
        'Export': {'DestinationConfigurations': {'S3Destination': {'S3Bucket': 'my-billing-bucket', 'S3Prefix': 'exports'}}}
    }

    # Mocked S3 paginator for Manifest.json
    mock_s3_paginator = MagicMock()
    mock_s3_paginator.paginate.return_value = [{
        'Contents': [{'Key': 'exports/DailyExport/metadata/Manifest.json', 'LastModified': '2024-01-01'}]
    }]
    mock_s3_client.get_paginator.return_value = mock_s3_paginator

    # Mocked Manifest with 1 csv file link
    mock_manifest_body = MagicMock()
    mock_manifest_body.read.return_value = b'{"dataFiles": ["s3://my-billing-bucket/exports/data.csv.gz"]}'
    mock_s3_client.get_object.return_value = {'Body': mock_manifest_body}

    # Act
    downloaded_files, success = worker.run()

    # Assert
    assert success is True
    assert len(downloaded_files) == 1
    # Check for the S3 call
    mock_s3_client.download_file.assert_called_once()
    assert "exports/data.csv.gz" in mock_s3_client.download_file.call_args[0]


@patch('cost_collector.downloaders.DefaultAzureCredential')
@patch('cost_collector.downloaders.requests.get')
@patch('cost_collector.downloaders.BlobClient')
@patch('builtins.open', new_callable=MagicMock)
@patch('cost_collector.downloaders.os.makedirs')
def test_azure_export_worker_success(mock_makedirs, mock_open, mock_blob_client, mock_requests_get, mock_credential):
    # Arrange
    worker = AzureExportWorker(scope_type='subscription', scope_id='sub-123', output_dir='/tmp', export_name='AzureDaily')

    # Mock the session token
    mock_token = MagicMock()
    mock_token.token = 'fake_token'
    mock_credential.return_value.get_token.return_value = mock_token

    # Mock the requests for CostExport list and lastRun
    mock_resp1 = MagicMock()
    mock_resp1.json.return_value = {'value': [{'name': 'AzureDaily'}]}
    
    mock_resp2 = MagicMock()
    mock_resp2.json.return_value = {
        'value': [{
            'properties': {
                'status': 'Completed',
                'manifestFile': '20240101/manifest.json',
                'runSettings': {
                    'deliveryInfo': {'destination': {'resourceId': '/storage/myacc', 'container': 'exports'}}
                }
            }
        }]
    }
    mock_requests_get.side_effect = [mock_resp1, mock_resp2]

    # Mock the BobClient
    mock_blob_instance = MagicMock()
    mock_blob_client.from_blob_url.return_value = mock_blob_instance
    
    # Mock readAll for Manifest and CSV file
    mock_blob_instance.download_blob.return_value.readall.side_effect = [
        b'{"blobs": [{"blobName": "20240101/data.csv"}]}', # manifest content
        b'fake csv data' # data content
    ]

    # Act
    downloaded_files, success = worker.run()

    # Assert
    assert success is True
    assert len(downloaded_files) == 1
    assert "data.csv" in downloaded_files[0]
    
    # Check the write
    mock_open.assert_called()