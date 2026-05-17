"""CredentialBroker exception hierarchy."""
from __future__ import annotations


class CredentialBrokerError(Exception):
    """Base class for all CredentialBroker errors."""


class AuthenticationError(CredentialBrokerError):
    """Raised when the broker cannot authenticate against its backing store
    (e.g. invalid Vault token, missing file-store dir, expired KMS handle).
    """


class RevokedTokenError(CredentialBrokerError):
    """Raised when a token is presented after revocation."""
