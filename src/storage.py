"""DynamoDB storage operations for sync state management."""

from datetime import datetime
from typing import Any

import boto3
import structlog
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError, NoCredentialsError

from .config import DynamoDBConfig
from .models import SyncDirection, SyncRecord, SyncStatus

logger = structlog.get_logger()


class StorageError(Exception):
    """Custom exception for storage operations."""

    pass


class DynamoDBStorage:
    """DynamoDB storage for sync state management."""

    def __init__(self, config: DynamoDBConfig) -> None:
        """Initialize DynamoDB storage."""
        self.config = config
        self.table_name = config.table_name

        try:
            self.dynamodb = boto3.resource("dynamodb", region_name=config.region)
            self.table = self.dynamodb.Table(self.table_name)
        except NoCredentialsError as e:
            raise StorageError(f"AWS credentials not found: {e}") from e
        except Exception as e:
            raise StorageError(f"Failed to initialize DynamoDB: {e}") from e

    def create_table_if_not_exists(self) -> None:
        """Create DynamoDB table if it doesn't exist."""
        try:
            # Check if table exists
            self.table.load()
            logger.info("DynamoDB table already exists", table_name=self.table_name)
            return
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise StorageError(f"Error checking table existence: {e}") from e

        # Create table
        try:
            logger.info("Creating DynamoDB table", table_name=self.table_name)

            table = self.dynamodb.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {"AttributeName": "sync_id", "KeyType": "HASH"},  # Partition key
                ],
                AttributeDefinitions=[
                    {"AttributeName": "sync_id", "AttributeType": "S"},
                    {"AttributeName": "jira_1_key", "AttributeType": "S"},
                    {"AttributeName": "jira_2_key", "AttributeType": "S"},
                    {"AttributeName": "status", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "jira-1-key-index",
                        "KeySchema": [
                            {"AttributeName": "jira_1_key", "KeyType": "HASH"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                        "BillingMode": "PAY_PER_REQUEST",
                    },
                    {
                        "IndexName": "jira-2-key-index",
                        "KeySchema": [
                            {"AttributeName": "jira_2_key", "KeyType": "HASH"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                        "BillingMode": "PAY_PER_REQUEST",
                    },
                    {
                        "IndexName": "status-index",
                        "KeySchema": [
                            {"AttributeName": "status", "KeyType": "HASH"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                        "BillingMode": "PAY_PER_REQUEST",
                    },
                ],
                BillingMode="PAY_PER_REQUEST",
                Tags=[
                    {"Key": "Application", "Value": "jira-sync"},
                    {"Key": "Environment", "Value": "production"},
                ],
            )

            # Wait for table to be created
            table.wait_until_exists()
            logger.info("DynamoDB table created successfully", table_name=self.table_name)

        except ClientError as e:
            raise StorageError(f"Failed to create DynamoDB table: {e}") from e

    def save_sync_record(self, record: SyncRecord) -> None:
        """Save sync record to DynamoDB."""
        try:
            item = self._sync_record_to_item(record)

            logger.info(
                "Saving sync record",
                sync_id=record.sync_id,
                status=record.status,
            )

            self.table.put_item(Item=item)

        except ClientError as e:
            error_msg = f"Failed to save sync record {record.sync_id}: {e}"
            logger.error("Error saving sync record", error=error_msg)
            raise StorageError(error_msg) from e

    def get_sync_record(self, sync_id: str) -> SyncRecord | None:
        """Get sync record by sync_id."""
        try:
            response = self.table.get_item(Key={"sync_id": sync_id})

            if "Item" not in response:
                return None

            return self._item_to_sync_record(response["Item"])

        except ClientError as e:
            error_msg = f"Failed to get sync record {sync_id}: {e}"
            logger.error("Error getting sync record", error=error_msg)
            raise StorageError(error_msg) from e

    def find_sync_record_by_jira_key(
        self,
        jira_key: str,
        jira_instance: int,  # 1 or 2
    ) -> SyncRecord | None:
        """Find sync record by JIRA key from either instance."""
        if jira_instance not in (1, 2):
            raise ValueError("jira_instance must be 1 or 2")

        try:
            index_name = f"jira-{jira_instance}-key-index"
            key_attr = f"jira_{jira_instance}_key"

            response = self.table.query(
                IndexName=index_name,
                KeyConditionExpression=Key(key_attr).eq(jira_key),
            )

            if not response["Items"]:
                return None

            # Return the first match (should be unique)
            return self._item_to_sync_record(response["Items"][0])

        except ClientError as e:
            error_msg = f"Failed to find sync record by {key_attr}={jira_key}: {e}"
            logger.error("Error finding sync record", error=error_msg)
            raise StorageError(error_msg) from e

    def get_records_by_status(self, status: SyncStatus) -> list[SyncRecord]:
        """Get all sync records with a specific status."""
        try:
            response = self.table.query(
                IndexName="status-index",
                KeyConditionExpression=Key("status").eq(status.value),
            )

            return [self._item_to_sync_record(item) for item in response["Items"]]

        except ClientError as e:
            error_msg = f"Failed to get records by status {status}: {e}"
            logger.error("Error getting records by status", error=error_msg)
            raise StorageError(error_msg) from e

    def delete_sync_record(self, sync_id: str) -> None:
        """Delete sync record from DynamoDB."""
        try:
            logger.info("Deleting sync record", sync_id=sync_id)

            self.table.delete_item(Key={"sync_id": sync_id})

        except ClientError as e:
            error_msg = f"Failed to delete sync record {sync_id}: {e}"
            logger.error("Error deleting sync record", error=error_msg)
            raise StorageError(error_msg) from e

    def get_all_sync_records(self, limit: int | None = None) -> list[SyncRecord]:
        """Get all sync records with optional limit."""
        try:
            scan_kwargs = {}
            if limit:
                scan_kwargs["Limit"] = limit

            response = self.table.scan(**scan_kwargs)

            records = [self._item_to_sync_record(item) for item in response["Items"]]

            # Handle pagination if needed
            while "LastEvaluatedKey" in response and (not limit or len(records) < limit):
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                if limit:
                    scan_kwargs["Limit"] = limit - len(records)

                response = self.table.scan(**scan_kwargs)
                records.extend([self._item_to_sync_record(item) for item in response["Items"]])

            return records

        except ClientError as e:
            error_msg = f"Failed to get all sync records: {e}"
            logger.error("Error getting all sync records", error=error_msg)
            raise StorageError(error_msg) from e

    def _sync_record_to_item(self, record: SyncRecord) -> dict[str, Any]:
        """Convert SyncRecord to DynamoDB item."""
        item = {
            "sync_id": record.sync_id,
            "status": record.status.value,
            "last_sync_timestamp": record.last_sync_timestamp.isoformat(),
            "error_count": record.error_count,
            "requires_manual_resolution": record.requires_manual_resolution,
        }

        # Optional fields
        if record.jira_1_key:
            item["jira_1_key"] = record.jira_1_key
        if record.jira_2_key:
            item["jira_2_key"] = record.jira_2_key
        if record.last_sync_direction:
            item["last_sync_direction"] = record.last_sync_direction.value
        if record.jira_1_last_updated:
            item["jira_1_last_updated"] = record.jira_1_last_updated.isoformat()
        if record.jira_2_last_updated:
            item["jira_2_last_updated"] = record.jira_2_last_updated.isoformat()
        if record.last_error:
            item["last_error"] = record.last_error
        if record.conflict_details:
            item["conflict_details"] = record.conflict_details

        return item

    def _item_to_sync_record(self, item: dict[str, Any]) -> SyncRecord:
        """Convert DynamoDB item to SyncRecord."""
        return SyncRecord(
            sync_id=item["sync_id"],
            jira_1_key=item.get("jira_1_key"),
            jira_2_key=item.get("jira_2_key"),
            status=SyncStatus(item["status"]),
            last_sync_direction=(SyncDirection(item["last_sync_direction"]) if "last_sync_direction" in item else None),
            last_sync_timestamp=datetime.fromisoformat(item["last_sync_timestamp"]),
            jira_1_last_updated=(
                datetime.fromisoformat(item["jira_1_last_updated"]) if "jira_1_last_updated" in item else None
            ),
            jira_2_last_updated=(
                datetime.fromisoformat(item["jira_2_last_updated"]) if "jira_2_last_updated" in item else None
            ),
            error_count=item.get("error_count", 0),
            last_error=item.get("last_error"),
            requires_manual_resolution=item.get("requires_manual_resolution", False),
            conflict_details=item.get("conflict_details"),
        )
