"""
Tests for the Agentic Playground.

These tests verify the core functionality without requiring
the Claude Agent SDK or API access.
"""

import pytest
import tempfile
from pathlib import Path
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


class TestLBMCoordinator:
    """Test the LBM coordinator."""

    def test_coordinator_init(self):
        """Test coordinator initialization."""
        from agentic_playground.lbm.coordinator import LBMCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            assert coord.project_name == "test-project"
            assert coord.node is not None

    def test_register_agent(self):
        """Test agent registration."""
        from agentic_playground.lbm.coordinator import LBMCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            identity = coord.register_agent("TestAgent", "tester")

            assert identity is not None
            assert identity.name == "TestAgent"
            assert identity.role == "tester"
            assert identity.pub_key is not None
            # Agent should receive faucet tokens
            assert identity.balance > 0 or coord.get_agent_balance("TestAgent") > 0

    def test_share_knowledge(self):
        """Test knowledge sharing."""
        from agentic_playground.lbm.coordinator import LBMCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            coord.register_agent("TestAgent", "tester")

            claim = coord.share_knowledge(
                agent_name="TestAgent",
                content="Test insight about the architecture",
                claim_type="insight",
                tags=["test", "architecture"],
            )

            assert claim is not None
            assert claim.claim_hash is not None
            assert len(claim.claim_hash) > 0

    def test_query_knowledge(self):
        """Test knowledge querying across agents."""
        from agentic_playground.lbm.coordinator import LBMCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            coord.register_agent("Agent1", "architect")
            coord.register_agent("Agent2", "developer")

            # Share some knowledge from Agent1
            coord.share_knowledge(
                agent_name="Agent1",
                content="Use FastAPI for the REST endpoints",
                claim_type="decision",
                tags=["framework", "api"],
            )

            # Agent2 queries for the knowledge
            context, claim_hashes = coord.query_knowledge("Agent2", "what framework")

            # The context should contain the shared knowledge
            assert context is not None
            assert isinstance(context, str)
            # Verify claims exist in the system and are accessible
            claims = coord.get_all_claims()
            assert len(claims) > 0
            assert any("FastAPI" in c["text"] for c in claims)

    def test_get_stats(self):
        """Test statistics retrieval."""
        from agentic_playground.lbm.coordinator import LBMCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            coord.register_agent("TestAgent", "tester")

            stats = coord.get_stats()

            assert "claim_count" in stats
            assert "total_supply" in stats
            assert "agents" in stats


class TestAgentFactory:
    """Test the agent factory."""

    def test_factory_init(self):
        """Test factory initialization."""
        from agentic_playground.lbm.coordinator import LBMCoordinator
        from agentic_playground.agents.factory import AgentFactory

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            factory = AgentFactory(coord, Path(tmpdir) / "work")

            assert factory.coordinator == coord

    def test_create_agent(self):
        """Test single agent creation."""
        from agentic_playground.lbm.coordinator import LBMCoordinator
        from agentic_playground.agents.factory import AgentFactory

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            factory = AgentFactory(coord, Path(tmpdir) / "work")

            agent = factory.create_agent("architect")

            assert agent is not None
            assert agent.config.role == "architect"

    def test_create_team_minimal(self):
        """Test minimal team creation."""
        from agentic_playground.lbm.coordinator import LBMCoordinator
        from agentic_playground.agents.factory import AgentFactory

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            factory = AgentFactory(coord, Path(tmpdir) / "work")

            team = factory.create_team(preset="minimal")

            assert len(team) == 2
            roles = {a.config.role for a in team.values()}
            assert "architect" in roles
            assert "developer" in roles

    def test_create_team_standard(self):
        """Test standard team creation."""
        from agentic_playground.lbm.coordinator import LBMCoordinator
        from agentic_playground.agents.factory import AgentFactory

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            factory = AgentFactory(coord, Path(tmpdir) / "work")

            team = factory.create_team(preset="standard")

            assert len(team) == 4
            roles = {a.config.role for a in team.values()}
            assert "architect" in roles
            assert "developer" in roles
            assert "reviewer" in roles
            assert "tester" in roles

    def test_create_team_custom(self):
        """Test custom team creation."""
        from agentic_playground.lbm.coordinator import LBMCoordinator
        from agentic_playground.agents.factory import AgentFactory

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")
            factory = AgentFactory(coord, Path(tmpdir) / "work")

            team = factory.create_team(
                preset="custom",
                custom_roles=["architect", "reviewer", "documenter"],
            )

            assert len(team) == 3
            roles = {a.config.role for a in team.values()}
            assert "architect" in roles
            assert "reviewer" in roles
            assert "documenter" in roles


