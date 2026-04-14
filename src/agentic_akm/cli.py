"""Command-line interface for Agentic AKM."""

import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from .graph import KnowledgeGraph
from .llm import GeminiClient
from .agents import (
    AgentContext,
    RepositoryScannerAgent,
    OpenShiftManifestAgent,
    JiraIngestionAgent,
    ServiceInferenceAgent,
    APIExtractionAgent,
    DependencyAnalysisAgent,
    ArchitectureDocAgent,
    ConsistencyValidatorAgent,
)
from .agents.synthesis import APIDocAgent, DeploymentDocAgent
from .agents.validation import HallucinationGuardAgent
from .orchestrator import AgentOrchestrator
from .visualizer import GraphVisualizer
from .utils import DocumentationWriter


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Architecture Knowledge Management"
    )
    parser.add_argument(
        "repository",
        type=str,
        help="Path to the repository to analyze",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="./output",
        help="Output directory for documentation and visualizations",
    )
    parser.add_argument(
        "--gemini-api-key",
        type=str,
        help="Gemini API key (or set GEMINI_API_KEY env var)",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM-based agents (for testing)",
    )
    parser.add_argument(
        "--github-json",
        type=str,
        help="Path to github.json file (input for Jira ingestion)",
    )
    parser.add_argument(
        "--jira-server",
        type=str,
        default="https://redhat.atlassian.net",
        help="JIRA server URL (default: https://redhat.atlassian.net)",
    )

    args = parser.parse_args()

    repo_path = Path(args.repository).absolute()
    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}")
        return 1

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Agentic Architecture Knowledge Management")
    print("=" * 60)
    print(f"Repository: {repo_path}")
    print(f"Output: {output_dir}")
    print()

    graph = KnowledgeGraph()

    agents = [
        RepositoryScannerAgent(),
        OpenShiftManifestAgent(),
        JiraIngestionAgent(),
        DependencyAnalysisAgent(),
        ConsistencyValidatorAgent(),
    ]

    if not args.skip_llm:
        try:
            api_key = args.gemini_api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                print("Warning: GOOGLE_API_KEY or GEMINI_API_KEY not set, skipping LLM-based agents")
                print("Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable to enable LLM agents")
            else:
                gemini = GeminiClient(api_key=api_key)
                agents.extend([
                    ServiceInferenceAgent(gemini),
                    APIExtractionAgent(gemini),
                    ArchitectureDocAgent(gemini),
                    APIDocAgent(gemini),
                    DeploymentDocAgent(gemini),
                ])
                agents.append(HallucinationGuardAgent())
        except Exception as e:
            print(f"Warning: Could not initialize Gemini client: {e}")
            print("Continuing without LLM-based agents")

    github_json_path = args.github_json
    jira_server = args.jira_server

    context = AgentContext(
        repository_path=str(repo_path),
        config={
            "github_json_path": github_json_path,
            "jira_server": jira_server,
            "jira_output_path": str(output_dir / "jira.json"),
        },
    )

    orchestrator = AgentOrchestrator(agents)
    result = orchestrator.run(context, graph)

    print("\n" + "=" * 60)
    print("Final Graph Statistics")
    print("=" * 60)
    stats = result["final_stats"]
    print(f"Total Nodes: {stats['total_nodes']}")
    print(f"Total Edges: {stats['total_edges']}")
    print("\nNode Types:")
    for node_type, count in stats["node_types"].items():
        print(f"  {node_type}: {count}")

    print("\n" + "=" * 60)
    print("Generating Outputs")
    print("=" * 60)

    doc_writer = DocumentationWriter(str(output_dir / "docs"))
    doc_writer.write_all(graph)

    visualizer = GraphVisualizer()

    viz_path = str(output_dir / "graph.html")
    visualizer.visualize(graph, viz_path)

    json_path = str(output_dir / "graph.json")
    visualizer.export_json(graph, json_path)

    print("\n" + "=" * 60)
    print("Complete!")
    print("=" * 60)
    print(f"Documentation: {output_dir / 'docs'}")
    print(f"Visualization: {output_dir / 'graph.html'}")
    print(f"Graph JSON: {output_dir / 'graph.json'}")

    return 0


if __name__ == "__main__":
    exit(main())
