"""Offline checks for the update script's blacklist decisions."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

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


def test_overnight_fifth_run_targets_previous_trading_day():
    taipei = ZoneInfo("Asia/Taipei")
    assert update_market_data.get_target_market_date(
        datetime(2026, 10, 8, 1, 35, tzinfo=taipei)
    ).isoformat() == "2026-10-07"
    assert update_market_data.get_target_market_date(
        datetime(2026, 10, 7, 17, 35, tzinfo=taipei)
    ).isoformat() == "2026-10-07"
    assert update_market_data.get_target_market_date(
        datetime(2026, 10, 10, 1, 35, tzinfo=taipei)
    ).isoformat() == "2026-10-09"


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
