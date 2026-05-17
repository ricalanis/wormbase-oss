"""Custom exceptions for the ledger package."""


class LedgerError(Exception):
    """Base for all ledger errors."""


class HashChainBroken(LedgerError):
    """Raised when verify_chain finds a tamper or skipped entry."""


class WriteRolledBack(LedgerError):
    """Raised when an atomic write_primitive sequence was rolled back."""


class UnknownEntryType(LedgerError):
    """Raised when an entry kind is not in KIND_REGISTRY."""


class VerifyFailed(LedgerError):
    """Raised by write_primitive when the verify step returns passed=False."""
