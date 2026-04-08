# Agentic Knowledge Management

An agentic documentation generator tailored for Red Hat OpenShift repositories using knowledge graph architecture.

## Overview

This proof-of-concept implements an agent-based system that:

- Extracts architecture knowledge from code and OpenShift manifests
- Builds an in-memory knowledge graph
- Uses Gemini LLM for inference and documentation synthesis
- Generates comprehensive documentation automatically
- Provides interactive graph visualization

## Architecture

The system follows AgenticAKM principles:

- Knowledge as a Living Graph: All knowledge stored in an in-memory NetworkX graph
- Agents as Knowledge Producers: Specialized agents read from and enrich the graph
- Iterative Refinement: Documentation evolves through extraction, structuring, synthesis, and validation
- Separation of Concerns: Distinct agent categories for different tasks

## Agent Types

### Ingestion Agents
- RepositoryScannerAgent: Scans repository structure and detects languages
- OpenShiftManifestAgent: Parses Kubernetes/OpenShift manifests

### Understanding Agents
- ServiceInferenceAgent: Infers logical services from deployments
- APIExtractionAgent: Extracts API endpoints from code
- DependencyAnalysisAgent: Builds dependency graph

### Synthesis Agents
- ArchitectureDocAgent: Generates architecture overview
- APIDocAgent: Generates API documentation
- DeploymentDocAgent: Documents deployment procedures

### Validation Agents
- ConsistencyValidatorAgent: Detects graph inconsistencies
- HallucinationGuardAgent: Validates LLM-generated content

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Set your Gemini API key:

```bash
export GEMINI_API_KEY=your_api_key_here
```

## Usage

Analyze a repository:

```bash
python main.py /path/to/openshift/repository
```

With custom output directory:

```bash
python main.py /path/to/repository --output ./my-docs
```

Skip LLM-based agents for testing:

```bash
python main.py /path/to/repository --skip-llm
```

## Output

The system generates:

- `output/docs/` - Generated markdown documentation
  - Overview.md
  - Architecture.md
  - API.md
  - Deployment.md
- `output/graph.html` - Interactive visualization
- `output/graph.json` - Graph data export

## Key Features

- Graph-first documentation generation
- OpenShift-native understanding
- Iterative agent refinement
- Strict separation of extraction and synthesis
- Gemini-only LLM consistency
- No diagrams, tables, or emojis in output

## Requirements

- Python 3.10+
- NetworkX for graph operations
- Google Generative AI for LLM
- PyVis for visualization
- PyYAML for manifest parsing

## Design Philosophy

Based on the [AgenticAKM paper](https://arxiv.org/abs/2602.04445), this system treats documentation as a living knowledge graph that evolves through agent interactions rather than static file generation.
