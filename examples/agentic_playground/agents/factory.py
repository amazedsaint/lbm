"""
Agent Factory - Dynamic Agent Creation

Creates specialized agents based on project requirements.
The orchestrator uses this factory to spin up the right
agents for the task at hand.
"""

from pathlib import Path
from typing import Dict, List, Optional, Type

from .base import BaseAgent, AgentConfig
from .specialized import (
    ArchitectAgent,
    DeveloperAgent,
    ReviewerAgent,
    TesterAgent,
    DocumenterAgent,
)
from ..lbm.coordinator import LBMCoordinator


class AgentFactory:
    """
    Factory for creating specialized agents.

    Supports dynamic agent creation based on role requirements.
    """

    # Registry of available agent types
    AGENT_TYPES: Dict[str, Type[BaseAgent]] = {
        "architect": ArchitectAgent,
        "developer": DeveloperAgent,
        "reviewer": ReviewerAgent,
        "tester": TesterAgent,
        "documenter": DocumenterAgent,
    }

    # Default team compositions for common project types
    TEAM_PRESETS = {
        "minimal": ["architect", "developer"],
        "standard": ["architect", "developer", "reviewer", "tester"],
        "full": ["architect", "developer", "reviewer", "tester", "documenter"],
        "api": ["architect", "developer", "tester", "documenter"],
        "library": ["architect", "developer", "tester", "documenter"],
        "cli": ["architect", "developer", "tester"],
    }

    def __init__(
        self,
        coordinator: LBMCoordinator,
        work_dir: Path,
    ):
        """
        Initialize the factory.

        Args:
            coordinator: LBM coordinator for knowledge sharing
            work_dir: Working directory for agents
        """
        self.coordinator = coordinator
        self.work_dir = Path(work_dir)
        self._agents: Dict[str, BaseAgent] = {}

    def create_agent(
        self,
        role: str,
        name: Optional[str] = None,
        **kwargs,
    ) -> BaseAgent:
        """
        Create a single agent by role.

        Args:
            role: Agent role (architect, developer, etc.)
            name: Optional custom name
            **kwargs: Additional arguments for agent creation

        Returns:
            The created agent

        Raises:
            ValueError: If role is unknown
        """
        role = role.lower()
        if role not in self.AGENT_TYPES:
            raise ValueError(
                f"Unknown agent role: {role}. "
                f"Available: {list(self.AGENT_TYPES.keys())}"
            )

        agent_class = self.AGENT_TYPES[role]
        agent_name = name or role.capitalize()

        # Create using the class factory method
        agent = agent_class.create(
            coordinator=self.coordinator,
            work_dir=self.work_dir,
            name=agent_name,
            **kwargs,
        )

        self._agents[agent_name] = agent
        return agent

    def create_team(
        self,
        preset: str = "standard",
        custom_roles: Optional[List[str]] = None,
    ) -> Dict[str, BaseAgent]:
        """
        Create a team of agents.

        Args:
            preset: Team preset name or "custom"
            custom_roles: List of roles if preset is "custom"

        Returns:
            Dict of agent name -> agent
        """
        if preset == "custom":
            if not custom_roles:
                raise ValueError("custom_roles required when preset='custom'")
            roles = custom_roles
        elif preset in self.TEAM_PRESETS:
            roles = self.TEAM_PRESETS[preset]
        else:
            raise ValueError(
                f"Unknown preset: {preset}. "
                f"Available: {list(self.TEAM_PRESETS.keys())}"
            )

        team = {}
        for role in roles:
            agent = self.create_agent(role)
            team[agent.config.name] = agent

        return team

    def create_developer_team(
        self,
        specialties: List[str],
    ) -> Dict[str, BaseAgent]:
        """
        Create multiple developers with different specialties.

        Args:
            specialties: List of developer specialties
                        (e.g., ["frontend", "backend", "devops"])

        Returns:
            Dict of agent name -> agent
        """
        team = {}
        for i, specialty in enumerate(specialties, 1):
            name = f"{specialty.capitalize()}Dev"
            agent = DeveloperAgent.create(
                coordinator=self.coordinator,
                work_dir=self.work_dir,
                name=name,
                specialty=specialty,
            )
            self._agents[name] = agent
            team[name] = agent

        return team

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """Get an existing agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> List[str]:
        """List all created agents."""
        return list(self._agents.keys())

    def get_team_status(self) -> Dict[str, Dict]:
        """Get status of all agents in the team."""
        return {
            name: {
                "role": agent.config.role,
                "balance": agent.get_balance(),
                "description": agent.config.description,
            }
            for name, agent in self._agents.items()
        }

    @classmethod
    def available_roles(cls) -> List[str]:
        """Get list of available agent roles."""
        return list(cls.AGENT_TYPES.keys())

    @classmethod
    def available_presets(cls) -> Dict[str, List[str]]:
        """Get available team presets."""
        return cls.TEAM_PRESETS.copy()
