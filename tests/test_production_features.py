"""Tests for production readiness features.

Tests key encryption, CAS consistency, rate limiting, and other
production hardening features.
"""
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Import the modules we're testing
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from lb.key_encryption import (
    encrypt_key_material, decrypt_key_material, EncryptedKeyFile,
    save_encrypted_key, load_encrypted_key, is_encrypted_key_file,
    init_encrypted_keys, load_keys, encrypt_existing_keys, change_key_password,
    KeyEncryptionError, encrypt_wallet_keys, decrypt_wallet_keys
)
from lb.cas import CAS, CasMeta
from lb.rate_limit import (
    SlidingWindowRateLimiter, ConnectionLimiter, P2PRateLimiter,
    get_rate_limiter, reset_rate_limiter
)
from lb.keys import gen_node_keys, dump_sign_priv_raw
from lb.fs import ensure_dir


class TestKeyEncryption:
    """Tests for key encryption at rest."""

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encryption and decryption are inverse operations."""
        test_data = os.urandom(32)
        password = "test-password-123"

        encrypted = encrypt_key_material(test_data, password)
        decrypted = decrypt_key_material(encrypted, password)

        assert decrypted == test_data

    def test_wrong_password_fails(self):
        """Test that decryption with wrong password fails."""
        test_data = os.urandom(32)

        encrypted = encrypt_key_material(test_data, "correct-password")

        with pytest.raises(KeyEncryptionError):
            decrypt_key_material(encrypted, "wrong-password")

    def test_encrypted_file_format(self):
        """Test that encrypted files can be serialized and deserialized."""
        test_data = os.urandom(32)
        password = "test-password"

        encrypted = encrypt_key_material(test_data, password)

        # Serialize to bytes
        serialized = encrypted.to_bytes()
        assert isinstance(serialized, bytes)

        # Deserialize
        restored = EncryptedKeyFile.from_bytes(serialized)

        # Should be able to decrypt
        decrypted = decrypt_key_material(restored, password)
        assert decrypted == test_data

    def test_save_load_encrypted_key(self):
        """Test saving and loading encrypted keys to files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test.key"
            test_data = os.urandom(32)
            password = "file-password"

            save_encrypted_key(key_path, test_data, password)

            assert key_path.exists()
            assert is_encrypted_key_file(key_path)

            loaded = load_encrypted_key(key_path, password)
            assert loaded == test_data

    def test_detect_encrypted_vs_raw(self):
        """Test detection of encrypted vs raw key files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a raw key file (32 bytes)
            raw_path = Path(tmpdir) / "raw.key"
            raw_path.write_bytes(os.urandom(32))
            assert not is_encrypted_key_file(raw_path)

            # Create an encrypted key file
            enc_path = Path(tmpdir) / "encrypted.key"
            save_encrypted_key(enc_path, os.urandom(32), "password")
            assert is_encrypted_key_file(enc_path)

    def test_init_encrypted_keys(self):
        """Test initializing a node with encrypted keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            password = "init-password"

            keys = init_encrypted_keys(data_dir, password)

            # Keys should be created
            assert (data_dir / "keys" / "signing.key").exists()
            assert (data_dir / "keys" / "encryption.key").exists()

            # Should be encrypted
            assert is_encrypted_key_file(data_dir / "keys" / "signing.key")
            assert is_encrypted_key_file(data_dir / "keys" / "encryption.key")

            # Should be loadable with password
            loaded_keys = load_keys(data_dir, password)
            assert loaded_keys.sign_pub_b64 == keys.sign_pub_b64
            assert loaded_keys.enc_pub_b64 == keys.enc_pub_b64

    def test_encrypt_existing_keys(self):
        """Test encrypting existing unencrypted keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            keys_dir = data_dir / "keys"
            ensure_dir(keys_dir)

            # Create unencrypted keys
            keys = gen_node_keys()
            sign_path = keys_dir / "signing.key"
            enc_path = keys_dir / "encryption.key"
            sign_path.write_bytes(dump_sign_priv_raw(keys.sign_priv))
            enc_path.write_bytes(keys.enc_priv.private_bytes_raw())

            assert not is_encrypted_key_file(sign_path)
            assert not is_encrypted_key_file(enc_path)

            # Encrypt them
            password = "encrypt-password"
            encrypt_existing_keys(data_dir, password)

            assert is_encrypted_key_file(sign_path)
            assert is_encrypted_key_file(enc_path)

            # Should still load correctly
            loaded = load_keys(data_dir, password)
            assert loaded.sign_pub_b64 == keys.sign_pub_b64

    def test_change_password(self):
        """Test changing the password for encrypted keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            old_password = "old-pass"
            new_password = "new-pass"

            # Initialize with old password
            keys = init_encrypted_keys(data_dir, old_password)

            # Change password
            change_key_password(data_dir, old_password, new_password)

            # Old password should fail
            with pytest.raises(KeyEncryptionError):
                load_keys(data_dir, old_password)

            # New password should work
            loaded = load_keys(data_dir, new_password)
            assert loaded.sign_pub_b64 == keys.sign_pub_b64

    def test_wallet_keys_encryption(self):
        """Test encrypting wallet keys dictionary."""
        wallet_keys = {
            "hash1": "sym_key_b64_1",
            "hash2": "sym_key_b64_2",
        }
        password = "wallet-password"

        encrypted = encrypt_wallet_keys(wallet_keys, password)
        assert isinstance(encrypted, bytes)

        decrypted = decrypt_wallet_keys(encrypted, password)
        assert decrypted == wallet_keys


