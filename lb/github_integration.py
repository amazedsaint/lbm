"""GitHub integration for Learning Battery Market.

This module provides seamless integration with GitHub repositories,
enabling automatic P2P knowledge sharing among collaborators.

Features:
- Initialize LBM in a GitHub repository
- Auto-discover collaborators via GitHub API
- Sync knowledge on git commits
- Agent auto-registration

Usage:
    # Initialize in a repo
    github_init(repo_path, github_repo="owner/repo")

    # Join existing LBM-enabled repo
    github_join(repo_path)

    # Sync with collaborators
    github_sync(repo_path)
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .github_discovery import (
    GitHubDiscovery,
    GitHubDiscoveryError,
    LBMPeer,
    load_peers_from_repo,
    save_peers_to_repo,
    get_git_remote_repo,
)
from .keys import gen_node_keys, NodeKeys
from .logging_config import get_logger
from .node import BatteryNode

logger = get_logger("lb.github")

# Default relay server URL (optional)
DEFAULT_RELAY_URL = "wss://relay.lbm.dev"


@dataclass
class LBMConfig:
    """LBM configuration for a GitHub repository."""
    group_id: str
    group_name: str
    created_by: str  # "github:username"
    created_at: str  # ISO format
    github_repo: str  # "owner/repo"
    discovery: str = "github"  # "github" or "manual"
    relay_url: Optional[str] = None
    sync_on_commit: bool = True
    sync_on_push: bool = True
    agent_auto_register: bool = True
    version: str = "1"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Remove None values
        return {k: v for k, v in d.items() if v is not None}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LBMConfig":
        return LBMConfig(
            group_id=d["group_id"],
            group_name=d["group_name"],
            created_by=d["created_by"],
            created_at=d["created_at"],
            github_repo=d["github_repo"],
            discovery=d.get("discovery", "github"),
            relay_url=d.get("relay_url"),
            sync_on_commit=d.get("sync_on_commit", True),
            sync_on_push=d.get("sync_on_push", True),
            agent_auto_register=d.get("agent_auto_register", True),
            version=d.get("version", "1"),
        )


class GitHubIntegrationError(Exception):
    """Error during GitHub integration operations."""
    pass


def is_lbm_initialized(repo_path: Path) -> bool:
    """Check if LBM is initialized in the repository."""
    config_path = repo_path / ".lbm" / "config.json"
    return config_path.exists()


def load_lbm_config(repo_path: Path) -> LBMConfig:
    """Load LBM configuration from repository.

    Args:
        repo_path: Path to repository root

    Returns:
        LBM configuration

    Raises:
        GitHubIntegrationError: If config doesn't exist or is invalid
    """
    config_path = repo_path / ".lbm" / "config.json"
    if not config_path.exists():
        raise GitHubIntegrationError(
            f"LBM not initialized in {repo_path}. Run 'lb github init' first."
        )

    try:
        with open(config_path, "r") as f:
            data = json.load(f)
        return LBMConfig.from_dict(data)
    except (json.JSONDecodeError, KeyError) as e:
        raise GitHubIntegrationError(f"Invalid LBM config: {e}")


def save_lbm_config(repo_path: Path, config: LBMConfig) -> None:
    """Save LBM configuration to repository."""
    config_path = repo_path / ".lbm" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)
        f.write("\n")


def get_or_create_node(repo_path: Path) -> BatteryNode:
    """Get or create LBM node for the repository.

    Node data is stored in .lbm/node/ and should be gitignored.

    Args:
        repo_path: Path to repository root

    Returns:
        BatteryNode instance
    """
    node_path = repo_path / ".lbm" / "node"

    if (node_path / "node.json").exists():
        return BatteryNode.load(node_path)
    else:
        return BatteryNode.init(node_path)


def github_init(
    repo_path: Path,
    *,
    github_repo: Optional[str] = None,
    group_name: Optional[str] = None,
    relay_url: Optional[str] = DEFAULT_RELAY_URL,
    sync_on_commit: bool = True,
    agent_auto_register: bool = True,
) -> LBMConfig:
    """Initialize LBM in a GitHub repository.

    This creates:
    - .lbm/config.json - shared configuration
    - .lbm/peers.json - peer public keys
    - .lbm/node/ - local node data (gitignored)
    - .lbm/hooks/ - git hooks
    - .lbm/.gitignore - ignore node/

    Args:
        repo_path: Path to repository root
        github_repo: Repository in "owner/repo" format. Auto-detected if not provided.
        group_name: Name for the knowledge group. Defaults to repo name.
        relay_url: Optional relay server URL for NAT traversal.
        sync_on_commit: Whether to sync on git commits.
        agent_auto_register: Whether agents auto-register.

    Returns:
        LBM configuration

    Raises:
        GitHubIntegrationError: On initialization errors
    """
    repo_path = Path(repo_path).resolve()

    # Verify this is a git repository
    if not (repo_path / ".git").exists():
        raise GitHubIntegrationError(
            f"Not a git repository: {repo_path}. Run 'git init' first."
        )

    # Check if already initialized
    if is_lbm_initialized(repo_path):
        raise GitHubIntegrationError(
            f"LBM already initialized in {repo_path}. Use 'lb github join' instead."
        )

    # Auto-detect GitHub repo from remote
    if not github_repo:
        github_repo = get_git_remote_repo(repo_path)
        if not github_repo:
            raise GitHubIntegrationError(
                "Could not detect GitHub repo. Provide --repo owner/repo"
            )

    # Get current GitHub user
    discovery = GitHubDiscovery(github_repo)
    try:
        current_user = discovery.get_authenticated_user()
        github_username = current_user.login
    except GitHubDiscoveryError as e:
        raise GitHubIntegrationError(f"GitHub authentication failed: {e}")

    # Verify user is a collaborator
    if not discovery.verify_collaborator_access(github_username):
        raise GitHubIntegrationError(
            f"User {github_username} is not a collaborator with push access"
        )

    # Default group name to repo name
    if not group_name:
        group_name = github_repo.split("/")[1]

    # Create local node
    node = get_or_create_node(repo_path)

    # Create knowledge group
    group_id = node.create_group(group_name)
    logger.info(f"Created knowledge group: {group_name} ({group_id})")

    # Create configuration
    config = LBMConfig(
        group_id=group_id,
        group_name=group_name,
        created_by=f"github:{github_username}",
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        github_repo=github_repo,
        relay_url=relay_url,
        sync_on_commit=sync_on_commit,
        agent_auto_register=agent_auto_register,
    )
    save_lbm_config(repo_path, config)

    # Create .gitignore for node data
    gitignore_path = repo_path / ".lbm" / ".gitignore"
    with open(gitignore_path, "w") as f:
        f.write("# Local node data - do not commit\n")
        f.write("node/\n")

    # Initialize peers.json with current user
    peer = LBMPeer(
        github_user=github_username,
        sign_pub=node.keys.sign_pub_b64,
        enc_pub=node.keys.enc_pub_b64,
        last_seen_ms=int(time.time() * 1000),
    )
    save_peers_to_repo(repo_path, [peer])

    # Install git hooks
    _install_git_hooks(repo_path)

    logger.info(f"Initialized LBM in {repo_path}")
    logger.info(f"  GitHub repo: {github_repo}")
    logger.info(f"  Group: {group_name} ({group_id})")
    logger.info(f"  Your identity: {github_username}")

    return config


def github_join(repo_path: Path) -> LBMConfig:
    """Join an existing LBM-enabled repository.

    This:
    - Creates local node in .lbm/node/
    - Adds your public key to .lbm/peers.json
    - Syncs existing knowledge from peers
    - Installs git hooks

    Args:
        repo_path: Path to repository root

    Returns:
        LBM configuration

    Raises:
        GitHubIntegrationError: On join errors
    """
    repo_path = Path(repo_path).resolve()

    # Verify LBM is initialized
    if not is_lbm_initialized(repo_path):
        raise GitHubIntegrationError(
            f"LBM not initialized in {repo_path}. Ask repo owner to run 'lb github init'."
        )

    # Load config
    config = load_lbm_config(repo_path)

    # Get current GitHub user
    discovery = GitHubDiscovery(config.github_repo)
    try:
        current_user = discovery.get_authenticated_user()
        github_username = current_user.login
    except GitHubDiscoveryError as e:
        raise GitHubIntegrationError(f"GitHub authentication failed: {e}")

    # Verify collaborator access
    if not discovery.verify_collaborator_access(github_username):
        raise GitHubIntegrationError(
            f"User {github_username} is not a collaborator. Request access first."
        )

    # Check if already joined
    peers = load_peers_from_repo(repo_path)
    for p in peers:
        if p.github_user.lower() == github_username.lower():
            logger.info(f"Already joined as {github_username}")
            return config

    # Create or load local node
    node = get_or_create_node(repo_path)

    # Join the knowledge group
    # First, sync from an existing peer to get the chain
    synced = False
    for peer in peers:
        if peer.host and peer.port:
            try:
                node.sync_group_from_peer(peer.host, peer.port, config.group_id)
                synced = True
                logger.info(f"Synced from peer {peer.github_user}")
                break
            except Exception as e:
                logger.debug(f"Failed to sync from {peer.github_user}: {e}")

    if not synced and peers:
        logger.warning("Could not sync from any peer. You may need to sync manually.")

    # Add self to peers
    new_peer = LBMPeer(
        github_user=github_username,
        sign_pub=node.keys.sign_pub_b64,
        enc_pub=node.keys.enc_pub_b64,
        last_seen_ms=int(time.time() * 1000),
    )
    peers.append(new_peer)
    save_peers_to_repo(repo_path, peers)

    # Install git hooks
    _install_git_hooks(repo_path)

    logger.info(f"Joined LBM in {repo_path}")
    logger.info(f"  Group: {config.group_name} ({config.group_id})")
    logger.info(f"  Your identity: {github_username}")
    logger.info(f"  Peers: {len(peers)}")

    return config


def github_sync(
    repo_path: Path,
    *,
    commit_msg: Optional[str] = None,
    files_changed: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Sync knowledge with collaborators.

    This:
    - Syncs chain state from available peers
    - Optionally publishes commit info as knowledge

    Args:
        repo_path: Path to repository root
        commit_msg: Git commit message to publish as knowledge
        files_changed: List of files changed in commit

    Returns:
        Sync result with stats

    Raises:
        GitHubIntegrationError: On sync errors
    """
    repo_path = Path(repo_path).resolve()

    if not is_lbm_initialized(repo_path):
        raise GitHubIntegrationError(f"LBM not initialized in {repo_path}")

    config = load_lbm_config(repo_path)
    node = get_or_create_node(repo_path)
    peers = load_peers_from_repo(repo_path)

    result = {
        "synced_from": [],
        "sync_errors": [],
        "claim_published": False,
    }

    # Sync from peers
    for peer in peers:
        if peer.sign_pub == node.keys.sign_pub_b64:
            continue  # Skip self

        if peer.host and peer.port:
            try:
                node.sync_group_from_peer(peer.host, peer.port, config.group_id)
                result["synced_from"].append(peer.github_user)
            except Exception as e:
                result["sync_errors"].append({
                    "peer": peer.github_user,
                    "error": str(e),
                })

    # Publish commit as knowledge if provided
    if commit_msg:
        try:
            tags = ["commit"]
            if files_changed:
                # Add file type tags
                extensions = set()
                for f in files_changed:
                    ext = Path(f).suffix.lower()
                    if ext:
                        extensions.add(ext[1:])  # Remove dot
                tags.extend(list(extensions)[:5])  # Max 5 extension tags

            text = f"Commit: {commit_msg}"
            if files_changed:
                text += f"\n\nFiles changed:\n" + "\n".join(f"- {f}" for f in files_changed[:20])

            node.publish_claim(config.group_id, text, tags)
            result["claim_published"] = True
            logger.debug(f"Published commit as knowledge claim")
        except Exception as e:
            logger.warning(f"Failed to publish commit as claim: {e}")

    return result


