"""
Base Agent - Foundation for Claude SDK Agents

This module provides the base agent class that integrates
Claude Agent SDK with LBM for knowledge coordination.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

# Claude Agent SDK imports (will be installed separately)
try:
    from claude_agent_sdk import (
        query,
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ToolResultBlock,
    )
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    # Provide mock classes for development/testing
    class ClaudeAgentOptions:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

from ..lbm.coordinator import LBMCoordinator


@dataclass
class AgentConfig:
    """Configuration for an agent."""
    name: str
    role: str
    description: str
    system_prompt: str
    allowed_tools: List[str] = field(default_factory=lambda: [
        "Read", "Write", "Edit", "Glob", "Grep", "Bash"
    ])
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 50
    permission_mode: str = "acceptEdits"


class BaseAgent(ABC):
    """
    Base class for Claude SDK agents with LBM integration.

    Agents can:
    - Execute tasks using Claude's capabilities
    - Share knowledge through LBM claims
    - Query existing knowledge before making decisions
    - Earn tokens for valuable contributions
    """

    def __init__(
        self,
        config: AgentConfig,
        coordinator: LBMCoordinator,
        work_dir: Path,
    ):
        """
        Initialize the agent.

        Args:
            config: Agent configuration
            coordinator: LBM coordinator for knowledge sharing
            work_dir: Working directory for file operations
        """
        self.config = config
        self.coordinator = coordinator
        self.work_dir = Path(work_dir)

        # Register with LBM
        self.identity = coordinator.register_agent(config.name, config.role)

        # Build system prompt with LBM context
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build the full system prompt with agent context."""
        return f"""{self.config.system_prompt}

## Your Identity
- Name: {self.config.name}
- Role: {self.config.role}
- Public Key: {self.identity.pub_key[:16]}...
- Token Balance: {self.identity.balance}

## Collaboration Guidelines
You are part of a multi-agent team collaborating through a shared knowledge base.

1. **Before starting any task**, query the knowledge base for relevant context
2. **Share your decisions and insights** by publishing claims
3. **Coordinate with other agents** through the knowledge network
4. **Verify your work** against existing knowledge

## Knowledge Sharing
When you complete significant work:
- Share architectural decisions with tag "decision"
- Share code implementations with tag "code"
- Share review findings with tag "review"
- Share insights and learnings with tag "insight"

## Working Directory
Your work directory is: {self.work_dir}
"""

    @property
    def claude_options(self) -> "ClaudeAgentOptions":
        """Get Claude Agent SDK options."""
        return ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            allowed_tools=self.config.allowed_tools,
            permission_mode=self.config.permission_mode,
            cwd=str(self.work_dir),
            model=self.config.model,
            max_turns=self.config.max_turns,
        )

    async def query_knowledge(self, query: str, top_k: int = 5) -> str:
        """
        Query existing knowledge before making decisions.

        Args:
            query: Search query
            top_k: Number of results

        Returns:
            Compiled context string
        """
        context, _ = self.coordinator.query_knowledge(
            self.config.name, query, top_k=top_k
        )
        return context

    async def share_insight(
        self,
        content: str,
        claim_type: str = "insight",
        tags: Optional[List[str]] = None,
    ) -> str:
        """
        Share an insight to the knowledge network.

        Args:
            content: The insight content
            claim_type: Type of claim
            tags: Additional tags

        Returns:
            Claim hash
        """
        claim = self.coordinator.share_knowledge(
            self.config.name,
            content,
            claim_type=claim_type,
            tags=tags,
        )
        return claim.claim_hash

    async def run(self, task: str) -> AsyncIterator[Dict[str, Any]]:
        """
        Run the agent on a task.

        Args:
            task: The task to perform

        Yields:
            Messages from the agent
        """
        if not CLAUDE_SDK_AVAILABLE:
            yield {
                "type": "error",
                "error": "Claude Agent SDK not installed. Run: pip install claude-agent-sdk"
            }
            return

        # First, query for relevant context
        context = await self.query_knowledge(task)
        if context.strip():
            enhanced_task = f"""## Existing Knowledge
{context}

## Your Task
{task}

Remember to share your key decisions and insights with the team."""
        else:
            enhanced_task = f"""## Your Task
{task}

Remember to share your key decisions and insights with the team."""

        # Run the Claude agent
        async for message in query(prompt=enhanced_task, options=self.claude_options):
            yield self._process_message(message)

    def _process_message(self, message: Any) -> Dict[str, Any]:
        """Process a message from Claude."""
        if not CLAUDE_SDK_AVAILABLE:
            return {"type": "raw", "content": str(message)}

        if isinstance(message, AssistantMessage):
            result = {"type": "assistant", "content": []}
            for block in message.content:
                if isinstance(block, TextBlock):
                    result["content"].append({
                        "type": "text",
                        "text": block.text
                    })
                elif isinstance(block, ToolUseBlock):
                    result["content"].append({
                        "type": "tool_use",
                        "tool": block.name,
                        "input": block.input
                    })
            return result
        else:
            return {"type": "message", "content": str(message)}

    @abstractmethod
    async def execute_task(self, task: str) -> Dict[str, Any]:
        """
        Execute a specific task. Override in subclasses.

        Args:
            task: The task to execute

        Returns:
            Result of the task
        """
        pass

    def get_balance(self) -> int:
        """Get current token balance."""
        return self.coordinator.get_agent_balance(self.config.name)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.config.name} role={self.config.role}>"