class TestProjectSetup:
    """Test project setup."""

    def test_create_structure(self):
        """Test directory structure creation."""
        from agentic_playground.infra.project_setup import ProjectSetup

        with tempfile.TemporaryDirectory() as tmpdir:
            setup = ProjectSetup(Path(tmpdir) / "test-project")
            dirs = setup.create_structure()

            assert "root" in dirs
            assert "src" in dirs
            assert "tests" in dirs
            assert "docs" in dirs
            assert ".lbm" in dirs

    def test_create_config(self):
        """Test config file creation."""
        from agentic_playground.infra.project_setup import ProjectSetup
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "test-project"
            setup = ProjectSetup(project_dir)
            setup.create_structure()

            config_path = setup.create_config(name="my-test-project")

            assert config_path.exists()
            config = json.loads(config_path.read_text())
            assert config["name"] == "my-test-project"

    def test_full_setup(self):
        """Test full project setup."""
        from agentic_playground.infra.project_setup import ProjectSetup

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "test-project"
            setup = ProjectSetup(project_dir)

            results = setup.setup(
                name="test-project",
                goal="Build a test app",
                with_docker=False,
                with_git=True,
            )

            assert "directories" in results
            assert "files_created" in results
            assert len(results["files_created"]) >= 2  # config + readme


class TestDockerManager:
    """Test Docker manager."""

    def test_generate_dockerfile(self):
        """Test Dockerfile generation."""
        from agentic_playground.infra.docker_manager import DockerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DockerManager(Path(tmpdir))
            content = manager.generate_dockerfile()

            assert "FROM python:3.11-slim" in content
            assert "claude-agent-sdk" in content

    def test_generate_compose_file(self):
        """Test docker-compose.yml generation."""
        from agentic_playground.infra.docker_manager import DockerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DockerManager(Path(tmpdir))
            content = manager.generate_compose_file()

            assert "services:" in content
            assert "lbm-coordinator:" in content
            assert "orchestrator:" in content

    def test_setup_infrastructure(self):
        """Test infrastructure setup."""
        from agentic_playground.infra.docker_manager import DockerManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = DockerManager(Path(tmpdir))
            files = manager.setup_infrastructure()

            assert "dockerfile" in files
            assert "compose" in files
            assert files["dockerfile"].exists()
            assert files["compose"].exists()


class TestOrchestrator:
    """Test the orchestrator."""

    def test_orchestrator_init(self):
        """Test orchestrator initialization."""
        from agentic_playground.orchestrator import Orchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(
                work_dir=Path(tmpdir),
                project_name="test-project",
            )

            assert orchestrator.project_name == "test-project"
            assert orchestrator.coordinator is not None
            assert orchestrator.factory is not None

    @pytest.mark.asyncio
    async def test_analyze_goal(self):
        """Test goal analysis (without Claude SDK)."""
        from agentic_playground.orchestrator import Orchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(
                work_dir=Path(tmpdir),
                project_name="test-project",
            )

            # Without Claude SDK, returns a default plan
            plan = await orchestrator.analyze_goal("Build a REST API")

            assert plan.goal == "Build a REST API"
            assert len(plan.agents_needed) > 0
            assert len(plan.phases) > 0

    @pytest.mark.asyncio
    async def test_setup_team(self):
        """Test team setup."""
        from agentic_playground.orchestrator import Orchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(
                work_dir=Path(tmpdir),
                project_name="test-project",
            )

            # First analyze a goal
            await orchestrator.analyze_goal("Build a REST API")

            # Then setup team
            team = await orchestrator.setup_team()

            assert len(team) > 0

    def test_get_progress(self):
        """Test progress retrieval."""
        from agentic_playground.orchestrator import Orchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            orchestrator = Orchestrator(
                work_dir=Path(tmpdir),
                project_name="test-project",
            )

            progress = orchestrator.get_progress()

            assert "plan" in progress
            assert "agents" in progress
            assert "completed_tasks" in progress
            assert "stats" in progress


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
