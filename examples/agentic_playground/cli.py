#!/usr/bin/env python3
"""
Agentic Playground CLI - Multi-Agent Coordination System

Command-line interface for running multi-agent projects.

Usage:
    # Initialize a new project
    agentic-playground init --name my-project

    # Run with a goal
    agentic-playground run --goal "Build a REST API"

    # Check status
    agentic-playground status
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from .orchestrator import Orchestrator
from .infra.project_setup import ProjectSetup
from .infra.docker_manager import DockerManager
from .lbm.coordinator import LBMCoordinator


def print_banner():
    """Print the CLI banner."""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║              AGENTIC PLAYGROUND                           ║
║         Multi-Agent Coordination System                   ║
║                                                           ║
║  Powered by Claude Agent SDK + Learning Batteries Market  ║
╚═══════════════════════════════════════════════════════════╝
"""
    print(banner)


def cmd_init(args):
    """Initialize a new project."""
    print_banner()
    print(f"Initializing project: {args.name}")
    print(f"Directory: {args.dir}")

    project_dir = Path(args.dir)
    setup = ProjectSetup(project_dir)

    results = setup.setup(
        name=args.name,
        goal=args.goal or "",
        with_docker=args.docker,
        with_git=not args.no_git,
    )

    print("\n✓ Project initialized successfully!")
    print(f"\nCreated directories: {len(results['directories'])}")
    print(f"Created files: {len(results['files_created'])}")

    if args.docker:
        print("\nDocker files created:")
        for name, path in results.get("docker_files", {}).items():
            print(f"  - {name}: {path}")

    print(f"\nNext steps:")
    print(f"  1. cd {project_dir}")
    print(f"  2. export ANTHROPIC_API_KEY=your-key")
    print(f"  3. agentic-playground run --goal 'Your goal here'")


def cmd_run(args):
    """Run the orchestrator with a goal."""
    print_banner()

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  Warning: ANTHROPIC_API_KEY not set")
        print("   Claude Agent SDK requires an API key.")
        print("   Set it with: export ANTHROPIC_API_KEY=your-key")
        print()

    work_dir = Path(args.dir)
    if not work_dir.exists():
        print(f"Creating work directory: {work_dir}")
        work_dir.mkdir(parents=True)

    print(f"Work directory: {work_dir}")
    print(f"Goal: {args.goal}")
    print()

    # Create and run orchestrator
    orchestrator = Orchestrator(
        work_dir=work_dir,
        project_name=args.name or work_dir.name,
    )

    try:
        results = asyncio.run(orchestrator.run(args.goal))

        print("\n" + "="*60)
        print("  RESULTS")
        print("="*60)
        print(json.dumps(results, indent=2, default=str))

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def cmd_status(args):
    """Show project status."""
    print_banner()

    work_dir = Path(args.dir)
    if not work_dir.exists():
        print(f"Project directory not found: {work_dir}")
        sys.exit(1)

    # Load project setup
    setup = ProjectSetup(work_dir)
    config = setup.load_config()

    print(f"Project: {config.get('name', 'unknown')}")
    print(f"Directory: {work_dir}")
    print()

    # Check LBM status
    lbm_dir = work_dir / ".lbm"
    coordinator_node = lbm_dir / "coordinator" / "node.json"
    if coordinator_node.exists():
        coordinator = LBMCoordinator(lbm_dir, config.get("name", "project"))
        stats = coordinator.get_stats()

        print("Knowledge Base:")
        print(f"  Claims: {stats.get('claim_count', 0)}")
        print(f"  Total Supply: {stats.get('total_supply', 0)} tokens")
        print(f"  Agents: {stats.get('agent_count', 0)}")
        print()

        if stats.get("agents"):
            print("Agents:")
            for name, info in stats["agents"].items():
                print(f"  - {name} ({info['role']}): {info['balance']} tokens")
            print()
    else:
        print("No LBM data found. Run 'agentic-playground run' first.")

    # Check Docker status
    docker = DockerManager(work_dir)
    docker_status = docker.get_status()

    print("Infrastructure:")
    print(f"  Docker available: {docker_status['docker_available']}")
    print(f"  Compose available: {docker_status['compose_available']}")


