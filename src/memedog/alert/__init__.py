"""Alert subsystem for MemeDog Radar."""
from memedog.alert.telegram import TelegramAlert, maybe_notify

__all__ = ["TelegramAlert", "maybe_notify"]
