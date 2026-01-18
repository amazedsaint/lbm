"""Tests for GitHub integration features.

Tests git hooks, GitHub discovery, LBM config management,
and MCP auto-detection of .lbm/ directories.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the modules we're testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from lb.git_hooks import (
    install_hooks, uninstall_hooks, list_hooks, verify_hooks,
    HOOK_TEMPLATES, DEFAULT_HOOKS
)
from lb.github_discovery import (
    GitHubDiscovery, GitHubDiscoveryError, GitHubUser, Collaborator, LBMPeer,
    load_peers_from_repo, save_peers_to_repo, get_git_remote_repo
)
from lb.github_integration import (
    LBMConfig, GitHubIntegrationError,
    is_lbm_initialized, load_lbm_config, save_lbm_config,
    get_or_create_node, github_status
)
from lb.mcp import _detect_lbm_repo, _load_node_for_mcp


class TestGitHooks:
    """Tests for git hook management."""

    @pytest.fixture
    def git_repo(self):
        """Create a temporary git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True)
            # Create .lbm directory for hooks
            (repo_path / ".lbm").mkdir()
            yield repo_path

    def test_install_hooks(self, git_repo):
        """Test installing default hooks."""
        installed = install_hooks(git_repo)

        assert len(installed) == len(DEFAULT_HOOKS)
        for hook_name in DEFAULT_HOOKS:
            assert hook_name in installed

            # Check hook exists in .lbm/hooks/
            lbm_hook = git_repo / ".lbm" / "hooks" / hook_name
            assert lbm_hook.exists()
            assert os.access(lbm_hook, os.X_OK)

            # Check symlink exists in .git/hooks/
            git_hook = git_repo / ".git" / "hooks" / hook_name
            assert git_hook.is_symlink()

    def test_install_hooks_not_git_repo(self):
        """Test installing hooks in non-git directory fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="Not a git repository"):
                install_hooks(Path(tmpdir))

    def test_install_hooks_no_overwrite(self, git_repo):
        """Test that existing hooks are not overwritten without force."""
        # Create existing hook
        git_hooks_dir = git_repo / ".git" / "hooks"
        git_hooks_dir.mkdir(parents=True, exist_ok=True)
        existing_hook = git_hooks_dir / "post-commit"
        existing_hook.write_text("#!/bin/bash\necho 'existing'")

        # Install hooks (should skip existing)
        installed = install_hooks(git_repo)

        # post-commit should be skipped
        assert "post-commit" not in installed
        assert existing_hook.read_text() == "#!/bin/bash\necho 'existing'"

    def test_install_hooks_force(self, git_repo):
        """Test that force flag overwrites existing hooks."""
        # Create existing hook
        git_hooks_dir = git_repo / ".git" / "hooks"
        git_hooks_dir.mkdir(parents=True, exist_ok=True)
        existing_hook = git_hooks_dir / "post-commit"
        existing_hook.write_text("#!/bin/bash\necho 'existing'")

        # Install hooks with force
        installed = install_hooks(git_repo, force=True)

        # post-commit should be installed (backup created)
        assert "post-commit" in installed
        assert (git_hooks_dir / "post-commit.backup").exists()

    def test_uninstall_hooks(self, git_repo):
        """Test uninstalling hooks."""
        # First install
        install_hooks(git_repo)

        # Then uninstall
        uninstalled = uninstall_hooks(git_repo)

        assert len(uninstalled) > 0
        for hook_name in uninstalled:
            git_hook = git_repo / ".git" / "hooks" / hook_name
            # Symlink should be removed
            assert not git_hook.exists() or not git_hook.is_symlink()

    def test_list_hooks(self, git_repo):
        """Test listing hook status."""
        # Install hooks first
        install_hooks(git_repo)

        hooks = list_hooks(git_repo)

        assert len(hooks) == len(HOOK_TEMPLATES)
        for hook in hooks:
            assert "name" in hook
            assert "available" in hook
            assert "installed" in hook
            assert "is_lbm_hook" in hook

            if hook["name"] in DEFAULT_HOOKS:
                assert hook["installed"]
                assert hook["is_lbm_hook"]

    def test_verify_hooks(self, git_repo):
        """Test hook verification."""
        # Before installation
        result = verify_hooks(git_repo)
        assert not result["ok"]
        assert len(result["issues"]) > 0

        # After installation
        install_hooks(git_repo)
        result = verify_hooks(git_repo)
        assert result["ok"]
        assert len(result["issues"]) == 0

    def test_hook_content(self, git_repo):
        """Test that installed hooks have correct content."""
        install_hooks(git_repo)

        for hook_name in DEFAULT_HOOKS:
            lbm_hook = git_repo / ".lbm" / "hooks" / hook_name
            content = lbm_hook.read_text()

            # Should start with shebang
            assert content.startswith("#!/bin/bash")
            # Should reference lb command
            assert "lb" in content


class TestGitHubDiscovery:
    """Tests for GitHub API discovery (mocked)."""

    def test_parse_repo_format(self):
        """Test parsing owner/repo format."""
        discovery = GitHubDiscovery("owner/repo")
        assert discovery._owner == "owner"
        assert discovery._name == "repo"

    def test_invalid_repo_format(self):
        """Test that invalid repo format raises error."""
        with pytest.raises(ValueError, match="Invalid repo format"):
            GitHubDiscovery("invalid")

        with pytest.raises(ValueError, match="Invalid repo format"):
            GitHubDiscovery("too/many/parts")

    @patch('lb.github_discovery.urllib.request.urlopen')
    def test_get_collaborators(self, mock_urlopen):
        """Test fetching collaborators with mocked API."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([
            {
                "login": "alice",
                "id": 1,
                "avatar_url": "https://example.com/alice.png",
                "permissions": {"admin": True, "push": True, "pull": True}
            },
            {
                "login": "bob",
                "id": 2,
                "permissions": {"admin": False, "push": True, "pull": True}
            }
        ]).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *args: None
        mock_urlopen.return_value = mock_response

        discovery = GitHubDiscovery("owner/repo", token="test-token")
        collaborators = discovery.get_collaborators()

        assert len(collaborators) == 2
        assert collaborators[0].user.login == "alice"
        assert collaborators[0].is_admin
        assert collaborators[1].user.login == "bob"
        assert collaborators[1].can_push
        assert not collaborators[1].is_admin


