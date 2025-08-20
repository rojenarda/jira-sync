#!/usr/bin/env python3
"""Test script for JIRA webhook endpoints."""

import hashlib
import hmac
import json
import sys
from datetime import UTC, datetime

import requests


def create_test_webhook_payload() -> dict:
    """Create a test JIRA webhook payload."""
    return {
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
        "webhookEvent": "jira:issue_created",
        "issue_event_type_name": "issue_created",
        "issue": {
            "key": "TEST-123",
            "fields": {
                "summary": "Test issue for webhook",
                "description": "This is a test issue created for webhook testing",
                "issuetype": {"name": "Task"},
                "priority": {"name": "Medium"},
                "status": {"name": "To Do"},
                "created": datetime.now(UTC).isoformat() + "Z",
                "updated": datetime.now(UTC).isoformat() + "Z",
                "project": {"key": "TEST"},
                "reporter": {
                    "emailAddress": "test@example.com",
                    "displayName": "Test User",
                },
            },
        },
        "user": {
            "emailAddress": "test@example.com",
            "displayName": "Test User",
        },
    }


def sign_payload(payload: str, secret: str) -> str:
    """Create HMAC signature for webhook payload."""
    signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"


def test_webhook(webhook_url: str, secret: str) -> None:
    """Test webhook endpoint with a sample payload."""
    payload_dict = create_test_webhook_payload()
    payload_str = json.dumps(payload_dict)
    signature = sign_payload(payload_str, secret)

    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature,
    }

    print(f"Testing webhook: {webhook_url}")  # noqa: T201
    print(f"Payload: {payload_str}")  # noqa: T201
    print(f"Signature: {signature}")  # noqa: T201

    try:
        response = requests.post(
            webhook_url,
            data=payload_str,
            headers=headers,
            timeout=30,
        )

        print(f"Response status: {response.status_code}")  # noqa: T201
        print(f"Response body: {response.text}")  # noqa: T201

        if response.status_code == 200:
            print("✅ Webhook test successful!")  # noqa: T201
        else:
            print(f"❌ Webhook test failed with status {response.status_code}")  # noqa: T201

    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")  # noqa: T201


def main() -> None:
    """Test webhook endpoint with sample payload."""
    if len(sys.argv) != 3:
        print("Usage: python test-webhook.py <webhook_url> <webhook_secret>")  # noqa: T201
        print("Example: python test-webhook.py https://api.example.com/webhook/jira1 mysecret")  # noqa: T201
        sys.exit(1)

    webhook_url = sys.argv[1]
    webhook_secret = sys.argv[2]

    test_webhook(webhook_url, webhook_secret)


if __name__ == "__main__":
    main()
