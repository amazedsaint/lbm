"""
Agentic Playground - Multi-Agent Coordination System

A full-featured agentic system using Claude Agent SDK with LBM
(Learning Batteries Market) for distributed knowledge coordination.

Usage:
    # Start the playground in any folder
    agentic-playground start --goal "Build a REST API for task management"

    # Or use as a library
    from agentic_playground import Orchestrator

    orchestrator = Orchestrator(work_dir="./my_project")
    await orchestrator.run("Build a REST API for task management")
"""

__version__ = "0.1.0"

from .orchestrator import Orchestrator
from .lbm.coordinator import LBMCoordinator
from .agents.factory import AgentFactory

__all__ = ["Orchestrator", "LBMCoordinator", "AgentFactory"]
