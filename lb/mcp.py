from __future__ import annotations

import asyncio
import base64
import json
import sys
from typing import Any, Dict, List

from . import __version__
from .node import BatteryNode, NodeError


class MCPParamError(Exception):
    """Error for missing or invalid MCP parameters."""
    def __init__(self, field: str, message: str = "is required"):
        self.field = field
        super().__init__(f"{field} {message}")


def _require(params: Dict[str, Any], field: str) -> Any:
    """Get a required parameter, raising MCPParamError if missing."""
    if field not in params:
        raise MCPParamError(field)
    return params[field]


def _require_str(params: Dict[str, Any], field: str) -> str:
    """Get a required string parameter."""
    value = _require(params, field)
    if not isinstance(value, str):
        raise MCPParamError(field, "must be a string")
    return value


def _require_int(params: Dict[str, Any], field: str) -> int:
    """Get a required integer parameter."""
    value = _require(params, field)
    try:
        return int(value)
    except (ValueError, TypeError):
        raise MCPParamError(field, "must be an integer")


def _ok(rid: Any, result: Any) -> None:
    sys.stdout.write(json.dumps({"id": rid, "result": result, "error": None}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _err(rid: Any, code: str, message: str) -> None:
    sys.stdout.write(json.dumps({"id": rid, "result": None, "error": {"code": code, "message": message}}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_mcp(data_dir: str) -> None:
    node = BatteryNode.load(data_dir)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            _err(None, "bad_json", str(e))
            continue

        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        try:
            if method == "initialize":
                _ok(rid, {"node_id": node.node_id, "sign_pub": node.keys.sign_pub_b64, "enc_pub": node.keys.enc_pub_b64, "version": __version__})
            elif method == "list_groups":
                gs = []
                for gid, g in node.groups.items():
                    gs.append({"group_id": gid, "name": g.chain.state.policy.name, "currency": g.chain.state.policy.currency})
                _ok(rid, {"groups": gs})
            elif method == "publish_claim":
                gid = params["group_id"]
                text = params["text"]
                tags = list(params.get("tags", []))
                h = node.publish_claim(gid, text, tags)
                _ok(rid, {"claim_hash": h})
            elif method == "retract_claim":
                node.retract_claim(params["group_id"], params["claim_hash"])
                _ok(rid, {"ok": True})
            elif method == "submit_experience":
                gid = params["group_id"]
                exp = params.get("experience", {}) or {}
                h = node.submit_experience(gid, exp)
                _ok(rid, {"experience_hash": h})
            elif method == "compile_context":
                gid = params["group_id"]
                q = params["query"]
                top_k = int(params.get("top_k", 8))
                text, chosen = node.compile_context(gid, q, top_k=top_k)
                _ok(rid, {"context": text, "claim_hashes": chosen})
            elif method == "create_offer":
                gid = params["group_id"]
                title = params["title"]
                text = params["text"]
                price = int(params["price"])
                tags = list(params.get("tags", []))
                host = str(params.get("announce_host", "127.0.0.1"))
                port = int(params.get("announce_port", 0))
                offer_id, package_hash = node.create_offer(gid, title=title, text=text, price=price, tags=tags, announce_host=host, announce_port=port)
                _ok(rid, {"offer_id": offer_id, "package_hash": package_hash})
            elif method == "list_offers":
                _ok(rid, {"offers": [o.to_dict() for o in node.list_offers()]})
            elif method == "market_pull":
                host = params["host"]
                port = int(params["port"])
                n = asyncio.run(node.pull_market_offers_from_peer(host, port))
                _ok(rid, {"imported": n})
            elif method == "sync_group":
                host = params["host"]
                port = int(params["port"])
                gid = params["group_id"]
                replaced = asyncio.run(node.sync_group_from_peer(host, port, gid))
                _ok(rid, {"replaced": replaced})
            elif method == "purchase_offer":
                host = params["host"]
                port = int(params["port"])
                offer_id = params["offer_id"]
                package_hash, pt = asyncio.run(node.purchase_offer_from_peer(host=host, port=port, offer_id=offer_id))
                # attempt to decode json package
                try:
                    pkg = json.loads(pt.decode("utf-8"))
                except Exception:
                    pkg = {"raw_b64": base64.b64encode(pt).decode("ascii")}
                _ok(rid, {"package_hash": package_hash, "package": pkg})
            else:
                _err(rid, "not_found", f"unknown method {method}")
        except MCPParamError as e:
            _err(rid, "bad_request", str(e))
        except KeyError as e:
            _err(rid, "bad_request", f"missing field {e}")
        except NodeError as e:
            _err(rid, "node_error", str(e))
        except Exception as e:
            _err(rid, "internal", str(e))
