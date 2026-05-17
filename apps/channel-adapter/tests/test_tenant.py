"""Tests for tenant_to_company_uuid — slug → stable UUIDv5 mapping."""

from __future__ import annotations

import pytest

from wormbase_channel_adapter.tenant import tenant_to_company_uuid


class TestTenantToCompanyUuid:
    def test_baseworm_is_stable(self) -> None:
        a = tenant_to_company_uuid("baseworm")
        b = tenant_to_company_uuid("baseworm")
        assert a == b

    def test_case_and_whitespace_normalized(self) -> None:
        assert tenant_to_company_uuid("baseworm") == tenant_to_company_uuid("BASEWORM")
        assert tenant_to_company_uuid("baseworm") == tenant_to_company_uuid(" baseworm ")

    def test_different_slugs_differ(self) -> None:
        assert tenant_to_company_uuid("baseworm") != tenant_to_company_uuid("acme")

    def test_empty_slug_rejected(self) -> None:
        with pytest.raises(ValueError):
            tenant_to_company_uuid("")
