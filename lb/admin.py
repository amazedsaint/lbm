"""Web-based admin panel for Learning Battery Market nodes.

Provides a user-friendly HTML interface to view and manage:
- Node information and status
- Knowledge groups and claims
- Peers and subscriptions
- Market offers
- Sync daemon status

SECURITY WARNING:
-----------------
This admin panel has NO AUTHENTICATION by default. It is designed for
localhost-only access. If you need remote access:
1. Use a reverse proxy (nginx, caddy) with TLS and authentication
2. Or enable basic auth via the auth_password parameter
3. NEVER expose this panel directly to the internet without auth

Usage with basic auth:
    server = AdminServer(node, auth_password="your-secure-password")
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Dict, Optional, Callable, Awaitable

from . import __version__
from .logging_config import get_logger

if TYPE_CHECKING:
    from .node import BatteryNode

logger = get_logger("lb.admin")

# Content types
CONTENT_TYPE_HTML = "text/html; charset=utf-8"
CONTENT_TYPE_JSON = "application/json; charset=utf-8"
CONTENT_TYPE_CSS = "text/css; charset=utf-8"
CONTENT_TYPE_JS = "application/javascript; charset=utf-8"


class AdminServer:
    """Lightweight HTTP server for the admin panel.

    Args:
        node: The BatteryNode to manage
        auth_password: Optional password for basic auth. If set, all requests
                      require HTTP Basic Authentication with username "admin".
    """

    def __init__(self, node: "BatteryNode", *, auth_password: Optional[str] = None):
        self.node = node
        self._server: Optional[asyncio.AbstractServer] = None
        self._routes: Dict[str, Callable[..., Awaitable[tuple]]] = {}
        self._auth_password = auth_password
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register all routes."""
        self._routes = {
            "/": self._handle_dashboard,
            "/api/node": self._handle_api_node,
            "/api/groups": self._handle_api_groups,
            "/api/group": self._handle_api_group_detail,
            "/api/peers": self._handle_api_peers,
            "/api/subscriptions": self._handle_api_subscriptions,
            "/api/offers": self._handle_api_offers,
            "/api/sync": self._handle_api_sync,
            "/api/claims": self._handle_api_claims,
        }

    def _check_auth(self, auth_header: Optional[str]) -> bool:
        """Check HTTP Basic Authentication.

        Args:
            auth_header: The Authorization header value (e.g., "Basic dXNlcjpwYXNz")

        Returns:
            True if authentication is disabled or credentials are valid.
        """
        if self._auth_password is None:
            return True  # Auth disabled

        if not auth_header:
            return False

        try:
            # Parse "Basic <base64>"
            if not auth_header.startswith("Basic "):
                return False

            encoded = auth_header[6:]
            decoded = base64.b64decode(encoded).decode("utf-8")

            # Parse "username:password"
            if ":" not in decoded:
                return False

            username, password = decoded.split(":", 1)

            # Only accept username "admin"
            if username != "admin":
                return False

            # Constant-time comparison to prevent timing attacks
            return hmac.compare_digest(password, self._auth_password)

        except Exception:
            return False

    async def _send_unauthorized(
        self,
        writer: asyncio.StreamWriter,
        origin: Optional[str] = None
    ) -> None:
        """Send a 401 Unauthorized response with WWW-Authenticate header."""
        body = b"<h1>401 Unauthorized</h1><p>Authentication required.</p>"

        cors_header = ""
        if origin:
            allowed_origins = [
                "http://127.0.0.1", "http://localhost",
                "https://127.0.0.1", "https://localhost",
            ]
            for allowed in allowed_origins:
                if origin == allowed or origin.startswith(allowed + ":"):
                    cors_header = f"Access-Control-Allow-Origin: {origin}\r\n"
                    break

        response = (
            f"HTTP/1.1 401 Unauthorized\r\n"
            f"Content-Type: {CONTENT_TYPE_HTML}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"WWW-Authenticate: Basic realm=\"LBM Admin Panel\"\r\n"
            f"Connection: close\r\n"
            f"{cors_header}"
            f"\r\n"
        ).encode("utf-8")
        writer.write(response + body)
        await writer.drain()

    async def start(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        """Start the admin server."""
        self._server = await asyncio.start_server(
            self._handle_connection, host, port
        )
        logger.info(f"Admin panel running at http://{host}:{port}")

    async def serve_forever(self) -> None:
        """Serve requests forever."""
        if self._server is None:
            raise RuntimeError("Server not started")
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Admin panel stopped")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle an incoming HTTP connection."""
        origin: Optional[str] = None
        auth_header: Optional[str] = None
        try:
            # Read request line
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=30.0
            )
            if not request_line:
                return

            request_str = request_line.decode("utf-8", errors="replace").strip()
            parts = request_str.split(" ")
            if len(parts) < 2:
                await self._send_response(writer, 400, "Bad Request", CONTENT_TYPE_HTML, b"Bad Request")
                return

            method = parts[0]
            path = parts[1]

            # Read headers and extract Origin for CORS and Authorization for auth
            while True:
                header_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                if header_line in (b"\r\n", b"\n", b""):
                    break
                header_str = header_line.decode("utf-8", errors="replace").strip()
                header_lower = header_str.lower()
                # Parse Origin header for CORS
                if header_lower.startswith("origin:"):
                    origin = header_str[7:].strip()
                # Parse Authorization header for Basic Auth
                elif header_lower.startswith("authorization:"):
                    auth_header = header_str[14:].strip()

            # Check authentication
            if not self._check_auth(auth_header):
                await self._send_unauthorized(writer, origin)
                return

            # Parse path and query string
            parsed = urllib.parse.urlparse(path)
            route_path = parsed.path
            query_params = urllib.parse.parse_qs(parsed.query)

            # Find route handler
            handler = self._routes.get(route_path)
            if handler:
                try:
                    status, content_type, body = await handler(method, query_params)
                    await self._send_response(writer, status, "OK", content_type, body, origin)
                except Exception as e:
                    logger.error(f"Error handling {route_path}: {e}")
                    await self._send_response(
                        writer, 500, "Internal Server Error",
                        CONTENT_TYPE_JSON,
                        json.dumps({"error": str(e)}).encode(),
                        origin
                    )
            else:
                await self._send_response(
                    writer, 404, "Not Found",
                    CONTENT_TYPE_HTML,
                    b"<h1>404 Not Found</h1>",
                    origin
                )

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.debug(f"Connection error: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        status_text: str,
        content_type: str,
        body: bytes,
        origin: Optional[str] = None
    ) -> None:
        """Send an HTTP response.

        CORS is restricted to localhost origins only for security.
        The admin panel should only be accessed from the same machine.
        """
        # Only allow CORS for localhost origins
        cors_header = ""
        if origin:
            # Whitelist localhost variants with strict matching
            # Must be exact match or followed by port (e.g., :8080)
            allowed_origins = [
                "http://127.0.0.1",
                "http://localhost",
                "https://127.0.0.1",
                "https://localhost",
            ]
            for allowed in allowed_origins:
                if origin == allowed:
                    # Exact match (no port)
                    cors_header = f"Access-Control-Allow-Origin: {origin}\r\n"
                    break
                elif origin.startswith(allowed + ":"):
                    # Match with port (e.g., http://localhost:8080)
                    cors_header = f"Access-Control-Allow-Origin: {origin}\r\n"
                    break

        response = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"{cors_header}"
            f"\r\n"
        ).encode("utf-8")
        writer.write(response + body)
        await writer.drain()

    # -------------------------------------------------------------------------
    # Route Handlers
    # -------------------------------------------------------------------------

    async def _handle_dashboard(self, method: str, params: dict) -> tuple:
        """Serve the main dashboard HTML."""
        html = self._get_dashboard_html()
        return 200, CONTENT_TYPE_HTML, html.encode("utf-8")

    async def _handle_api_node(self, method: str, params: dict) -> tuple:
        """Return node information."""
        data = {
            "node_id": self.node.node_id,
            "sign_pub": self.node.keys.sign_pub_b64,
            "enc_pub": self.node.keys.enc_pub_b64,
            "data_dir": str(self.node.data_dir),
            "groups_count": len(self.node.groups),
            "offers_count": len(self.node.offer_book),
            "version": __version__,
            "auth_enabled": self._auth_password is not None,
        }
        return 200, CONTENT_TYPE_JSON, json.dumps(data).encode()

    async def _handle_api_groups(self, method: str, params: dict) -> tuple:
        """Return list of all groups."""
        groups = []
        for gid, g in self.node.groups.items():
            state = g.chain.state
            groups.append({
                "group_id": gid,
                "name": state.policy.name,
                "currency": state.policy.currency,
                "height": g.chain.head.height,
                "member_count": len(state.members),
                "claims_count": len(g.graph.claims) if g.graph else 0,
                "offers_count": len(state.offers),
            })
        return 200, CONTENT_TYPE_JSON, json.dumps({"groups": groups}).encode()

    async def _handle_api_group_detail(self, method: str, params: dict) -> tuple:
        """Return detailed info for a specific group."""
        group_id = params.get("id", [""])[0]
        if not group_id or group_id not in self.node.groups:
            return 404, CONTENT_TYPE_JSON, json.dumps({"error": "Group not found"}).encode()

        g = self.node.groups[group_id]
        state = g.chain.state

        # Get members with roles (admins and members are separate sets)
        members = []
        for pub in state.admins:
            members.append({"pub": pub[:16] + "...", "pub_full": pub, "role": "admin"})
        for pub in state.members:
            if pub not in state.admins:
                members.append({"pub": pub[:16] + "...", "pub_full": pub, "role": "member"})

        # Get balances
        balances = [
            {"pub": pub[:16] + "...", "pub_full": pub, "amount": amt}
            for pub, amt in state.balances.items()
            if amt > 0
        ]

        # Get offers
        offers = [
            {
                "offer_id": oid,
                "title": o.title,
                "price": o.price,
                "active": o.active,
                "seller": o.seller[:16] + "...",
            }
            for oid, o in state.offers.items()
        ]

        data = {
            "group_id": group_id,
            "name": state.policy.name,
            "currency": state.policy.currency,
            "height": g.chain.head.height,
            "head_hash": g.chain.head.block_id[:16] + "...",
            "members": members,
            "balances": balances,
            "offers": offers,
            "policy": {
                "name": state.policy.name,
                "currency": state.policy.currency,
            }
        }
        return 200, CONTENT_TYPE_JSON, json.dumps(data).encode()

    async def _handle_api_claims(self, method: str, params: dict) -> tuple:
        """Return claims for a specific group."""
        group_id = params.get("group_id", [""])[0]
        if not group_id or group_id not in self.node.groups:
            return 404, CONTENT_TYPE_JSON, json.dumps({"error": "Group not found"}).encode()

        g = self.node.groups[group_id]
        claims = []

        if g.graph:
            for claim_hash, claim in g.graph.claims.items():
                # Get the actual text from CAS
                try:
                    artifact = self.node.cas.get(claim_hash)
                    artifact_data = json.loads(artifact.decode("utf-8"))
                    text = artifact_data.get("text", "")
                    tags = artifact_data.get("tags", [])
                except Exception:
                    text = "[Unable to load]"
                    tags = []

                claims.append({
                    "hash": claim_hash[:16] + "...",
                    "hash_full": claim_hash,
                    "text": text[:200] + ("..." if len(text) > 200 else ""),
                    "text_full": text,
                    "tags": tags,
                    "retracted": claim.retracted,
                    "created_ms": claim.created_ms,
                })

        return 200, CONTENT_TYPE_JSON, json.dumps({"claims": claims}).encode()

    async def _handle_api_peers(self, method: str, params: dict) -> tuple:
        """Return list of registered peers."""
        peers = []
        if hasattr(self.node, '_registry') and self.node._registry:
            for p in self.node.peer_registry.list_peers():
                peers.append({
                    "host": p.host,
                    "port": p.port,
                    "node_id": p.node_id,
                    "alias": p.alias,
                    "last_seen_ms": p.last_seen_ms,
                    "last_error": p.last_error,
                    "added_ms": p.added_ms,
                })
        return 200, CONTENT_TYPE_JSON, json.dumps({"peers": peers}).encode()

    async def _handle_api_subscriptions(self, method: str, params: dict) -> tuple:
        """Return list of subscriptions."""
        subs = []
        if hasattr(self.node, '_registry') and self.node._registry:
            for s in self.node.peer_registry.list_subscriptions():
                subs.append({
                    "group_id": s.group_id,
                    "peer_host": s.peer_host,
                    "peer_port": s.peer_port,
                    "sync_interval_s": s.sync_interval_s,
                    "enabled": s.enabled,
                    "last_sync_ms": s.last_sync_ms,
                    "last_error": s.last_error,
                })
        return 200, CONTENT_TYPE_JSON, json.dumps({"subscriptions": subs}).encode()

    async def _handle_api_offers(self, method: str, params: dict) -> tuple:
        """Return list of market offers."""
        offers = []
        for oid, o in self.node.offer_book.items():
            # offer_book stores dicts from OfferAnnouncement.to_dict()
            seller_pub = o.get("seller_sign_pub", "")
            offers.append({
                "offer_id": oid,
                "group_id": o.get("group_id", ""),
                "title": o.get("title", ""),
                "price": o.get("price", 0),
                "currency": o.get("currency", "KAT"),
                "tags": o.get("tags", []),
                "host": o.get("host", ""),
                "port": o.get("port", 0),
                "seller": seller_pub[:16] + "..." if seller_pub else "",
                "created_ms": o.get("created_ms", 0),
                "expires_ms": o.get("expires_ms"),
            })
        return 200, CONTENT_TYPE_JSON, json.dumps({"offers": offers}).encode()

    async def _handle_api_sync(self, method: str, params: dict) -> tuple:
        """Return sync daemon status."""
        data = {
            "daemon_available": False,
            "running": False,
            "subscriptions_total": 0,
            "subscriptions_enabled": 0,
            "subscriptions_due": 0,
        }
        # Note: Sync daemon status would need to be passed in or accessed differently
        # For now, just return subscription counts from registry
        if hasattr(self.node, '_registry') and self.node._registry:
            subs = self.node.peer_registry.list_subscriptions()
            data["subscriptions_total"] = len(subs)
            data["subscriptions_enabled"] = sum(1 for s in subs if s.enabled)
            data["daemon_available"] = True

        return 200, CONTENT_TYPE_JSON, json.dumps(data).encode()

    def _get_dashboard_html(self) -> str:
        """Return the main dashboard HTML."""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Learning Battery Market - Admin Panel</title>
    <style>
        :root {
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
            --text-secondary: #64748b;
            --border: #e2e8f0;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }

        .header {
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
            color: white;
            padding: 1.5rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .header h1 {
            font-size: 1.5rem;
            font-weight: 600;
        }

        .header .subtitle {
            font-size: 0.875rem;
            opacity: 0.9;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 1.5rem;
        }

        .nav-tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1.5rem;
            border-bottom: 2px solid var(--border);
            padding-bottom: 0.5rem;
            overflow-x: auto;
        }

        .nav-tab {
            padding: 0.75rem 1.25rem;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            border-radius: 0.5rem 0.5rem 0 0;
            transition: all 0.2s;
            white-space: nowrap;
        }

        .nav-tab:hover {
            color: var(--primary);
            background: rgba(37, 99, 235, 0.1);
        }

        .nav-tab.active {
            color: var(--primary);
            background: var(--card-bg);
            box-shadow: 0 -2px 0 var(--primary) inset;
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }

        .stat-card {
            background: var(--card-bg);
            padding: 1.25rem;
            border-radius: 0.75rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .stat-card .label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            margin-bottom: 0.25rem;
        }

        .stat-card .value {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--text);
        }

        .card {
            background: var(--card-bg);
            border-radius: 0.75rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 1.5rem;
            overflow: hidden;
        }

        .card-header {
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .card-body {
            padding: 1.25rem;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            text-align: left;
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--border);
        }

        th {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            font-weight: 600;
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover {
            background: rgba(0,0,0,0.02);
        }

        .badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem;
            font-weight: 500;
            border-radius: 9999px;
        }

        .badge-success { background: #d1fae5; color: #065f46; }
        .badge-warning { background: #fef3c7; color: #92400e; }
        .badge-danger { background: #fee2e2; color: #991b1b; }
        .badge-info { background: #dbeafe; color: #1e40af; }

        .tag {
            display: inline-block;
            padding: 0.125rem 0.5rem;
            font-size: 0.75rem;
            background: var(--border);
            border-radius: 0.25rem;
            margin: 0.125rem;
        }

        .btn {
            padding: 0.5rem 1rem;
            font-size: 0.875rem;
            font-weight: 500;
            border: none;
            border-radius: 0.5rem;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--primary);
            color: white;
        }

        .btn-primary:hover {
            background: var(--primary-dark);
        }

        .btn-sm {
            padding: 0.375rem 0.75rem;
            font-size: 0.75rem;
        }

        .empty-state {
            text-align: center;
            padding: 3rem;
            color: var(--text-secondary);
        }

        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
        }

        .node-id {
            font-family: monospace;
            background: var(--bg);
            padding: 0.25rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.875rem;
        }

        .claim-text {
            max-width: 400px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .clickable {
            cursor: pointer;
            color: var(--primary);
        }

        .clickable:hover {
            text-decoration: underline;
        }

        .modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }

        .modal-overlay.active {
            display: flex;
        }

        .modal {
            background: var(--card-bg);
            border-radius: 0.75rem;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            box-shadow: 0 25px 50px rgba(0,0,0,0.25);
        }

        .modal-header {
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-header h3 {
            font-size: 1.125rem;
        }

        .modal-close {
            background: none;
            border: none;
            font-size: 1.5rem;
            cursor: pointer;
            color: var(--text-secondary);
        }

        .modal-body {
            padding: 1.25rem;
        }

        .modal-body pre {
            background: var(--bg);
            padding: 1rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            font-size: 0.875rem;
        }

        .detail-row {
            display: flex;
            margin-bottom: 0.75rem;
        }

        .detail-label {
            width: 120px;
            color: var(--text-secondary);
            font-size: 0.875rem;
        }

        .detail-value {
            flex: 1;
            font-size: 0.875rem;
        }

        .loading {
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
        }

        @media (max-width: 768px) {
            .container {
                padding: 1rem;
            }

            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }

            table {
                font-size: 0.875rem;
            }

            th, td {
                padding: 0.5rem;
            }
        }

        .security-warning {
            background: #fef3c7;
            border: 1px solid #f59e0b;
            color: #92400e;
            padding: 0.75rem 1rem;
            border-radius: 0.5rem;
            margin-bottom: 1rem;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Learning Battery Market</h1>
        <div class="subtitle">Node Admin Panel</div>
    </div>

    <div class="container">
        <!-- Security Warning Banner (shown when auth disabled) -->
        <div id="security-warning" class="security-warning" style="display: none;">
            <strong>Security Warning:</strong> Authentication is disabled. This panel should only be accessed from localhost.
            Do not expose this server to the network without enabling authentication.
        </div>

        <div class="nav-tabs">
            <button class="nav-tab active" data-tab="overview">Overview</button>
            <button class="nav-tab" data-tab="groups">Groups</button>
            <button class="nav-tab" data-tab="knowledge">Knowledge</button>
            <button class="nav-tab" data-tab="peers">Peers</button>
            <button class="nav-tab" data-tab="subscriptions">Subscriptions</button>
            <button class="nav-tab" data-tab="market">Market</button>
        </div>

        <!-- Overview Tab -->
        <div id="overview" class="tab-content active">
            <div class="stats-grid" id="stats-grid">
                <div class="stat-card">
                    <div class="label">Node ID</div>
                    <div class="value" id="node-id">-</div>
                </div>
                <div class="stat-card">
                    <div class="label">Groups</div>
                    <div class="value" id="groups-count">-</div>
                </div>
                <div class="stat-card">
                    <div class="label">Market Offers</div>
                    <div class="value" id="offers-count">-</div>
                </div>
                <div class="stat-card">
                    <div class="label">Version</div>
                    <div class="value" id="version">-</div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">Node Information</div>
                <div class="card-body">
                    <div class="detail-row">
                        <div class="detail-label">Sign Public Key</div>
                        <div class="detail-value"><code id="sign-pub">-</code></div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Enc Public Key</div>
                        <div class="detail-value"><code id="enc-pub">-</code></div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Data Directory</div>
                        <div class="detail-value"><code id="data-dir">-</code></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Groups Tab -->
        <div id="groups" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Knowledge Groups</span>
                    <button class="btn btn-sm btn-primary" onclick="loadGroups()">Refresh</button>
                </div>
                <div class="card-body" id="groups-table-container">
                    <div class="loading">Loading...</div>
                </div>
            </div>
        </div>

        <!-- Knowledge Tab -->
        <div id="knowledge" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Knowledge Claims</span>
                    <select id="group-select" class="btn btn-sm" onchange="loadClaims()">
                        <option value="">Select a group...</option>
                    </select>
                </div>
                <div class="card-body" id="claims-container">
                    <div class="empty-state">
                        <div class="empty-state-icon">📚</div>
                        <div>Select a group to view its knowledge claims</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Peers Tab -->
        <div id="peers" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Registered Peers</span>
                    <button class="btn btn-sm btn-primary" onclick="loadPeers()">Refresh</button>
                </div>
                <div class="card-body" id="peers-container">
                    <div class="loading">Loading...</div>
                </div>
            </div>
        </div>

        <!-- Subscriptions Tab -->
        <div id="subscriptions" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Auto-Sync Subscriptions</span>
                    <button class="btn btn-sm btn-primary" onclick="loadSubscriptions()">Refresh</button>
                </div>
                <div class="card-body" id="subscriptions-container">
                    <div class="loading">Loading...</div>
                </div>
            </div>
        </div>

        <!-- Market Tab -->
        <div id="market" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>Market Offers</span>
                    <button class="btn btn-sm btn-primary" onclick="loadOffers()">Refresh</button>
                </div>
                <div class="card-body" id="offers-container">
                    <div class="loading">Loading...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Modal for details -->
    <div class="modal-overlay" id="modal-overlay" onclick="closeModal(event)">
        <div class="modal" onclick="event.stopPropagation()">
            <div class="modal-header">
                <h3 id="modal-title">Details</h3>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modal-body"></div>
        </div>
    </div>

    <script>
        // Tab switching
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab).classList.add('active');

                // Load data for the tab
                switch(tab.dataset.tab) {
                    case 'groups': loadGroups(); break;
                    case 'peers': loadPeers(); break;
                    case 'subscriptions': loadSubscriptions(); break;
                    case 'market': loadOffers(); break;
                    case 'knowledge': loadGroupSelect(); break;
                }
            });
        });

        // Modal functions
        function showModal(title, content) {
            document.getElementById('modal-title').textContent = title;
            document.getElementById('modal-body').innerHTML = content;
            document.getElementById('modal-overlay').classList.add('active');
        }

        function closeModal(event) {
            if (!event || event.target === document.getElementById('modal-overlay')) {
                document.getElementById('modal-overlay').classList.remove('active');
            }
        }

        // Format timestamp
        function formatTime(ms) {
            if (!ms) return '-';
            const date = new Date(ms);
            return date.toLocaleString();
        }

        // Format relative time
        function formatRelativeTime(ms) {
            if (!ms) return '-';
            const now = Date.now();
            const diff = now - ms;
            if (diff < 60000) return 'Just now';
            if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
            if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
            return Math.floor(diff / 86400000) + 'd ago';
        }

        // API calls
        async function fetchAPI(endpoint) {
            const response = await fetch(endpoint);
            return response.json();
        }

        // Load node info
        async function loadNodeInfo() {
            try {
                const data = await fetchAPI('/api/node');
                document.getElementById('node-id').textContent = data.node_id;
                document.getElementById('groups-count').textContent = data.groups_count;
                document.getElementById('offers-count').textContent = data.offers_count;
                document.getElementById('version').textContent = 'v' + data.version;
                document.getElementById('sign-pub').textContent = data.sign_pub;
                document.getElementById('enc-pub').textContent = data.enc_pub;
                document.getElementById('data-dir').textContent = data.data_dir;

                // Show security warning if auth is disabled
                const warningEl = document.getElementById('security-warning');
                if (!data.auth_enabled) {
                    warningEl.style.display = 'block';
                } else {
                    warningEl.style.display = 'none';
                }
            } catch (e) {
                console.error('Failed to load node info:', e);
            }
        }

        // Load groups
        async function loadGroups() {
            try {
                const data = await fetchAPI('/api/groups');
                const container = document.getElementById('groups-table-container');

                if (data.groups.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">📁</div>
                            <div>No groups found</div>
                        </div>`;
                    return;
                }

                container.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Group ID</th>
                                <th>Height</th>
                                <th>Members</th>
                                <th>Claims</th>
                                <th>Offers</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.groups.map(g => `
                                <tr>
                                    <td><strong>${escapeHtml(g.name)}</strong></td>
                                    <td><code>${g.group_id.substring(0, 12)}...</code></td>
                                    <td>${g.height}</td>
                                    <td>${g.member_count}</td>
                                    <td>${g.claims_count}</td>
                                    <td>${g.offers_count}</td>
                                    <td><button class="btn btn-sm btn-primary" onclick="showGroupDetails('${g.group_id}')">Details</button></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>`;
            } catch (e) {
                console.error('Failed to load groups:', e);
            }
        }

        // Show group details
        async function showGroupDetails(groupId) {
            try {
                const data = await fetchAPI('/api/group?id=' + groupId);
                const content = `
                    <div class="detail-row">
                        <div class="detail-label">Group ID</div>
                        <div class="detail-value"><code>${data.group_id}</code></div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Name</div>
                        <div class="detail-value">${escapeHtml(data.name)}</div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Currency</div>
                        <div class="detail-value">${data.currency}</div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Chain Height</div>
                        <div class="detail-value">${data.height}</div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Head Hash</div>
                        <div class="detail-value"><code>${data.head_hash}</code></div>
                    </div>
                    <h4 style="margin-top: 1rem; margin-bottom: 0.5rem;">Members (${data.members.length})</h4>
                    <table>
                        <thead><tr><th>Public Key</th><th>Role</th></tr></thead>
                        <tbody>
                            ${data.members.map(m => `
                                <tr>
                                    <td><code title="${m.pub_full}">${m.pub}</code></td>
                                    <td><span class="badge badge-info">${m.role}</span></td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                    ${data.balances.length > 0 ? `
                        <h4 style="margin-top: 1rem; margin-bottom: 0.5rem;">Balances</h4>
                        <table>
                            <thead><tr><th>Public Key</th><th>Amount</th></tr></thead>
                            <tbody>
                                ${data.balances.map(b => `
                                    <tr>
                                        <td><code title="${b.pub_full}">${b.pub}</code></td>
                                        <td>${b.amount} ${data.policy.currency}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    ` : ''}
                `;
                showModal('Group: ' + data.name, content);
            } catch (e) {
                console.error('Failed to load group details:', e);
            }
        }

        // Load group select for knowledge tab
        async function loadGroupSelect() {
            try {
                const data = await fetchAPI('/api/groups');
                const select = document.getElementById('group-select');
                select.innerHTML = '<option value="">Select a group...</option>' +
                    data.groups.map(g => `<option value="${g.group_id}">${escapeHtml(g.name)}</option>`).join('');
            } catch (e) {
                console.error('Failed to load groups for select:', e);
            }
        }

        // Load claims
        async function loadClaims() {
            const groupId = document.getElementById('group-select').value;
            const container = document.getElementById('claims-container');

            if (!groupId) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📚</div>
                        <div>Select a group to view its knowledge claims</div>
                    </div>`;
                return;
            }

            try {
                const data = await fetchAPI('/api/claims?group_id=' + groupId);

                if (data.claims.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">📝</div>
                            <div>No claims in this group yet</div>
                        </div>`;
                    return;
                }

                container.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>Hash</th>
                                <th>Text</th>
                                <th>Tags</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.claims.map(c => `
                                <tr>
                                    <td><code class="clickable" onclick="showClaimDetails('${c.hash_full}')">${c.hash}</code></td>
                                    <td class="claim-text" title="${escapeHtml(c.text_full)}">${escapeHtml(c.text)}</td>
                                    <td>${c.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</td>
                                    <td>${c.retracted ? '<span class="badge badge-danger">Retracted</span>' : '<span class="badge badge-success">Active</span>'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>`;
            } catch (e) {
                console.error('Failed to load claims:', e);
            }
        }

        // Show claim details
        function showClaimDetails(hash) {
            // This would need an API endpoint to get full claim details
            showModal('Claim Details', `<div class="detail-row"><div class="detail-label">Hash</div><div class="detail-value"><code>${hash}</code></div></div>`);
        }

        // Load peers
        async function loadPeers() {
            try {
                const data = await fetchAPI('/api/peers');
                const container = document.getElementById('peers-container');

                if (data.peers.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">🔗</div>
                            <div>No peers registered</div>
                            <div style="margin-top: 0.5rem; font-size: 0.875rem;">Use <code>lb peer-add</code> to register peers</div>
                        </div>`;
                    return;
                }

                container.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>Alias</th>
                                <th>Host</th>
                                <th>Port</th>
                                <th>Node ID</th>
                                <th>Last Seen</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.peers.map(p => `
                                <tr>
                                    <td>${p.alias || '-'}</td>
                                    <td><code>${p.host}</code></td>
                                    <td>${p.port}</td>
                                    <td><code>${p.node_id}</code></td>
                                    <td>${formatRelativeTime(p.last_seen_ms)}</td>
                                    <td>${p.last_error ?
                                        `<span class="badge badge-danger" title="${escapeHtml(p.last_error)}">Error</span>` :
                                        '<span class="badge badge-success">OK</span>'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>`;
            } catch (e) {
                console.error('Failed to load peers:', e);
            }
        }

        // Load subscriptions
        async function loadSubscriptions() {
            try {
                const data = await fetchAPI('/api/subscriptions');
                const container = document.getElementById('subscriptions-container');

                if (data.subscriptions.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">🔄</div>
                            <div>No subscriptions configured</div>
                            <div style="margin-top: 0.5rem; font-size: 0.875rem;">Use <code>lb subscribe</code> to set up auto-sync</div>
                        </div>`;
                    return;
                }

                container.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>Group ID</th>
                                <th>Peer</th>
                                <th>Interval</th>
                                <th>Last Sync</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.subscriptions.map(s => `
                                <tr>
                                    <td><code>${s.group_id.substring(0, 12)}...</code></td>
                                    <td><code>${s.peer_host}:${s.peer_port}</code></td>
                                    <td>${s.sync_interval_s}s</td>
                                    <td>${formatRelativeTime(s.last_sync_ms)}</td>
                                    <td>
                                        ${!s.enabled ? '<span class="badge badge-warning">Disabled</span>' :
                                          s.last_error ? `<span class="badge badge-danger" title="${escapeHtml(s.last_error)}">Error</span>` :
                                          '<span class="badge badge-success">Active</span>'}
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>`;
            } catch (e) {
                console.error('Failed to load subscriptions:', e);
            }
        }

        // Load offers
        async function loadOffers() {
            try {
                const data = await fetchAPI('/api/offers');
                const container = document.getElementById('offers-container');

                if (data.offers.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">🏪</div>
                            <div>No market offers available</div>
                            <div style="margin-top: 0.5rem; font-size: 0.875rem;">Use <code>lb market-pull</code> to fetch offers from peers</div>
                        </div>`;
                    return;
                }

                container.innerHTML = `
                    <table>
                        <thead>
                            <tr>
                                <th>Title</th>
                                <th>Price</th>
                                <th>Tags</th>
                                <th>Seller</th>
                                <th>Host</th>
                                <th>Created</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.offers.map(o => `
                                <tr>
                                    <td><strong>${escapeHtml(o.title)}</strong></td>
                                    <td>${o.price} ${o.currency}</td>
                                    <td>${o.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</td>
                                    <td><code>${o.seller}</code></td>
                                    <td><code>${o.host}:${o.port}</code></td>
                                    <td>${formatRelativeTime(o.created_ms)}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>`;
            } catch (e) {
                console.error('Failed to load offers:', e);
            }
        }

        // Escape HTML to prevent XSS
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Initial load
        loadNodeInfo();
    </script>
</body>
</html>'''


async def run_admin(
    node: "BatteryNode",
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    auth_password: Optional[str] = None
) -> None:
    """Run the admin panel server.

    Args:
        node: The BatteryNode to manage
        host: Host to bind to (default: 127.0.0.1 for localhost only)
        port: Port to listen on (default: 8080)
        auth_password: Optional password for HTTP Basic Auth. If set,
                      all requests require authentication with username "admin".
    """
    server = AdminServer(node, auth_password=auth_password)
    await server.start(host, port)
    print(f"Admin panel running at http://{host}:{port}")
    if auth_password:
        print("Authentication enabled (username: admin)")
    else:
        print("WARNING: No authentication configured - localhost access only recommended")
    print("Press Ctrl+C to stop")
    await server.serve_forever()
