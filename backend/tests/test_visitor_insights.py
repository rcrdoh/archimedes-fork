"""Tests for the visitor-insights instrument — geography + device class (#787).

Hermetic — mocks the Redis boundary. Covers the store (record + read + fail-safe),
country normalization, the device-class derivation (CloudFront headers + UA
fallback), and the humans-only capture gate.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from archimedes.api.visitor_insights import _device_class, record_visitor_insight
from archimedes.services.visitor_insights_store import (
    DEVICE_CLASSES,
    VisitorInsightsStore,
    _norm_country,
)


def _mock_redis(pfcounts=None, members=None):
    pipe = MagicMock()
    pipe.pfadd = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.sadd = MagicMock(return_value=pipe)
    pipe.pfcount = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=pfcounts if pfcounts is not None else [])
    r = MagicMock()
    r.pipeline = MagicMock(return_value=pipe)
    r.smembers = AsyncMock(return_value=members or set())
    return r, pipe


def _req(headers=None):
    return SimpleNamespace(headers=headers or {}, state=SimpleNamespace(visitor_id="vid-1"))


# ─── country normalization ───────────────────────────────────────────────


def test_norm_country_valid():
    assert _norm_country("us") == "US"
    assert _norm_country("DE") == "DE"


def test_norm_country_invalid_or_missing():
    assert _norm_country(None) == "ZZ"
    assert _norm_country("") == "ZZ"
    assert _norm_country("USA") == "ZZ"  # not 2 letters
    assert _norm_country("1!") == "ZZ"


# ─── device class derivation ─────────────────────────────────────────────


def test_device_class_cloudfront_headers_win():
    assert _device_class(_req({"cloudfront-is-mobile-viewer": "true"})) == "mobile"
    assert _device_class(_req({"cloudfront-is-tablet-viewer": "true"})) == "tablet"
    assert _device_class(_req({"cloudfront-is-desktop-viewer": "true"})) == "desktop"
    assert _device_class(_req({"cloudfront-is-smarttv-viewer": "true"})) == "tv"


def test_device_class_ua_fallback():
    assert _device_class(_req({"user-agent": "Mozilla/5.0 (iPhone) Mobile"})) == "mobile"
    assert _device_class(_req({"user-agent": "Mozilla/5.0 (iPad)"})) == "tablet"
    assert _device_class(_req({"user-agent": "Mozilla/5.0 (Macintosh)"})) == "desktop"
    assert _device_class(_req({})) == "unknown"


# ─── store record + read ─────────────────────────────────────────────────


async def test_record_pfadds_country_and_device_and_indexes():
    store = VisitorInsightsStore()
    r, pipe = _mock_redis()
    store._get_redis = AsyncMock(return_value=r)

    await store.record("US", "mobile", "vid-1")

    # 4 pfadds: country total + device total + country day + device day
    assert pipe.pfadd.call_count == 4
    # country code indexed for enumeration on read
    pipe.sadd.assert_called_once()
    assert pipe.sadd.call_args.args[1] == "US"
    pipe.execute.assert_awaited_once()


async def test_record_normalizes_bad_country_and_device():
    store = VisitorInsightsStore()
    r, pipe = _mock_redis()
    store._get_redis = AsyncMock(return_value=r)
    await store.record("not-a-country", "watch", "vid-1")
    # bad country → ZZ, bad device → unknown (in the key names)
    keys = [c.args[0] for c in pipe.pfadd.call_args_list]
    assert any(k.endswith(":ZZ") for k in keys)
    assert any(":device:" in k and k.endswith(":unknown") for k in keys)


async def test_record_noop_without_visitor_id():
    store = VisitorInsightsStore()
    r, _ = _mock_redis()
    store._get_redis = AsyncMock(return_value=r)
    await store.record("US", "mobile", "")
    r.pipeline.assert_not_called()


async def test_record_fails_open():
    store = VisitorInsightsStore()
    store._get_redis = AsyncMock(side_effect=ConnectionError("down"))
    await store.record("US", "mobile", "vid-1")  # must not raise


async def test_get_insights_reads_countries_and_devices():
    store = VisitorInsightsStore()
    # smembers → {US, DE}; first pipeline (countries) → [10, 4]; second (devices, 5
    # classes in DEVICE_CLASSES order) → [7, 1, 6, 0, 0]
    r, pipe = _mock_redis(members={"US", "DE"})
    pipe.execute = AsyncMock(side_effect=[[10, 4], [7, 1, 6, 0, 0]])
    store._get_redis = AsyncMock(return_value=r)

    countries, devices = await store.get_insights()

    assert countries == {"DE": 10, "US": 4}  # sorted(codes) = [DE, US]
    assert devices == dict(zip(DEVICE_CLASSES, [7, 1, 6, 0, 0], strict=False))


async def test_get_insights_fails_open():
    store = VisitorInsightsStore()
    store._get_redis = AsyncMock(side_effect=ConnectionError("down"))
    countries, devices = await store.get_insights()
    assert countries == {}
    assert devices == dict.fromkeys(DEVICE_CLASSES, 0)


# ─── capture gate (humans only) ──────────────────────────────────────────


async def test_capture_skips_agents(monkeypatch):
    calls = {"n": 0}

    class FakeStore:
        async def record(self, *a):
            calls["n"] += 1

        async def close(self):
            pass

    monkeypatch.setattr("archimedes.services.visitor_insights_store.VisitorInsightsStore", FakeStore)
    await record_visitor_insight(_req({"cloudfront-viewer-country": "US"}), is_agent=True)
    assert calls["n"] == 0  # agents are NOT recorded — keep geography human-only


async def test_capture_records_humans(monkeypatch):
    recorded = {}

    class FakeStore:
        async def record(self, country, device, vid):
            recorded["args"] = (country, device, vid)

        async def close(self):
            pass

    monkeypatch.setattr("archimedes.services.visitor_insights_store.VisitorInsightsStore", FakeStore)
    req = _req({"cloudfront-viewer-country": "DE", "cloudfront-is-mobile-viewer": "true"})
    await record_visitor_insight(req, is_agent=False)
    assert recorded["args"] == ("DE", "mobile", "vid-1")
