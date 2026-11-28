"""Verify both visible lists against partially refreshed market data."""
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.test_screening import confirmed_history


def test_only_current_signals_appear_in_their_respective_lists(monkeypatch):
    history = confirmed_history()
    confirmed = history.iloc[:89].copy()
    watching = history.iloc[:88].copy()
    watching.index = confirmed.index[-len(watching):]
    old_confirmed = confirmed.copy()
    old_confirmed.index -= pd.Timedelta(days=7)
    old_watching = watching.copy()
    old_watching.index -= pd.Timedelta(days=7)
    market = pd.concat([frame.assign(Stock_ID=sid) for sid, frame in [
        ("2330", confirmed), ("2317", watching),
        ("1101", old_confirmed), ("1102", old_watching)
    ]]).reset_index()
    monkeypatch.setattr(pd, "read_parquet", lambda *_args, **_kwargs: market.copy())
    st.cache_data.clear()
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=30)
        assert not app.exception
        assert [opt.split(" - ")[0] for opt in app.selectbox(key="selected_stock").options] == ["2330"]
        watch = next(box for box in app.expander if "拉回觀察名單" in box.label)
        assert watch.dataframe[0].value["股票代號"].tolist() == ["2317"]
        assert any("2/4" in item.value for item in app.sidebar.caption)
    finally:
        st.cache_data.clear()
