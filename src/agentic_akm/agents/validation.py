"""Validation agents."""

from typing import List

from .base import Agent, AgentContext
from ..graph import KnowledgeGraph, NodeType, EdgeType


class ConsistencyValidatorAgent(Agent):
    """Validates graph consistency."""

    def __init__(self):
        super().__init__("ConsistencyValidatorAgent")

    @property
    def input_requirements(self) -> List[str]:
        return []

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.RISK]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        issues = []

        orphan_nodes = []
        for node in graph.graph.nodes():
            in_degree = graph.graph.in_degree(node)
            out_degree = graph.graph.out_degree(node)
            if in_degree == 0 and out_degree == 0:
                node_data = graph.get_node(node)
                if node_data and node_data.get("type") != NodeType.REPOSITORY.value:
                    orphan_nodes.append(node)
                    issues.append(f"Orphan node: {node}")

        if orphan_nodes:
            graph.add_node(
                NodeType.RISK,
                {
                    "type": "orphan_nodes",
                    "count": len(orphan_nodes),
                    "nodes": orphan_nodes,
                    "severity": "medium",
                },
                self.name,
            )

        service_nodes = graph.get_nodes_by_type(NodeType.SERVICE)
        deployment_nodes = graph.get_nodes_by_type(NodeType.DEPLOYMENT)

        if len(service_nodes) == 0 and len(deployment_nodes) > 0:
            graph.add_node(
                NodeType.RISK,
                {
                    "type": "missing_services",
                    "message": "Deployments exist but no services inferred",
                    "severity": "high",
                },
                self.name,
            )
            issues.append("Missing services for deployments")

        if issues:
            print(f"Validation issues found: {len(issues)}")
            for issue in issues:
                print(f"  - {issue}")


class HallucinationGuardAgent(Agent):
    """Guards against LLM hallucinations."""

    def __init__(self):
        super().__init__("HallucinationGuardAgent")

    @property
    def input_requirements(self) -> List[str]:
        return ["documentation_artifact"]

    @property
    def output_types(self) -> List[NodeType]:
        return [NodeType.RISK]

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        doc_nodes = graph.get_nodes_by_type(NodeType.DOCUMENTATION_ARTIFACT)

        for doc_id in doc_nodes:
            doc = graph.get_node(doc_id)
            if not doc:
                continue

            confidence = doc.get("confidence", 1.0)
            if confidence < 0.7:
                graph.add_node(
                    NodeType.RISK,
                    {
                        "type": "low_confidence_documentation",
                        "doc_id": doc_id,
                        "confidence": confidence,
                        "severity": "low",
                    },
                    self.name,
                )