def github_status(repo_path: Path) -> Dict[str, Any]:
    """Get LBM status for the repository.

    Returns:
        Status information including peers, sync state, etc.
    """
    repo_path = Path(repo_path).resolve()

    if not is_lbm_initialized(repo_path):
        return {"initialized": False}

    config = load_lbm_config(repo_path)
    node = get_or_create_node(repo_path)
    peers = load_peers_from_repo(repo_path)

    # Get group info
    group = node.groups.get(config.group_id)
    group_info = None
    if group:
        group_info = {
            "height": group.chain.head.height,
            "claims": len(group.graph.claims) if group.graph else 0,
            "members": len(group.chain.state.members),
        }

    # Find current user in peers
    my_peer = None
    for p in peers:
        if p.sign_pub == node.keys.sign_pub_b64:
            my_peer = p.github_user
            break

    return {
        "initialized": True,
        "github_repo": config.github_repo,
        "group_name": config.group_name,
        "group_id": config.group_id,
        "my_identity": my_peer,
        "node_id": node.node_id,
        "peers": [
            {
                "github_user": p.github_user,
                "sign_pub": p.sign_pub[:16] + "...",
                "has_address": bool(p.host and p.port),
                "is_self": p.sign_pub == node.keys.sign_pub_b64,
            }
            for p in peers
        ],
        "group": group_info,
        "config": {
            "sync_on_commit": config.sync_on_commit,
            "agent_auto_register": config.agent_auto_register,
            "relay_url": config.relay_url,
        },
    }


