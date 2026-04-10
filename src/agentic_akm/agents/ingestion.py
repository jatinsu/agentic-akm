"""Ingestion agents."""

import os
import re
import json
import yaml
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional

from jira import JIRA, JIRAError

from .base import Agent, AgentContext
from ..graph import KnowledgeGraph, NodeType, EdgeType


class RepositoryScannerAgent(Agent):
    """Scans repository structure and detects modules."""

    def __init__(self):
        super().__init__("RepositoryScannerAgent")

    @property
    def input_requirements(self) -> List[str]:
        return ["filesystem"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.REPOSITORY, NodeType.MODULE]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        repo_path = Path(context.repository_path)

        repo_node = graph.add_node(
            NodeType.REPOSITORY,
            {
                "name": repo_path.name,
                "path": str(repo_path.absolute()),
            },
            self.name,
        )

        languages = set()
        build_systems = []

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for file in files:
                if file.endswith(".py"):
                    languages.add("Python")
                elif file.endswith((".js", ".ts")):
                    languages.add("JavaScript/TypeScript")
                elif file.endswith(".go"):
                    languages.add("Go")
                elif file.endswith(".java"):
                    languages.add("Java")

                if file == "pom.xml":
                    build_systems.append("Maven")
                elif file == "build.gradle":
                    build_systems.append("Gradle")
                elif file == "go.mod":
                    build_systems.append("Go Modules")
                elif file == "package.json":
                    build_systems.append("npm")

        module_node = graph.add_node(
            NodeType.MODULE,
            {
                "name": "root",
                "languages": list(languages),
                "build_systems": build_systems,
            },
            self.name,
        )

        # Create edge: Repository contains Module
        graph.add_edge(
            repo_node,
            module_node,
            EdgeType.RELATED_TO,
            {"relationship": "contains"},
        )


