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
    """Fetches GitHub PRs, extracts JIRA keys, and retrieves JIRA issue details.

    Follows the approach from kenjpais/web-page-summarizer-ai:
    1. Fetch merged PRs from a GitHub repository using the REST API.
    2. Extract JIRA issue keys from the PR titles using regex.
    3. Fetch each JIRA issue's details via the jira library.
    4. Write combined github + jira data to a JSON file.
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

        # --- Step 1: Fetch repo info and merged PRs from GitHub ---
        repo_info = self._fetch_repo_info(github_repo, github_token)
        prs = self._fetch_prs(github_repo, github_token)
        if not prs:
            print(f"[{self.name}] No merged PRs fetched from {github_repo}")
            return

        print(f"[{self.name}] Fetched {len(prs)} merged PRs from {github_repo}")

        # --- Step 2: Extract JIRA keys from PR titles ---
        jira_key_to_prs: Dict[str, List[Dict[str, Any]]] = {}
        for pr in prs:
            keys = extract_jira_ids(pr["title"])
            pr["jira_keys"] = keys
            for key in keys:
                jira_key_to_prs.setdefault(key, []).append(pr)

        unique_keys = list(jira_key_to_prs.keys())
        if not unique_keys:
            print(f"[{self.name}] No JIRA keys found in PR titles")
            return

        print(f"[{self.name}] Found {len(unique_keys)} unique JIRA keys in PR titles")

        # Derive project key from the first jira key (e.g. "MCO-445" -> "MCO")
        project_key = unique_keys[0].rsplit("-", 1)[0]

        # --- Step 3: Fetch JIRA issue details ---
        jira_issues = self._fetch_jira_issues(unique_keys, jira_server)
        print(f"[{self.name}] Fetched {len(jira_issues)} JIRA issues")

        # --- Step 4: Cross-reference and build output ---
        # Attach related_prs to each jira issue
        for issue in jira_issues:
            related = jira_key_to_prs.get(issue["key"], [])
            issue["related_prs"] = [
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "state": pr["state"],
                    "merged_at": pr["merged_at"],
                }
                for pr in related
            ]

        # --- Step 5: Write to JSON ---
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        result = {
            "github": {
                "repository": repo_info,
                "pull_requests": prs,
            },
            "jira": {
                "project_key": project_key,
                "issues": jira_issues,
            },
        }

        with open(output_file, "w") as f:
            json.dump(result, f, indent=2)

        print(f"[{self.name}] Wrote output to {output_file}")

    def _fetch_repo_info(
        self, github_repo: str, github_token: Optional[str] = None
    ) -> Dict[str, str]:
        """Fetch repository metadata from GitHub."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        try:
            resp = requests.get(
                f"https://api.github.com/repos/{github_repo}",
                headers=headers, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "name": data.get("name", ""),
                "full_name": data.get("full_name", ""),
                "description": data.get("description") or "",
            }
        except requests.RequestException as e:
            print(f"[{self.name}] Failed to fetch repo info: {e}")
            owner, name = github_repo.split("/", 1)
            return {"name": name, "full_name": github_repo, "description": ""}

    def _fetch_prs(
        self, github_repo: str, github_token: Optional[str] = None, max_pages: int = 3
    ) -> List[Dict[str, Any]]:
        """Fetch merged PRs with full details from a GitHub repository."""
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
                if not pr.get("merged_at"):
                    continue

                files = self._fetch_pr_files(github_repo, pr["number"], headers)

                pr_list.append({
                    "number": pr["number"],
                    "title": pr["title"],
                    "body": pr.get("body") or "",
                    "state": pr.get("state", ""),
                    "merged_at": pr["merged_at"],
                    "head_ref": pr.get("head", {}).get("ref", ""),
                    "base_ref": pr.get("base", {}).get("ref", ""),
                    "user": pr.get("user", {}).get("login", ""),
                    "labels": [label["name"] for label in pr.get("labels", [])],
                    "jira_keys": extract_jira_ids(pr["title"]),
                    "files_changed": files,
                })

        return pr_list

    def _fetch_pr_files(
        self, github_repo: str, pr_number: int, headers: Dict[str, str]
    ) -> List[str]:
        """Fetch the list of files changed in a PR."""
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{github_repo}/pulls/{pr_number}/files",
                headers=headers, timeout=30,
            )
            resp.raise_for_status()
            return [f["filename"] for f in resp.json()]
        except requests.RequestException:
            return []

    def _fetch_jira_issues(
        self, jira_keys: List[str], jira_server: str
    ) -> List[Dict[str, Any]]:
        """Fetch JIRA issue details using the jira library.

        Follows the approach from web-page-summarizer-ai/clients/jira_client.py
        and scrapers/jira_scraper.py — connect without auth for public instances.
        """
        try:
            jira = JIRA(options={"server": jira_server})
        except JIRAError as e:
            print(f"[{self.name}] Failed to connect to JIRA server {jira_server}: {e}")
            return []

        issues = []
        for key in jira_keys:
            try:
                issue = jira.issue(
                    key,
                    fields="summary,description,status,labels,created,updated,"
                           "assignee,reporter,comment,issuelinks",
                )
                fields = issue.fields

                # Comments
                comments = []
                raw_comments = getattr(fields, "comment", None)
                if raw_comments:
                    for c in getattr(raw_comments, "comments", []):
                        comments.append({
                            "author": getattr(c.author, "displayName", "") if hasattr(c, "author") else "",
                            "body": getattr(c, "body", "") or "",
                            "created": getattr(c, "created", "") or "",
                        })

                # Issue links
                links = []
                for link in getattr(fields, "issuelinks", []) or []:
                    link_entry = {"type": getattr(link.type, "name", "")}
                    if hasattr(link, "inwardIssue"):
                        link_entry["inward_key"] = link.inwardIssue.key
                    if hasattr(link, "outwardIssue"):
                        link_entry["outward_key"] = link.outwardIssue.key
                    links.append(link_entry)

                assignee = getattr(fields, "assignee", None)
                reporter = getattr(fields, "reporter", None)
                status = getattr(fields, "status", None)

                issues.append({
                    "key": key,
                    "id": issue.id,
                    "summary": getattr(fields, "summary", "") or "",
                    "description": getattr(fields, "description", "") or "",
                    "status": getattr(status, "name", "") if status else "",
                    "labels": list(getattr(fields, "labels", []) or []),
                    "created": getattr(fields, "created", "") or "",
                    "updated": getattr(fields, "updated", "") or "",
                    "assignee": getattr(assignee, "displayName", "") if assignee else "",
                    "reporter": getattr(reporter, "displayName", "") if reporter else "",
                    "comments": comments,
                    "links": links,
                })
            except JIRAError as e:
                print(f"[{self.name}] Failed to fetch {key}: {e}")
            except Exception as e:
                print(f"[{self.name}] Unexpected error fetching {key}: {e}")

        return issues
