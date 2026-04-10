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
            "jira_server": "https://issues.redhat.com",
            "jira_output_path": os.path.join(tmpdir or "/tmp", "jira_issues.json"),
        },
    )


class TestJiraIngestionAgentUnit:
    """Unit tests with mocked external calls."""

    def test_skips_when_no_github_repo(self):
        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_repo=None)

        # Should return without error
        agent.run(context, graph)

    @patch.object(JiraIngestionAgent, "_fetch_pr_titles")
    def test_skips_when_no_prs(self, mock_fetch_prs):
        mock_fetch_prs.return_value = []

        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_repo="openshift/installer")

        agent.run(context, graph)

    @patch.object(JiraIngestionAgent, "_fetch_pr_titles")
    def test_skips_when_no_jira_keys_in_titles(self, mock_fetch_prs):
        mock_fetch_prs.return_value = [
            {"number": 1, "title": "Update README"},
            {"number": 2, "title": "Fix typo in docs"},
        ]

        agent = JiraIngestionAgent()
        graph = KnowledgeGraph()
        context = _make_context(github_repo="openshift/installer")

        agent.run(context, graph)

    @patch.object(JiraIngestionAgent, "_fetch_jira_issues")
    @patch.object(JiraIngestionAgent, "_fetch_pr_titles")
    def test_full_flow_with_mocks(self, mock_fetch_prs, mock_fetch_jira):
        """End-to-end test: PR titles -> Jira key extraction -> Jira fetch -> JSON."""
        mock_fetch_prs.return_value = [
            {"number": 100, "title": "OCPBUGS-82439: [release-4.21] Mount pullsecret manifest to UI container", "body": "Mounts pull secret volume."},
            {"number": 101, "title": "STOR-456: Fix storage driver", "body": "Fixes CSI driver panic."},
            {"number": 102, "title": "Update docs, no jira key here", "body": "Doc updates."},
        ]
        mock_fetch_jira.return_value = [
            {
                "key": "OCPBUGS-82439",
                "summary": "Mount pullsecret manifest to UI container",
                "description": "The pull secret needs to be mounted into the console container.",
            },
            {
                "key": "STOR-456",
                "summary": "Fix storage driver",
                "description": "Storage driver crashes under high load.",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_repo="openshift/installer", tmpdir=tmpdir)
            agent.run(context, graph)

            # Verify Jira keys were passed correctly to _fetch_jira_issues
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

            assert len(data) == 2
            keys_in_json = {item["key"] for item in data}
            assert keys_in_json == {"OCPBUGS-82439", "STOR-456"}

            # Verify source_prs are included with body
            for item in data:
                assert "source_prs" in item
                if item["key"] == "OCPBUGS-82439":
                    assert item["source_prs"][0]["number"] == 100
                    assert item["source_prs"][0]["body"] == "Mounts pull secret volume."
                elif item["key"] == "STOR-456":
                    assert item["source_prs"][0]["number"] == 101
                    assert item["source_prs"][0]["body"] == "Fixes CSI driver panic."

    @patch.object(JiraIngestionAgent, "_fetch_jira_issues")
    @patch.object(JiraIngestionAgent, "_fetch_pr_titles")
    def test_json_output_structure(self, mock_fetch_prs, mock_fetch_jira):
        """Verify the JSON output has the expected schema."""
        mock_fetch_prs.return_value = [
            {"number": 1, "title": "ABC-10: some fix", "body": "Fix description."},
        ]
        mock_fetch_jira.return_value = [
            {"key": "ABC-10", "summary": "Some fix", "description": "Details here."},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = JiraIngestionAgent()
            graph = KnowledgeGraph()
            context = _make_context(github_repo="org/repo", tmpdir=tmpdir)
            agent.run(context, graph)

            with open(os.path.join(tmpdir, "jira_issues.json")) as f:
                data = json.load(f)

            assert len(data) == 1
            issue = data[0]
            assert set(issue.keys()) == {"key", "summary", "description", "source_prs"}
            assert set(issue["source_prs"][0].keys()) == {"number", "title", "body"}
            assert issue["key"] == "ABC-10"
            assert issue["summary"] == "Some fix"
            assert issue["description"] == "Details here."


# ---------------------------------------------------------------------------
# Tests for _fetch_jira_issues (mocking jira library)
# ---------------------------------------------------------------------------

class TestFetchJiraIssues:
    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_fetches_issues(self, mock_jira_class):
        """Should fetch summary and description for each key."""
        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira

        mock_issue = MagicMock()
        mock_issue.fields.summary = "Fix the bug"
        mock_issue.fields.description = "Detailed description of the bug."
        mock_jira.issue.return_value = mock_issue

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(["OCPBUGS-123"], "https://issues.redhat.com")

        assert len(results) == 1
        assert results[0]["key"] == "OCPBUGS-123"
        assert results[0]["summary"] == "Fix the bug"
        assert results[0]["description"] == "Detailed description of the bug."

    @patch("src.agentic_akm.agents.ingestion.JIRA")
    def test_handles_missing_issue(self, mock_jira_class):
        """Should skip issues that fail to fetch and continue."""
        from jira import JIRAError

        mock_jira = MagicMock()
        mock_jira_class.return_value = mock_jira

        mock_issue_good = MagicMock()
        mock_issue_good.fields.summary = "Good issue"
        mock_issue_good.fields.description = "Description"

        mock_jira.issue.side_effect = [
            JIRAError("Not found"),
            mock_issue_good,
        ]

        agent = JiraIngestionAgent()
        results = agent._fetch_jira_issues(
            ["BAD-999", "GOOD-1"], "https://issues.redhat.com"
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
