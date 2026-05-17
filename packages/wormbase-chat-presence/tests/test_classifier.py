"""Block D tests: semantic classifier."""

from __future__ import annotations

import pytest

from wormbase_chat_presence.classifier import (
    OllamaCloudClassifier,
    StubClassifier,
    evaluate_on_seed_bank,
)


@pytest.fixture
def stub() -> StubClassifier:
    return StubClassifier(domain="saas")


# -- targeted unit tests ---------------------------------------------


async def test_question_about_known_metric(stub: StubClassifier) -> None:
    res = await stub.classify("what's churn this month?", {})
    assert "churn" in res.concepts
    assert res.event_type == "question"
    assert res.confidence >= 0.8


async def test_credential_offer_in_dm(stub: StubClassifier) -> None:
    res = await stub.classify(
        "our postgres is at postgres://reader:secret@db/prod",
        {"source": "dm"},
    )
    assert res.event_type == "credential_offer"
    assert res.confidence >= 0.9


async def test_file_reference_detected(stub: StubClassifier) -> None:
    res = await stub.classify("subscriptions.csv uploaded", {})
    assert res.event_type == "file_reference"


async def test_off_topic_low_confidence(stub: StubClassifier) -> None:
    res = await stub.classify("lunch in 10?", {})
    # "lunch" has a question hint but no concept, so confidence is low.
    assert res.confidence < 0.5


async def test_empty_text_other(stub: StubClassifier) -> None:
    res = await stub.classify("", {})
    assert res.event_type == "other"
    assert res.confidence == 0.0


async def test_data_mention_recognized(stub: StubClassifier) -> None:
    res = await stub.classify("we should pull from Stripe", {})
    assert "stripe" in res.concepts
    assert res.event_type == "data_mention"


# -- accuracy gate ---------------------------------------------------


async def test_classifier_accuracy_on_seed_bank_ge_80(stub: StubClassifier) -> None:
    report = await evaluate_on_seed_bank(stub)
    assert report["accuracy"] >= 0.80, report


# -- ollama cloud safety -------------------------------------------


async def test_ollama_classifier_returns_other_without_api_key() -> None:
    cls = OllamaCloudClassifier(api_key="")  # explicit empty
    res = await cls.classify("anything", {})
    assert res.event_type == "other"
    assert res.confidence == 0.0
