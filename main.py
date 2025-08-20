"""Main module for JIRA automation system."""

from src.lambda_handlers import (
    health_check_handler,
    jira_webhook_handler,
    manual_sync_handler,
    scheduled_sync_handler,
)

# Export Lambda handlers for AWS
__all__ = [
    "jira_webhook_handler",
    "scheduled_sync_handler",
    "manual_sync_handler",
    "health_check_handler",
]


def main() -> None:
    """Main function for local testing."""  # noqa: D401
    print("JIRA Automation System")  # noqa: T201
    print("This system provides bidirectional sync between JIRA instances.")  # noqa: T201
    print("Deploy to AWS Lambda for production use.")  # noqa: T201


if __name__ == "__main__":
    main()
