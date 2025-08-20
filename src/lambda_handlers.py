"""AWS Lambda handlers for JIRA webhook events and scheduled syncs."""

import hashlib
import hmac
import json
from typing import Any

import structlog

from .config import SyncConfig, load_config
from .models import WebhookPayload
from .sync_engine import SyncEngine

logger = structlog.get_logger()

# Global sync engine instance (reused across Lambda invocations)
_sync_engine: SyncEngine | None = None


def get_sync_engine() -> SyncEngine:
    """Get or create the global sync engine instance."""
    global _sync_engine
    if _sync_engine is None:
        config = load_config()
        _sync_engine = SyncEngine(config)
        _sync_engine.initialize()
    return _sync_engine


def verify_webhook_signature(payload: str, signature: str, secret: str) -> bool:
    """Verify JIRA webhook signature."""
    if not signature:
        return False

    # JIRA webhooks use HMAC-SHA256
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Remove 'sha256=' prefix if present
    if signature.startswith("sha256="):
        signature = signature[7:]

    return hmac.compare_digest(expected_signature, signature)


def should_process_event(webhook_payload: WebhookPayload) -> bool:
    """Determine if the webhook event should be processed."""
    # Process issue creation and updates
    relevant_events = [
        "jira:issue_created",
        "jira:issue_updated",
        "jira:issue_deleted",  # You might want to handle deletions
    ]

    if webhook_payload.webhookEvent not in relevant_events:
        return False

    # Skip certain types of updates (optional)
    # if webhook_payload.webhookEvent == "jira:issue_updated":
    #     # Skip if only comment was added (optional)
    #     if webhook_payload.issue_event_type_name == "issue_commented":
    #         return False

    #     # Skip workflow transitions that don't change content (optional)
    #     # You can customize this based on your needs
    #     if webhook_payload.changelog:
    #         items = webhook_payload.changelog.get("items", [])
    #         # Only process if there are meaningful field changes
    #         meaningful_fields = {"summary", "description", "priority", "assignee", "labels", "components"}
    #         for item in items:
    #             if item.get("field") in meaningful_fields:
    #                 return True
    #         # If only status changes, you might want to skip or process
    #         return len(items) > 0

    return True


def jira_webhook_handler(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Lambda handler for JIRA webhook events."""
    try:
        logger.info("Processing JIRA webhook", event_keys=list(event.keys()))

        # Extract request details
        headers = event.get("headers", {})
        body = event.get("body", "")

        if event.get("isBase64Encoded", False):
            import base64

            body = base64.b64decode(body).decode("utf-8")

        # Verify webhook signature
        signature = headers.get("x-hub-signature-256") or headers.get("X-Hub-Signature-256")
        config = load_config()

        if not verify_webhook_signature(body, signature or "", config.webhook_secret):
            logger.warning("Invalid webhook signature")
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Invalid signature"}),
            }

        # Parse webhook payload
        try:
            webhook_data = json.loads(body)
            webhook_payload = WebhookPayload(**webhook_data)
        except Exception as e:
            logger.error("Failed to parse webhook payload", error=str(e))
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid payload format"}),
            }

        # Determine which JIRA instance this webhook is from
        # You'll need to configure this based on your webhook URLs
        source_instance = determine_source_instance(event, config)

        # Filter relevant events
        if not should_process_event(webhook_payload):
            logger.info(
                "Skipping event",
                event_type=webhook_payload.webhookEvent,
                issue_key=webhook_payload.issue.get("key"),
            )
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Event skipped"}),
            }

        # Get issue key
        issue_key = webhook_payload.issue.get("key")
        if not issue_key:
            logger.error("No issue key in webhook payload")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No issue key found"}),
            }

        # Process the sync
        sync_engine = get_sync_engine()
        result = sync_engine.sync_issue_from_webhook(issue_key, source_instance)

        if result.success:
            logger.info(
                "Webhook sync completed successfully",
                issue_key=issue_key,
                sync_id=result.sync_record.sync_id,
            )
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Sync completed successfully",
                        "sync_id": result.sync_record.sync_id,
                    }
                ),
            }
        else:
            logger.error(
                "Webhook sync failed",
                issue_key=issue_key,
                error=result.error_message,
            )
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "error": "Sync failed",
                        "message": result.error_message,
                    }
                ),
            }

    except Exception as e:
        logger.error("Unexpected error in webhook handler", error=str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }


def scheduled_sync_handler(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Lambda handler for scheduled sync operations."""
    try:
        logger.info("Starting scheduled sync")

        sync_engine = get_sync_engine()

        # Determine sync type from event
        sync_type = event.get("sync_type", "retry_failed")

        if sync_type == "full_sync":
            results = sync_engine.perform_full_sync()
        elif sync_type == "retry_failed":
            results = sync_engine.retry_failed_syncs()
        else:
            logger.error("Unknown sync type", sync_type=sync_type)
            return {
                "statusCode": 400,
                "body": json.dumps({"error": f"Unknown sync type: {sync_type}"}),
            }

        # Summarize results
        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count

        logger.info(
            "Scheduled sync completed",
            sync_type=sync_type,
            total=len(results),
            success=success_count,
            failed=failed_count,
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": f"Scheduled sync completed: {sync_type}",
                    "summary": {
                        "total": len(results),
                        "success": success_count,
                        "failed": failed_count,
                    },
                }
            ),
        }

    except Exception as e:
        logger.error("Error in scheduled sync", error=str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Scheduled sync failed"}),
        }


