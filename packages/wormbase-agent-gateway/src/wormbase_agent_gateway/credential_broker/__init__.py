"""CredentialBroker — unified data + model credential surface.

Per Wave 2 plan §Task 2. Two implementations satisfy the
`CredentialBroker` Protocol:

- `EnvCredentialBroker` — file-based, hermetic, used in unit tests and local dev
- `VaultCredentialBroker` — production-grade, productionized from the S4 spike
"""
from __future__ import annotations

from .env import EnvCredentialBroker
from .errors import AuthenticationError, CredentialBrokerError, RevokedTokenError
from .protocol import CredentialBroker
from .types import AccountHandle, DataScope, ModelScope, ScopedToken
from .vault import VaultCredentialBroker

__all__ = [
    "AccountHandle",
    "AuthenticationError",
    "CredentialBroker",
    "CredentialBrokerError",
    "DataScope",
    "EnvCredentialBroker",
    "ModelScope",
    "RevokedTokenError",
    "ScopedToken",
    "VaultCredentialBroker",
]
