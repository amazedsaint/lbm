# Changelog

All notable changes to Learning Batteries Market are documented here.

## [0.5.0] - 2026-01-13

### Token Economy Release

This release adds a comprehensive, configurable token economy system with automatic token distribution, rewards, transfer fees, and supply caps.

### Added

- **Member Faucet**: Auto-mint tokens to new members joining a group
  - Configurable `faucet_amount` per group policy
  - Only grants tokens to genuinely new members (not duplicates)
  - Returning members (previously removed) receive faucet amount

- **Claim Rewards**: Earn tokens when publishing knowledge claims
  - Configurable `claim_reward_amount` per group policy
  - Block author receives reward for each claim transaction
  - Respects supply caps

- **Transfer Fees**: Percentage-based fees on token transfers
  - Configurable `transfer_fee_bps` (basis points, 100 = 1%)
  - Fees sent to treasury account
  - Maximum fee capped at 50% (5000 bps)

- **Supply Caps**: Limit total and per-account token supply
  - `max_total_supply`: Cap on total tokens in circulation
  - `max_account_balance`: Cap on individual account balance
  - Supply cap can only be raised, never lowered below current supply

- **Total Supply Tracking**: GroupState now tracks `total_supply`
  - Updated on mint, faucet, and claim rewards
  - Included in snapshots for persistence

- **Policy Update Transaction**: New `policy_update` transaction type
  - Admin-only operation
  - Update any policy field: faucet_amount, claim_reward_amount, transfer_fee_bps, max_total_supply, max_account_balance
  - Validation for unknown keys and empty updates

- **Node API Methods**:
  - `update_group_policy(group_id, **updates)`: Update policy fields
  - `get_token_stats(group_id)`: Get token economy statistics
  - `transfer(group_id, to_pub, amount)`: Transfer with automatic fee handling

### Security

- **Integer Overflow Protection**: MAX_TOKEN_VALUE = 2^63 - 1
  - All token operations check for overflow
  - Transfer amount + fee overflow check

- **Validation**: Strict input validation for policy updates
  - Unknown keys rejected
  - Empty updates rejected
  - Fee bounds enforced (0-5000 bps)
  - Supply cap bounds enforced

### Tests

- 33 new tests in `tests/test_token_economy.py`:
  - Policy update tests (admin-only, invalid values, unknown keys)
  - Member faucet tests (new member, duplicate, returning member)
  - Claim reward tests (basic, supply cap, zero reward)
  - Transfer fee tests (calculation, treasury, zero fee)
  - Supply cap tests (mint blocked, cap increase, cap decrease)
  - Edge cases (fee rounding, treasury transfers, large values)
- All 102 tests passing

---

## [0.4.1] - 2026-01-12

### Security and Reliability Fixes

This patch release addresses security vulnerabilities and improves reliability of the sync daemon.

### Security

- **CORS Subdomain Spoofing Fix** (`lb/admin.py`): Fixed vulnerability where malicious subdomains like `localhost.evil.com` could bypass CORS restrictions. Now uses strict matching requiring exact origin or origin with port suffix.

- **Connection Acquisition Race Condition** (`lb/p2p.py`): Fixed race condition where connection slot could leak if rate limiter threw an exception. Now properly initializes tracking before check and handles exceptions.

### Changed

- **Sync Daemon Retry Backoff** (`lb/sync_daemon.py`): Implemented proper exponential backoff for failed syncs
  - Tracks consecutive failure count per subscription
  - Linear backoff: `retry_delay_s × failure_count` (capped at sync_interval)
  - Auto-disables subscription after `max_retries` (default: 3) consecutive failures
  - Prevents hammering unresponsive peers

- **Thread-Safe Peer Registry** (`lb/node.py`): Fixed potential race condition in lazy initialization of `peer_registry` property using double-checked locking pattern

### Fixed

- **MCP Base64 Import** (`lb/mcp.py`): Replaced dynamic `__import__("base64")` with proper static import

### Configuration

- New environment variables for retry behavior:
  - `LB_SYNC_RETRY_DELAY_S`: Delay between retries (default: 60s)
  - `LB_SYNC_MAX_RETRIES`: Max consecutive failures before disabling (default: 3)

---

## [0.4.0] - 2026-01-12

### Auto-Sync, Peer Discovery, and Admin Panel Release

This release adds automatic synchronization for subscribed groups, peer discovery capabilities, and a user-friendly web admin panel.

### Added

- **Web Admin Panel** (`lb/admin.py`): User-friendly HTML dashboard
  - Overview tab with node info and stats
  - Groups tab with member/balance/offer details
  - Knowledge tab to browse claims with text and tags
  - Peers tab showing registered peers and status
  - Subscriptions tab for auto-sync monitoring
  - Market tab listing available offers
  - Modal dialogs for detailed views
  - Responsive design for mobile/desktop
  - CLI command: `lb run-admin --host 0.0.0.0 --port 8080`

- **Peer Registry** (`lb/registry.py`): Persistent peer tracking
  - Store known peers with host, port, node_id, public keys
  - Alias support for friendly peer names
  - Status tracking (last seen, errors)
  - Atomic JSON persistence (peers.json)

- **Subscription Management**: Auto-sync for groups
  - Subscribe to groups with configurable sync intervals
  - Enable/disable individual subscriptions
  - Per-subscription error tracking
  - Atomic JSON persistence (subscriptions.json)

- **Sync Daemon** (`lb/sync_daemon.py`): Background synchronization
  - Automatic sync of due subscriptions
  - Configurable check interval (default: 10s)
  - Semaphore-limited concurrent syncs (default: 3)
  - Manual sync trigger via `sync_now()`
  - Status reporting (running, due subscriptions, results)

