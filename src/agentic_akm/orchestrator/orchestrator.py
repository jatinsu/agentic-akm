"""Loop-based agent orchestrator."""

from typing import List, Dict, Any, Set

from ..agents.base import Agent, AgentContext
from ..graph import KnowledgeGraph


class AgentOrchestrator:
    """Coordinates agent execution with dependency-aware scheduling."""

    def __init__(self, agents: List[Agent]):
        self.agents = agents
        self.max_iterations = 10

    def run(self, context: AgentContext, graph: KnowledgeGraph) -> Dict[str, Any]:
        """Execute agents in dependency-aware order until stable."""

        print("Starting agent orchestration")
        print(f"Registered agents: {len(self.agents)}")

        executed_agents: Set[str] = set()
        iteration = 0

        while iteration < self.max_iterations:
            print(f"\n--- Iteration {iteration + 1} ---")

            agents_executed = 0
            for agent in self.agents:
                if agent.name in executed_agents:
                    continue

                if agent.can_run(graph):
                    print(f"Running: {agent.name}")
                    try:
                        agent.run(context, graph)
                        agents_executed += 1
                        executed_agents.add(agent.name)
                    except Exception as e:
                        print(f"Error in {agent.name}: {e}")
                else:
                    print(f"Waiting: {agent.name} (requirements not met)")

            stats = graph.get_stats()
            print(f"Graph stats: {stats['total_nodes']} nodes, {stats['total_edges']} edges")

            if agents_executed == 0:
                print("No new agents executed, system stable")
                break

            iteration += 1

        remaining = len(self.agents) - len(executed_agents)
        if remaining > 0:
            print(f"\nNote: {remaining} agents did not run (requirements not met)")

        print(f"\nOrchestration complete after {iteration + 1} iterations")

        return {
            "iterations": iteration + 1,
            "executed_agents": len(executed_agents),
            "final_stats": graph.get_stats(),
        }
