# wormbase-tools-test

Pip-installable conformance harness for the WormBase Connector Protocol.

The WormBase data substrate accepts any class that satisfies the
``Connector`` Protocol — a five-method async surface (``authenticate``,
``discover``, ``profile``, ``sample``, ``watch``). Adding a connector
should be a class plus a registry entry; nothing else.

This package gives third-party connector authors a one-command
verification that their class behaves like every connector in the
WormBase catalog. It runs the same six invariants the W6.A4 conformance
suite asserts in the monorepo, but without requiring you to clone
WormBase or install anything beyond ``pytest``.

## Install

```bash
pip install wormbase-tools-test
```

## Use

Write your connector in a module that's importable from where you run
``pytest``:

```python
# my_connector.py
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class SecretBundle:
    payload: dict[str, Any]

@dataclass(frozen=True)
class AuthHandle:
    connector_kind: str
    handle_id: str
    extra: dict[str, Any] = field(default_factory=dict)

# ... ResourceProposal, Profile, Change ...

class MyConnector:
    kind = "my_kind"
    capability = {"discover", "profile", "sample"}
    classification_hints: list[str] = []
    status = "production"
    status_note = "Ships with my package."

    async def authenticate(self, secrets):
        if "token" not in secrets.payload:
            raise ValueError("my_kind requires {token: str}")
        return AuthHandle(connector_kind=self.kind, handle_id="x", extra={})

    # ... discover / profile / sample / watch ...
```

Then run the harness:

```bash
pytest --connector my_connector:MyConnector
```

Six tests run; if all pass, your class is Protocol-compliant.

## Six invariants

The harness asserts:

1. ``authenticate(valid)`` returns an AuthHandle with ``connector_kind``
   and ``handle_id`` populated.
2. ``authenticate(invalid)`` raises ``ValueError`` (or ``KeyError``).
3. ``discover()`` returns a list of ResourceProposals; ordering stable
   across two consecutive calls.
4. ``profile()`` returns a Profile with stable ``schema_hash`` across
   two calls for the same input.
5. ``sample()`` returns ``bytes``, deterministic for the same triple
   ``(handle, resource_id, n)``.
6. ``watch()`` returns an async iterator that exhausts cleanly without
   leaked coroutines.

## Custom secrets / known resource id

By default the harness probes secrets shapes and discovers a known
resource. Override via env vars or a fixture in your ``conftest.py``:

```python
# conftest.py
import pytest

@pytest.fixture
def connector_valid_secrets():
    from my_connector import SecretBundle
    return SecretBundle({"token": "real-test-token", "url": "..."})

@pytest.fixture
def connector_invalid_secrets():
    from my_connector import SecretBundle
    return SecretBundle({})  # missing required keys

@pytest.fixture
def connector_known_resource_id():
    return "my-known-resource"
```

If unset, the harness inspects what ``discover()`` returns for
``valid_secrets`` and uses the first proposal's ``resource_id`` for
profile/sample tests.

## Skeletal connectors

If your connector is not yet production-ready (``status='coming_soon'``
or ``status='preview'``), set ``connector_is_skeletal=True`` in your
fixture. The harness will then assert that ``profile``, ``sample``, and
``watch`` raise ``NotImplementedError`` rather than producing data.

## License

Apache 2.0. Same license as the WormBase monorepo.
