"""PaperTrader package — simulated (paper) trading with SQLite persistence."""
from memedog.papertrader.trader import PaperTrader
from memedog.papertrader.watcher import PriceWatcher

__all__ = ["PaperTrader", "PriceWatcher"]
