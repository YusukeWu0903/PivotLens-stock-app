"""Offline checks for the update script's blacklist decisions."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import update_market_data


class FakeDataLoader:
    def taiwan_stock_info(self):
        return pd.DataFrame({
            "stock_id": ["1111", "2222", "3333", "4444"],
            "type": ["suspended", "delisted", "terminated", "listed"],
        })


def test_suspended_stocks_leave_permanent_blacklist(tmp_path, monkeypatch):
    blacklist = tmp_path / "blacklist.txt"
    blacklist.write_text("1111\n2222\n4444\n", encoding="utf-8")
    monkeypatch.setattr(update_market_data, "BLACKLIST_FILE", str(blacklist))
    monkeypatch.setattr(
        update_market_data, "TEMP_BLACKLIST_FILE", str(tmp_path / "missing_temp.txt")
    )

    blocked = update_market_data.smart_blacklist_manager(FakeDataLoader())

    assert blocked == {"2222", "3333", "4444"}
    assert set(blacklist.read_text(encoding="utf-8").splitlines()) == blocked


class MarketResponse:
    def __init__(self, days):
        self.days = days

    def raise_for_status(self):
        pass

    def json(self):
        return {"stat": "OK", "data": [[f"{d.year - 1911}/{d.month:02}/{d.day:02}"] for d in self.days]}


@pytest.mark.parametrize(("clock", "published", "expected"), [
    # Normal evening and the existing overnight fifth run.
    ((2026, 10, 7, 17, 35), [date(2026, 10, 7)], date(2026, 10, 7)),
    ((2026, 10, 8, 1, 35), [date(2026, 10, 7), date(2026, 10, 8)], date(2026, 10, 7)),
    ((2026, 10, 10, 1, 35), [date(2026, 10, 9)], date(2026, 10, 9)),
    ((2026, 10, 11, 17, 35), [date(2026, 10, 9)], date(2026, 10, 9)),
    # The holiday itself and the following overnight batch.
    ((2026, 12, 25, 17, 35), [date(2026, 12, 24)], date(2026, 12, 24)),
    ((2026, 12, 26, 1, 35), [date(2026, 12, 24)], date(2026, 12, 24)),
    # Typhoon Kong-rey closed the market on 2024-10-31.
    ((2024, 10, 31, 17, 35), [date(2024, 10, 30)], date(2024, 10, 30)),
    # First of the month: the first published row is after cutoff.
    ((2026, 6, 1, 17, 35), [date(2026, 6, 2), date(2026, 5, 29)], date(2026, 5, 29)),
])
def test_target_uses_only_confirmed_trades(monkeypatch, clock, published, expected):
    def market_summary(url, *, params, headers, timeout):
        assert url == update_market_data.TWSE_DAILY_MARKET_URLS[0]
        month = params["date"][:6]
        return MarketResponse([d for d in published if d.strftime("%Y%m") == month])

    monkeypatch.setattr(update_market_data.requests, "get", market_summary)
    actual = update_market_data.get_target_market_date(datetime(*clock, tzinfo=ZoneInfo("Asia/Taipei")))
    assert actual == expected


def test_invalid_primary_response_uses_alternate_official_endpoint(monkeypatch):
    target = date(2026, 12, 24)
    urls = []

    def market_summary(url, **kwargs):
        urls.append(url)
        return MarketResponse([target] if len(urls) == 2 else [])

    monkeypatch.setattr(update_market_data.requests, "get", market_summary)
    now = datetime(2026, 12, 25, 17, 35, tzinfo=ZoneInfo("Asia/Taipei"))
    assert update_market_data.get_target_market_date(now) == target
    assert urls == list(update_market_data.TWSE_DAILY_MARKET_URLS)


def test_market_source_unavailable_keeps_cache_and_does_not_login(tmp_path, monkeypatch):
    cache = tmp_path / "market_cache"
    cache.mkdir()
    old_data = cache / "previous.parquet"
    old_data.write_bytes(b"existing market data")
    watchlist = tmp_path / "watchlist.txt"
    watchlist.write_text("existing entry\n", encoding="utf-8")
    monkeypatch.setattr(update_market_data, "CACHE_DIR", str(cache))
    monkeypatch.setattr(update_market_data, "WATCHLIST_FILE", str(watchlist))
    monkeypatch.setattr(update_market_data, "FINMIND_TOKEN", "offline-placeholder")

    def unavailable(*args, **kwargs):
        raise update_market_data.requests.Timeout("test timeout")

    monkeypatch.setattr(update_market_data.requests, "get", unavailable)
    monkeypatch.setattr(update_market_data, "DataLoader", lambda: pytest.fail("Must stop before FinMind"))
    update_market_data.update_market_cache()

    assert old_data.read_bytes() == b"existing market data"
    assert watchlist.read_text(encoding="utf-8") == "existing entry\n"


@pytest.mark.parametrize("data_available", [False, True])
def test_fallback_only_fetches_lagging_stock_through_previous_session(tmp_path, monkeypatch, data_available):
    cutoff = date(2026, 12, 25)
    target = date(2026, 12, 24)
    watchlist = tmp_path / "watchlist.txt"
    cache_dir = tmp_path / "market_cache"
    calls = []
    monkeypatch.setattr(update_market_data, "CHECKPOINT_FILE", str(tmp_path / "checkpoint.parquet"))
    monkeypatch.setattr(update_market_data, "CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(update_market_data, "FINMIND_TOKEN", "offline-placeholder")
    monkeypatch.setattr(update_market_data, "WATCHLIST_FILE", str(watchlist))
    monkeypatch.setattr(update_market_data, "STOCK_NAMES_FILE", str(tmp_path / "stock_names.json"))
    monkeypatch.setattr(update_market_data, "EMERGING_LIST_FILE", str(tmp_path / "emerging.txt"))
    monkeypatch.setattr(update_market_data, "market_date_cutoff", lambda now: cutoff)
    monkeypatch.setattr(update_market_data, "get_target_market_date", lambda now: target)
    monkeypatch.setattr(update_market_data, "smart_blacklist_manager", lambda _: set())
    cache = pd.DataFrame({
        "Stock_ID": ["TAIEX", "TPEx", "1111", "2222"],
        "Date": pd.to_datetime([target, target, target, date(2026, 12, 23)]),
        "Volume": [200, 100, 60, 50],
    })
    monkeypatch.setattr(update_market_data, "read_existing_cache", lambda: cache)

    class Loader:
        def login_by_token(self, api_token):
            pass

        def taiwan_stock_info(self):
            return pd.DataFrame({
                "stock_id": ["1111", "2222"],
                "stock_name": ["A", "B"],
                "type": ["listed", "otc"],
                "industry_category": ["other", "other"],
            })

    def fetch(loader, sid, start, end):
        calls.append((sid, start, end))
        if data_available:
            return pd.DataFrame({"stock_id": [sid], "date": [end], "Trading_Volume": [55]})
        return None

    monkeypatch.setattr(update_market_data, "DataLoader", Loader)
    monkeypatch.setattr(update_market_data, "fetch_single_stock_daily", fetch)
    update_market_data.update_market_cache()

    assert calls == [("2222", "2026-12-24", "2026-12-24")]
    assert not watchlist.exists()
    if data_available:
        saved = pd.read_parquet(cache_dir)
        assert set(saved["Stock_ID"]) == {"TAIEX", "TPEx", "1111", "2222"}
        assert saved.loc[saved["Stock_ID"] == "2222", "Date"].max().date() == target


def test_request_spacing_is_applied_before_each_fetch(monkeypatch):
    clock = [100.0]
    waits = []
    monkeypatch.setattr(update_market_data, "REQUEST_DELAY", 3.0)
    monkeypatch.setattr(update_market_data, "_next_request_at", 0.0)
    monkeypatch.setattr(update_market_data.time, "monotonic", lambda: clock[0])

    def advance(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(update_market_data.time, "sleep", advance)
    update_market_data.wait_for_request_slot()
    update_market_data.wait_for_request_slot()
    assert waits == [3.0]
    assert update_market_data._next_request_at == 106.0

@pytest.mark.parametrize("failure", ["write", "switch"])
def test_interrupted_publish_preserves_previous_snapshot(tmp_path, monkeypatch, failure):
    from pathlib import Path
    cache = tmp_path / "market_cache"
    old = pd.DataFrame({"Stock_ID": ["2330"], "Date": pd.to_datetime(["2026-10-07"]),
                        "Close": [100.], "Tier": ["tier1_hot"]})
    old.to_parquet(cache, partition_cols=["Tier"], index=False)
    new = old.assign(Close=120.)
    if failure == "write":
        def interrupted(*args, **kwargs):
            raise OSError("injected write failure")
        monkeypatch.setattr(pd.DataFrame, "to_parquet", interrupted)
    else:
        rename = Path.rename
        def interrupted(path, destination):
            if path.name == "snapshot":
                raise OSError("injected switch failure")
            return rename(path, destination)
        monkeypatch.setattr(Path, "rename", interrupted)
    with pytest.raises(OSError, match="injected"):
        update_market_data.publish_market_cache(new, cache)
    assert pd.read_parquet(cache)["Close"].tolist() == [100.]
