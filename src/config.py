"""Configuration management for JIRA sync system."""

from decouple import config
from pydantic import BaseModel, Field


class JiraConfig(BaseModel):
    """Configuration for a JIRA instance."""

    base_url: str = Field(..., description="JIRA instance base URL")
    username: str = Field(..., description="JIRA username")
    api_token: str = Field(..., description="JIRA API token")
    project_key: str = Field(..., description="Project key to sync")


class DynamoDBConfig(BaseModel):
    """Configuration for DynamoDB."""

    table_name: str = Field(default="jira-sync-state", description="DynamoDB table name")
    region: str = Field(default="us-east-1", description="AWS region")


class SyncConfig(BaseModel):
    """Main sync configuration."""

    jira_instance_1: JiraConfig
    jira_instance_2: JiraConfig
    dynamodb: DynamoDBConfig
    webhook_secret: str = Field(..., description="Webhook authentication secret")
    sync_interval_seconds: int = Field(default=300, description="Fallback sync interval in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_delay_seconds: int = Field(default=5, description="Delay between retries")
    sync_status_transitions: bool = Field(
        default=True, description="Whether to sync status changes using JIRA transitions"
    )
    sync_assignee: bool = Field(
        default=False, description="Whether to sync assignee (users may not exist in both instances)"
    )


def load_config() -> SyncConfig:
    """Load configuration from environment variables."""
    return SyncConfig(
        jira_instance_1=JiraConfig(
            base_url=config("JIRA_1_BASE_URL"),
            username=config("JIRA_1_USERNAME"),
            api_token=config("JIRA_1_API_TOKEN"),
            project_key=config("JIRA_1_PROJECT_KEY"),
        ),
        jira_instance_2=JiraConfig(
            base_url=config("JIRA_2_BASE_URL"),
            username=config("JIRA_2_USERNAME"),
            api_token=config("JIRA_2_API_TOKEN"),
            project_key=config("JIRA_2_PROJECT_KEY"),
        ),
        dynamodb=DynamoDBConfig(
            table_name=config("DYNAMODB_TABLE_NAME", default="jira-sync-state"),
            region=config("AWS_REGION", default="us-east-1"),
        ),
        webhook_secret=config("WEBHOOK_SECRET"),
        sync_interval_seconds=config("SYNC_INTERVAL_SECONDS", default=300, cast=int),
        max_retries=config("MAX_RETRIES", default=3, cast=int),
        retry_delay_seconds=config("RETRY_DELAY_SECONDS", default=5, cast=int),
        sync_status_transitions=config("SYNC_STATUS_TRANSITIONS", default=True, cast=bool),
        sync_assignee=config("SYNC_ASSIGNEE", default=False, cast=bool),
    )
