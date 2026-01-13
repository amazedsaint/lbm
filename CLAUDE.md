# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Learning Batteries Market is a **production-ready**, **local-first**, **peer-to-peer** knowledge marketplace. AI agents write experience and domain knowledge into Knowledge Groups (permissioned append-only chains). Knowledge compiles into context slices via latent-space retrieval. Nodes replicate securely using Ed25519/X25519 cryptography.

**Version**: 0.5.0 (Token Economy Release)

## Quick Reference

```bash
# Install
python -m venv .venv && source .venv/bin/activate && pip install -e .

# Run tests
python -m pytest tests/ -v

# Initialize node with encrypted keys
lb init --data ./mynode --encrypt-keys

# Start P2P server
lb run-p2p --data ./mynode --host 0.0.0.0 --port 7337
```

## Architecture

### Package Structure (`lb/`)

```
lb/
├── __main__.py      # CLI entry point
├── node.py          # BatteryNode - main orchestrator
├── chain.py         # Permissioned append-only chain
├── group.py         # Knowledge group management
├── cas.py           # Content-addressed storage (thread-safe)
├── context_graph.py # Truth-maintenance claims
├── latent.py        # Latent-space retrieval
├── keys.py          # Ed25519 + X25519 key management
├── key_encryption.py# Key encryption at rest (Scrypt + ChaCha20)
├── crypto.py        # AEAD encryption, sealed boxes
├── canonical.py     # Deterministic JSON serialization
├── wire.py          # Frame encoding (4-byte length prefix)
├── secure_channel.py# Encrypted session with HKDF
├── p2p.py           # P2P server and RPC client
├── mcp.py           # Agent connector (stdio JSON-RPC)
├── config.py        # Configuration management
├── logging_config.py# Structured logging
├── validation.py    # Input validation
├── rate_limit.py    # Connection and request limiting
└── fs.py            # Filesystem utilities
```

### Core Components

| Component | File | Purpose |
|-----------|------|---------|
| BatteryNode | `node.py` | Orchestrates keys, CAS, groups, offer book |
| GroupChain | `chain.py` | Validates and appends blocks with transactions |
| CAS | `cas.py` | Thread-safe content-addressed storage |
| P2PServer | `p2p.py` | Rate-limited RPC server |
| SecureChannel | `secure_channel.py` | Noise-like encrypted sessions |

### Transaction Types

```python
# Membership
{"type": "member_add", "pub": "...", "role": "member", "ts_ms": ...}
{"type": "member_remove", "pub": "...", "ts_ms": ...}

# Tokens
{"type": "mint", "to": "...", "amount": 100, "ts_ms": ...}
{"type": "transfer", "from": "...", "to": "...", "amount": 50, "ts_ms": ...}
{"type": "policy_update", "updates": {"faucet_amount": 100, ...}, "ts_ms": ...}

# Knowledge
{"type": "claim", "artifact_hash": "...", "ts_ms": ...}
{"type": "retract", "claim_hash": "...", "ts_ms": ...}

# Market
{"type": "offer_create", "offer": {...}, "ts_ms": ...}
{"type": "purchase", "offer_id": "...", "buyer": "...", "nonce": "...", "ts_ms": ...}
{"type": "grant", "offer_id": "...", "buyer": "...", "sealed_key": "...", "ts_ms": ...}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LB_LOG_LEVEL` | INFO | DEBUG, INFO, WARNING, ERROR |
| `LB_LOG_DIR` | "" | Log file directory |
| `LB_LOG_JSON` | false | JSON format for logs |
| `LB_MAX_CLOCK_DRIFT_MS` | 300000 | Max block timestamp drift (5 min) |
| `LB_NONCE_EXPIRY_MS` | 86400000 | Nonce expiration (24 hours) |
| `LB_MIN_NONCE_LENGTH` | 32 | Minimum nonce length |
| `LB_P2P_MAX_CONN_PER_IP` | 10 | Max connections per IP |
| `LB_P2P_MAX_REQ_PER_MIN` | 100 | Max requests per minute per peer |
| `LB_P2P_READ_TIMEOUT_S` | 30 | Handshake timeout |
| `LB_P2P_IDLE_TIMEOUT_S` | 300 | Idle connection timeout |

### Programmatic Access

```python
from lb.config import get_config

config = get_config()
print(config.chain.max_clock_drift_ms)  # 300000
print(config.p2p.max_connections_per_ip)  # 10
```

## Security Features

### Key Encryption

```python
from lb.key_encryption import init_encrypted_keys, load_keys

# Initialize with encryption
keys = init_encrypted_keys(data_dir, password="secure-password")

# Load encrypted keys
keys = load_keys(data_dir, password="secure-password")
```

### Rate Limiting

```python
from lb.rate_limit import get_rate_limiter

limiter = get_rate_limiter()
result = await limiter.check_connection("192.168.1.1")
if not result.allowed:
    print(f"Blocked: {result.reason}")
```

### Input Validation

```python
from lb.validation import validate_claim_text, validate_offer, ValidationError

try:
    validate_claim_text(user_input)  # Max 64KB
    validate_offer(title, description, tags, price)
except ValidationError as e:
    print(f"Invalid: {e.field} - {e.message}")
```

