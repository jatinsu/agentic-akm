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
# Helper: sample github.json data
# ---------------------------------------------------------------------------

SAMPLE_GITHUB_DATA = {
    "github": {
        "repository": {
            "name": "installer",
            "full_name": "openshift/installer",
        },
        "pull_requests": [
            {
                "number": 100,
                "title": "OCPBUGS-82439: [release-4.21] Mount pullsecret manifest to UI container",
            },
            {
                "number": 101,
                "title": "STOR-456: Fix storage driver",
            },
            {
                "number": 102,
                "title": "Update docs, no jira key here",
            },
        ],
    }
}


def _make_context(github_json_path=None, tmpdir=None):
    """Helper to create an AgentContext with test config."""
    return AgentContext(
        repository_path=tmpdir or "/tmp",
        config={
            "github_json_path": github_json_path,
            "jira_server": "https://redhat.atlassian.net",
            "jira_output_path": os.path.join(tmpdir or "/tmp", "jira.json"),
        },
    )


def _write_github_json(tmpdir, data=None):
    """Write sample github.json and return its path."""
    path = os.path.join(tmpdir, "github.json")
    with open(path, "w") as f:
        json.dump(data or SAMPLE_GITHUB_DATA, f)
    return path


# ---------------------------------------------------------------------------
# Tests for JiraIngestionAgent
# ---------------------------------------------------------------------------

