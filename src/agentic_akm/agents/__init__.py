"""Agent system."""

from .base import Agent, AgentContext
from .ingestion import RepositoryScannerAgent, OpenShiftManifestAgent
from .understanding import ServiceInferenceAgent, APIExtractionAgent, DependencyAnalysisAgent
from .synthesis import ArchitectureDocAgent
from .validation import ConsistencyValidatorAgent

__all__ = [
    "Agent",
    "AgentContext",
    "RepositoryScannerAgent",
    "OpenShiftManifestAgent",
    "ServiceInferenceAgent",
    "APIExtractionAgent",
    "DependencyAnalysisAgent",
    "ArchitectureDocAgent",
    "ConsistencyValidatorAgent",
]