class OpenShiftManifestAgent(Agent):
    """Parses OpenShift/Kubernetes manifests."""

    def __init__(self):
        super().__init__("OpenShiftManifestAgent")

    @property
    def input_requirements(self) -> List[str]:
        return ["filesystem"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.OPENSHIFT_RESOURCE, NodeType.SERVICE, NodeType.DEPLOYMENT]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        repo_path = Path(context.repository_path)

        # Get repository node
        repo_nodes = graph.get_nodes_by_type(NodeType.REPOSITORY)
        repo_node = repo_nodes[0] if repo_nodes else None

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]

            for file in files:
                if file.endswith((".yaml", ".yml")):
                    file_path = Path(root) / file
                    self._process_manifest(file_path, graph, repo_node)

    def _process_manifest(self, file_path: Path, graph: KnowledgeGraph, repo_node: str = None) -> None:
        try:
            with open(file_path, "r") as f:
                docs = yaml.safe_load_all(f)
                for doc in docs:
                    if not doc or "kind" not in doc:
                        continue

                    kind = doc.get("kind")
                    metadata = doc.get("metadata", {})
                    name = metadata.get("name", "unknown")
                    namespace = metadata.get("namespace")

                    if kind in ["Deployment", "DeploymentConfig"]:
                        node_id = graph.add_node(
                            NodeType.DEPLOYMENT,
                            {
                                "name": name,
                                "kind": kind,
                                "file": str(file_path),
                                "namespace": namespace,
                                "spec": doc.get("spec", {}),
                            },
                            self.name,
                        )

                        # Link to repository
                        if repo_node:
                            graph.add_edge(
                                repo_node,
                                node_id,
                                EdgeType.RELATED_TO,
                                {"relationship": "contains_deployment"},
                            )

                        # Link to services by label matching
                        spec = doc.get("spec", {})
                        selector = spec.get("selector", {})
                        if selector:
                            self._link_deployment_to_service(graph, node_id, selector, namespace)

                    elif kind == "Service":
                        node_id = graph.add_node(
                            NodeType.SERVICE,
                            {
                                "name": name,
                                "kind": kind,
                                "file": str(file_path),
                                "namespace": namespace,
                                "ports": doc.get("spec", {}).get("ports", []),
                                "selector": doc.get("spec", {}).get("selector", {}),
                            },
                            self.name,
                        )

                        # Link to repository
                        if repo_node:
                            graph.add_edge(
                                repo_node,
                                node_id,
                                EdgeType.RELATED_TO,
                                {"relationship": "contains_service"},
                            )

                    elif kind in ["Route", "BuildConfig", "ImageStream"]:
                        node_id = graph.add_node(
                            NodeType.OPENSHIFT_RESOURCE,
                            {
                                "name": name,
                                "kind": kind,
                                "file": str(file_path),
                                "namespace": namespace,
                                "spec": doc.get("spec", {}),
                            },
                            self.name,
                        )

                        # Link to repository
                        if repo_node:
                            graph.add_edge(
                                repo_node,
                                node_id,
                                EdgeType.RELATED_TO,
                                {"relationship": f"contains_{kind.lower()}"},
                            )

                        # Link Routes to Services
                        if kind == "Route":
                            self._link_route_to_service(graph, node_id, doc.get("spec", {}), namespace)

                    elif kind == "ConfigMap":
                        node_id = graph.add_node(
                            NodeType.CONFIG_MAP,
                            {
                                "name": name,
                                "file": str(file_path),
                                "namespace": namespace,
                                "data": doc.get("data", {}),
                            },
                            self.name,
                        )

                        # Link to repository
                        if repo_node:
                            graph.add_edge(
                                repo_node,
                                node_id,
                                EdgeType.CONFIGURED_BY,
                                {"relationship": "repository_config"},
                            )

        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    def _link_deployment_to_service(self, graph: KnowledgeGraph, deployment_id: str, selector: dict, namespace: str):
        """Link deployment to matching services."""
        services = graph.get_nodes_by_type(NodeType.SERVICE)
        for service_id in services:
            service = graph.get_node(service_id)
            if not service:
                continue

            service_attrs = service.get("attributes", {})
            service_selector = service_attrs.get("selector", {})
            service_namespace = service_attrs.get("namespace")

            # Match if selectors overlap and same namespace
            if service_namespace == namespace and service_selector:
                if self._selectors_match(selector, service_selector):
                    graph.add_edge(
                        deployment_id,
                        service_id,
                        EdgeType.EXPOSES_API,
                        {"relationship": "deployment_to_service"},
                    )

    def _link_route_to_service(self, graph: KnowledgeGraph, route_id: str, spec: dict, namespace: str):
        """Link route to target service."""
        to_spec = spec.get("to", {})
        service_name = to_spec.get("name")

        if service_name:
            services = graph.get_nodes_by_type(NodeType.SERVICE)
            for service_id in services:
                service = graph.get_node(service_id)
                if not service:
                    continue

                service_attrs = service.get("attributes", {})
                if (service_attrs.get("name") == service_name and
                    service_attrs.get("namespace") == namespace):
                    graph.add_edge(
                        route_id,
                        service_id,
                        EdgeType.EXPOSES_API,
                        {"relationship": "route_to_service"},
                    )

    def _selectors_match(self, selector1: dict, selector2: dict) -> bool:
        """Check if selectors match (any common labels)."""
        if not selector1 or not selector2:
            return False

        # Check for matchLabels (Deployment style)
        match_labels1 = selector1.get("matchLabels", selector1)

        # Check if any labels match
        for key, value in match_labels1.items():
            if selector2.get(key) == value:
                return True

        return False


def extract_jira_ids(text: str) -> List[str]:
    """Extract JIRA issue keys from text (e.g. 'OCPBUGS-82439' from a PR title).

    Matches the pattern used in web-page-summarizer-ai/scrapers/jira_scraper.py.
    """
    return re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", text)


