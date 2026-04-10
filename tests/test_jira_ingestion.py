"""Tests for JiraIngestionAgent and extract_jira_ids."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from src.agentic_akm.agents.ingestion import JiraIngestionAgent, extract_jira_ids
from src.agentic_akm.agents.base import AgentContext
from src.agentic_akm.graph.knowledge_graph import KnowledgeGraph


# ---------------------------------------------------------------------------
# Tests for extract_jira_ids
# ---------------------------------------------------------------------------

class TestExtractJiraIds:
    def test_single_key(self):
        text = "OCPBUGS-82439: [release-4.21] Mount pullsecret manifest to UI container"
        assert extract_jira_ids(text) == ["OCPBUGS-82439"]

    def test_multiple_keys(self):
        text = "STOR-456: Fix storage issue and OCPBUGS-789: related fix"
        assert extract_jira_ids(text) == ["STOR-456", "OCPBUGS-789"]

    def test_no_key(self):
        assert extract_jira_ids("Bug 12345: some fix with no jira key") == []

    def test_empty_string(self):
        assert extract_jira_ids("") == []

    def test_key_with_long_project(self):
        assert extract_jira_ids("OPENSHIFTBUGS-123: fix") == ["OPENSHIFTBUGS-123"]

    def test_lowercase_ignored(self):
        assert extract_jira_ids("ocpbugs-123: lowercase should not match") == []

    def test_key_at_start_of_string(self):
        assert extract_jira_ids("ABC-1 title") == ["ABC-1"]

    def test_key_at_end_of_string(self):
        assert extract_jira_ids("title ABC-1") == ["ABC-1"]


# ---------------------------------------------------------------------------
# Tests for JiraIngestionAgent
# ---------------------------------------------------------------------------

def _make_context(github_repo=None, tmpdir=None):
    """Helper to create an AgentContext with test config."""
    return AgentContext(
        repository_path=tmpdir or "/tmp",
        config={
            "github_repo": github_repo,
            "github_token": None,
            "jira_server": "https://redhat.atlassian.net",
            "jira_output_path": os.path.join(tmpdir or "/tmp", "jira_issues.json"),
        },
    )


MOCK_PRS = [
    {
        "number": 100,
        "title": "OCPBUGS-82439: [release-4.21] Mount pullsecret manifest to UI container",
        "body": "Mounts pull secret volume.",
        "state": "closed",
        "merged_at": "2024-01-15T10:30:00Z",
        "head_ref": "fix/OCPBUGS-82439",
        "base_ref": "master",
        "user": "dev1",
        "labels": ["bug"],
        "jira_keys": ["OCPBUGS-82439"],
        "files_changed": ["pkg/console/deployment.go"],
    },
    {
        "number": 101,
        "title": "STOR-456: Fix storage driver",
        "body": "Fixes CSI driver panic.",
        "state": "closed",
        "merged_at": "2024-01-10T14:20:00Z",
        "head_ref": "fix/STOR-456",
        "base_ref": "master",
        "user": "dev2",
        "labels": ["bug", "storage"],
        "jira_keys": ["STOR-456"],
        "files_changed": ["pkg/csi/driver.go"],
    },
    {
        "number": 102,
        "title": "Update docs, no jira key here",
        "body": "Doc updates.",
        "state": "closed",
        "merged_at": "2024-01-09T08:00:00Z",
        "head_ref": "docs/update",
        "base_ref": "master",
        "user": "dev3",
        "labels": ["docs"],
        "jira_keys": [],
        "files_changed": ["README.md"],
    },
]

MOCK_REPO_INFO = {
    "name": "installer",
    "full_name": "openshift/installer",
    "description": "OpenShift installer",
}

MOCK_JIRA_ISSUES = [
    {
        "key": "OCPBUGS-82439",
        "id": "10001",
        "summary": "Mount pullsecret manifest to UI container",
        "description": "The pull secret needs to be mounted into the console container.",
        "status": "Done",
        "labels": ["bug"],
        "created": "2024-01-05T10:00:00Z",
        "updated": "2024-01-15T10:30:00Z",
        "assignee": "Console Team",
        "reporter": "QE",
        "comments": [
            {"author": "Tech Lead", "body": "Needs volume mount", "created": "2024-01-06T09:00:00Z"}
        ],
        "links": [],
    },
    {
        "key": "STOR-456",
        "id": "10002",
        "summary": "Fix storage driver",
        "description": "Storage driver crashes under high load.",
        "status": "Done",
        "labels": ["bug"],
        "created": "2024-01-03T14:00:00Z",
        "updated": "2024-01-10T14:20:00Z",
        "assignee": "Storage Team",
        "reporter": "Customer Support",
        "comments": [],
        "links": [],
    },
]


class TestJiraIngestionAgentUnit:
    """Unit tests with mocked external calls."""

    def test_skips_when_no_github_repo(self):
        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_repo=None)
        agent.run(context, graph)

    @patch.object(JiraIngestionAgent, "_fetch_repo_info", return_value=MOCK_REPO_INFO)
    @patch.object(JiraIngestionAgent, "_fetch_prs")
    def test_skips_when_no_prs(self, mock_fetch_prs, _mock_repo):
        mock_fetch_prs.return_value = []

        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_repo="openshift/installer")
        agent.run(context, graph)

    @patch.object(JiraIngestionAgent, "_fetch_repo_info", return_value=MOCK_REPO_INFO)
    @patch.object(JiraIngestionAgent, "_fetch_prs")
    def test_skips_when_no_jira_keys_in_titles(self, mock_fetch_prs, _mock_repo):
        mock_fetch_prs.return_value = [MOCK_PRS[2]]  # PR with no jira key

        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_repo="openshift/installer")
        agent.run(context, graph)

    @patch.object(JiraIngestionAgent, "_fetch_jira_issues")
    @patch.object(JiraIngestionAgent, "_fetch_repo_info", return_value=MOCK_REPO_INFO)
    @patch.object(JiraIngestionAgent, "_fetch_prs")
    def test_full_flow_with_mocks(self, mock_fetch_prs, _mock_repo, mock_fetch_jira):
        """End-to-end test: PRs -> Jira key extraction -> Jira fetch -> JSON."""
        mock_fetch_prs.return_value = MOCK_PRS
        mock_fetch_jira.return_value = MOCK_JIRA_ISSUES

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_repo="openshift/installer", tmpdir=tmpdir)
            agent.run(context, graph)

            # Verify Jira keys were passed correctly
            called_keys = mock_fetch_jira.call_args[0][0]
            assert "OCPBUGS-82439" in called_keys
            assert "STOR-456" in called_keys

            # Verify JSON output
            json_path = os.path.join(tmpdir, "jira_issues.json")
            assert os.path.exists(json_path)

            with open(json_path) as f:
                data = json.load(f)

            print("\n--- jira_issues.json ---")
            print(json.dumps(data, indent=2))
            print("--- end ---")

            # Top-level structure
            assert "github" in data
            assert "jira" in data

            # GitHub section
            assert data["github"]["repository"] == MOCK_REPO_INFO
            assert len(data["github"]["pull_requests"]) == 3

            pr0 = data["github"]["pull_requests"][0]
            assert pr0["number"] == 100
            assert pr0["jira_keys"] == ["OCPBUGS-82439"]
            assert pr0["files_changed"] == ["pkg/console/deployment.go"]
            assert pr0["user"] == "dev1"

            # Jira section
            assert data["jira"]["project_key"] == "OCPBUGS"
            assert len(data["jira"]["issues"]) == 2

            issue0 = data["jira"]["issues"][0]
            assert issue0["key"] == "OCPBUGS-82439"
            assert issue0["summary"] == "Mount pullsecret manifest to UI container"
            assert issue0["status"] == "Done"
            assert issue0["comments"][0]["author"] == "Tech Lead"

            # Cross-reference: related_prs on jira issues
            assert issue0["related_prs"][0]["number"] == 100

    @patch.object(JiraIngestionAgent, "_fetch_jira_issues")
    @patch.object(JiraIngestionAgent, "_fetch_repo_info", return_value=MOCK_REPO_INFO)
    @patch.object(JiraIngestionAgent, "_fetch_prs")
    def test_json_output_structure(self, mock_fetch_prs, _mock_repo, mock_fetch_jira):
        """Verify the JSON output has the expected top-level schema."""
        mock_fetch_prs.return_value = [MOCK_PRS[0]]
        mock_fetch_jira.return_value = [MOCK_JIRA_ISSUES[0]]

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_repo="org/repo", tmpdir=tmpdir)
            agent.run(context, graph)

            with open(os.path.join(tmpdir, "jira_issues.json")) as f:
                data = json.load(f)

            assert set(data.keys()) == {"github", "jira"}
            assert set(data["github"].keys()) == {"repository", "pull_requests"}
            assert set(data["jira"].keys()) == {"project_key", "issues"}

            pr = data["github"]["pull_requests"][0]
            expected_pr_keys = {
                "number", "title", "body", "state", "merged_at",
                "head_ref", "base_ref", "user", "labels",
                "jira_keys", "files_changed",
            }
            assert set(pr.keys()) == expected_pr_keys

            issue = data["jira"]["issues"][0]
            expected_issue_keys = {
                "key", "id", "summary", "description", "status",
                "labels", "created", "updated", "assignee", "reporter",
                "comments", "links", "related_prs",
            }
            assert set(issue.keys()) == expected_issue_keys


# ---------------------------------------------------------------------------
# Tests for _fetch_jira_issues (mocking jira library)
# ---------------------------------------------------------------------------

class TestFetchJiraIssues:
    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_fetches_issues(self, mock_jira_class):
        """Should fetch full issue details for each key."""
        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira

        mock_issue = MagicMock()
        mock_issue.id = "10001"
        mock_issue.fields.summary = "Fix the bug"
        mock_issue.fields.description = "Detailed description of the bug."
        mock_issue.fields.status.name = "Done"
        mock_issue.fields.labels = ["bug"]
        mock_issue.fields.created = "2024-01-01T00:00:00Z"
        mock_issue.fields.updated = "2024-01-02T00:00:00Z"
        mock_issue.fields.assignee.displayName = "Dev Team"
        mock_issue.fields.reporter.displayName = "Reporter"
        mock_issue.fields.comment.comments = []
        mock_issue.fields.issuelinks = []
        mock_jira.issue.return_value = mock_issue

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(["OCPBUGS-123"], "https://redhat.atlassian.net")

        assert len(results) == 1
        assert results[0]["key"] == "OCPBUGS-123"
        assert results[0]["id"] == "10001"
        assert results[0]["summary"] == "Fix the bug"
        assert results[0]["description"] == "Detailed description of the bug."
        assert results[0]["status"] == "Done"
        assert results[0]["assignee"] == "Dev Team"

    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_handles_missing_issue(self, mock_jira_class):
        """Should skip issues that fail to fetch and continue."""
        from jira import JIRAError

        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira

        mock_issue_good = MagicMock()
        mock_issue_good.id = "10002"
        mock_issue_good.fields.summary = "Good issue"
        mock_issue_good.fields.description = "Description"
        mock_issue_good.fields.status.name = "Open"
        mock_issue_good.fields.labels = []
        mock_issue_good.fields.created = "2024-01-01T00:00:00Z"
        mock_issue_good.fields.updated = "2024-01-01T00:00:00Z"
        mock_issue_good.fields.assignee = None
        mock_issue_good.fields.reporter = None
        mock_issue_good.fields.comment.comments = []
        mock_issue_good.fields.issuelinks = []

        mock_jira.issue.side_effect = [
            JIRAError("Not found"),
            mock_issue_good,
        ]

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(
            ["BAD-999", "GOOD-1"], "https://redhat.atlassian.net"
        )

        assert len(results) == 1
        assert results[0]["key"] == "GOOD-1"

    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_handles_connection_failure(self, mock_jira_class):
        """Should return empty list if JIRA connection fails."""
        from jira import JIRAError

        mock_jira_class.side_effect = JIRAError("Connection refused")

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(["ABC-1"], "https://bad-server.example.com")

        assert results == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
