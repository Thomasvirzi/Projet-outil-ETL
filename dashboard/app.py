from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from dashboard.backtest_page import render_backtest_dashboard
from dashboard.comparison_page import render_comparison_dashboard


st.set_page_config(
    page_title="Commodities Backtest Lab",
    page_icon="📈",
    layout="wide",
)

st.sidebar.title("Commodities Backtest Lab")
page = st.sidebar.radio(
    "Outil",
    ["Backtest", "Comparaison"],
    label_visibility="collapsed",
)

if page == "Backtest":
    render_backtest_dashboard()
else:
    render_comparison_dashboard()
