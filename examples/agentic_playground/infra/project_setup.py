"""
Project Setup - Initialize project structure for agent collaboration.

Creates the necessary directory structure and configuration files
for a new multi-agent project.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class ProjectSetup:
    """
    Sets up project infrastructure for multi-agent collaboration.

    Creates:
    - Project directory structure
    - Configuration files
    - LBM data directory
    - Docker infrastructure (optional)
    """

    # Default project structure
    DEFAULT_STRUCTURE = {
        "src": {},
        "tests": {},
        "docs": {},
        ".lbm": {
            "coordinator": {},
            "agents": {},
        },
    }

    # Default configuration
    DEFAULT_CONFIG = {
        "name": "agentic-project",
        "version": "0.1.0",
        "lbm": {
            "faucet_amount": 100,
            "claim_reward": 10,
            "transfer_fee_bps": 100,
        },
        "agents": {
            "default_team": "standard",
        },
        "docker": {
            "enabled": False,
            "image": "agentic-playground:latest",
        },
    }

    def __init__(self, project_dir: Path):
        """
        Initialize project setup.

        Args:
            project_dir: Root directory for the project
        """
        self.project_dir = Path(project_dir)
        self._config: Dict[str, Any] = {}

    def create_structure(
        self,
        structure: Optional[Dict] = None,
        exist_ok: bool = True,
    ) -> Dict[str, Path]:
        """
        Create the project directory structure.

        Args:
            structure: Custom structure (uses default if not provided)
            exist_ok: Don't raise if directories exist

        Returns:
            Dict of name -> path for created directories
        """
        structure = structure or self.DEFAULT_STRUCTURE
        created = {}

        def create_recursive(base: Path, struct: Dict) -> None:
            for name, contents in struct.items():
                path = base / name
                path.mkdir(parents=True, exist_ok=exist_ok)
                created[name] = path
                if isinstance(contents, dict) and contents:
                    create_recursive(path, contents)

        self.project_dir.mkdir(parents=True, exist_ok=exist_ok)
        created["root"] = self.project_dir
        create_recursive(self.project_dir, structure)

        return created

    def create_config(
        self,
        name: str = "agentic-project",
        **kwargs,
    ) -> Path:
        """
        Create project configuration file.

        Args:
            name: Project name
            **kwargs: Additional config options

        Returns:
            Path to config file
        """
        config = self.DEFAULT_CONFIG.copy()
        config["name"] = name
        config["created_at"] = datetime.now().isoformat()
        config.update(kwargs)

        config_path = self.project_dir / "agentic.json"
        config_path.write_text(json.dumps(config, indent=2))

        self._config = config
        return config_path

    def create_gitignore(self) -> Path:
        """Create .gitignore file."""
        content = """# Agentic Playground
.lbm/
learnings.json
.env

# Python
__pycache__/
*.py[cod]
*$py.class
.Python
*.so
.venv/
venv/
ENV/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Docker
.docker/

# OS
.DS_Store
Thumbs.db
"""
        gitignore_path = self.project_dir / ".gitignore"
        gitignore_path.write_text(content)
        return gitignore_path

    def create_readme(self, project_name: str, goal: str = "") -> Path:
        """
        Create README.md file.

        Args:
            project_name: Name of the project
            goal: Project goal/description

        Returns:
            Path to README
        """
        content = f"""# {project_name}

{goal if goal else "A multi-agent project powered by Agentic Playground."}

## Getting Started

### Prerequisites

- Python 3.10+
- Claude Agent SDK: `pip install claude-agent-sdk`
- Anthropic API key

### Setup

```bash
# Set your API key
export ANTHROPIC_API_KEY=your-key-here

# Run the playground
python -m agentic_playground run --goal "Your project goal"
```

## Project Structure

```
{project_name}/
├── src/              # Source code
├── tests/            # Test files
├── docs/             # Documentation
├── .lbm/             # LBM knowledge base
│   ├── coordinator/  # Coordinator node data
│   └── agents/       # Agent node data
├── agentic.json      # Project configuration
└── learnings.json    # Exported knowledge
```

## Knowledge Sharing

All agents share knowledge through the Learning Batteries Market (LBM):

- **Claims**: Insights, decisions, and learnings
- **Context**: Retrievable knowledge for informed decisions
- **Tokens**: Earned for valuable contributions

## Generated with Agentic Playground

This project uses multi-agent coordination for development.
"""
        readme_path = self.project_dir / "README.md"
        readme_path.write_text(content)
        return readme_path

    def setup(
        self,
        name: str = "agentic-project",
        goal: str = "",
        with_docker: bool = False,
        with_git: bool = True,
    ) -> Dict[str, Any]:
        """
        Full project setup.

        Args:
            name: Project name
            goal: Project goal/description
            with_docker: Include Docker infrastructure
            with_git: Initialize git repository

        Returns:
            Setup results
        """
        results = {
            "project_dir": str(self.project_dir),
            "files_created": [],
        }

        # Create structure
        dirs = self.create_structure()
        results["directories"] = list(dirs.keys())

        # Create config
        config_path = self.create_config(name)
        results["files_created"].append(str(config_path))

        # Create README
        readme_path = self.create_readme(name, goal)
        results["files_created"].append(str(readme_path))

        # Create .gitignore
        if with_git:
            gitignore_path = self.create_gitignore()
            results["files_created"].append(str(gitignore_path))

        # Create Docker files
        if with_docker:
            from .docker_manager import DockerManager
            docker = DockerManager(self.project_dir)
            docker_files = docker.setup_infrastructure()
            results["docker_files"] = {k: str(v) for k, v in docker_files.items()}

        return results

    def load_config(self) -> Dict[str, Any]:
        """Load existing project configuration."""
        config_path = self.project_dir / "agentic.json"
        if config_path.exists():
            self._config = json.loads(config_path.read_text())
        return self._config

    @property
    def config(self) -> Dict[str, Any]:
        """Get current configuration."""
        if not self._config:
            self.load_config()
        return self._config
