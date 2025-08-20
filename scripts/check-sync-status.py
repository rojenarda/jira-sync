#!/usr/bin/env python3
"""Script to check sync status and troubleshoot issues."""

import os
import sys
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


def get_dynamodb_table(table_name: str, region: str = "us-east-1"):
    """Get DynamoDB table resource."""
    dynamodb = boto3.resource("dynamodb", region_name=region)
    return dynamodb.Table(table_name)


def get_all_sync_records(table) -> list[dict[str, Any]]:
    """Get all sync records from DynamoDB."""
    response = table.scan()
    items = response["Items"]

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response["Items"])

    return items


def get_sync_record_by_id(table, sync_id: str) -> dict[str, Any] | None:
    """Get specific sync record by ID."""
    response = table.get_item(Key={"sync_id": sync_id})
    return response.get("Item")


def get_records_by_status(table, status: str) -> list[dict[str, Any]]:
    """Get records with specific status."""
    response = table.query(
        IndexName="status-index",
        KeyConditionExpression=Key("status").eq(status),
    )
    return response["Items"]


def print_sync_summary(records: list[dict[str, Any]]) -> None:
    """Print summary of sync records."""
    status_counts = {}
    conflict_count = 0
    error_count = 0

    for record in records:
        status = record.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

        if record.get("requires_manual_resolution", False):
            conflict_count += 1

        if record.get("error_count", 0) > 0:
            error_count += 1

    print("📊 Sync Status Summary")  # noqa: T201
    print("=" * 40)  # noqa: T201
    print(f"Total records: {len(records)}")  # noqa: T201
    print(f"Records with conflicts: {conflict_count}")  # noqa: T201
    print(f"Records with errors: {error_count}")  # noqa: T201
    print()  # noqa: T201

    print("Status breakdown:")  # noqa: T201
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")  # noqa: T201
    print()  # noqa: T201


def print_detailed_record(record: dict[str, Any]) -> None:
    """Print detailed information about a sync record."""
    print(f"🔍 Sync Record: {record.get('sync_id', 'unknown')}")  # noqa: T201
    print("-" * 50)  # noqa: T201
    print(f"JIRA 1 Key: {record.get('jira_1_key', 'N/A')}")  # noqa: T201
    print(f"JIRA 2 Key: {record.get('jira_2_key', 'N/A')}")  # noqa: T201
    print(f"Status: {record.get('status', 'unknown')}")  # noqa: T201
    print(f"Last Sync: {record.get('last_sync_timestamp', 'N/A')}")  # noqa: T201
    print(f"Direction: {record.get('last_sync_direction', 'N/A')}")  # noqa: T201
    print(f"Error Count: {record.get('error_count', 0)}")  # noqa: T201

    if record.get("last_error"):
        print(f"Last Error: {record['last_error']}")  # noqa: T201

    if record.get("requires_manual_resolution"):
        print("⚠️  REQUIRES MANUAL RESOLUTION")  # noqa: T201
        if record.get("conflict_details"):
            print(f"Conflict Details: {record['conflict_details']}")  # noqa: T201

    print()  # noqa: T201


def main() -> None:
    """Run the sync status checker."""
    table_name = os.getenv("DYNAMODB_TABLE_NAME", "jira-sync-state")
    region = os.getenv("AWS_REGION", "us-east-1")

    if len(sys.argv) < 2:
        print("Usage: python check-sync-status.py <command> [args]")  # noqa: T201
        print()  # noqa: T201
        print("Commands:")  # noqa: T201
        print("  summary                    - Show sync status summary")  # noqa: T201
        print("  failed                     - Show failed sync records")  # noqa: T201
        print("  conflicts                  - Show records with conflicts")  # noqa: T201
        print("  record <sync_id>          - Show specific record details")  # noqa: T201
        print("  all                       - Show all records")  # noqa: T201
        print()  # noqa: T201
        print("Environment variables:")  # noqa: T201
        print(f"  DYNAMODB_TABLE_NAME={table_name}")  # noqa: T201
        print(f"  AWS_REGION={region}")  # noqa: T201
        sys.exit(1)

    command = sys.argv[1].lower()

    try:
        table = get_dynamodb_table(table_name, region)

        if command == "summary":
            records = get_all_sync_records(table)
            print_sync_summary(records)

        elif command == "failed":
            records = get_records_by_status(table, "failed")
            print(f"Found {len(records)} failed sync records:")  # noqa: T201
            print()  # noqa: T201
            for record in records:
                print_detailed_record(record)

        elif command == "conflicts":
            records = get_all_sync_records(table)
            conflict_records = [r for r in records if r.get("requires_manual_resolution")]
            print(f"Found {len(conflict_records)} records with conflicts:")  # noqa: T201
            print()  # noqa: T201
            for record in conflict_records:
                print_detailed_record(record)

        elif command == "record":
            if len(sys.argv) < 3:
                print("Error: sync_id required for 'record' command")  # noqa: T201
                sys.exit(1)

            sync_id = sys.argv[2]
            record = get_sync_record_by_id(table, sync_id)
            if record:
                print_detailed_record(record)
            else:
                print(f"❌ Sync record '{sync_id}' not found")  # noqa: T201

        elif command == "all":
            records = get_all_sync_records(table)
            print_sync_summary(records)
            print("All sync records:")  # noqa: T201
            print()  # noqa: T201
            for record in records:
                print_detailed_record(record)

        else:
            print(f"❌ Unknown command: {command}")  # noqa: T201
            sys.exit(1)

    except Exception as e:
        print(f"❌ Error: {e}")  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
