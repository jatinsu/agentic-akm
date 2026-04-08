"""Graph visualization engine."""

import json
from pathlib import Path
from typing import Optional, List

from pyvis.network import Network

from ..graph import KnowledgeGraph, NodeType


class GraphVisualizer:
    """Visualizes knowledge graph using PyVis."""

    def __init__(self):
        self.node_colors = {
            NodeType.REPOSITORY.value: "#FF6B6B",
            NodeType.MODULE.value: "#4ECDC4",
            NodeType.SERVICE.value: "#45B7D1",
            NodeType.API.value: "#FFA07A",
            NodeType.DEPLOYMENT.value: "#98D8C8",
            NodeType.OPENSHIFT_RESOURCE.value: "#6C5CE7",
            NodeType.CONFIG_MAP.value: "#FDCB6E",
            NodeType.SECRET.value: "#E17055",
            NodeType.PIPELINE.value: "#74B9FF",
            NodeType.DEPENDENCY.value: "#A29BFE",
            NodeType.DOCUMENTATION_ARTIFACT.value: "#55EFC4",
            NodeType.CONCEPT.value: "#DFE6E9",
            NodeType.RISK.value: "#D63031",
            NodeType.UNKNOWN.value: "#B2BEC3",
        }

    def visualize(
        self,
        graph: KnowledgeGraph,
        output_path: str,
        filter_types: Optional[List[NodeType]] = None,
    ) -> None:
        """Generate interactive HTML visualization."""

        net = Network(
            height="800px",
            width="100%",
            directed=True,
            notebook=False,
            cdn_resources='in_line'
        )

        net.force_atlas_2based()

        subgraph = (
            graph.query_subgraph(filter_types) if filter_types else graph.graph
        )

        for node_id, data in subgraph.nodes(data=True):
            node_type = data.get("type", "Unknown")
            attrs = data.get("attributes", {})
            name = attrs.get("name", node_id)

            color = self.node_colors.get(node_type, "#B2BEC3")

            title = f"Type: {node_type}\n"
            title += f"ID: {node_id}\n"
            title += f"Name: {name}\n"
            title += f"Confidence: {data.get('confidence', 1.0)}\n"

            net.add_node(
                node_id,
                label=name,
                title=title,
                color=color,
                shape="dot",
                size=20,
            )

        for source, target, data in subgraph.edges(data=True):
            edge_type = data.get("type", "related_to")
            confidence = data.get("confidence", 1.0)

            net.add_edge(
                source,
                target,
                label=edge_type,
                title=f"{edge_type} (confidence: {confidence})",
                arrows="to",
            )

        try:
            net.save_graph(output_path)
            print(f"Visualization saved to: {output_path}")
        except Exception as e:
            print(f"Warning: Could not generate visualization: {e}")
            print("Skipping visualization step")

    def export_json(self, graph: KnowledgeGraph, output_path: str) -> None:
        """Export graph to JSON."""
        data = graph.export_to_dict()

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        print(f"Graph exported to: {output_path}")
