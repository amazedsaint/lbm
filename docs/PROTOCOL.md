# Protocol

## Wire framing
TCP stream with 4-byte big-endian length prefix. Payload is:
- handshake frames (plaintext JSON)
- encrypted frames (JSON envelope with ciphertext)

## Handshake
Client -> Server: `hello`
Fields:
- v: protocol version
- sign_pub: b64
- enc_pub: b64
- eph_pub: b64 (X25519 ephemeral)
- nonce: b64 (32 bytes)
- ts: int
- sig: Ed25519 signature over canonical JSON without sig

Server -> Client: `welcome`
Fields:
- v, sign_pub, enc_pub, eph_pub, nonce, ts
- client_hello_hash: sha256 hex
- sig: signature over canonical JSON without sig

Session keys:
- shared = X25519(eph_priv, peer_eph_pub)
- transcript_hash = sha256(hello||welcome)
- HKDF-SHA256(shared, salt=transcript_hash, info="lb-p2p-v1", len=64)
- split into send_key/recv_key by direction

## Encrypted frame envelope
JSON:
- ctr: int (monotonic)
- ct: b64 (ciphertext)
- aad: implicit (proto + ctr)

Nonce:
- 4 bytes prefix from transcript hash + 8 byte ctr

## RPC messages
Plaintext inside encryption:
Request:
- id: int
- method: str
- params: object

Response:
- id: int
- result: object | null
- error: {code, message} | null

Methods:
- ping
- node_info
- group_get_snapshot (member-only)
- group_push_snapshot (member-only)
- cas_get (public or member-only depending on meta)
- cas_put (member-only for group objects)
- market_list_offers (public)
- market_announce_offers (public, signature-verified)
- market_purchase (public, but enforces group rules)
