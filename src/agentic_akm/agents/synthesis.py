"""Documentation synthesis agents."""

from typing import List
from pathlib import Path

from .base import Agent, AgentContext
from ..graph import KnowledgeGraph, NodeType, EdgeType
from ..llm import GeminiClient, PromptMode


class ArchitectureDocAgent(Agent):
    """Generates architecture documentation."""

    def __init__(self, gemini_client: GeminiClient):
        super().__init__("ArchitectureDocAgent")
        self.gemini = gemini_client

    @property
    def input_requirements(self) -> List[str]:
        return ["service", "deployment"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.DOCUMENTATION_ARTIFACT]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        services = graph.get_nodes_by_type(NodeType.SERVICE)
        deployments = graph.get_nodes_by_type(NodeType.DEPLOYMENT)
        resources = graph.get_nodes_by_type(NodeType.OPENSHIFT_RESOURCE)

        graph_data = {
            "services": [graph.get_node(s) for s in services],
            "deployments": [graph.get_node(d) for d in deployments],
            "openshift_resources": [graph.get_node(r) for r in resources],
        }

        prompt = f"""
        Generate a comprehensive architecture overview document based on this system data:

        Services: {len(services)}
        Deployments: {len(deployments)}
        OpenShift Resources: {len(resources)}

        Include:
        1. System Overview
        2. Service Relationships
        3. OpenShift Deployment Model
        4. Key Components

        Write in markdown format without diagrams, tables, or emojis.
        """

        content = self.gemini.generate_documentation("Architecture", graph_data)

        doc_node = graph.add_node(
            NodeType.DOCUMENTATION_ARTIFACT,
            {
                "type": "Architecture",
                "content": content,
            },
            self.name,
        )

        for service in services:
            graph.add_edge(doc_node, service, EdgeType.DOCUMENTS)


class APIDocAgent(Agent):
    """Generates API documentation."""

    def __init__(self, gemini_client: GeminiClient):
        super().__init__("APIDocAgent")
        self.gemini = gemini_client

    @property
    def input_requirements(self) -> List[str]:
        return ["api"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.DOCUMENTATION_ARTIFACT]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        apis = graph.get_nodes_by_type(NodeType.API)

        for api_id in apis:
            api = graph.get_node(api_id)
            if not api:
                continue

            attrs = api.get("attributes", {})

            prompt = f"""
            Generate API documentation for:
            File: {attrs.get('file')}
            Extracted Info: {attrs.get('extracted_info')}

            Include:
            1. API endpoint descriptions
            2. Request/response structure
            3. Authentication requirements

            Write in markdown format without diagrams, tables, or emojis.
            """

            content = self.gemini.generate(prompt, mode=PromptMode.DOCUMENTATION)

            doc_node = graph.add_node(
                NodeType.DOCUMENTATION_ARTIFACT,
                {
                    "type": "API",
                    "api_file": attrs.get("file"),
                    "content": content,
                },
                self.name,
            )

            graph.add_edge(doc_node, api_id, EdgeType.DOCUMENTS)


class DeploymentDocAgent(Agent):
    """Generates deployment documentation."""

    def __init__(self, gemini_client: GeminiClient):
        super().__init__("DeploymentDocAgent")
        self.gemini = gemini_client

    @property
    def input_requirements(self) -> List[str]:
        return ["deployment"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.DOCUMENTATION_ARTIFACT]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        deployments = graph.get_nodes_by_type(NodeType.DEPLOYMENT)
        pipelines = graph.get_nodes_by_type(NodeType.PIPELINE)

        graph_data = {
            "deployments": [graph.get_node(d) for d in deployments],
            "pipelines": [graph.get_node(p) for p in pipelines],
        }

        prompt = """
        Generate deployment documentation focusing on:
        1. OpenShift-specific deployment flows
        2. CI/CD pipelines
        3. Environment configuration
        4. Deployment procedures

        Write in markdown format without diagrams, tables, or emojis.
        """

        content = self.gemini.generate_documentation("Deployment", graph_data)

        doc_node = graph.add_node(
            NodeType.DOCUMENTATION_ARTIFACT,
            {
                "type": "Deployment",
                "content": content,
            },
            self.name,
        )