def manual_sync_handler(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Lambda handler for manual sync operations."""
    try:
        logger.info("Processing manual sync request")

        # Extract parameters
        issue_key = event.get("issue_key")
        source_instance = event.get("source_instance")
        sync_id = event.get("sync_id")
        resolve_conflict = event.get("resolve_conflict")
        resolution_direction = event.get("resolution_direction")

        sync_engine = get_sync_engine()

        if resolve_conflict and sync_id and resolution_direction:
            # Manual conflict resolution
            from .models import SyncDirection

            direction = SyncDirection(resolution_direction)
            result = sync_engine.resolve_conflict_manual(sync_id, direction)

            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Conflict resolved",
                        "sync_id": result.sync_record.sync_id,
                        "success": result.success,
                    }
                ),
            }

        elif issue_key and source_instance:
            # Manual issue sync
            result = sync_engine.sync_issue_from_webhook(issue_key, source_instance)

            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "message": "Manual sync completed",
                        "sync_id": result.sync_record.sync_id,
                        "success": result.success,
                        "error": result.error_message,
                    }
                ),
            }
        else:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": "Invalid parameters. Provide either (issue_key, source_instance) or (sync_id, resolution_direction)",  # noqa: E501
                    }
                ),
            }

    except Exception as e:
        logger.error("Error in manual sync", error=str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Manual sync failed"}),
        }


def health_check_handler(event: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Lambda handler for health checks."""
    try:
        config = load_config()

        # Basic health checks
        health_status = {
            "status": "healthy",
            "timestamp": structlog.get_logger().info("Health check"),
            "config_loaded": True,
            "jira_instances": {
                "jira_1": {
                    "base_url": config.jira_instance_1.base_url,
                    "project_key": config.jira_instance_1.project_key,
                },
                "jira_2": {
                    "base_url": config.jira_instance_2.base_url,
                    "project_key": config.jira_instance_2.project_key,
                },
            },
            "dynamodb": {
                "table_name": config.dynamodb.table_name,
                "region": config.dynamodb.region,
            },
        }

        return {
            "statusCode": 200,
            "body": json.dumps(health_status),
        }

    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "unhealthy",
                    "error": str(e),
                }
            ),
        }


def determine_source_instance(event: dict[str, Any], config: SyncConfig) -> int:
    """Determine which JIRA instance the webhook is from based on the request."""
    # Method 1: Check the request path or headers
    path = event.get("path", "")
    if "/jira1/webhook" in path or "/webhook/jira1" in path:
        return 1
    elif "/jira2/webhook" in path or "/webhook/jira2" in path:
        return 2

    # Method 2: Check the request origin
    headers = event.get("headers", {})
    origin = headers.get("origin") or headers.get("Origin")
    if origin:
        if config.jira_instance_1.base_url in origin:
            return 1
        elif config.jira_instance_2.base_url in origin:
            return 2

    # Method 3: Check custom header (you can configure this in JIRA webhook)
    jira_instance_header = headers.get("x-jira-instance") or headers.get("X-Jira-Instance")
    if jira_instance_header:
        try:
            return int(jira_instance_header)
        except ValueError:
            pass

    # Default to instance 1 (you might want to raise an error instead)
    logger.warning("Could not determine source instance, defaulting to 1")
    return 1
