"""JIRA API client for sync operations."""

import time
from datetime import datetime
from typing import Any

import requests
import structlog
from requests.auth import HTTPBasicAuth

from .config import JiraConfig
from .models import JiraIssue

logger = structlog.get_logger()


class JiraAPIError(Exception):
    """Custom exception for JIRA API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize JIRA API error."""
        super().__init__(message)
        self.status_code = status_code


class JiraClient:
    """JIRA API client with authentication and CRUD operations."""

    def __init__(self, config: JiraConfig, sync_assignee: bool = False) -> None:
        """Initialize JIRA client."""
        self.config = config
        self.sync_assignee = sync_assignee
        self.base_url = config.base_url.rstrip("/")
        self.auth = HTTPBasicAuth(config.username, config.api_token)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any] | dict[Any, Any] | None:
        """Make HTTP request to JIRA API with retries."""
        url = f"{self.base_url}/rest/api/3/{endpoint.lstrip('/')}"

        for attempt in range(max_retries):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    timeout=30,
                )

                if response.status_code == 429:  # Rate limited
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        "Rate limited, waiting",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    time.sleep(retry_after)
                    continue

                if not response.ok:
                    error_msg = f"JIRA API error: {response.status_code} - {response.text}"
                    logger.error(
                        "JIRA API request failed",
                        status_code=response.status_code,
                        response_text=response.text,
                        url=url,
                    )
                    raise JiraAPIError(error_msg, response.status_code)

                return response.json() if response.content else {}

            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise JiraAPIError(f"Request failed after {max_retries} attempts: {e}") from e  # will from e work?

                wait_time = 2**attempt
                logger.warning(
                    "Request failed, retrying",
                    error=str(e),
                    attempt=attempt + 1,
                    wait_time=wait_time,
                )
                time.sleep(wait_time)

        raise JiraAPIError(f"Request failed after {max_retries} attempts")

    def get_issue(self, issue_key: str) -> JiraIssue:
        """Get JIRA issue by key."""
        logger.info("Fetching JIRA issue", issue_key=issue_key)

        data = self._make_request(
            "GET",
            f"issue/{issue_key}",
            params={
                "expand": "changelog",
                "fields": "*all",
            },
        )

        return self._parse_issue(data)

    def create_issue(self, issue_data: dict[str, Any]) -> JiraIssue:
        """Create a new JIRA issue."""
        logger.info("Creating JIRA issue", project=self.config.project_key)

        # Ensure project key is set
        issue_data["fields"]["project"] = {"key": self.config.project_key}

        data = self._make_request("POST", "issue", data=issue_data)

        # Get the created issue with full details
        issue_key = data["key"]
        return self.get_issue(issue_key)

    def update_issue(self, issue_key: str, update_data: dict[str, Any]) -> JiraIssue:
        """Update an existing JIRA issue."""
        logger.info("Updating JIRA issue", issue_key=issue_key)

        self._make_request("PUT", f"issue/{issue_key}", data=update_data)

        # Return updated issue
        return self.get_issue(issue_key)

    def search_issues(
        self,
        jql: str,
        start_at: int = 0,
        max_results: int = 50,
    ) -> list[JiraIssue]:
        """Search for issues using JQL."""
        logger.info("Searching JIRA issues", jql=jql)

        data = self._make_request(
            "POST",
            "search",
            data={
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": "*all",
                "expand": ["changelog"],
            },
        )

        return [self._parse_issue(issue_data) for issue_data in data["issues"]]

    def get_project_issues_updated_since(
        self,
        since: datetime,
        max_results: int = 100,
    ) -> list[JiraIssue]:
        """Get all issues in the project updated since a specific datetime."""
        since_str = since.strftime("%Y-%m-%d %H:%M")
        jql = f'project = "{self.config.project_key}" AND updated >= "{since_str}"'

        return self.search_issues(jql, max_results=max_results)

    def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        """Get available transitions for an issue."""
        logger.info("Getting transitions for issue", issue_key=issue_key)

        data = self._make_request("GET", f"issue/{issue_key}/transitions")
        return data.get("transitions", [])

    def transition_issue(self, issue_key: str, transition_id: str, fields: dict[str, Any] | None = None) -> None:
        """Transition an issue to a new status."""
        logger.info("Transitioning issue", issue_key=issue_key, transition_id=transition_id)

        transition_data = {"transition": {"id": transition_id}}

        if fields:
            transition_data["fields"] = fields

        self._make_request("POST", f"issue/{issue_key}/transitions", data=transition_data)

    def transition_issue_to_status(self, issue_key: str, target_status: str) -> bool:
        """Transition an issue to a specific status by finding the appropriate transition."""
        logger.info("Attempting to transition issue to status", issue_key=issue_key, target_status=target_status)

        try:
            # Get current issue to check if already in target status
            current_issue = self.get_issue(issue_key)
            if current_issue.status == target_status:
                logger.info("Issue already in target status", issue_key=issue_key, status=target_status)
                return True

            # Get available transitions
            transitions = self.get_transitions(issue_key)

            # Find transition that leads to target status
            target_transition = None
            for transition in transitions:
                transition_to_status = transition.get("to", {}).get("name", "")
                if transition_to_status.lower() == target_status.lower():
                    target_transition = transition
                    break

            if target_transition:
                transition_id = target_transition["id"]
                self.transition_issue(issue_key, transition_id)
                logger.info(
                    "Successfully transitioned issue",
                    issue_key=issue_key,
                    from_status=current_issue.status,
                    to_status=target_status,
                    transition_id=transition_id,
                )
                return True
            else:
                # Log available transitions for debugging
                available_statuses = [t.get("to", {}).get("name", "") for t in transitions]
                logger.warning(
                    "No direct transition found to target status",
                    issue_key=issue_key,
                    current_status=current_issue.status,
                    target_status=target_status,
                    available_transitions=available_statuses,
                )
                return False

        except JiraAPIError as e:
            logger.error(
                "Failed to transition issue",
                issue_key=issue_key,
                target_status=target_status,
                error=str(e),
            )
            return False

    def _parse_issue(self, issue_data: dict[str, Any]) -> JiraIssue:
        """Parse JIRA issue data into our standardized model."""
        fields = issue_data["fields"]

        # Extract basic fields
        summary = fields.get("summary", "")
        description = fields.get("description", {})
        if isinstance(description, dict):
            description = description.get("content", [{}])[0].get("content", [{}])[0].get("text", "")

        # Extract complex fields safely
        issue_type = fields.get("issuetype", {}).get("name", "")
        status = fields.get("status", {}).get("name", "")
        priority = fields.get("priority", {}).get("name", "")

        assignee = None
        if fields.get("assignee"):
            assignee = fields["assignee"].get("emailAddress", fields["assignee"].get("displayName"))

        reporter = ""
        if fields.get("reporter"):
            reporter = fields["reporter"].get("emailAddress", fields["reporter"].get("displayName", ""))

        # Extract arrays
        labels = fields.get("labels", [])
        components = [comp["name"] for comp in fields.get("components", [])]
        fix_versions = [ver["name"] for ver in fields.get("fixVersions", [])]

        # Extract timestamps
        created = datetime.fromisoformat(fields["created"].replace("Z", "+00:00"))
        updated = datetime.fromisoformat(fields["updated"].replace("Z", "+00:00"))

        resolution = fields.get("resolution", {})
        resolution_name = resolution.get("name") if resolution else None

        return JiraIssue(
            key=issue_data["key"],
            summary=summary,
            description=description,
            issue_type=issue_type,
            status=status,
            priority=priority,
            assignee=assignee,
            reporter=reporter,
            labels=labels,
            components=components,
            fix_versions=fix_versions,
            custom_fields=self._extract_custom_fields(fields),
            created=created,
            updated=updated,
            resolution=resolution_name,
        )

    def _extract_custom_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Extract custom fields from JIRA issue fields."""
        custom_fields = {}

        for key, value in fields.items():
            if key.startswith("customfield_"):
                if value is not None:
                    # Handle different custom field types
                    if isinstance(value, dict):
                        custom_fields[key] = value.get("value", value)
                    elif isinstance(value, list):
                        custom_fields[key] = [
                            item.get("value", item) if isinstance(item, dict) else item for item in value
                        ]
                    else:
                        custom_fields[key] = value

        return custom_fields

    def convert_to_create_payload(self, issue: JiraIssue) -> dict[str, Any]:
        """Convert JiraIssue to JIRA create payload format."""
        payload = {
            "fields": {
                "project": {"key": self.config.project_key},
                "summary": issue.summary,
                "issuetype": {"name": issue.issue_type},
                "priority": {"name": issue.priority},
                "labels": issue.labels,
            }
        }

        if issue.description:
            payload["fields"]["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": issue.description}],
                    }
                ],
            }

        if self.sync_assignee and issue.assignee:
            payload["fields"]["assignee"] = {"emailAddress": issue.assignee}  # Probably won't work...

        if issue.components:
            payload["fields"]["components"] = [{"name": comp} for comp in issue.components]  # type: ignore

        if issue.fix_versions:
            payload["fields"]["fixVersions"] = [{"name": ver} for ver in issue.fix_versions]  # type: ignore

        # Add custom fields, should we?
        for key, value in issue.custom_fields.items():
            payload["fields"][key] = value

        return payload

    def convert_to_update_payload(
        self,
        current_issue: JiraIssue,
        target_issue: JiraIssue,
    ) -> dict[str, Any]:
        """Convert differences between issues to JIRA update payload format."""
        update_fields = {}

        # Compare and update fields that have changed
        if current_issue.summary != target_issue.summary:
            update_fields["summary"] = target_issue.summary

        if current_issue.description != target_issue.description:
            if target_issue.description:
                update_fields["description"] = {  # type: ignore
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": target_issue.description}],
                        }
                    ],
                }
            else:
                update_fields["description"] = None  # type: ignore

        if current_issue.priority != target_issue.priority:
            update_fields["priority"] = {"name": target_issue.priority}  # type: ignore

        # Only sync assignee if configured to do so
        if self.sync_assignee and current_issue.assignee != target_issue.assignee:
            if target_issue.assignee:
                update_fields["assignee"] = {"emailAddress": target_issue.assignee}  # type: ignore
            else:
                update_fields["assignee"] = None  # type: ignore

        if current_issue.labels != target_issue.labels:
            update_fields["labels"] = target_issue.labels  # type: ignore

        if current_issue.components != target_issue.components:
            update_fields["components"] = [{"name": comp} for comp in target_issue.components]  # type: ignore

        if current_issue.fix_versions != target_issue.fix_versions:
            update_fields["fixVersions"] = [{"name": ver} for ver in target_issue.fix_versions]  # type: ignore

        # Handle custom fields
        for key, value in target_issue.custom_fields.items():
            if current_issue.custom_fields.get(key) != value:
                update_fields[key] = value

        # Note: Status changes are handled separately via transitions
        # We don't include status in the update payload

        return {"fields": update_fields} if update_fields else {}

    def apply_issue_updates(
        self,
        issue_key: str,
        current_issue: JiraIssue,
        target_issue: JiraIssue,
    ) -> JiraIssue:
        """Apply all updates to an issue including field changes and status transitions."""
        logger.info("Applying updates to issue", issue_key=issue_key)

        # Apply field updates first
        update_payload = self.convert_to_update_payload(current_issue, target_issue)
        if update_payload.get("fields"):
            self.update_issue(issue_key, update_payload)
            logger.info("Applied field updates", issue_key=issue_key, fields=list(update_payload["fields"].keys()))

        # Handle status change separately using transitions
        if current_issue.status != target_issue.status:
            logger.info(
                "Status change detected",
                issue_key=issue_key,
                from_status=current_issue.status,
                to_status=target_issue.status,
            )

            status_success = self.transition_issue_to_status(issue_key, target_issue.status)
            if not status_success:
                logger.warning(
                    "Status transition failed - issue may need manual intervention",
                    issue_key=issue_key,
                    target_status=target_issue.status,
                )

        # Return the updated issue
        return self.get_issue(issue_key)