- **Group Discovery**: New RPC methods
  - `group_list_available`: List groups on a peer
  - `peer_exchange`: Exchange peer lists (gossip foundation)
  - `sync_status`: Extended health with per-group chain heights

- **CLI Commands**: 11 new commands
  - Peer management: `peer-add`, `peer-list`, `peer-remove`
  - Discovery: `discover-groups`
  - Subscriptions: `subscribe`, `unsubscribe`, `subscription-list`, `subscription-set`
  - Sync: `sync-now`, `run-sync-daemon`
  - Updated `run-p2p` with `--no-sync` flag

- **Exception Hierarchy** (`lb/exceptions.py`): Base error classes
  - `LBError`: Base for all LB exceptions
  - `LBNetworkError`, `LBSecurityError`, `LBValidationError`, `LBStorageError`

- **Configuration**: Sync-related environment variables
  - `LB_SYNC_INTERVAL_S`: Default sync interval (300s)
  - `LB_SYNC_MIN_INTERVAL_S`: Minimum interval (60s)
  - `LB_SYNC_AUTO_START`: Auto-start daemon (true)
  - `LB_SYNC_MAX_CONCURRENT`: Max concurrent syncs (3)

### Changed

- `run-p2p` now auto-starts sync daemon by default
- Node has lazy-loaded `peer_registry` property
- Updated demo script with sync examples

### Fixed

- Added proper error handling for JSON parsing in `crypto.py`
- Added type hints to `fs.py` functions
- Improved MCP parameter validation

### Tests

- 16 new tests for sync functionality (`tests/test_sync.py`)
- 9 new tests for admin panel (`tests/test_admin.py`)
- All 52 tests passing

## [0.3.0] - 2025-01-12

### Security Hardening Release

This release focuses on production readiness with comprehensive security hardening.

### Added

- **Key Encryption at Rest**: Private keys can now be encrypted with password protection
  - Scrypt key derivation (N=2^17, r=8, p=1)
  - ChaCha20-Poly1305 AEAD encryption
  - CLI commands: `--encrypt-keys`, `encrypt-keys`, `change-password`
  - Automatic detection of encrypted vs unencrypted key files

- **Rate Limiting**: DoS protection for P2P server
  - Per-IP connection limiting (default: 10 connections)
  - Per-peer request rate limiting (default: 100/minute)
  - Memory-bounded tracking with LRU eviction
  - `rate_limited` error code for programmatic handling

- **Network Timeouts**: Configurable timeouts for P2P operations
  - Handshake timeout (default: 30s)
  - Idle connection timeout (default: 5 minutes)
  - Proper cleanup on timeout

- **Health Check Endpoint**: New `health` RPC method
  - Node status, version, group/offer counts
  - Timestamp for monitoring

- **CAS Index Consistency**: Thread-safe content-addressed storage
  - Thread locking for concurrent access
  - Startup validation for stale/orphan entries
  - Atomic index writes with fsync

- **Input Validation Module**: Centralized validation (`lb/validation.py`)
  - Configurable size limits for all inputs
  - Claim text: 64KB max
  - Offer titles: 256 chars, descriptions: 4KB
  - Tags: 20 max per item, 64 chars each

- **Structured Logging**: Production-ready logging (`lb/logging_config.py`)
  - JSON format support for log aggregation
  - Log rotation (10MB, 5 backups)
  - Timer context manager for operation timing
  - Separate loggers per component

- **Configuration Management**: Centralized config (`lb/config.py`)
  - Environment variable overrides (LB_* prefix)
  - JSON file support for config persistence
  - Per-component configuration sections

### Changed

- **Offer Expiration**: Now uses block timestamp instead of local time
  - Prevents backdating attacks
  - Consistent expiration across all nodes

- **Nonce Validation**: Uses block timestamp for clock skew protection
  - Reference time from authoritative block timestamp
  - Prevents replay across clock-skewed nodes

- **Fork Resolution**: Fully deterministic ordering
  - Primary: chain height
  - Secondary: unique author count
  - Tertiary: total work
  - Tie-break: lexicographic block ID

- **P2P Connection Handling**: Improved reliability
  - Proper connection tracking and cleanup
  - Finally blocks ensure resource release
  - Better error logging with peer identification

- **Visibility Parsing**: Stricter validation for group visibility strings
  - Rejects malformed `group:` prefixes
  - Prevents empty group ID extraction

### Fixed

- Rate limiter unbounded memory growth (now LRU-bounded)
- Connection limiter unbounded IP tracking (now bounded)
- Missing `import time` causing `UnboundLocalError` in health check
- Ledger durability (added fsync after writes)

### Security

- Nonce replay prevention with 24-hour expiration
- Per buyer+offer nonce keys prevent cross-transaction replay
- Minimum nonce length enforcement (32 chars)
- Clock drift validation (5 minutes max)
- Memory bounds on all tracking data structures

## [0.2.0]

### Added

- Knowledge market: offers, purchases, access grants, token ledger
- Public offer broadcasting over secure P2P
- Encrypted package delivery (sealed symmetric keys to buyer)
- MCP-like connector extended with market methods

### Documentation

- Expanded tests and docs

## [0.1.0]

### Added

- Initial release
- Knowledge groups with append-only chains
- Ed25519/X25519 cryptographic identity
- Content-addressed storage (CAS)
- Context compilation with latent-space retrieval
- P2P synchronization with encrypted transport
- CLI for node management
