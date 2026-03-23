import time
from datetime import datetime
from typing import List

import requests

from backtester import MaCrossoverStrategy, Candle

PAIR = "XBTEUR"
INTERVAL_SECONDS = 60  # כמה זמן לחכות בין עדכונים
INITIAL_CASH = 1000.0
FEE_RATE = 0.002  # 0.2% עמלה משוערת לכל טרייד


def fetch_live_price(pair: str = PAIR) -> float:
    """מביא מחיר נוכחי מקרקן לזוג נתון (משתמש ב-Ticker public API)."""
    url = "https://api.kraken.com/0/public/Ticker"
    params = {"pair": pair}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"Kraken error: {data['error']}")

    key = next(k for k in data["result"].keys())
    info = data["result"][key]
    last_trade_price = float(info["c"][0])
    return last_trade_price


def run_paper_trader():
    """בוט paper trading פשוט על נתונים חיים מקרקן.

    חשוב: אין כאן מסחר אמיתי, רק עדכון cash/position בזיכרון.
    """
    cash = INITIAL_CASH
    position = 0.0  # BTC

    candles: List[Candle] = []
    strat = MaCrossoverStrategy(short_win=10, long_win=30, max_exposure=0.5)

    print(f"Starting paper trader for {PAIR} with €{INITIAL_CASH:.2f} cash")
    print("Press Ctrl+C to stop.\n")

    # לולאה אינסופית עד שעוצרים ידנית
    while True:
        try:
            price = fetch_live_price()
            now = datetime.now()

            # בונים candle מדומה על בסיס מחיר אחד (open=high=low=close)
            candle = Candle(
                time=now,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=0.0,
            )
            candles.append(candle)

            # מעדכנים את הנתונים באסטרטגיה (closes + MAs)
            strat.closes = [c.close for c in candles]
            strat.ma_short = strat._ma(strat.closes, strat.short_win)
            strat.ma_long = strat._ma(strat.closes, strat.long_win)

            idx = len(candles) - 1
            signal = strat.on_bar(idx, candle, cash, position) or {}
            action = signal.get("action", "hold")
            frac = float(signal.get("fraction", 0.0))

            # מחשבים הון נוכחי לפני פעולה
            equity_before = cash + position * price

            if action == "buy" and frac > 0 and cash > 0:
                amount_eur = cash * min(frac, 1.0)
                if amount_eur >= 10:  # מתעלמים מטריידים קטנים
                    qty = amount_eur / price
                    fee = amount_eur * FEE_RATE
                    cash -= (amount_eur + fee)
                    position += qty
                    print(
                        f"{now} | BUY  {qty:.6f} @ {price:.2f}, "
                        f"fee={fee:.2f}, cash={cash:.2f}, pos={position:.6f}",
                    )

            elif action == "sell" and frac > 0 and position > 0:
                qty = position * min(frac, 1.0)
                proceeds = qty * price
                fee = proceeds * FEE_RATE
                cash += (proceeds - fee)
                position -= qty
                print(
                    f"{now} | SELL {qty:.6f} @ {price:.2f}, "
                    f"fee={fee:.2f}, cash={cash:.2f}, pos={position:.6f}",
                )

            equity_after = cash + position * price
            if action == "hold":
                print(
                    f"{now} | HOLD price={price:.2f}, "
                    f"cash={cash:.2f}, pos={position:.6f}, equity={equity_after:.2f}",
                )
            else:
                print(f"    Equity before={equity_before:.2f} -> after={equity_after:.2f}")

            time.sleep(INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nStopping paper trader.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    run_paper_trader()