## Token Economy

Configurable per-group token economy with automatic minting, rewards, and fees.

### Policy Fields (GroupPolicy)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `faucet_amount` | int | 0 | Tokens auto-minted to new members |
| `claim_reward_amount` | int | 0 | Tokens earned per knowledge claim |
| `transfer_fee_bps` | int | 0 | Transfer fee in basis points (100 = 1%) |
| `max_total_supply` | int\|None | None | Maximum total token supply (None = unlimited) |
| `max_account_balance` | int\|None | None | Maximum per-account balance (None = unlimited) |

### Node API Methods

```python
# Update group policy (admin only)
node.update_group_policy(group_id,
    faucet_amount=100,
    claim_reward_amount=10,
    transfer_fee_bps=250,  # 2.5% fee
    max_total_supply=1_000_000
)

# Get token statistics
stats = node.get_token_stats(group_id)
# Returns: total_supply, max_total_supply, treasury_balance,
#          faucet_amount, claim_reward_amount, transfer_fee_bps

# Transfer tokens (auto-calculates fee)
node.transfer(group_id, to_pub="...", amount=100)
```

### Security Limits

- Integer overflow protection: MAX_TOKEN_VALUE = 2^63 - 1
- Transfer fee capped at 50% (5000 bps)
- Supply cap cannot be lowered below current supply
- Empty policy updates rejected

## Testing

### Run Tests

```bash
# All tests
python -m pytest tests/ -v

# Specific file
python -m pytest tests/test_production_features.py -v

# Specific test
python -m pytest tests/test_market.py::TestMarketEndToEnd::test_offer_purchase_flow -v

# With coverage
python -m pytest tests/ -v --cov=lb --cov-report=html
```

### Test Structure

- `tests/test_chain.py` - Chain validation, fork resolution
- `tests/test_market.py` - Offer creation, purchase flow
- `tests/test_token_economy.py` - Token economy (faucet, rewards, fees, caps)
- `tests/test_production_features.py` - Key encryption, rate limiting, CAS consistency

### Writing Tests

```python
import pytest
import tempfile
from pathlib import Path
from lb.node import BatteryNode

@pytest.fixture
def temp_node():
    with tempfile.TemporaryDirectory() as tmpdir:
        node = BatteryNode.init(Path(tmpdir))
        yield node

def test_example(temp_node):
    # Test with isolated node
    assert temp_node.node_id is not None
```

## Common Tasks

### Add a New RPC Method

1. Add handler in `p2p.py` `P2PServer._handle()`:
```python
elif method == "my_method":
    param = params.get("param")
    if not isinstance(param, str):
        raise RPCError("bad_request", "missing param")
    result = do_something(param)
    resp["result"] = {"data": result}
```

2. Add client wrapper in `node.py` if needed
3. Document in `docs/API_REFERENCE.md`

### Add a New Transaction Type

1. Add to `chain.py` `_validate_tx()`:
```python
elif ttype == "my_tx":
    _require(author_role == "admin", "must be admin")
    value = tx.get("value")
    _require(isinstance(value, int) and value > 0, "invalid value")
```

2. Add state update in `_apply_tx()`:
```python
elif ttype == "my_tx":
    st.my_data[tx["key"]] = tx["value"]
```

3. Add to GroupState dataclass if storing state

### Add Configuration Option

1. Add to appropriate config class in `config.py`:
```python
@dataclass
class P2PConfig:
    my_option: int = 100
```

2. Add env var loading in `_load_env_overrides()`:
```python
if v := os.environ.get("LB_MY_OPTION"):
    config.p2p.my_option = int(v)
```

## Debugging

### Enable Debug Logging

```bash
export LB_LOG_LEVEL=DEBUG
lb run-p2p --data ./mynode --port 7337
```

### Check Node State

```python
from lb.node import BatteryNode
from pathlib import Path

node = BatteryNode.load(Path("./mynode"))
print(f"Node ID: {node.node_id}")
print(f"Groups: {list(node.groups.keys())}")
print(f"Offers: {len(node.offer_book)}")

# Check group state
for gid, group in node.groups.items():
    state = group.chain.state
    print(f"Group {gid}: {len(state.members)} members, height {group.chain.head.height}")
```

### Inspect CAS

```python
from lb.cas import CAS
from pathlib import Path

cas = CAS(Path("./mynode/cas"))
stats = cas.stats()
print(f"Objects: {stats['object_count']}")
print(f"By kind: {stats['by_kind']}")
```

## Code Style

- Type hints for all public functions
- Docstrings for public API
- Use `_require()` for validation in chain.py
- Use `RPCError` for P2P errors
- Use `ValidationError` for input validation
- Prefix private methods with `_`
- Use async/await for I/O operations

## Documentation

- `README.md` - User-facing quickstart
- `SECURITY.md` - Security model and features
- `CHANGELOG.md` - Version history
- `docs/API_REFERENCE.md` - RPC method documentation
- `docs/PROTOCOL.md` - Wire protocol details
- `docs/ARCHITECTURE.md` - System design
- `docs/PRODUCTION_READINESS_PLAN.md` - Deployment checklist