class TestJiraIngestionAgentUnit:
    """Unit tests with mocked external calls."""

    def test_skips_when_no_github_json_path(self):
        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_json_path=None)
        # Should not raise
        agent.run(context, graph)

    def test_skips_when_github_json_not_found(self):
        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_json_path="/nonexistent/github.json")
        # Should not raise
        agent.run(context, graph)

    def test_skips_when_no_prs_in_github_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"github": {"pull_requests": []}}
            path = _write_github_json(tmpdir, data)

            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_json_path=path, tmpdir=tmpdir)
            agent.run(context, graph)

    def test_skips_when_no_jira_keys_in_titles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {
                "github": {
                    "pull_requests": [
                        {"number": 1, "title": "Update docs, no jira key"},
                    ]
                }
            }
            path = _write_github_json(tmpdir, data)

            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_json_path=path, tmpdir=tmpdir)
            agent.run(context, graph)

    @patch.object(JiraIngestionAgent, "_fetch_jira_issues")
    def test_full_flow(self, mock_fetch_jira):
        """End-to-end: github.json -> extract keys -> fetch Jira -> jira.json."""
        mock_fetch_jira.return_value = {
            "OCPBUGS-82439": {
                "summary": "Mount pullsecret manifest to UI container",
                "description": "The pull secret needs to be mounted.",
                "comments": ["Needs volume mount"],
            },
            "STOR-456": {
                "summary": "Fix storage driver",
                "description": "Storage driver crashes under high load.",
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            github_path = _write_github_json(tmpdir)

            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_json_path=github_path, tmpdir=tmpdir)
            agent.run(context, graph)

            # Verify Jira keys were passed correctly
            called_keys = mock_fetch_jira.call_args[0][0]
            assert "OCPBUGS-82439" in called_keys
            assert "STOR-456" in called_keys

            # Verify jira.json output
            output_path = os.path.join(tmpdir, "jira.json")
            assert os.path.exists(output_path)

            with open(output_path) as f:
                data = json.load(f)

            print("\n--- jira.json ---")
            print(json.dumps(data, indent=2))
            print("--- end ---")

            # Should be keyed by issue key
            assert "OCPBUGS-82439" in data
            assert "STOR-456" in data

            assert data["OCPBUGS-82439"]["summary"] == "Mount pullsecret manifest to UI container"
            assert data["OCPBUGS-82439"]["comments"] == ["Needs volume mount"]

            assert data["STOR-456"]["summary"] == "Fix storage driver"
            assert "comments" not in data["STOR-456"]  # no comments -> key omitted

    @patch.object(JiraIngestionAgent, "_fetch_jira_issues")
    def test_output_structure(self, mock_fetch_jira):
        """Verify jira.json has the expected per-issue schema."""
        mock_fetch_jira.return_value = {
            "ABC-123": {
                "summary": "Test issue",
                "description": "A test description.",
                "comments": ["comment 1"],
                "epic_key": "ABC-100",
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            github_path = _write_github_json(tmpdir)
            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_json_path=github_path, tmpdir=tmpdir)
            agent.run(context, graph)

            with open(os.path.join(tmpdir, "jira.json")) as f:
                data = json.load(f)

            issue = data["ABC-123"]
            assert issue["summary"] == "Test issue"
            assert issue["description"] == "A test description."
            assert issue["comments"] == ["comment 1"]
            assert issue["epic_key"] == "ABC-100"


# ---------------------------------------------------------------------------
# Tests for _fetch_jira_issues (mocking jira library)
# ---------------------------------------------------------------------------

class TestFetchJiraIssues:
    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_fetches_issues(self, mock_jira_class):
        """Should return a dict keyed by issue key."""
        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira
        mock_jira.fields.return_value = []  # no epic link field

        mock_issue = MagicMock()
        mock_issue.fields.summary = "Fix the bug"
        mock_issue.fields.description = "Detailed description of the bug."
        mock_issue.fields.comment.comments = []
        mock_jira.issue.return_value = mock_issue

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(["OCPBUGS-123"], "https://redhat.atlassian.net")

        assert "OCPBUGS-123" in results
        assert results["OCPBUGS-123"]["summary"] == "Fix the bug"
        assert results["OCPBUGS-123"]["description"] == "Detailed description of the bug."

    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_includes_comments_when_present(self, mock_jira_class):
        """Should include comments list when issue has comments."""
        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira
        mock_jira.fields.return_value = []

        mock_comment = MagicMock()
        mock_comment.body = "verified before merge"

        mock_issue = MagicMock()
        mock_issue.fields.summary = "Issue with comments"
        mock_issue.fields.description = "Desc"
        mock_issue.fields.comment.comments = [mock_comment]
        mock_jira.issue.return_value = mock_issue

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(["ABC-1"], "https://redhat.atlassian.net")

        assert results["ABC-1"]["comments"] == ["verified before merge"]

    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_includes_epic_key_when_present(self, mock_jira_class):
        """Should include epic_key when epic link field exists."""
        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira
        mock_jira.fields.return_value = [
            {"id": "customfield_12345", "name": "Epic Link"},
        ]

        mock_issue = MagicMock()
        mock_issue.fields.summary = "Child issue"
        mock_issue.fields.description = "Desc"
        mock_issue.fields.comment.comments = []
        mock_issue.fields.customfield_12345 = "EPIC-100"
        mock_jira.issue.return_value = mock_issue

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(["CHILD-1"], "https://redhat.atlassian.net")

        assert results["CHILD-1"]["epic_key"] == "EPIC-100"

    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_handles_missing_issue(self, mock_jira_class):
        """Should skip issues that fail to fetch and continue."""
        from jira import JIRAError

        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira
        mock_jira.fields.return_value = []

        mock_good_issue = MagicMock()
        mock_good_issue.fields.summary = "Good issue"
        mock_good_issue.fields.description = "Description"
        mock_good_issue.fields.comment.comments = []

        mock_jira.issue.side_effect = [
            JIRAError("Not found"),
            mock_good_issue,
        ]

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(
            ["BAD-999", "GOOD-1"], "https://redhat.atlassian.net"
        )

        assert len(results) == 1
        assert "GOOD-1" in results

    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_handles_connection_failure(self, mock_jira_class):
        """Should return empty dict if JIRA connection fails."""
        from jira import JIRAError

        mock_jira_class.side_effect = JIRAError("Connection refused")

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(["ABC-1"], "https://bad-server.example.com")

        assert results == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