def cmd_export(args):
    """Export learnings to a file."""
    print_banner()

    work_dir = Path(args.dir)
    lbm_dir = work_dir / ".lbm"
    coordinator_node = lbm_dir / "coordinator" / "node.json"

    if not coordinator_node.exists():
        print("No LBM data found. Run 'agentic-playground run' first.")
        sys.exit(1)

    # Load config for project name
    setup = ProjectSetup(work_dir)
    config = setup.load_config()

    coordinator = LBMCoordinator(lbm_dir, config.get("name", "project"))

    output_file = Path(args.output)
    coordinator.export_learnings(output_file)

    print(f"Learnings exported to: {output_file}")
    stats = coordinator.get_stats()
    print(f"  Claims: {stats.get('claim_count', 0)}")


def cmd_docker(args):
    """Manage Docker infrastructure."""
    print_banner()

    work_dir = Path(args.dir)
    docker = DockerManager(work_dir)

    if args.action == "setup":
        print("Setting up Docker infrastructure...")
        files = docker.setup_infrastructure()
        print("\nFiles created:")
        for name, path in files.items():
            print(f"  - {name}: {path}")

    elif args.action == "up":
        print("Starting containers...")
        success = asyncio.run(docker.compose_up())
        if success:
            print("✓ Containers started")
        else:
            print("✗ Failed to start containers")

    elif args.action == "down":
        print("Stopping containers...")
        success = asyncio.run(docker.compose_down())
        if success:
            print("✓ Containers stopped")
        else:
            print("✗ Failed to stop containers")

    elif args.action == "status":
        status = docker.get_status()
        print(json.dumps(status, indent=2))


def cmd_knowledge(args):
    """View knowledge base."""
    print_banner()

    work_dir = Path(args.dir)
    lbm_dir = work_dir / ".lbm"
    coordinator_node = lbm_dir / "coordinator" / "node.json"

    if not coordinator_node.exists():
        print("No LBM data found. Run 'agentic-playground run' first.")
        sys.exit(1)

    setup = ProjectSetup(work_dir)
    config = setup.load_config()

    coordinator = LBMCoordinator(lbm_dir, config.get("name", "project"))
    claims = coordinator.get_all_claims()

    print(f"Knowledge Base: {len(claims)} claims\n")

    for claim in claims[-args.limit:]:
        print(f"[{claim['author']}] (height: {claim['block_height']})")
        print(f"  Tags: {', '.join(claim['tags'])}")
        text = claim['text']
        if len(text) > 100:
            text = text[:100] + "..."
        print(f"  {text}")
        print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agentic-playground",
        description="Multi-Agent Coordination System",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new project")
    init_parser.add_argument(
        "--name", "-n",
        default="agentic-project",
        help="Project name",
    )
    init_parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Project directory",
    )
    init_parser.add_argument(
        "--goal", "-g",
        default="",
        help="Project goal",
    )
    init_parser.add_argument(
        "--docker",
        action="store_true",
        help="Include Docker infrastructure",
    )
    init_parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip git initialization",
    )
    init_parser.set_defaults(func=cmd_init)

    # run command
    run_parser = subparsers.add_parser("run", help="Run the orchestrator")
    run_parser.add_argument(
        "--goal", "-g",
        required=True,
        help="Project goal",
    )
    run_parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Work directory",
    )
    run_parser.add_argument(
        "--name", "-n",
        help="Project name",
    )
    run_parser.set_defaults(func=cmd_run)

    # status command
    status_parser = subparsers.add_parser("status", help="Show project status")
    status_parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Project directory",
    )
    status_parser.set_defaults(func=cmd_status)

    # export command
    export_parser = subparsers.add_parser("export", help="Export learnings")
    export_parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Project directory",
    )
    export_parser.add_argument(
        "--output", "-o",
        default="learnings.json",
        help="Output file",
    )
    export_parser.set_defaults(func=cmd_export)

    # docker command
    docker_parser = subparsers.add_parser("docker", help="Manage Docker infrastructure")
    docker_parser.add_argument(
        "action",
        choices=["setup", "up", "down", "status"],
        help="Docker action",
    )
    docker_parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Project directory",
    )
    docker_parser.set_defaults(func=cmd_docker)

    # knowledge command
    knowledge_parser = subparsers.add_parser("knowledge", help="View knowledge base")
    knowledge_parser.add_argument(
        "--dir", "-d",
        default=".",
        help="Project directory",
    )
    knowledge_parser.add_argument(
        "--limit", "-l",
        type=int,
        default=10,
        help="Number of claims to show",
    )
    knowledge_parser.set_defaults(func=cmd_knowledge)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
