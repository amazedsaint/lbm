"""Base exception classes for Learning Battery Market.

All module-specific exceptions inherit from LBError for unified error handling.
"""
from __future__ import annotations


class LBError(Exception):
    """Base exception for all Learning Battery Market errors.

    This provides a common base class for catching any LB-related error:
        try:
            node.some_operation()
        except LBError as e:
            handle_any_lb_error(e)
    """
    pass


class LBNetworkError(LBError):
    """Network-related errors (connection failures, timeouts)."""
    pass


class LBSecurityError(LBError):
    """Security-related errors (authentication, authorization, crypto)."""
    pass


class LBValidationError(LBError):
    """Input validation errors."""
    pass


class LBStorageError(LBError):
    """Storage-related errors (CAS, filesystem)."""
    pass
