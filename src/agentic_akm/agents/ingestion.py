"""Ingestion agents."""

import os
import re
import json
import yaml
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

    Matches the pattern used in kenjpais/web-page-summarizer-ai.
    """
    return re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", text)


class JiraIngestionAgent(Agent):
    """Reads a github.json file, extracts JIRA keys from PR titles, fetches
    JIRA issue details, and writes jira.json.

    Input:  github.json  (repository + pull_requests)
    Output: jira.json    (keyed by JIRA issue key with summary, description,
                          comments, and epic_key)
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

        github_json_path = config.get("github_json_path")
        jira_server = config.get("jira_server", "https://redhat.atlassian.net")
        output_path = config.get("jira_output_path", "./output/jira.json")

        if not github_json_path:
            print(f"[{self.name}] Skipping: no github_json_path configured")
            return

        # --- Step 1: Read github.json ---
        github_data = self._read_github_json(github_json_path)
        if not github_data:
            return

        prs = github_data.get("github", {}).get("pull_requests", [])
        if not prs:
            print(f"[{self.name}] No pull_requests found in {github_json_path}")
            return

        print(f"[{self.name}] Read {len(prs)} PRs from {github_json_path}")

        # --- Step 2: Extract JIRA keys from PR titles ---
        unique_keys = set()
        for pr in prs:
            keys = extract_jira_ids(pr.get("title", ""))
            unique_keys.update(keys)

        if not unique_keys:
            print(f"[{self.name}] No JIRA keys found in PR titles")
            return

        print(f"[{self.name}] Found {len(unique_keys)} unique JIRA keys")

        # --- Step 3: Fetch JIRA issue details ---
        jira_issues = self._fetch_jira_issues(list(unique_keys), jira_server)
        print(f"[{self.name}] Fetched {len(jira_issues)} JIRA issues")

        # --- Step 4: Write jira.json ---
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            json.dump(jira_issues, f, indent=2)

        print(f"[{self.name}] Wrote {len(jira_issues)} issues to {output_file}")

    def _read_github_json(self, path: str) -> Optional[Dict[str, Any]]:
        """Read and parse a github.json file."""
        try:
            with open(path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"[{self.name}] File not found: {path}")
            return None
        except json.JSONDecodeError as e:
            print(f"[{self.name}] Invalid JSON in {path}: {e}")
            return None

    def _fetch_jira_issues(
        self, jira_keys: List[str], jira_server: str
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch JIRA issue details and return as a dict keyed by issue key.

        Each value contains summary, description, comments (list of strings),
        and epic_key. Follows the approach from kenjpais/web-page-summarizer-ai 
        """
        try:
            jira = JIRA(options={"server": jira_server})
        except JIRAError as e:
            print(f"[{self.name}] Failed to connect to JIRA server {jira_server}: {e}")
            return {}

        # Find the epic link custom field ID
        epic_link_field_id = None
        try:
            for field in jira.fields():
                if field.get("name", "").lower() == "epic link":
                    epic_link_field_id = field["id"]
                    break
        except Exception:
            pass

        issues: Dict[str, Dict[str, Any]] = {}
        queue = list(jira_keys)
        visited: set = set()

        while queue:
            key = queue.pop(0)
            if key in visited:
                continue
            visited.add(key)

            try:
                fields_to_fetch = "summary,description,comment"
                if epic_link_field_id:
                    fields_to_fetch += f",{epic_link_field_id}"

                issue = jira.issue(key, fields=fields_to_fetch)
                fields = issue.fields

                entry: Dict[str, Any] = {
                    "summary": getattr(fields, "summary", "") or "",
                    "description": getattr(fields, "description", "") or "",
                }

                # Comments as plain strings
                raw_comments = getattr(fields, "comment", None)
                if raw_comments:
                    comment_bodies = [
                        getattr(c, "body", "") or ""
                        for c in getattr(raw_comments, "comments", [])
                    ]
                    if comment_bodies:
                        entry["comments"] = comment_bodies

                # Epic key — follow the link and queue the epic for fetching
                if epic_link_field_id:
                    epic_key = getattr(fields, epic_link_field_id, None)
                    if epic_key:
                        entry["epic_key"] = epic_key
                        if epic_key not in visited:
                            queue.append(epic_key)

                issues[key] = entry
            except JIRAError as e:
                print(f"[{self.name}] Failed to fetch {key}: {e}")
            except Exception as e:
                print(f"[{self.name}] Unexpected error fetching {key}: {e}")

        return issues
