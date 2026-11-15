"""Plotly Dash interface for the Statistical Screener."""

from .app import create_app
from .data import ScreenerData

__all__ = ["ScreenerData", "create_app"]
