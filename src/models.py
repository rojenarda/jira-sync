"""Data models for JIRA sync system."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SyncDirection(str, Enum):
    """Direction of sync operation."""

    JIRA_1_TO_2 = "jira_1_to_2"
    JIRA_2_TO_1 = "jira_2_to_1"


class SyncStatus(str, Enum):
    """Status of sync operation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CONFLICT = "conflict"


class JiraIssue(BaseModel):
    """Standardized JIRA issue representation."""

    key: str
    summary: str
    description: str | None = None
    issue_type: str
    status: str
    priority: str
    assignee: str | None = None
    reporter: str
    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    fix_versions: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    created: datetime
    updated: datetime
    resolution: str | None = None


class SyncRecord(BaseModel):
    """Record of a sync operation stored in DynamoDB."""

    # Partition key: jira_1_key#jira_2_key
    sync_id: str = Field(..., description="Unique sync identifier")

    # Issue keys
    jira_1_key: str | None = None
    jira_2_key: str | None = None

    # Sync metadata
    status: SyncStatus
    last_sync_direction: SyncDirection | None = None
    last_sync_timestamp: datetime

    # Version tracking for conflict detection
    jira_1_last_updated: datetime | None = None
    jira_2_last_updated: datetime | None = None

    # Error tracking
    error_count: int = Field(default=0)
    last_error: str | None = None

    # Conflict resolution
    requires_manual_resolution: bool = Field(default=False)
    conflict_details: str | None = None


class WebhookPayload(BaseModel):
    """JIRA webhook payload."""

    timestamp: int
    webhookEvent: str  # noqa: N815
    issue_event_type_name: str | None = None
    issue: dict[str, Any]
    user: dict[str, Any]
    changelog: dict[str, Any] | None = None


class SyncResult(BaseModel):
    """Result of a sync operation."""

    success: bool
    sync_record: SyncRecord
    error_message: str | None = None
    conflicts_detected: bool = Field(default=False)
