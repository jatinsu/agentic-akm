"""Base agent interface."""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass

from ..graph import KnowledgeGraph, NodeType


@dataclass
class AgentContext:
    """Context passed to agents during execution."""

    repository_path: str
    config: Dict[str, Any]


class Agent(ABC):
    """Base class for all agents."""

    def __init__(self, name: str):
        self.name = name

    @property
    @abstractmethod
    def input_requirements(self) -> List[str]:
        """Required inputs for this agent."""
        pass

    @property
    @abstractmethod
    def output_types(self) -> List[NodeType]:
        """Node types this agent produces."""
        pass

    @abstractmethod
    def run(self, context: AgentContext, graph: KnowledgeGraph) -> None:
        """Execute the agent and update the graph."""
        pass

    def can_run(self, graph: KnowledgeGraph) -> bool:
        """Check if agent can run based on graph state."""
        for requirement in self.input_requirements:
            if requirement != "filesystem":
                required_type = NodeType[requirement.upper()]
                if not graph.get_nodes_by_type(required_type):
                    return False
        return True