class TestLBMPeers:
    """Tests for peer management."""

    @pytest.fixture
    def repo_with_lbm(self):
        """Create a temp directory with .lbm/ structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".lbm").mkdir()
            yield repo_path

    def test_save_load_peers(self, repo_with_lbm):
        """Test saving and loading peers."""
        peers = [
            LBMPeer(github_user="alice", sign_pub="pubkey1", enc_pub="enckey1"),
            LBMPeer(github_user="bob", sign_pub="pubkey2", host="192.168.1.1", port=7337),
        ]

        save_peers_to_repo(repo_with_lbm, peers)

        # Check file exists
        peers_file = repo_with_lbm / ".lbm" / "peers.json"
        assert peers_file.exists()

        # Load back
        loaded = load_peers_from_repo(repo_with_lbm)

        assert len(loaded) == 2
        assert loaded[0].github_user == "alice"
        assert loaded[0].sign_pub == "pubkey1"
        assert loaded[1].github_user == "bob"
        assert loaded[1].host == "192.168.1.1"
        assert loaded[1].port == 7337

    def test_load_peers_no_file(self, repo_with_lbm):
        """Test loading peers when file doesn't exist."""
        peers = load_peers_from_repo(repo_with_lbm)
        assert peers == []


class TestGetGitRemoteRepo:
    """Tests for extracting repo from git remote."""

    @pytest.fixture
    def git_repo_with_remote(self):
        """Create a git repo with origin remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
            yield repo_path

    def test_https_remote(self, git_repo_with_remote):
        """Test parsing HTTPS remote URL."""
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/owner/repo.git"],
            cwd=git_repo_with_remote
        )

        result = get_git_remote_repo(git_repo_with_remote)
        assert result == "owner/repo"

    def test_ssh_remote(self, git_repo_with_remote):
        """Test parsing SSH remote URL."""
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=git_repo_with_remote
        )

        result = get_git_remote_repo(git_repo_with_remote)
        assert result == "owner/repo"

    def test_no_remote(self, git_repo_with_remote):
        """Test when no remote is configured."""
        result = get_git_remote_repo(git_repo_with_remote)
        assert result is None


class TestLBMConfig:
    """Tests for LBM configuration."""

    def test_config_roundtrip(self):
        """Test config serialization and deserialization."""
        config = LBMConfig(
            group_id="group123",
            group_name="test-project",
            created_by="github:alice",
            created_at="2024-01-15T00:00:00Z",
            github_repo="owner/repo",
            relay_url="wss://relay.example.com",
            sync_on_commit=True,
            agent_auto_register=False,
        )

        data = config.to_dict()
        restored = LBMConfig.from_dict(data)

        assert restored.group_id == config.group_id
        assert restored.group_name == config.group_name
        assert restored.created_by == config.created_by
        assert restored.github_repo == config.github_repo
        assert restored.relay_url == config.relay_url
        assert restored.sync_on_commit == config.sync_on_commit
        assert restored.agent_auto_register == config.agent_auto_register

    def test_save_load_config(self):
        """Test saving and loading config to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            config = LBMConfig(
                group_id="group123",
                group_name="test-project",
                created_by="github:alice",
                created_at="2024-01-15T00:00:00Z",
                github_repo="owner/repo",
            )

            save_lbm_config(repo_path, config)

            assert is_lbm_initialized(repo_path)

            loaded = load_lbm_config(repo_path)
            assert loaded.group_id == config.group_id
            assert loaded.github_repo == config.github_repo

    def test_load_config_not_initialized(self):
        """Test loading config when not initialized raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(GitHubIntegrationError, match="not initialized"):
                load_lbm_config(Path(tmpdir))


class TestGitHubStatus:
    """Tests for github_status function."""

    def test_status_not_initialized(self):
        """Test status when LBM is not initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status = github_status(Path(tmpdir))
            assert not status["initialized"]

    def test_status_initialized(self):
        """Test status when LBM is initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Create minimal .lbm structure
            config = LBMConfig(
                group_id="group123",
                group_name="test-project",
                created_by="github:alice",
                created_at="2024-01-15T00:00:00Z",
                github_repo="owner/repo",
            )
            save_lbm_config(repo_path, config)

            # Create node directory
            node_path = repo_path / ".lbm" / "node"
            from lb.node import BatteryNode
            BatteryNode.init(node_path)

            # Save peers
            peers = [LBMPeer(github_user="alice", sign_pub="pubkey1")]
            save_peers_to_repo(repo_path, peers)

            status = github_status(repo_path)

            assert status["initialized"]
            assert status["github_repo"] == "owner/repo"
            assert status["group_name"] == "test-project"
            assert status["group_id"] == "group123"
            assert len(status["peers"]) == 1


class TestMCPDetection:
    """Tests for MCP .lbm/ auto-detection."""

    def test_detect_lbm_repo_cwd(self):
        """Test detection in current working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir).resolve()

            # Create .lbm/config.json
            lbm_dir = repo_path / ".lbm"
            lbm_dir.mkdir()
            config = {"group_id": "test", "group_name": "test", "created_by": "test",
                      "created_at": "2024-01-01", "github_repo": "o/r"}
            (lbm_dir / "config.json").write_text(json.dumps(config))

            # Should detect with explicit working_dir
            result = _detect_lbm_repo(str(repo_path))
            # Use resolve() on both to handle macOS /var -> /private/var symlinks
            assert result.resolve() == repo_path.resolve()

    def test_detect_lbm_repo_not_found(self):
        """Test detection when no .lbm/ exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _detect_lbm_repo(tmpdir)
            assert result is None

    def test_detect_lbm_repo_incomplete(self):
        """Test detection when .lbm/ exists but no config.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".lbm").mkdir()  # No config.json

            result = _detect_lbm_repo(str(repo_path))
            assert result is None

    def test_detect_via_env_var(self):
        """Test detection via LBM_REPO_PATH environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Create .lbm/config.json
            lbm_dir = repo_path / ".lbm"
            lbm_dir.mkdir()
            config = {"group_id": "test", "group_name": "test", "created_by": "test",
                      "created_at": "2024-01-01", "github_repo": "o/r"}
            (lbm_dir / "config.json").write_text(json.dumps(config))

            # Set environment variable
            old_env = os.environ.get("LBM_REPO_PATH")
            try:
                os.environ["LBM_REPO_PATH"] = str(repo_path)
                result = _detect_lbm_repo()  # No explicit working_dir
                # Should find via env var (but cwd takes precedence if it also has .lbm)
                assert result is not None
            finally:
                if old_env is not None:
                    os.environ["LBM_REPO_PATH"] = old_env
                else:
                    os.environ.pop("LBM_REPO_PATH", None)


class TestGetOrCreateNode:
    """Tests for node creation in .lbm/node/."""

    def test_create_new_node(self):
        """Test creating a new node when none exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".lbm").mkdir()

            node = get_or_create_node(repo_path)

            assert node is not None
            assert node.node_id is not None
            assert (repo_path / ".lbm" / "node" / "node.json").exists()

    def test_load_existing_node(self):
        """Test loading an existing node."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            (repo_path / ".lbm").mkdir()

            # Create node first time
            node1 = get_or_create_node(repo_path)
            node_id = node1.node_id

            # Load same node second time
            node2 = get_or_create_node(repo_path)

            assert node2.node_id == node_id


class TestHookTemplates:
    """Tests for hook template content."""

    def test_post_commit_hook_template(self):
        """Test post-commit hook template has required elements."""
        template = HOOK_TEMPLATES["post-commit"]

        # Should be bash script
        assert template.startswith("#!/bin/bash")

        # Should check for lb command
        assert "command -v lb" in template

        # Should check for .lbm directory
        assert ".lbm" in template

        # Should get commit message
        assert "git log" in template

        # Should call lb github sync
        assert "lb github sync" in template

    def test_post_checkout_hook_template(self):
        """Test post-checkout hook template has required elements."""
        template = HOOK_TEMPLATES["post-checkout"]

        # Should be bash script
        assert template.startswith("#!/bin/bash")

        # Should check for branch checkout (not file checkout)
        assert '"$3" != "1"' in template

        # Should call lb github sync
        assert "lb github sync" in template

    def test_all_hooks_are_valid_bash(self):
        """Test that all hook templates are syntactically valid bash."""
        for hook_name, template in HOOK_TEMPLATES.items():
            # Check shebang
            assert template.startswith("#!/bin/bash"), f"{hook_name} missing shebang"

            # Check for lb command reference
            assert "lb" in template, f"{hook_name} doesn't reference lb"
