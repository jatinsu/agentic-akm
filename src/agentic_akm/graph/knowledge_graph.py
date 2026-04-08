"""In-memory knowledge graph implementation using NetworkX."""

from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime
import networkx as nx


class NodeType(Enum):
    REPOSITORY = "Repository"
    MODULE = "Module"
    SERVICE = "Service"
    API = "API"
    DEPLOYMENT = "Deployment"
    OPENSHIFT_RESOURCE = "OpenShiftResource"
    CONFIG_MAP = "ConfigMap"
    SECRET = "Secret"
    PIPELINE = "Pipeline"
    DEPENDENCY = "Dependency"
    DOCUMENTATION_ARTIFACT = "DocumentationArtifact"
    CONCEPT = "Concept"
    RISK = "Risk"
    UNKNOWN = "Unknown"


class EdgeType(Enum):
    DEPENDS_ON = "depends_on"
    EXPOSES_API = "exposes_api"
    DEPLOYS_TO = "deploys_to"
    CONFIGURED_BY = "configured_by"
    USES_IMAGE = "uses_image"
    TRIGGERS_PIPELINE = "triggers_pipeline"
    RELATED_TO = "related_to"
    DOCUMENTS = "documents"
    INFERRED_FROM = "inferred_from"
    VALIDATED_BY = "validated_by"


class KnowledgeGraph:
    """Typed, attributed, directed multigraph for architecture knowledge."""

    def __init__(self):
        self.graph = nx.MultiDiGraph()
        self._node_counter = 0

    def add_node(
        self,
        node_type: NodeType,
        attributes: Dict[str, Any],
        agent_name: str,
        confidence: float = 1.0,
    ) -> str:
        """Add a node to the graph."""
        node_id = f"{node_type.value}_{self._node_counter}"
        self._node_counter += 1

        self.graph.add_node(
            node_id,
            type=node_type.value,
            attributes=attributes,
            provenance={
                "agent": agent_name,
                "timestamp": datetime.now().isoformat(),
            },
            confidence=confidence,
        )
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType,
        attributes: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
    ) -> None:
        """Add an edge to the graph."""
        self.graph.add_edge(
            source,
            target,
            type=edge_type.value,
            attributes=attributes or {},
            confidence=confidence,
        )

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get node data by ID."""
        if node_id in self.graph.nodes:
            return dict(self.graph.nodes[node_id])
        return None

    def get_nodes_by_type(self, node_type: NodeType) -> List[str]:
        """Get all nodes of a specific type."""
        return [
            node
            for node, data in self.graph.nodes(data=True)
            if data.get("type") == node_type.value
        ]

    def get_edges_by_type(self, edge_type: EdgeType) -> List[tuple]:
        """Get all edges of a specific type."""
        return [
            (u, v, data)
            for u, v, data in self.graph.edges(data=True)
            if data.get("type") == edge_type.value
        ]

    def get_neighbors(
        self, node_id: str, edge_type: Optional[EdgeType] = None
    ) -> List[str]:
        """Get neighbors of a node, optionally filtered by edge type."""
        if node_id not in self.graph.nodes:
            return []

        neighbors = []
        for _, target, data in self.graph.edges(node_id, data=True):
            if edge_type is None or data.get("type") == edge_type.value:
                neighbors.append(target)
        return neighbors

    def query_subgraph(
        self, node_types: Optional[List[NodeType]] = None
    ) -> nx.MultiDiGraph:
        """Extract a subgraph containing only specified node types."""
        if node_types is None:
            return self.graph.copy()

        type_values = [nt.value for nt in node_types]
        nodes = [
            node
            for node, data in self.graph.nodes(data=True)
            if data.get("type") in type_values
        ]
        return self.graph.subgraph(nodes).copy()

    def export_to_dict(self) -> Dict[str, Any]:
        """Export graph to dictionary format."""
        return {
            "nodes": [
                {"id": node, **data} for node, data in self.graph.nodes(data=True)
            ],
            "edges": [
                {"source": u, "target": v, **data}
                for u, v, data in self.graph.edges(data=True)
            ],
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        node_types = {}
        for _, data in self.graph.nodes(data=True):
            node_type = data.get("type", "Unknown")
            node_types[node_type] = node_types.get(node_type, 0) + 1

        edge_types = {}
        for _, _, data in self.graph.edges(data=True):
            edge_type = data.get("type", "Unknown")
            edge_types[edge_type] = edge_types.get(edge_type, 0) + 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "node_types": node_types,
            "edge_types": edge_types,
        }