def register_agent(
    repo_path: Path,
    agent_name: str,
    agent_type: str = "claude",
) -> Dict[str, Any]:
    """Register an AI agent with unique identity.

    Args:
        repo_path: Path to repository root
        agent_name: Name for the agent (e.g., "claude-session-123")
        agent_type: Type of agent ("claude", "codex", etc.)

    Returns:
        Agent registration info including keys

    Raises:
        GitHubIntegrationError: On registration errors
    """
    repo_path = Path(repo_path).resolve()

    if not is_lbm_initialized(repo_path):
        raise GitHubIntegrationError(f"LBM not initialized in {repo_path}")

    config = load_lbm_config(repo_path)

    if not config.agent_auto_register:
        raise GitHubIntegrationError("Agent auto-registration disabled in config")

    node = get_or_create_node(repo_path)

    # Generate unique agent keys
    agent_keys = gen_node_keys()

    # Add agent as member with "agent" role
    node.add_member(config.group_id, agent_keys.sign_pub_b64, role="member")

    logger.info(f"Registered agent: {agent_name} ({agent_type})")

    return {
        "agent_name": agent_name,
        "agent_type": agent_type,
        "sign_pub": agent_keys.sign_pub_b64,
        "enc_pub": agent_keys.enc_pub_b64,
        "group_id": config.group_id,
        # Note: Private keys should be stored securely by the caller
        "_sign_priv_b64": agent_keys.sign_priv_b64,
        "_enc_priv_b64": agent_keys.enc_priv_b64,
    }


