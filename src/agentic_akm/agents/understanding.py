"""Understanding agents."""

import json
from typing import List
from pathlib import Path

from .base import Agent, AgentContext
from ..graph import KnowledgeGraph, NodeType, EdgeType
from ..llm import GeminiClient, PromptMode


class ServiceInferenceAgent(Agent):
    """Infers logical services from code and manifests."""

    def __init__(self, gemini_client: GeminiClient):
        super().__init__("ServiceInferenceAgent")
        self.gemini = gemini_client

    @property
    def input_requirements(self) -> List[str]:
        return ["deployment"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.SERVICE]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        deployments = graph.get_nodes_by_type(NodeType.DEPLOYMENT)

        for deployment_id in deployments:
            deployment = graph.get_node(deployment_id)
            if not deployment:
                continue

            deployment_attrs = deployment.get("attributes", {})
            name = deployment_attrs.get("name", "unknown")

            prompt = f"""
            Analyze this deployment and infer the logical service:
            Name: {name}
            Spec: {json.dumps(deployment_attrs.get("spec", {}), indent=2)}

            Determine:
            1. Service purpose
            2. Service type (API, worker, database, etc.)
            3. Key responsibilities

            Respond in JSON format.
            """

            response = self.gemini.generate(prompt, mode=PromptMode.INFERENCE)

            service_node = graph.add_node(
                NodeType.SERVICE,
                {
                    "name": name,
                    "inferred_purpose": response,
                    "source_deployment": deployment_id,
                },
                self.name,
                confidence=0.8,
            )

            graph.add_edge(
                deployment_id,
                service_node,
                EdgeType.INFERRED_FROM,
                confidence=0.8,
            )


class APIExtractionAgent(Agent):
    """Extracts REST/gRPC endpoints."""

    def __init__(self, gemini_client: GeminiClient):
        super().__init__("APIExtractionAgent")
        self.gemini = gemini_client

    @property
    def input_requirements(self) -> List[str]:
        return ["module"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.API]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        repo_path = Path(context.repository_path)

        api_files = []
        for py_file in repo_path.rglob("*.py"):
            if "api" in str(py_file).lower() or "controller" in str(py_file).lower():
                api_files.append(py_file)

        for api_file in api_files[:5]:
            try:
                with open(api_file, "r") as f:
                    code = f.read()

                if len(code) > 5000:
                    code = code[:5000]

                response = self.gemini.extract_entities(code)

                api_node = graph.add_node(
                    NodeType.API,
                    {
                        "file": str(api_file),
                        "extracted_info": response,
                    },
                    self.name,
                    confidence=0.7,
                )

            except Exception as e:
                print(f"Error processing {api_file}: {e}")


class DependencyAnalysisAgent(Agent):
    """Builds dependency graph."""

    def __init__(self):
        super().__init__("DependencyAnalysisAgent")

    @property
    def input_requirements(self) -> List[str]:
        return ["module"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.DEPENDENCY]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        repo_path = Path(context.repository_path)

        # Get module node to link dependencies
        module_nodes = graph.get_nodes_by_type(NodeType.MODULE)
        module_node = module_nodes[0] if module_nodes else None

        dependency_files = {
            "requirements.txt": self._parse_python_requirements,
            "package.json": self._parse_npm_package,
            "go.mod": self._parse_go_mod,
        }

        for filename, parser in dependency_files.items():
            dep_file = repo_path / filename
            if dep_file.exists():
                parser(dep_file, graph, module_node)

    def _parse_python_requirements(self, file_path: Path, graph: KnowledgeGraph, module_node: str = None):
        try:
            with open(file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        dep_name = line.split(">=")[0].split("==")[0].strip()
                        dep_node = graph.add_node(
                            NodeType.DEPENDENCY,
                            {"name": dep_name, "type": "python", "file": str(file_path)},
                            self.name,
                        )
                        if module_node:
                            graph.add_edge(
                                module_node,
                                dep_node,
                                EdgeType.DEPENDS_ON,
                                {"dependency_type": "python"},
                            )
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")

    def _parse_npm_package(self, file_path: Path, graph: KnowledgeGraph, module_node: str = None):
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                dependencies = data.get("dependencies", {})
                for dep_name in dependencies:
                    dep_node = graph.add_node(
                        NodeType.DEPENDENCY,
                        {"name": dep_name, "type": "npm", "file": str(file_path)},
                        self.name,
                    )
                    if module_node:
                        graph.add_edge(
                            module_node,
                            dep_node,
                            EdgeType.DEPENDS_ON,
                            {"dependency_type": "npm"},
                        )
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")

    def _parse_go_mod(self, file_path: Path, graph: KnowledgeGraph, module_node: str = None):
        try:
            with open(file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("require"):
                        parts = line.split()
                        if len(parts) >= 2:
                            dep_name = parts[1]
                            dep_node = graph.add_node(
                                NodeType.DEPENDENCY,
                                {"name": dep_name, "type": "go", "file": str(file_path)},
                                self.name,
                            )
                            if module_node:
                                graph.add_edge(
                                    module_node,
                                    dep_node,
                                    EdgeType.DEPENDS_ON,
                                    {"dependency_type": "go"},
                                )
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