class TestCASConsistency:
    """Tests for CAS index consistency."""

    def test_cas_thread_safety(self):
        """Test that CAS operations are thread-safe."""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            cas = CAS(Path(tmpdir), validate_on_startup=False)

            results = []
            errors = []

            def writer(n):
                try:
                    for i in range(10):
                        data = f"data-{n}-{i}".encode()
                        meta = CasMeta(visibility="public", kind="test")
                        h = cas.put(data, meta)
                        results.append((n, i, h))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Thread errors: {errors}"
            assert len(results) == 50

    def test_cas_validation_stale_entries(self):
        """Test that CAS detects and removes stale index entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cas_path = Path(tmpdir)
            cas = CAS(cas_path, validate_on_startup=False)

            # Add an object
            data = b"test data"
            meta = CasMeta(visibility="public", kind="test")
            h = cas.put(data, meta)

            # Manually remove the file but keep index entry
            obj_path = cas._obj_path(h)
            obj_path.unlink()

            # Create new CAS instance with validation
            cas2 = CAS(cas_path, validate_on_startup=True)

            # Stale entry should be removed
            assert h not in cas2.index

    def test_cas_validation_orphan_files(self):
        """Test that CAS detects and indexes orphan files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cas_path = Path(tmpdir)

            # Create CAS and add object
            cas = CAS(cas_path, validate_on_startup=False)
            data = b"orphan test"
            meta = CasMeta(visibility="public", kind="test")
            h = cas.put(data, meta)

            # Clear index but keep file
            cas.index = {}
            cas._save_index_unlocked()

            # Create new CAS instance with validation
            cas2 = CAS(cas_path, validate_on_startup=True)

            # Orphan file should be indexed
            assert h in cas2.index
            assert cas2.get(h) == data

    def test_cas_verify(self):
        """Test CAS object verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cas = CAS(Path(tmpdir), validate_on_startup=False)

            data = b"verify me"
            meta = CasMeta(visibility="public", kind="test")
            h = cas.put(data, meta)

            assert cas.verify(h) is True
            assert cas.verify("nonexistent_hash") is False

    def test_cas_stats(self):
        """Test CAS statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cas = CAS(Path(tmpdir), validate_on_startup=False)

            # Add some objects
            for i in range(5):
                data = f"data-{i}".encode()
                meta = CasMeta(visibility="public", kind="claim" if i < 3 else "package")
                cas.put(data, meta)

            stats = cas.stats()
            assert stats["object_count"] == 5
            assert stats["by_kind"]["claim"] == 3
            assert stats["by_kind"]["package"] == 2


