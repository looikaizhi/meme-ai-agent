from decimal import Decimal
from typing import Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class MemeDogMomentumStrategyConfig(StrategyConfig):
    instrument_id: Optional[InstrumentId] = None
    bar_type: Optional[BarType] = None
    instrument_ids: tuple[InstrumentId, ...] = ()
    bar_types: tuple[BarType, ...] = ()
    order_id_tag: str = "memedog"
    trade_size: str = "100"
    fast_period: int = 10
    slow_period: int = 30


class MemeDogMomentumStrategy(Strategy):
    def __init__(self, config: MemeDogMomentumStrategyConfig) -> None:
        super().__init__(config)
        self.cfg = config
        self._fast_ema: Optional[float] = None
        self._slow_ema: Optional[float] = None
        self._prev_diff: Optional[float] = None
        self._bars_seen = 0
        self._position = "NONE"
        self._instrument: Optional[Instrument] = None

    def on_start(self) -> None:
        bar_type = self.cfg.bar_type or (
            self.cfg.bar_types[0] if self.cfg.bar_types else None
        )
        instrument_id = self.cfg.instrument_id or (
            self.cfg.instrument_ids[0] if self.cfg.instrument_ids else None
        )
        if bar_type is None or instrument_id is None:
            raise RuntimeError("bar_type and instrument_id must be set")
        self._instrument = self.cache.instrument(instrument_id)
        self.subscribe_bars(bar_type)

    def on_bar(self, bar: Bar) -> None:
        close = float(bar.close)
        self._bars_seen += 1
        self._fast_ema = self._update_ema(self._fast_ema, close, self.cfg.fast_period)
        self._slow_ema = self._update_ema(self._slow_ema, close, self.cfg.slow_period)

        warmup = max(self.cfg.fast_period, self.cfg.slow_period) + 1
        if self._bars_seen < warmup:
            return

        diff = self._fast_ema - self._slow_ema  # type: ignore[operator]
        if self._prev_diff is None:
            self._prev_diff = diff
            return

        cross_up = self._prev_diff <= 0.0 < diff
        cross_down = self._prev_diff >= 0.0 > diff
        self._prev_diff = diff

        instrument = self._instrument
        if instrument is None:
            return
        quantity = Quantity(Decimal(self.cfg.trade_size), instrument.size_precision)

        if self._position == "NONE" and cross_up:
            self._submit(instrument.id, OrderSide.BUY, quantity)
            self._position = "LONG"
            return

        if self._position == "LONG" and cross_down:
            self._close_open(instrument.id, OrderSide.SELL)
            self._position = "NONE"

    @staticmethod
    def _update_ema(prev: Optional[float], value: float, period: int) -> float:
        if prev is None:
            return value
        alpha = 2.0 / (period + 1)
        return alpha * value + (1.0 - alpha) * prev

    def _submit(
        self,
        instrument_id: InstrumentId,
        side: OrderSide,
        quantity: Quantity,
    ) -> None:
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=side,
            quantity=quantity,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def _close_open(self, instrument_id: InstrumentId, side: OrderSide) -> None:
        for position in self.cache.positions_open(instrument_id=instrument_id):
            self._submit(instrument_id, side, position.quantity)

    def on_stop(self) -> None:
        if self._instrument is not None:
            self.cancel_all_orders(self._instrument.id)
            self.close_all_positions(self._instrument.id)