class JiraIngestionAgent(Agent):
    """Fetches GitHub PR titles, extracts JIRA keys, and retrieves JIRA issue details.

    Follows the approach from kenjpais/web-page-summarizer-ai:
    1. Fetch PR titles from a GitHub repository using the REST API.
    2. Extract JIRA issue keys from the titles using regex.
    3. Fetch each JIRA issue's summary and description via the jira library.
    4. Write results to a JSON file and add nodes to the knowledge graph.
    """

    def __init__(self):
        super().__init__("JiraIngestionAgent")

    @property
    def input_requirements(self) -> List[str]:
        return ["filesystem"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.JIRA_ISSUE]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        config = context.config

        github_repo = config.get("github_repo")  # e.g. "openshift/installer"
        jira_server = config.get("jira_server", "https://redhat.atlassian.net")
        github_token = config.get("github_token")
        output_path = config.get("jira_output_path", "./output/jira_issues.json")

        if not github_repo:
            print(f"[{self.name}] Skipping: no github_repo configured")
            return

        # --- Step 1: Fetch PR titles from GitHub ---
        pr_titles = self._fetch_pr_titles(github_repo, github_token)
        if not pr_titles:
            print(f"[{self.name}] No PR titles fetched from {github_repo}")
            return

        print(f"[{self.name}] Fetched {len(pr_titles)} PR titles from {github_repo}")

        # --- Step 2: Extract JIRA keys from PR titles ---
        jira_key_to_pr = {}
        for pr in pr_titles:
            keys = extract_jira_ids(pr["title"])
            for key in keys:
                jira_key_to_pr.setdefault(key, []).append(pr)

        unique_keys = list(jira_key_to_pr.keys())
        if not unique_keys:
            print(f"[{self.name}] No JIRA keys found in PR titles")
            return

        print(f"[{self.name}] Found {len(unique_keys)} unique JIRA keys in PR titles")

        # --- Step 3: Fetch JIRA issue details ---
        jira_issues = self._fetch_jira_issues(unique_keys, jira_server)
        print(f"[{self.name}] Fetched {len(jira_issues)} JIRA issues")

        # --- Step 4: Write to JSON ---
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        results = []
        for issue in jira_issues:
            result = {
                "key": issue["key"],
                "summary": issue["summary"],
                "description": issue["description"],
                "source_prs": [
                    {"number": pr["number"], "title": pr["title"], "body": pr["body"]}
                    for pr in jira_key_to_pr.get(issue["key"], [])
                ],
            }
            results.append(result)

        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)

        print(f"[{self.name}] Wrote {len(results)} issues to {output_file}")

    def _fetch_pr_titles(
        self, github_repo: str, github_token: Optional[str] = None, max_pages: int = 3
    ) -> List[Dict[str, Any]]:
        """Fetch merged PR titles from a GitHub repository using the REST API."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        pr_list = []
        for page in range(1, max_pages + 1):
            url = f"https://api.github.com/repos/{github_repo}/pulls"
            params = {"state": "closed", "per_page": 100, "page": page}

            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"[{self.name}] GitHub API error on page {page}: {e}")
                break

            pulls = resp.json()
            if not pulls:
                break

            for pr in pulls:
                if pr.get("merged_at"):
                    pr_list.append({"number": pr["number"], "title": pr["title"], "body": pr.get("body") or ""})

        return pr_list

    def _fetch_jira_issues(
        self, jira_keys: List[str], jira_server: str
    ) -> List[Dict[str, Any]]:
        """Fetch JIRA issue details using the jira library.

        Follows the approach from web-page-summarizer-ai/clients/jira_client.py
        and scrapers/jira_scraper.py — connect without auth for public instances,
        then fetch summary and description for each issue.
        """
        try:
            jira = JIRA(options={"server": jira_server})
        except JIRAError as e:
            print(f"[{self.name}] Failed to connect to JIRA server {jira_server}: {e}")
            return []

        issues = []
        for key in jira_keys:
            try:
                issue = jira.issue(key, fields="summary,description")
                summary = getattr(issue.fields, "summary", "") or ""
                description = getattr(issue.fields, "description", "") or ""
                issues.append({
                    "key": key,
                    "summary": summary,
                    "description": description,
                })
            except JIRAError as e:
                print(f"[{self.name}] Failed to fetch {key}: {e}")
            except Exception as e:
                print(f"[{self.name}] Unexpected error fetching {key}: {e}")

        return issues
