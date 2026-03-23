import math
from typing import List

import requests
from datetime import datetime

PAIR = "XBTEUR"
INTERVAL = 60  # minutes for each OHLC candle


def fetch_ohlc(pair: str = PAIR, interval: int = INTERVAL):
    """Fetch OHLC data from Kraken public API (historical candles)."""
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": pair, "interval": interval}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("error"):
        raise RuntimeError(f"Kraken error: {data['error']}")

    key = next(k for k in data["result"].keys() if k != "last")
    ohlc = data["result"][key]

    candles = []
    for c in ohlc:
        ts, o, h, l, cl, v, *_ = c
        candles.append(
            {
                "time": datetime.fromtimestamp(ts),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(cl),
                "volume": float(v),
            }
        )
    return candles


def returns_from_closes(closes: List[float]) -> List[float]:
    """Simple log-returns between candles."""
    rets = [0.0]
    for i in range(1, len(closes)):
        if closes[i - 1] == 0:
            rets.append(0.0)
        else:
            rets.append(math.log(closes[i] / closes[i - 1]))
    return rets


def normal_logpdf(x: float, mu: float, sigma: float) -> float:
    """Log of Normal(mu, sigma^2) PDF (for likelihood)."""
    if sigma <= 0:
        return -1e9
    return -0.5 * math.log(2 * math.pi * sigma * sigma) - (x - mu) ** 2 / (2 * sigma * sigma)


def bayesian_trend_strategy(candles):
    """Very simple 2‑state Bayesian trend follower + basic risk rules.

    Hidden state S_t in {UP, DOWN}.

    Extra rules we מוסיפים עכשיו:
    - לא נכנסים ביותר מ‑max_exposure מההון הכולל.
    - לא קונים אם ה‑buy_amount קטן מ‑min_trade_eur (כדי לא לראות BUY 0.000000).
    - סטופ‑לוס גס: אם יש drawdown גדול מהסף מאז מחיר הכניסה הממוצע, מקטינים פוזיציה.
    """

    closes = [c["close"] for c in candles]
    rets = returns_from_closes(closes)

    # Hyper‑parameters (פשוטים)
    mu_up = 0.0004
    mu_down = -0.0004
    sigma_up = 0.005
    sigma_down = 0.005

    # Prior – מתחילים נייטרלי
    p_up = 0.5
    p_down = 0.5

    balance = 1000.0  # EUR
    position = 0.0    # BTC

    # כללי ניהול סיכונים בסיסיים
    max_exposure = 0.5      # לא יותר מ‑50% מההון בביטקוין
    min_trade_eur = 10.0    # לא מבצעים טריידים קטנים יותר מזה
    stop_loss_dd = -0.03    # אם ירדנו יותר מ‑3% מהכניסה הממוצעת → למכור קצת

    avg_entry_price = None  # מחיר כניסה ממוצע משוקלל

    threshold = 0.7

    for c, r in zip(candles[1:], rets[1:]):
        price = c["close"]

        # Likelihoods
        log_l_up = normal_logpdf(r, mu_up, sigma_up)
        log_l_down = normal_logpdf(r, mu_down, sigma_down)

        # Bayes update in log-space
        log_p_up = math.log(p_up) + log_l_up
        log_p_down = math.log(p_down) + log_l_down

        m = max(log_p_up, log_p_down)
        p_up_new = math.exp(log_p_up - m)
        p_down_new = math.exp(log_p_down - m)
        s = p_up_new + p_down_new
        p_up = p_up_new / s
        p_down = p_down_new / s

        # Equity ו‑exposure נוכחי
        equity = balance + position * price
        position_value = position * price
        if equity > 0:
            exposure = position_value / equity
        else:
            exposure = 0.0

        # ---- BUY RULE ----
        if p_up > threshold and balance > min_trade_eur and exposure < max_exposure:
            # כמה מותר לנו להגדיל פוזיציה מבלי לעבור את max_exposure?
            target_position_value = equity * max_exposure
            allowed_additional = max(0.0, target_position_value - position_value)
            buy_amount = min(balance * 0.3, allowed_additional)

            if buy_amount >= min_trade_eur:
                qty = buy_amount / price
                position += qty
                balance -= buy_amount

                # עדכון מחיר כניסה ממוצע
                if avg_entry_price is None:
                    avg_entry_price = price
                else:
                    total_value_before = (position - qty) * avg_entry_price
                    total_value_after = total_value_before + buy_amount
                    avg_entry_price = total_value_after / (position * price) * price

                print(
                    c["time"],
                    f"POST_UP={p_up:.2f} BUY  {qty:.6f} @ {price:.2f}, "
                    f"exposure={exposure:.2f}, balance={balance:.2f}, pos={position:.6f}",
                )

        # ---- STOP‑LOSS RULE ----
        if position > 0 and avg_entry_price is not None:
            dd = (price - avg_entry_price) / avg_entry_price
            if dd <= stop_loss_dd:
                # למכור 30% מהפוזיציה אם חטפנו drawdown גדול
                sell_qty = position * 0.3
                proceeds = sell_qty * price
                position -= sell_qty
                balance += proceeds
                # אם מכרנו הכול כמעט – מאפסים avg_entry_price
                if position <= 1e-8:
                    position = 0.0
                    avg_entry_price = None
                print(
                    c["time"],
                    f"STOP_LOSS dd={dd:.3f} SELL {sell_qty:.6f} @ {price:.2f}, "
                    f"balance={balance:.2f}, pos={position:.6f}",
                )

        # ---- DOWNTREND RULE ----
        if p_down > threshold and position > 0:
            sell_qty = position * 0.3
            proceeds = sell_qty * price
            position -= sell_qty
            balance += proceeds
            if position <= 1e-8:
                position = 0.0
                avg_entry_price = None
            print(
                c["time"],
                f"POST_DOWN={p_down:.2f} SELL {sell_qty:.6f} @ {price:.2f}, "
                f"balance={balance:.2f}, pos={position:.6f}",
            )

    final_price = candles[-1]["close"]
    equity = balance + position * final_price
    print("----")
    print(
        f"Final equity (Bayesian+risk): {equity:.2f} "
        f"(cash={balance:.2f}, pos={position:.6f} @ {final_price:.2f})",
    )


def main():
    print(f"Fetching OHLC from Kraken for {PAIR} (interval={INTERVAL}m)...")
    candles = fetch_ohlc()
    print(f"Got {len(candles)} candles")
    bayesian_trend_strategy(candles)


if __name__ == "__main__":
    main()
