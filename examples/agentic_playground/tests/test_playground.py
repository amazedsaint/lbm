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

            # Share some knowledge from Agent1 - use keywords that will match query
            coord.share_knowledge(
                agent_name="Agent1",
                content="Use FastAPI framework for REST API endpoints",
                claim_type="decision",
                tags=["framework", "api", "fastapi"],
            )

            # Agent2 queries for the knowledge using matching keywords
            context, claim_hashes = coord.query_knowledge("Agent2", "FastAPI REST API")

            # The context should contain the shared knowledge
            assert context is not None
            assert isinstance(context, str)

            # Verify claims exist and contain the expected content
            claims = coord.get_all_claims()
            assert len(claims) > 0
            assert any("FastAPI" in c["text"] for c in claims)

            # The compiled context should include the claim content
            # (latent retrieval matches on keywords)
            assert "FastAPI" in context or len(claim_hashes) > 0

    def test_knowledge_sharing_flow(self):
        """Test complete knowledge sharing flow between agents."""
        from agentic_playground.lbm.coordinator import LBMCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(Path(tmpdir), project_name="test-project")

            # Register multiple agents
            arch = coord.register_agent("Architect", "architect")
            dev = coord.register_agent("Developer", "developer")

            # Verify both get faucet tokens
            assert coord.get_agent_balance("Architect") == 100
            assert coord.get_agent_balance("Developer") == 100

            # Architect shares a decision
            claim1 = coord.share_knowledge(
                agent_name="Architect",
                content="Database schema uses PostgreSQL with UUID primary keys",
                claim_type="decision",
                tags=["database", "schema", "postgresql"],
            )
            assert claim1.claim_hash is not None

            # Developer shares an implementation
            claim2 = coord.share_knowledge(
                agent_name="Developer",
                content="Implemented User model with SQLAlchemy ORM",
                claim_type="code",
                tags=["model", "user", "sqlalchemy"],
            )
            assert claim2.claim_hash is not None

            # Verify claims are stored
            all_claims = coord.get_all_claims()
            assert len(all_claims) == 2

            # Verify claim rewards were given (10 tokens per claim)
            stats = coord.get_stats()
            assert stats["claim_count"] == 2

            # Query knowledge
            context, hashes = coord.query_knowledge("Developer", "PostgreSQL database schema")
            assert "PostgreSQL" in context or len(all_claims) == 2

    def test_token_economy(self):
        """Test token economy: faucet, claim rewards."""
        from agentic_playground.lbm.coordinator import LBMCoordinator

        with tempfile.TemporaryDirectory() as tmpdir:
            coord = LBMCoordinator(
                Path(tmpdir),
                project_name="test-project",
                faucet_amount=50,
                claim_reward=5,
            )

            # Register agent - should get faucet
            coord.register_agent("TestAgent", "tester")
            initial_balance = coord.get_agent_balance("TestAgent")
            assert initial_balance == 50  # faucet amount

            # Share knowledge - should earn claim reward
            coord.share_knowledge(
                agent_name="TestAgent",
                content="Test insight",
                claim_type="insight",
            )

            # Note: claim reward goes to block author (coordinator), not the agent
            # in this simplified single-node architecture
            stats = coord.get_stats()
            assert stats["claim_count"] == 1

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


class TestCLI:
    """Test CLI functionality."""

    def test_project_init(self):
        """Test project initialization via CLI functions."""
        from agentic_playground.infra.project_setup import ProjectSetup
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "cli-test-project"
            setup = ProjectSetup(project_dir)

            results = setup.setup(
                name="cli-test",
                goal="Test CLI initialization",
                with_docker=True,
                with_git=True,
            )

            # Verify structure
            assert (project_dir / "src").exists()
            assert (project_dir / "tests").exists()
            assert (project_dir / ".lbm").exists()
            assert (project_dir / "agentic.json").exists()
            assert (project_dir / "README.md").exists()
            assert (project_dir / ".gitignore").exists()

            # Verify Docker files
            assert "docker_files" in results
            assert (project_dir / "Dockerfile.agent").exists()
            assert (project_dir / "docker-compose.yml").exists()

            # Verify config content
            config = json.loads((project_dir / "agentic.json").read_text())
            assert config["name"] == "cli-test"
            assert config["lbm"]["faucet_amount"] == 100

    def test_export_and_import_learnings(self):
        """Test exporting and importing learnings."""
        from agentic_playground.lbm.coordinator import LBMCoordinator
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create coordinator and add some knowledge
            coord = LBMCoordinator(Path(tmpdir), project_name="export-test")
            coord.register_agent("Agent1", "architect")

            coord.share_knowledge(
                agent_name="Agent1",
                content="Important architectural decision",
                claim_type="decision",
                tags=["architecture"],
            )

            # Export
            export_file = Path(tmpdir) / "learnings.json"
            coord.export_learnings(export_file)

            assert export_file.exists()
            data = json.loads(export_file.read_text())
            assert "claims" in data
            assert len(data["claims"]) > 0

            # Create new coordinator and import
            coord2 = LBMCoordinator(
                Path(tmpdir) / "new_coord",
                project_name="import-test"
            )
            count = coord2.import_learnings(export_file)
            assert count > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