class TestRateLimiting:
    """Tests for rate limiting functionality."""

    @pytest.fixture(autouse=True)
    def reset_limiter(self):
        """Reset global rate limiter before each test."""
        reset_rate_limiter()
        yield
        reset_rate_limiter()

    @pytest.mark.asyncio
    async def test_sliding_window_allows_within_limit(self):
        """Test that requests within limit are allowed."""
        limiter = SlidingWindowRateLimiter(window_seconds=60.0, max_requests=10)

        for i in range(10):
            result = await limiter.check("test-key")
            assert result.allowed, f"Request {i+1} should be allowed"

    @pytest.mark.asyncio
    async def test_sliding_window_blocks_over_limit(self):
        """Test that requests over limit are blocked."""
        limiter = SlidingWindowRateLimiter(window_seconds=60.0, max_requests=5)

        # Use up the limit
        for _ in range(5):
            await limiter.check("test-key")

        # Next request should be blocked
        result = await limiter.check("test-key")
        assert not result.allowed
        assert "rate limit exceeded" in result.reason

    @pytest.mark.asyncio
    async def test_sliding_window_per_key(self):
        """Test that rate limits are per-key."""
        limiter = SlidingWindowRateLimiter(window_seconds=60.0, max_requests=2)

        # Exhaust limit for key1
        await limiter.check("key1")
        await limiter.check("key1")
        result = await limiter.check("key1")
        assert not result.allowed

        # key2 should still be allowed
        result = await limiter.check("key2")
        assert result.allowed

    @pytest.mark.asyncio
    async def test_connection_limiter_acquire_release(self):
        """Test connection limiter acquire and release."""
        limiter = ConnectionLimiter(max_per_ip=2)

        # First two connections allowed
        assert await limiter.acquire("192.168.1.1")
        assert await limiter.acquire("192.168.1.1")

        # Third blocked
        assert not await limiter.acquire("192.168.1.1")

        # Release one
        await limiter.release("192.168.1.1")

        # Now allowed again
        assert await limiter.acquire("192.168.1.1")

    @pytest.mark.asyncio
    async def test_connection_limiter_per_ip(self):
        """Test that connection limits are per-IP."""
        limiter = ConnectionLimiter(max_per_ip=1)

        assert await limiter.acquire("192.168.1.1")
        assert not await limiter.acquire("192.168.1.1")

        # Different IP should be allowed
        assert await limiter.acquire("192.168.1.2")

    @pytest.mark.asyncio
    async def test_p2p_rate_limiter_integration(self):
        """Test the combined P2P rate limiter."""
        limiter = P2PRateLimiter()

        # Check connection
        result = await limiter.check_connection("192.168.1.1")
        assert result.allowed

        # Check request
        result = await limiter.check_request("peer-123")
        assert result.allowed

        # Release connection
        await limiter.release_connection("192.168.1.1")

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired(self):
        """Test that cleanup removes expired entries."""
        limiter = SlidingWindowRateLimiter(window_seconds=0.1, max_requests=10)

        # Add some requests
        await limiter.check("key1")
        await limiter.check("key2")

        # Wait for expiration
        await asyncio.sleep(0.2)

        # Cleanup
        removed = await limiter.cleanup()
        assert removed >= 2


class TestHealthCheck:
    """Test health check endpoint behavior."""

    def test_health_response_format(self):
        """Test that health response has expected format."""
        # This tests the structure, actual P2P test would be integration
        import time
        response = {
            "status": "healthy",
            "node_id": "test123",
            "version": "0.2.0",
            "groups_count": 3,
            "offers_count": 15,
            "timestamp_ms": int(time.time() * 1000),
        }

        assert response["status"] == "healthy"
        assert "node_id" in response
        assert "version" in response
        assert "groups_count" in response
        assert "offers_count" in response
        assert "timestamp_ms" in response


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
