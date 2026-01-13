"""Input validation for Learning Battery Market.

Provides validation functions and size limits for all user inputs.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

from .config import get_config


def _get_validation_config():
    """Get validation config with lazy loading."""
    return get_config().validation


# Pattern for valid identifiers (alphanumeric, colons, dashes, underscores)
VALID_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9:_-]+$')
VALID_HEX_PATTERN = re.compile(r'^[a-fA-F0-9]+$')


class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def validate_group_name(name: str) -> str:
    """Validate and normalize a group name.

    Args:
        name: Group name to validate

    Returns:
        Normalized group name

    Raises:
        ValidationError: If name is invalid
    """
    if not isinstance(name, str):
        raise ValidationError("group_name", "must be a string")

    name = name.strip()

    if not name:
        raise ValidationError("group_name", "cannot be empty")

    max_len = _get_validation_config().max_group_name_length
    if len(name) > max_len:
        raise ValidationError(
            "group_name",
            f"exceeds maximum length of {max_len} characters"
        )

    if not VALID_NAME_PATTERN.match(name):
        raise ValidationError(
            "group_name",
            "must contain only alphanumeric characters, colons, dashes, and underscores"
        )

    return name


def validate_claim_text(text: str) -> str:
    """Validate claim text.

    Args:
        text: Claim text to validate

    Returns:
        Validated text

    Raises:
        ValidationError: If text is invalid
    """
    if not isinstance(text, str):
        raise ValidationError("claim_text", "must be a string")

    if not text.strip():
        raise ValidationError("claim_text", "cannot be empty")

    max_len = _get_validation_config().max_claim_text_length
    if len(text) > max_len:
        raise ValidationError(
            "claim_text",
            f"exceeds maximum length of {max_len} characters"
        )

    return text


def validate_offer_title(title: str) -> str:
    """Validate offer title.

    Args:
        title: Offer title to validate

    Returns:
        Validated title

    Raises:
        ValidationError: If title is invalid
    """
    if not isinstance(title, str):
        raise ValidationError("offer_title", "must be a string")

    title = title.strip()

    if not title:
        raise ValidationError("offer_title", "cannot be empty")

    max_len = _get_validation_config().max_offer_title_length
    if len(title) > max_len:
        raise ValidationError(
            "offer_title",
            f"exceeds maximum length of {max_len} characters"
        )

    return title


def validate_offer_description(description: str) -> str:
    """Validate offer description.

    Args:
        description: Offer description to validate

    Returns:
        Validated description

    Raises:
        ValidationError: If description is invalid
    """
    if not isinstance(description, str):
        raise ValidationError("offer_description", "must be a string")

    max_len = _get_validation_config().max_offer_description_length
    if len(description) > max_len:
        raise ValidationError(
            "offer_description",
            f"exceeds maximum length of {max_len} characters"
        )

    return description


def validate_tags(tags: List[str]) -> List[str]:
    """Validate a list of tags.

    Args:
        tags: List of tags to validate

    Returns:
        Validated and normalized tags

    Raises:
        ValidationError: If tags are invalid
    """
    cfg = _get_validation_config()
    if not isinstance(tags, list):
        raise ValidationError("tags", "must be a list")

    if len(tags) > cfg.max_tags_per_item:
        raise ValidationError(
            "tags",
            f"exceeds maximum of {cfg.max_tags_per_item} tags"
        )

    validated = []
    for i, tag in enumerate(tags):
        if not isinstance(tag, str):
            raise ValidationError(f"tags[{i}]", "must be a string")

        tag = tag.strip().lower()

        if not tag:
            continue  # Skip empty tags

        if len(tag) > cfg.max_tag_length:
            raise ValidationError(
                f"tags[{i}]",
                f"exceeds maximum length of {cfg.max_tag_length} characters"
            )

        if not VALID_NAME_PATTERN.match(tag):
            raise ValidationError(
                f"tags[{i}]",
                "must contain only alphanumeric characters, colons, dashes, and underscores"
            )

        validated.append(tag)

    return validated


def validate_price(price: Any) -> int:
    """Validate a price value.

    Args:
        price: Price to validate

    Returns:
        Validated price as integer

    Raises:
        ValidationError: If price is invalid
    """
    try:
        price = int(price)
    except (TypeError, ValueError):
        raise ValidationError("price", "must be an integer")

    if price < 0:
        raise ValidationError("price", "cannot be negative")

    return price


def validate_amount(amount: Any, field_name: str = "amount") -> int:
    """Validate an amount value.

    Args:
        amount: Amount to validate
        field_name: Name of field for error messages

    Returns:
        Validated amount as integer

    Raises:
        ValidationError: If amount is invalid
    """
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise ValidationError(field_name, "must be an integer")

    if amount < 0:
        raise ValidationError(field_name, "cannot be negative")

    return amount


def validate_hex_string(value: str, field_name: str, min_length: int = 1) -> str:
    """Validate a hexadecimal string.

    Args:
        value: String to validate
        field_name: Name of field for error messages
        min_length: Minimum required length

    Returns:
        Validated lowercase hex string

    Raises:
        ValidationError: If value is invalid
    """
    if not isinstance(value, str):
        raise ValidationError(field_name, "must be a string")

    value = value.lower().strip()

    if len(value) < min_length:
        raise ValidationError(
            field_name,
            f"must be at least {min_length} characters"
        )

    if not VALID_HEX_PATTERN.match(value):
        raise ValidationError(field_name, "must be a valid hexadecimal string")

    return value


def validate_public_key(pub_b64: str, field_name: str = "public_key") -> str:
    """Validate a base64-encoded public key.

    Args:
        pub_b64: Base64-encoded public key
        field_name: Name of field for error messages

    Returns:
        Validated public key string

    Raises:
        ValidationError: If key is invalid
    """
    if not isinstance(pub_b64, str):
        raise ValidationError(field_name, "must be a string")

    pub_b64 = pub_b64.strip()

    if not pub_b64:
        raise ValidationError(field_name, "cannot be empty")

    # Basic base64 validation
    try:
        import base64
        decoded = base64.b64decode(pub_b64, validate=True)
        if len(decoded) != 32:
            raise ValidationError(field_name, "must be 32 bytes when decoded")
    except Exception as e:
        if isinstance(e, ValidationError):
            raise
        raise ValidationError(field_name, "must be valid base64")

    return pub_b64


def validate_package_content(content: bytes) -> bytes:
    """Validate package content size.

    Args:
        content: Package content bytes

    Returns:
        Validated content

    Raises:
        ValidationError: If content is too large
    """
    if not isinstance(content, bytes):
        raise ValidationError("package_content", "must be bytes")

    max_size = _get_validation_config().max_package_size_bytes
    if len(content) > max_size:
        raise ValidationError(
            "package_content",
            f"exceeds maximum size of {max_size} bytes"
        )

    return content


def validate_experience(experience: dict) -> dict:
    """Validate experience data.

    Args:
        experience: Experience dictionary

    Returns:
        Validated experience

    Raises:
        ValidationError: If experience is invalid
    """
    if not isinstance(experience, dict):
        raise ValidationError("experience", "must be a dictionary")

    import json
    try:
        serialized = json.dumps(experience, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise ValidationError("experience", f"must be JSON-serializable: {e}")

    max_size = _get_validation_config().max_experience_size_bytes
    if len(serialized) > max_size:
        raise ValidationError(
            "experience",
            f"exceeds maximum size of {max_size} bytes"
        )

    return experience