def _install_git_hooks(repo_path: Path) -> None:
    """Install git hooks for automatic sync.

    Creates hooks in .lbm/hooks/ and symlinks to .git/hooks/
    """
    hooks_dir = repo_path / ".lbm" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Post-commit hook
    post_commit = hooks_dir / "post-commit"
    post_commit_content = '''#!/bin/bash
# LBM auto-sync on commit
# Generated by 'lb github init'

# Check if lb command exists
if ! command -v lb &> /dev/null; then
    exit 0
fi

# Get commit info
COMMIT_MSG=$(git log -1 --pretty=%B 2>/dev/null)
FILES_CHANGED=$(git diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null | tr '\\n' ',')

# Sync in background (don't block commit)
(lb github sync --commit "$COMMIT_MSG" --files "$FILES_CHANGED" 2>/dev/null &)
'''
    with open(post_commit, "w") as f:
        f.write(post_commit_content)
    os.chmod(post_commit, 0o755)

    # Post-checkout hook
    post_checkout = hooks_dir / "post-checkout"
    post_checkout_content = '''#!/bin/bash
# LBM sync on checkout
# Generated by 'lb github init'

# Only run on branch checkout, not file checkout
if [ "$3" != "1" ]; then
    exit 0
fi

# Check if lb command exists
if ! command -v lb &> /dev/null; then
    exit 0
fi

# Sync in background
(lb github sync 2>/dev/null &)
'''
    with open(post_checkout, "w") as f:
        f.write(post_checkout_content)
    os.chmod(post_checkout, 0o755)

    # Symlink to .git/hooks/
    git_hooks_dir = repo_path / ".git" / "hooks"
    git_hooks_dir.mkdir(parents=True, exist_ok=True)

    for hook_name in ["post-commit", "post-checkout"]:
        src = hooks_dir / hook_name
        dst = git_hooks_dir / hook_name

        # Don't overwrite existing hooks
        if dst.exists() and not dst.is_symlink():
            logger.warning(f"Existing {hook_name} hook found, not overwriting")
            continue

        # Remove old symlink if exists
        if dst.is_symlink():
            dst.unlink()

        # Create relative symlink
        rel_src = os.path.relpath(src, git_hooks_dir)
        dst.symlink_to(rel_src)

    logger.debug("Installed git hooks")
