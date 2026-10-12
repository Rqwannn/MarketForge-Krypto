"""Alur yang dijalankan dari CLI. Semua mode memakai algoritma SOP yang sama (workflows/sop.py)."""

from binance_bot.workflows.base import Workflow
from binance_bot.workflows.fill_test import FillTestWorkflow
from binance_bot.workflows.follower import FollowerWorkflow
from binance_bot.workflows.journal_report import JournalWorkflow
from binance_bot.workflows.leader import LeaderWorkflow
from binance_bot.workflows.open_app import OpenBinanceWorkflow
from binance_bot.workflows.readiness import ReadinessWorkflow
from binance_bot.workflows.single import SingleWorkflow
from binance_bot.workflows.sop import SopTrader
from binance_bot.workflows.window_size import WindowSizeWorkflow

__all__ = [
    "FillTestWorkflow",
    "FollowerWorkflow",
    "JournalWorkflow",
    "LeaderWorkflow",
    "OpenBinanceWorkflow",
    "ReadinessWorkflow",
    "SingleWorkflow",
    "SopTrader",
    "WindowSizeWorkflow",
    "Workflow",
]
