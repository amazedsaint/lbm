"""GitHub API integration for collaborator discovery.

This module provides functionality to:
- Discover repository collaborators via GitHub API
- Find collaborators who have LBM configured
- Verify collaborator status for access control
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from pathlib import Path

from .logging_config import get_logger

logger = get_logger("lb.github")

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class GitHubUser:
    """GitHub user information."""
    login: str
    id: int
    avatar_url: Optional[str] = None
    html_url: Optional[str] = None


@dataclass
class Collaborator:
    """Repository collaborator with permissions."""
    user: GitHubUser
    permissions: Dict[str, bool]  # admin, maintain, push, triage, pull

    @property
    def can_push(self) -> bool:
        return self.permissions.get("push", False)

    @property
    def is_admin(self) -> bool:
        return self.permissions.get("admin", False)


@dataclass
class LBMPeer:
    """A collaborator who has LBM configured."""
    github_user: str
    sign_pub: str
    enc_pub: Optional[str] = None
    last_seen_ms: Optional[int] = None
    host: Optional[str] = None
    port: Optional[int] = None


class GitHubDiscoveryError(Exception):
    """Error during GitHub API operations."""
    pass


class GitHubDiscovery:
    """Discover collaborators via GitHub API.

    Usage:
        discovery = GitHubDiscovery("owner/repo")
        collaborators = await discovery.get_collaborators()

        # Or with explicit token
        discovery = GitHubDiscovery("owner/repo", token="ghp_...")
    """

    def __init__(self, repo: str, *, token: Optional[str] = None):
        """Initialize GitHub discovery.

        Args:
            repo: Repository in "owner/repo" format
            token: GitHub personal access token. If not provided,
                   uses GITHUB_TOKEN environment variable.
        """
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self._owner, self._name = self._parse_repo(repo)

    @staticmethod
    def _parse_repo(repo: str) -> tuple:
        """Parse owner/repo format."""
        parts = repo.strip().split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid repo format: {repo}. Expected 'owner/repo'")
        return parts[0], parts[1]

    def _request(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Any:
        """Make a GitHub API request.

        Args:
            endpoint: API endpoint (e.g., "/repos/owner/repo/collaborators")
            method: HTTP method
            data: JSON body for POST/PUT requests

        Returns:
            Parsed JSON response

        Raises:
            GitHubDiscoveryError: On API errors
        """
        url = f"{GITHUB_API_BASE}{endpoint}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LearningBatteryMarket/0.6.1",
        }

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = None
        if data:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            if e.code == 401:
                raise GitHubDiscoveryError("GitHub authentication failed. Set GITHUB_TOKEN.")
            elif e.code == 403:
                raise GitHubDiscoveryError(f"GitHub API rate limit or permission denied: {error_body}")
            elif e.code == 404:
                raise GitHubDiscoveryError(f"Repository not found: {self.repo}")
            else:
                raise GitHubDiscoveryError(f"GitHub API error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise GitHubDiscoveryError(f"Network error: {e.reason}")

    def get_collaborators(self) -> List[Collaborator]:
        """Fetch repository collaborators from GitHub API.

        Returns:
            List of collaborators with their permissions

        Raises:
            GitHubDiscoveryError: On API errors
        """
        endpoint = f"/repos/{self._owner}/{self._name}/collaborators"
        data = self._request(endpoint)

        collaborators = []
        for item in data:
            user = GitHubUser(
                login=item["login"],
                id=item["id"],
                avatar_url=item.get("avatar_url"),
                html_url=item.get("html_url"),
            )
            perms = item.get("permissions", {})
            collaborators.append(Collaborator(user=user, permissions=perms))

        logger.debug(f"Found {len(collaborators)} collaborators for {self.repo}")
        return collaborators

    def get_authenticated_user(self) -> GitHubUser:
        """Get the currently authenticated GitHub user.

        Returns:
            Current user info

        Raises:
            GitHubDiscoveryError: If not authenticated or API error
        """
        if not self.token:
            raise GitHubDiscoveryError("GITHUB_TOKEN required to get authenticated user")

        data = self._request("/user")
        return GitHubUser(
            login=data["login"],
            id=data["id"],
            avatar_url=data.get("avatar_url"),
            html_url=data.get("html_url"),
        )

    def is_collaborator(self, username: str) -> bool:
        """Check if a user is a collaborator on the repository.

        Args:
            username: GitHub username to check

        Returns:
            True if user is a collaborator with push access
        """
        try:
            endpoint = f"/repos/{self._owner}/{self._name}/collaborators/{username}"
            self._request(endpoint)
            return True
        except GitHubDiscoveryError as e:
            if "404" in str(e):
                return False
            raise

    def get_repo_info(self) -> Dict[str, Any]:
        """Get repository information.

        Returns:
            Repository metadata including visibility, default branch, etc.
        """
        endpoint = f"/repos/{self._owner}/{self._name}"
        return self._request(endpoint)

    def verify_collaborator_access(self, username: str) -> bool:
        """Verify a user has collaborator access (for LBM join).

        This checks that the user:
        1. Is listed as a collaborator
        2. Has at least push access

        Args:
            username: GitHub username

        Returns:
            True if user can join the LBM group
        """
        collaborators = self.get_collaborators()
        for collab in collaborators:
            if collab.user.login.lower() == username.lower():
                return collab.can_push
        return False


def load_peers_from_repo(repo_path: Path) -> List[LBMPeer]:
    """Load LBM peers from a repository's .lbm/peers.json.

    Args:
        repo_path: Path to the repository root

    Returns:
        List of configured peers
    """
    peers_file = repo_path / ".lbm" / "peers.json"
    if not peers_file.exists():
        return []

    try:
        with open(peers_file, "r") as f:
            data = json.load(f)

        peers = []
        for p in data.get("peers", []):
            peers.append(LBMPeer(
                github_user=p["github_user"],
                sign_pub=p["sign_pub"],
                enc_pub=p.get("enc_pub"),
                last_seen_ms=p.get("last_seen_ms"),
                host=p.get("host"),
                port=p.get("port"),
            ))
        return peers
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to parse peers.json: {e}")
        return []


def save_peers_to_repo(repo_path: Path, peers: List[LBMPeer]) -> None:
    """Save LBM peers to a repository's .lbm/peers.json.

    Args:
        repo_path: Path to the repository root
        peers: List of peers to save
    """
    peers_file = repo_path / ".lbm" / "peers.json"
    peers_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "peers": [
            {
                "github_user": p.github_user,
                "sign_pub": p.sign_pub,
                **({"enc_pub": p.enc_pub} if p.enc_pub else {}),
                **({"last_seen_ms": p.last_seen_ms} if p.last_seen_ms else {}),
                **({"host": p.host} if p.host else {}),
                **({"port": p.port} if p.port else {}),
            }
            for p in peers
        ]
    }

    with open(peers_file, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def get_git_remote_repo(repo_path: Path) -> Optional[str]:
    """Extract owner/repo from git remote origin URL.

    Args:
        repo_path: Path to git repository

    Returns:
        "owner/repo" string or None if not found
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        url = result.stdout.strip()

        # Parse various URL formats:
        # git@github.com:owner/repo.git
        # https://github.com/owner/repo.git
        # https://github.com/owner/repo

        if url.startswith("git@github.com:"):
            path = url[15:]  # Remove git@github.com:
        elif "github.com/" in url:
            path = url.split("github.com/")[1]
        else:
            return None

        # Remove .git suffix
        if path.endswith(".git"):
            path = path[:-4]

        # Validate format
        if "/" in path:
            parts = path.split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"

        return None
    except Exception as e:
        logger.debug(f"Failed to get git remote: {e}")
        return None
