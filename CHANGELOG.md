# Changelog

## [0.6.2] - GitHub Integration Release

This release adds seamless GitHub integration for multi-developer collaboration.

### GitHub Integration

- **Repository Integration**: Initialize LBM directly in GitHub repositories
  - `lb github init` - Creates `.lbm/` directory with config, peers, and node data
  - `lb github join` - Join existing LBM-enabled repositories as collaborator
  - `lb github status` - Show LBM status, peers, and group info
  - `lb github sync` - Manual sync with collaborators

- **Git Hooks**: Automatic knowledge sync on git operations
  - `post-commit` hook publishes commit info as knowledge claims
  - `post-checkout` hook syncs when switching branches
  - `lb github hooks --install/--uninstall/--list` for hook management

- **GitHub Discovery**: Auto-discover collaborators via GitHub API
  - Collaborator verification before joining groups
  - Peer management with public keys stored in `.lbm/peers.json`

- **Agent Auto-Registration**: Seamless agent integration
  - MCP auto-detects `.lbm/` in working directory
  - Agents auto-register with unique keys when `agent_auto_register` is enabled
  - `lb github agent-register` for manual registration
  - `LBM_REPO_PATH` environment variable support

### MCP Enhancements

- New `--working-dir` parameter to specify repo location
- New `--agent-name` parameter for agent identification
- `initialize` response includes `github_integration` section when in repo

### New Modules

- `lb/github_discovery.py` - GitHub API client for collaborator discovery
- `lb/github_integration.py` - Main integration with init, join, sync, status
- `lb/git_hooks.py` - Git hook templates and management

### Tests

- 30 new tests for GitHub integration (total: 191 tests)
- Tests for hooks, discovery, config, MCP detection

---

## [0.6.1] - Production Hardening Release

This release completes production-grade durability and security features.

### Durability

- **Write-Ahead Log (WAL)**: Atomic multi-file operations prevent split-brain state
  - New `lb/wal.py` module with `WriteAheadLog` and `Transaction` classes
  - Automatic crash recovery on startup
  - Integrated into `_append_block` for atomic chain+graph persistence

### Security

- **TOCTOU Fix**: Access control now ties authorization to specific chain state
  - `at_head` parameter in P2P methods (`group_get_snapshot`, `cas_get`)
  - Returns `stale_state` error if chain has advanced since authorization check

- **Admin Panel Authentication**: HTTP Basic Auth support
  - `auth_password` parameter on `AdminServer` and `run_admin()`
  - Security warning banner displayed when auth is disabled
  - Username: "admin", constant-time password comparison

### Documentation

- Updated production readiness plan to 100% complete
- Clarified latent retrieval is deterministic hashing (not semantic embeddings)
- Added WAL and TOCTOU implementation details

---

## [0.6.0] - Multi-Agent Coordination Release

This release adds comprehensive multi-agent coordination features including claim threading, task management, agent presence tracking, and time-windowed queries.

### Multi-Agent Coordination

- **Claim Threading**: Parent-child relationships for threaded conversations
  - `parent_hash` parameter on `publish_claim`
  - Query claims with thread context

- **Task Management**: Full task lifecycle with state machine
  - State machine: `pending` → `assigned` → `in_progress` → `completed`/`failed`
  - Transaction types: `task_create`, `task_assign`, `task_start`, `task_complete`, `task_fail`
  - Automatic token rewards on task completion
  - Query tasks by status or assignee

- **Agent Presence**: Heartbeat tracking with stale detection
  - Status updates: `active`, `idle`, `busy`, `offline`
  - Custom metadata support (max 4KB)
  - Stale detection (default: 5 minutes)

- **Time-Windowed Queries**: Get "what's new" since a timestamp
  - `since_ms` parameter on `compile_context`
  - `get_recent_claims` for time-filtered claims
  - `watch_claims` for cursor-based pagination

### MCP Tools

New tools for agent integration:
- `create_task`, `assign_task`, `start_task`, `complete_task`, `fail_task`, `list_tasks`
- `update_presence`, `get_presence`
- `get_recent_claims`, `watch_claims`
- Updated `publish_claim` with `parent_hash`
- Updated `compile_context` with `since_ms`

### Token Economy

- Member faucet (auto-mint on join)
- Claim rewards (tokens for knowledge)
- Task rewards (tokens for task completion)
- Transfer fees (basis points to treasury)
- Supply caps (total and per-account)

### Security

- Task ID length limit (256 chars)
- Task title/description limits (256 chars / 4KB)
- Error message limit (1KB)
- Presence metadata limit (4KB)
- Assignee must be group member
- Integer overflow protection (MAX_TOKEN_VALUE = 2^63 - 1)

### Infrastructure

- Key encryption at rest (Scrypt + ChaCha20-Poly1305)
- Rate limiting (per-IP connections, per-peer requests)
- Web admin panel
- Auto-sync daemon
- Peer discovery and registry

### Tests

- 177 tests covering all functionality
- Edge case tests for security validations
- Multi-agent coordination tests

### CLI Commands

```bash
lb init --data ./mynode --encrypt-keys
lb run-p2p --data ./mynode --port 7337
lb run-admin --data ./mynode --port 8080
lb run-mcp --data ./mynode
```
