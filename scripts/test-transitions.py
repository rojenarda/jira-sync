#!/usr/bin/env python3
"""Test script for JIRA status transitions."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import load_config
from jira_client import JiraClient


def test_transitions(issue_key: str, jira_instance: int = 1) -> None:
    """Test available transitions for an issue."""
    print(f"Testing transitions for issue: {issue_key}")  # noqa: T201

    try:
        config = load_config()

        if jira_instance == 1:
            jira_config = config.jira_instance_1
        else:
            jira_config = config.jira_instance_2

        client = JiraClient(jira_config)

        # Get current issue status
        issue = client.get_issue(issue_key)
        print(f"Current status: {issue.status}")  # noqa: T201

        # Get available transitions
        transitions = client.get_transitions(issue_key)

        print(f"\nAvailable transitions ({len(transitions)}):")  # noqa: T201
        for i, transition in enumerate(transitions, 1):
            transition_id = transition.get("id")
            transition_name = transition.get("name")
            to_status = transition.get("to", {}).get("name", "Unknown")

            print(f"  {i}. {transition_name} (ID: {transition_id}) -> {to_status}")  # noqa: T201

        # Test transition (interactive)
        if transitions:
            print(f"\nEnter transition number to test (1-{len(transitions)}) or 'q' to quit:")  # noqa: T201
            choice = input().strip()

            if choice.lower() == "q":
                return

            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(transitions):
                    selected_transition = transitions[choice_num - 1]
                    transition_id = selected_transition["id"]
                    transition_name = selected_transition["name"]
                    to_status = selected_transition.get("to", {}).get("name", "Unknown")

                    print(f"Executing transition: {transition_name} -> {to_status}")  # noqa: T201
                    client.transition_issue(issue_key, transition_id)

                    # Verify the change
                    updated_issue = client.get_issue(issue_key)
                    print(f"✅ Transition successful! New status: {updated_issue.status}")  # noqa: T201
                else:
                    print("❌ Invalid choice")  # noqa: T201
            except ValueError:
                print("❌ Invalid input")  # noqa: T201

    except Exception as e:
        print(f"❌ Error: {e}")  # noqa: T201


def test_status_mapping(issue_key: str, target_status: str, jira_instance: int = 1) -> None:
    """Test transitioning to a specific status."""
    print(f"Testing transition to status '{target_status}' for issue: {issue_key}")  # noqa: T201

    try:
        config = load_config()

        if jira_instance == 1:
            jira_config = config.jira_instance_1
        else:
            jira_config = config.jira_instance_2

        client = JiraClient(jira_config)

        # Get current status
        issue = client.get_issue(issue_key)
        print(f"Current status: {issue.status}")  # noqa: T201

        # Test the transition
        success = client.transition_issue_to_status(issue_key, target_status)

        if success:
            updated_issue = client.get_issue(issue_key)
            print(f"✅ Successfully transitioned to: {updated_issue.status}")  # noqa: T201
        else:
            print(f"❌ Could not transition to: {target_status}")  # noqa: T201

            # Show available options
            transitions = client.get_transitions(issue_key)
            available_statuses = [t.get("to", {}).get("name", "") for t in transitions]
            print(f"Available target statuses: {available_statuses}")  # noqa: T201

    except Exception as e:
        print(f"❌ Error: {e}")  # noqa: T201


def main() -> None:
    """Test JIRA transitions."""
    if len(sys.argv) < 3:
        print("Usage:")  # noqa: T201
        print("  python test-transitions.py <issue_key> <jira_instance>")  # noqa: T201
        print("  python test-transitions.py <issue_key> <jira_instance> <target_status>")  # noqa: T201
        print("")  # noqa: T201
        print("Examples:")  # noqa: T201
        print("  python test-transitions.py PROJ-123 1")  # noqa: T201
        print("  python test-transitions.py PROJ-123 1 'In Progress'")  # noqa: T201
        sys.exit(1)

    issue_key = sys.argv[1]
    jira_instance = int(sys.argv[2])

    if len(sys.argv) >= 4:
        target_status = sys.argv[3]
        test_status_mapping(issue_key, target_status, jira_instance)
    else:
        test_transitions(issue_key, jira_instance)


if __name__ == "__main__":
    main()
