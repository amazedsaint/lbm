"""
Docker Manager - Container Infrastructure for Agents

Manages Docker containers for running isolated agent environments.
Each agent can run in its own container with specific dependencies.
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ContainerConfig:
    """Configuration for a Docker container."""
    name: str
    image: str = "python:3.11-slim"
    work_dir: str = "/workspace"
    ports: Dict[int, int] = None  # host -> container
    volumes: Dict[str, str] = None  # host -> container
    env: Dict[str, str] = None
    command: Optional[str] = None

    def __post_init__(self):
        self.ports = self.ports or {}
        self.volumes = self.volumes or {}
        self.env = self.env or {}


class DockerManager:
    """
    Manages Docker containers for agent infrastructure.

    Features:
    - Create isolated containers for agents
    - Manage networking between containers
    - Share volumes for knowledge persistence
    - Run LBM nodes in containers
    """

    # Default Dockerfile for agent containers
    AGENT_DOCKERFILE = '''FROM python:3.11-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \\
    claude-agent-sdk \\
    httpx \\
    pydantic

# Install LBM
COPY . /lbm
RUN pip install -e /lbm

# Default command
CMD ["python", "-c", "print('Agent container ready')"]
'''

    # Docker Compose template for multi-agent setup
    COMPOSE_TEMPLATE = '''version: "3.8"

services:
  lbm-coordinator:
    build:
      context: .
      dockerfile: Dockerfile.agent
    container_name: lbm-coordinator
    volumes:
      - ./workspace:/workspace
      - ./lbm-data:/data
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    ports:
      - "7337:7337"
    command: lb run-p2p --data /data --host 0.0.0.0 --port 7337

  orchestrator:
    build:
      context: .
      dockerfile: Dockerfile.agent
    container_name: orchestrator
    depends_on:
      - lbm-coordinator
    volumes:
      - ./workspace:/workspace
      - ./lbm-data:/data
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - LBM_HOST=lbm-coordinator
      - LBM_PORT=7337
    command: python -m agentic_playground.cli run --data /data

networks:
  default:
    name: agentic-network
'''

    def __init__(self, work_dir: Path):
        """
        Initialize Docker manager.

        Args:
            work_dir: Working directory for Docker files
        """
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._containers: Dict[str, ContainerConfig] = {}

    def is_docker_available(self) -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ["docker", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def is_compose_available(self) -> bool:
        """Check if Docker Compose is available."""
        try:
            result = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def generate_dockerfile(self, output_path: Optional[Path] = None) -> str:
        """
        Generate Dockerfile for agent containers.

        Args:
            output_path: Optional path to write the file

        Returns:
            Dockerfile content
        """
        content = self.AGENT_DOCKERFILE

        if output_path:
            output_path = Path(output_path)
            output_path.write_text(content)

        return content

    def generate_compose_file(
        self,
        output_path: Optional[Path] = None,
        agents: Optional[List[str]] = None,
    ) -> str:
        """
        Generate docker-compose.yml for multi-agent setup.

        Args:
            output_path: Optional path to write the file
            agents: List of agent roles to include

        Returns:
            Docker Compose content
        """
        content = self.COMPOSE_TEMPLATE

        if output_path:
            output_path = Path(output_path)
            output_path.write_text(content)

        return content

    def setup_infrastructure(self) -> Dict[str, Path]:
        """
        Set up all Docker infrastructure files.

        Returns:
            Dict of file type -> path
        """
        files = {}

        # Create Dockerfile
        dockerfile_path = self.work_dir / "Dockerfile.agent"
        self.generate_dockerfile(dockerfile_path)
        files["dockerfile"] = dockerfile_path

        # Create docker-compose.yml
        compose_path = self.work_dir / "docker-compose.yml"
        self.generate_compose_file(compose_path)
        files["compose"] = compose_path

        # Create directories
        (self.work_dir / "workspace").mkdir(exist_ok=True)
        (self.work_dir / "lbm-data").mkdir(exist_ok=True)

        # Create .env template
        env_path = self.work_dir / ".env.template"
        env_path.write_text("ANTHROPIC_API_KEY=your-api-key-here\n")
        files["env_template"] = env_path

        return files

    async def build_image(self, tag: str = "agentic-playground:latest") -> bool:
        """
        Build the Docker image.

        Args:
            tag: Image tag

        Returns:
            True if successful
        """
        dockerfile_path = self.work_dir / "Dockerfile.agent"
        if not dockerfile_path.exists():
            self.generate_dockerfile(dockerfile_path)

        process = await asyncio.create_subprocess_exec(
            "docker", "build",
            "-t", tag,
            "-f", str(dockerfile_path),
            str(self.work_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()
        return process.returncode == 0

    async def start_container(
        self,
        config: ContainerConfig,
    ) -> bool:
        """
        Start a Docker container.

        Args:
            config: Container configuration

        Returns:
            True if successful
        """
        cmd = ["docker", "run", "-d", "--name", config.name]

        # Add ports
        for host_port, container_port in config.ports.items():
            cmd.extend(["-p", f"{host_port}:{container_port}"])

        # Add volumes
        for host_path, container_path in config.volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

        # Add environment variables
        for key, value in config.env.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Add working directory
        cmd.extend(["-w", config.work_dir])

        # Add image
        cmd.append(config.image)

        # Add command if specified
        if config.command:
            cmd.extend(config.command.split())

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            self._containers[config.name] = config
        return process.returncode == 0

    async def stop_container(self, name: str) -> bool:
        """Stop a container by name."""
        process = await asyncio.create_subprocess_exec(
            "docker", "stop", name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()

        if process.returncode == 0 and name in self._containers:
            del self._containers[name]

        return process.returncode == 0

    async def compose_up(self, detach: bool = True) -> bool:
        """
        Start all services with docker-compose.

        Args:
            detach: Run in background

        Returns:
            True if successful
        """
        compose_path = self.work_dir / "docker-compose.yml"
        if not compose_path.exists():
            self.generate_compose_file(compose_path)

        cmd = ["docker", "compose", "-f", str(compose_path), "up"]
        if detach:
            cmd.append("-d")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.work_dir),
        )

        stdout, stderr = await process.communicate()
        return process.returncode == 0

    async def compose_down(self) -> bool:
        """Stop all docker-compose services."""
        compose_path = self.work_dir / "docker-compose.yml"

        process = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", str(compose_path), "down",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.work_dir),
        )

        await process.communicate()
        return process.returncode == 0

    def list_containers(self) -> List[str]:
        """List managed containers."""
        return list(self._containers.keys())

    def get_status(self) -> Dict[str, Any]:
        """Get infrastructure status."""
        return {
            "docker_available": self.is_docker_available(),
            "compose_available": self.is_compose_available(),
            "work_dir": str(self.work_dir),
            "containers": list(self._containers.keys()),
            "files": {
                "dockerfile": (self.work_dir / "Dockerfile.agent").exists(),
                "compose": (self.work_dir / "docker-compose.yml").exists(),
            },
        }
