import math
from dataclasses import dataclass
from typing import List, Protocol, Dict, Any

import requests
from datetime import datetime

PAIR = "XBTEUR"
INTERVAL = 60  # minutes per candle


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    time: datetime
    side: str  # "buy" or "sell"
    price: float
    qty: float
    cash_after: float
    position_after: float


@dataclass
class Result:
    initial_equity: float
    final_equity: float
    trades: List[Trade]


class Strategy(Protocol):
    def on_init(self, candles: List[Candle]) -> None: ...

    def on_bar(
        self,
        idx: int,
        candle: Candle,
        cash: float,
        position: float,
    ) -> Dict[str, Any]:
        """Return dict with optional 'buy'/'sell' instructions.

        Example:
        {"action": "buy", "fraction": 0.3}  # buy using 30% of cash
        {"action": "sell", "fraction": 0.3} # sell 30% of position
        {"action": "hold"}
        """
        ...


def fetch_candles(pair: str = PAIR, interval: int = INTERVAL) -> List[Candle]:
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": pair, "interval": interval}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"Kraken error: {data['error']}")

    key = next(k for k in data["result"].keys() if k != "last")
    ohlc = data["result"][key]

    candles: List[Candle] = []
    for c in ohlc:
        ts, o, h, l, cl, v, *_ = c
        candles.append(
            Candle(
                time=datetime.fromtimestamp(ts),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(cl),
                volume=float(v),
            )
        )
    return candles


def backtest(
    candles: List[Candle],
    strategy: Strategy,
    initial_cash: float = 1000.0,
    fee_rate: float = 0.002,  # 0.2% per trade (approx typical)
) -> Result:
    cash = initial_cash
    position = 0.0  # BTC
    trades: List[Trade] = []

    strategy.on_init(candles)

    for i, c in enumerate(candles):
        if i == 0:
            continue

        signal = strategy.on_bar(i, c, cash, position) or {}
        action = signal.get("action", "hold")
        frac = float(signal.get("fraction", 0.0))

        price = c.close

        if action == "buy" and frac > 0 and cash > 0:
            amount_eur = cash * min(frac, 1.0)
            if amount_eur < 10:  # ignore tiny trades
                continue
            qty = amount_eur / price
            fee = amount_eur * fee_rate
            cash -= (amount_eur + fee)
            position += qty
            trades.append(
                Trade(c.time, "buy", price, qty, cash, position)
            )

        elif action == "sell" and frac > 0 and position > 0:
            qty = position * min(frac, 1.0)
            proceeds = qty * price
            fee = proceeds * fee_rate
            cash += (proceeds - fee)
            position -= qty
            trades.append(
                Trade(c.time, "sell", price, qty, cash, position)
            )

    final_price = candles[-1].close
    final_equity = cash + position * final_price
    return Result(initial_cash, final_equity, trades)


# --- Example: MA 10/30 strategy ---

class MaCrossoverStrategy:
    def __init__(self, short_win: int = 10, long_win: int = 30, max_exposure: float = 0.5):
        self.short_win = short_win
        self.long_win = long_win
        self.max_exposure = max_exposure
        self.closes: List[float] = []
        self.ma_short: List[float] = []
        self.ma_long: List[float] = []
        self.prev_state: str | None = None

    def on_init(self, candles: List[Candle]) -> None:
        self.closes = [c.close for c in candles]
        self.ma_short = self._ma(self.closes, self.short_win)
        self.ma_long = self._ma(self.closes, self.long_win)

    @staticmethod
    def _ma(values: List[float], window: int) -> List[float]:
        out: List[float] = []
        s = 0.0
        for i, v in enumerate(values):
            s += v
            if i >= window:
                s -= values[i - window]
            if i >= window - 1:
                out.append(s / window)
            else:
                out.append(math.nan)
        return out

    def on_bar(self, idx: int, candle: Candle, cash: float, position: float) -> Dict[str, Any]:
        ms = self.ma_short[idx]
        ml = self.ma_long[idx]
        if math.isnan(ms) or math.isnan(ml):
            return {"action": "hold"}

        state = "above" if ms > ml else "below" if ms < ml else self.prev_state
        if self.prev_state is None:
            self.prev_state = state
            return {"action": "hold"}

        price = candle.close
        equity = cash + position * price
        exposure = (position * price / equity) if equity > 0 else 0.0

        # Cross up: try to increase exposure up to max_exposure
        if self.prev_state == "below" and state == "above" and cash > 0 and exposure < self.max_exposure:
            self.prev_state = state
            return {"action": "buy", "fraction": 0.5}

        # Cross down: reduce exposure
        if self.prev_state == "above" and state == "below" and position > 0:
            self.prev_state = state
            return {"action": "sell", "fraction": 0.5}

        self.prev_state = state
        return {"action": "hold"}


def main() -> None:
    candles = fetch_candles()
    strat = MaCrossoverStrategy(short_win=10, long_win=30, max_exposure=0.5)
    result = backtest(candles, strat, initial_cash=1000.0, fee_rate=0.002)

    print(f"Initial equity: {result.initial_equity:.2f}")
    print(f"Final equity  : {result.final_equity:.2f}")
    print(f"Trades        : {len(result.trades)}")
    if result.trades:
        print("Last trades:")
        for t in result.trades[-10:]:
            print(
                f"  {t.time} {t.side.upper()} {t.qty:.6f} @ {t.price:.2f} "
                f"cash={t.cash_after:.2f}, pos={t.position_after:.6f}"
            )


if __name__ == "__main__":
    main()
