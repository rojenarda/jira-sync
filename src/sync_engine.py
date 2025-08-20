"""Core sync engine for bidirectional JIRA synchronization."""

import time
from datetime import UTC, datetime

import structlog

from .config import SyncConfig
from .jira_client import JiraAPIError, JiraClient
from .models import (
    JiraIssue,
    SyncDirection,
    SyncRecord,
    SyncResult,
    SyncStatus,
)
from .storage import DynamoDBStorage, StorageError

logger = structlog.get_logger()


class SyncEngine:
    """Main synchronization engine for bidirectional JIRA sync."""

    def __init__(self, config: SyncConfig) -> None:
        """Initialize sync engine."""
        self.config = config
        self.jira_1 = JiraClient(config.jira_instance_1, sync_assignee=config.sync_assignee)
        self.jira_2 = JiraClient(config.jira_instance_2, sync_assignee=config.sync_assignee)
        self.storage = DynamoDBStorage(config.dynamodb)

    def initialize(self) -> None:
        """Initialize storage and ensure table exists."""
        logger.info("Initializing sync engine")
        self.storage.create_table_if_not_exists()

    def sync_issue_from_webhook(
        self,
        issue_key: str,
        source_instance: int,  # 1 or 2
    ) -> SyncResult:
        """Sync a single issue triggered by webhook."""
        logger.info(
            "Starting webhook-triggered sync",
            issue_key=issue_key,
            source_instance=source_instance,
        )

        if source_instance not in (1, 2):
            raise ValueError("source_instance must be 1 or 2")

        try:
            # Get the source issue
            source_client = self.jira_1 if source_instance == 1 else self.jira_2
            source_issue = source_client.get_issue(issue_key)

            # Find existing sync record
            sync_record = self.storage.find_sync_record_by_jira_key(issue_key, source_instance)

            if sync_record is None:
                # New issue - create sync record and sync to other instance
                return self._sync_new_issue(source_issue, source_instance)
            else:
                # Existing issue - update sync
                return self._sync_existing_issue(source_issue, sync_record, source_instance)

        except (JiraAPIError, StorageError) as e:
            error_msg = f"Sync failed for {issue_key}: {e}"
            logger.error("Sync failed", error=error_msg, issue_key=issue_key)

            # Try to update sync record with error
            if sync_record:
                sync_record.status = SyncStatus.FAILED
                sync_record.error_count += 1
                sync_record.last_error = error_msg
                sync_record.last_sync_timestamp = datetime.now(UTC)
                try:
                    self.storage.save_sync_record(sync_record)
                except StorageError:
                    logger.error("Failed to save error state to storage")

            return SyncResult(
                success=False,
                sync_record=sync_record or self._create_error_sync_record(issue_key, source_instance),
                error_message=error_msg,
            )

    def _sync_new_issue(self, source_issue: JiraIssue, source_instance: int) -> SyncResult:
        """Sync a new issue to the target instance."""
        target_instance = 2 if source_instance == 1 else 1
        target_client = self.jira_2 if source_instance == 1 else self.jira_1
        direction = SyncDirection.JIRA_1_TO_2 if source_instance == 1 else SyncDirection.JIRA_2_TO_1

        logger.info(
            "Syncing new issue",
            source_key=source_issue.key,
            direction=direction,
        )

        # Create sync record
        sync_id = self._generate_sync_id(source_issue.key, None)
        sync_record = SyncRecord(
            sync_id=sync_id,
            status=SyncStatus.IN_PROGRESS,
            last_sync_timestamp=datetime.now(UTC),
        )

        if source_instance == 1:
            sync_record.jira_1_key = source_issue.key
            sync_record.jira_1_last_updated = source_issue.updated
        else:
            sync_record.jira_2_key = source_issue.key
            sync_record.jira_2_last_updated = source_issue.updated

        # Save initial record
        self.storage.save_sync_record(sync_record)

        try:
            # Create issue in target instance
            create_payload = target_client.convert_to_create_payload(source_issue)
            target_issue = target_client.create_issue(create_payload)

            # Update sync record with target key
            if target_instance == 1:
                sync_record.jira_1_key = target_issue.key
                sync_record.jira_1_last_updated = target_issue.updated
            else:
                sync_record.jira_2_key = target_issue.key
                sync_record.jira_2_last_updated = target_issue.updated

            sync_record.status = SyncStatus.SUCCESS
            sync_record.last_sync_direction = direction
            sync_record.sync_id = self._generate_sync_id(sync_record.jira_1_key, sync_record.jira_2_key)

            self.storage.save_sync_record(sync_record)

            logger.info(
                "New issue sync completed",
                source_key=source_issue.key,
                target_key=target_issue.key,
            )

            return SyncResult(
                success=True,
                sync_record=sync_record,
            )

        except Exception as e:
            sync_record.status = SyncStatus.FAILED
            sync_record.error_count += 1
            sync_record.last_error = str(e)
            self.storage.save_sync_record(sync_record)
            raise

    def _sync_existing_issue(
        self,
        source_issue: JiraIssue,
        sync_record: SyncRecord,
        source_instance: int,
    ) -> SyncResult:
        """Sync updates to an existing issue."""
        target_instance = 2 if source_instance == 1 else 1
        target_client = self.jira_2 if source_instance == 1 else self.jira_1
        direction = SyncDirection.JIRA_1_TO_2 if source_instance == 1 else SyncDirection.JIRA_2_TO_1

        target_key = sync_record.jira_2_key if source_instance == 1 else sync_record.jira_1_key

        if not target_key:
            logger.error("Target key not found in sync record", sync_id=sync_record.sync_id)
            return SyncResult(
                success=False,
                sync_record=sync_record,
                error_message="Target issue key not found in sync record",
            )

        logger.info(
            "Syncing existing issue update",
            source_key=source_issue.key,
            target_key=target_key,
            direction=direction,
        )

        # Check for conflicts
        conflict_result = self._check_for_conflicts(source_issue, sync_record, source_instance)
        if conflict_result.conflicts_detected:
            return conflict_result

        # Update sync record status
        sync_record.status = SyncStatus.IN_PROGRESS
        sync_record.last_sync_timestamp = datetime.now(UTC)
        self.storage.save_sync_record(sync_record)

        try:
            # Get current target issue
            target_issue = target_client.get_issue(target_key)

            # Check if any changes are needed (including status)
            update_payload = target_client.convert_to_update_payload(target_issue, source_issue)
            status_changed = self.config.sync_status_transitions and target_issue.status != source_issue.status

            if not update_payload.get("fields") and not status_changed:
                # No changes needed
                logger.info("No changes detected, skipping update", target_key=target_key)
                sync_record.status = SyncStatus.SUCCESS
            else:
                # Apply updates including status transitions (if configured)
                if status_changed:
                    updated_target = target_client.apply_issue_updates(target_key, target_issue, source_issue)
                else:
                    # Only update fields, skip status
                    updated_target = target_client.update_issue(target_key, update_payload)
                    updated_target = target_client.get_issue(target_key)

                # Update sync record
                if target_instance == 1:
                    sync_record.jira_1_last_updated = updated_target.updated
                else:
                    sync_record.jira_2_last_updated = updated_target.updated

                sync_record.status = SyncStatus.SUCCESS

                # Log what was updated
                updated_fields = list(update_payload.get("fields", {}).keys())
                if status_changed:
                    updated_fields.append("status")

                logger.info(
                    "Issue update sync completed",
                    source_key=source_issue.key,
                    target_key=target_key,
                    updated_fields=updated_fields,
                )

            if source_instance == 1:
                sync_record.jira_1_last_updated = source_issue.updated
            else:
                sync_record.jira_2_last_updated = source_issue.updated

            sync_record.last_sync_direction = direction
            sync_record.error_count = 0  # Reset error count on success
            sync_record.last_error = None

            self.storage.save_sync_record(sync_record)

            return SyncResult(
                success=True,
                sync_record=sync_record,
            )

        except Exception as e:
            sync_record.status = SyncStatus.FAILED
            sync_record.error_count += 1
            sync_record.last_error = str(e)
            self.storage.save_sync_record(sync_record)

            return SyncResult(
                success=False,
                sync_record=sync_record,
                error_message=str(e),
            )

    def _check_for_conflicts(
        self,
        source_issue: JiraIssue,
        sync_record: SyncRecord,
        source_instance: int,
    ) -> SyncResult:
        """Check for conflicts in bidirectional sync."""
        # target_instance = 2 if source_instance == 1 else 1
        target_client = self.jira_2 if source_instance == 1 else self.jira_1
        target_key = sync_record.jira_2_key if source_instance == 1 else sync_record.jira_1_key

        if not target_key:
            # No target issue yet, no conflict possible
            return SyncResult(
                success=True,
                sync_record=sync_record,
                conflicts_detected=False,
            )

        try:
            target_issue = target_client.get_issue(target_key)
        except JiraAPIError:
            # Target issue doesn't exist, no conflict
            return SyncResult(
                success=True,
                sync_record=sync_record,
                conflicts_detected=False,
            )

        # Get last known update timestamps
        source_last_known = sync_record.jira_1_last_updated if source_instance == 1 else sync_record.jira_2_last_updated
        target_last_known = sync_record.jira_2_last_updated if source_instance == 1 else sync_record.jira_1_last_updated

        # Check if both issues were updated since last sync
        source_updated_since_sync = source_last_known is None or source_issue.updated > source_last_known
        target_updated_since_sync = target_last_known is None or target_issue.updated > target_last_known

        if source_updated_since_sync and target_updated_since_sync:
            # Conflict detected
            logger.warning(
                "Conflict detected",
                source_key=source_issue.key,
                target_key=target_key,
                source_updated=source_issue.updated,
                target_updated=target_issue.updated,
                source_last_known=source_last_known,
                target_last_known=target_last_known,
            )

            conflict_details = (
                f"Both issues updated since last sync. "
                f"Source ({source_issue.key}) updated: {source_issue.updated}, "
                f"Target ({target_key}) updated: {target_issue.updated}, "
                f"Last sync: {sync_record.last_sync_timestamp}"
            )

            sync_record.status = SyncStatus.CONFLICT
            sync_record.requires_manual_resolution = True
            sync_record.conflict_details = conflict_details
            sync_record.last_sync_timestamp = datetime.now(UTC)

            self.storage.save_sync_record(sync_record)

            return SyncResult(
                success=False,
                sync_record=sync_record,
                error_message=conflict_details,
                conflicts_detected=True,
            )

        return SyncResult(
            success=True,
            sync_record=sync_record,
            conflicts_detected=False,
        )

    def resolve_conflict_manual(
        self,
        sync_id: str,
        resolution_direction: SyncDirection,
    ) -> SyncResult:
        """Manually resolve a conflict by specifying which direction to sync."""
        sync_record = self.storage.get_sync_record(sync_id)
        if not sync_record:
            raise ValueError(f"Sync record {sync_id} not found")

        if sync_record.status != SyncStatus.CONFLICT:
            raise ValueError(f"Sync record {sync_id} is not in conflict state")

        logger.info(
            "Manually resolving conflict",
            sync_id=sync_id,
            resolution_direction=resolution_direction,
        )

        # Determine source and target based on resolution direction
        if resolution_direction == SyncDirection.JIRA_1_TO_2:
            source_instance = 1
            source_key = sync_record.jira_1_key
        else:
            source_instance = 2
            source_key = sync_record.jira_2_key

        if not source_key:
            raise ValueError("Source key not found in sync record")

        # Get source issue and perform sync
        source_client = self.jira_1 if source_instance == 1 else self.jira_2
        source_issue = source_client.get_issue(source_key)

        # Reset conflict state
        sync_record.status = SyncStatus.PENDING
        sync_record.requires_manual_resolution = False
        sync_record.conflict_details = None

        # Perform the sync
        return self._sync_existing_issue(source_issue, sync_record, source_instance)

    def perform_full_sync(self) -> list[SyncResult]:
        """Perform a full sync of all issues in both projects."""
        logger.info("Starting full sync")
        results = []

        # Get all issues from both instances
        # Note: In practice, you might want to limit this with date filters
        jira_1_issues = self.jira_1.search_issues(
            f'project = "{self.config.jira_instance_1.project_key}"',
            max_results=1000,
        )
        jira_2_issues = self.jira_2.search_issues(
            f'project = "{self.config.jira_instance_2.project_key}"',
            max_results=1000,
        )

        # Process JIRA 1 issues
        for issue in jira_1_issues:
            try:
                result = self.sync_issue_from_webhook(issue.key, 1)
                results.append(result)
                time.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.error("Error in full sync", issue_key=issue.key, error=str(e))

        # Process JIRA 2 issues
        for issue in jira_2_issues:
            try:
                # Check if this issue is already synced
                existing_record = self.storage.find_sync_record_by_jira_key(issue.key, 2)
                if not existing_record:
                    result = self.sync_issue_from_webhook(issue.key, 2)
                    results.append(result)
                time.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.error("Error in full sync", issue_key=issue.key, error=str(e))

        logger.info("Full sync completed", total_results=len(results))
        return results

    def retry_failed_syncs(self) -> list[SyncResult]:
        """Retry all failed sync operations."""
        logger.info("Retrying failed syncs")

        failed_records = self.storage.get_records_by_status(SyncStatus.FAILED)
        results = []

        for record in failed_records:
            if record.error_count >= self.config.max_retries:
                logger.warning(
                    "Skipping retry for record with too many failures",
                    sync_id=record.sync_id,
                    error_count=record.error_count,
                )
                continue

            try:
                # Determine which issue to retry
                if record.last_sync_direction == SyncDirection.JIRA_1_TO_2:
                    source_instance = 1
                    source_key = record.jira_1_key
                elif record.last_sync_direction == SyncDirection.JIRA_2_TO_1:
                    source_instance = 2
                    source_key = record.jira_2_key
                else:
                    # Try both directions if unclear
                    if record.jira_1_key:
                        source_instance = 1
                        source_key = record.jira_1_key
                    elif record.jira_2_key:
                        source_instance = 2
                        source_key = record.jira_2_key
                    else:
                        logger.error("No source key found for retry", sync_id=record.sync_id)
                        continue

                if source_key:
                    result = self.sync_issue_from_webhook(source_key, source_instance)
                    results.append(result)

                    # Add delay between retries
                    time.sleep(self.config.retry_delay_seconds)

            except Exception as e:
                logger.error(
                    "Error during retry",
                    sync_id=record.sync_id,
                    error=str(e),
                )

        logger.info("Retry completed", retry_count=len(results))
        return results

    def _generate_sync_id(self, jira_1_key: str | None, jira_2_key: str | None) -> str:
        """Generate a unique sync ID."""
        key_1 = jira_1_key or "unknown"
        key_2 = jira_2_key or "unknown"
        return f"{key_1}#{key_2}"

    def _create_error_sync_record(self, issue_key: str, source_instance: int) -> SyncRecord:
        """Create a sync record for error tracking."""
        sync_id = self._generate_sync_id(
            issue_key if source_instance == 1 else None,
            issue_key if source_instance == 2 else None,
        )

        record = SyncRecord(
            sync_id=sync_id,
            status=SyncStatus.FAILED,
            last_sync_timestamp=datetime.now(UTC),
            error_count=1,
        )

        if source_instance == 1:
            record.jira_1_key = issue_key
        else:
            record.jira_2_key = issue_key

        return record
