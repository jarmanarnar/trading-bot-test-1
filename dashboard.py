import math
from typing import List

import streamlit as st
import pandas as pd

from backtester import fetch_candles, backtest, MaCrossoverStrategy, Candle


def candles_to_df(candles: List[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "time": c.time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    ).set_index("time")


def main() -> None:
    st.set_page_config(page_title="Trading Bot Backtest", layout="wide")
    st.title("Trading Bot Backtest – Kraken XBTEUR")

    st.sidebar.header("Parameters")
    short_win = st.sidebar.slider("Short MA window", min_value=3, max_value=50, value=10, step=1)
    long_win = st.sidebar.slider("Long MA window", min_value=10, max_value=200, value=30, step=1)
    fee_rate = st.sidebar.slider("Fee rate (per trade)", min_value=0.0, max_value=0.005, value=0.002, step=0.0005)
    max_exposure = st.sidebar.slider("Max exposure", min_value=0.1, max_value=1.0, value=0.5, step=0.05)

    st.sidebar.write("\nClick to run backtest:")
    if st.sidebar.button("Run backtest"):
        with st.spinner("Fetching data from Kraken and running backtest..."):
            candles = fetch_candles()
            df = candles_to_df(candles)

            strat = MaCrossoverStrategy(
                short_win=short_win,
                long_win=long_win,
                max_exposure=max_exposure,
            )
            result = backtest(candles, strat, initial_cash=1000.0, fee_rate=fee_rate)

        final_pct = (result.final_equity / result.initial_equity - 1.0) * 100.0

        col1, col2, col3 = st.columns(3)
        col1.metric("Initial equity", f"€{result.initial_equity:,.2f}")
        col2.metric("Final equity", f"€{result.final_equity:,.2f}", f"{final_pct:+.2f}%")
        col3.metric("Number of trades", f"{len(result.trades)}")

        # Trades table
        if result.trades:
            trades_df = pd.DataFrame(
                [
                    {
                        "time": t.time,
                        "side": t.side,
                        "price": t.price,
                        "qty": t.qty,
                        "cash_after": t.cash_after,
                        "position_after": t.position_after,
                    }
                    for t in result.trades
                ]
            ).set_index("time")

            st.subheader("Trades")
            st.dataframe(trades_df.tail(50))

            # Price chart with buy/sell markers
            st.subheader("Price with trades")
            chart_df = df[["close"]].copy()
            chart_df["buy"] = math.nan
            chart_df["sell"] = math.nan
            for t in result.trades:
                if t.time in chart_df.index:
                    if t.side == "buy":
                        chart_df.at[t.time, "buy"] = t.price
                    else:
                        chart_df.at[t.time, "sell"] = t.price

            st.line_chart(chart_df)
        else:
            st.info("No trades executed with these parameters.")
    else:
        st.info("Set parameters in the sidebar and click 'Run backtest'.")


if __name__ == "__main__":
    main()
