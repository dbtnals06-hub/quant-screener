"""미국 유니버스 정적 폴백 목록.

us.py 는 우선 위키피디아의 S&P500 구성종목을 동적으로 가져오되,
오프라인·차단 시 아래 시가총액 상위 대형주 목록으로 폴백한다.
(정확한 순서는 중요치 않다 — 어차피 팩터로 재랭킹하므로.)
"""
from __future__ import annotations

# 시총 상위 대형주 ~130선(섹터 다양성 포함). 폴백 용도.
US_LARGE_CAP_FALLBACK: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "BRK-B", "LLY", "AVGO",
    "TSLA", "JPM", "WMT", "UNH", "V", "XOM", "MA", "ORCL", "PG", "JNJ",
    "HD", "COST", "ABBV", "BAC", "KO", "MRK", "NFLX", "CVX", "CRM", "AMD",
    "PEP", "ADBE", "TMO", "LIN", "WFC", "MCD", "CSCO", "ACN", "ABT", "DHR",
    "TXN", "INTU", "QCOM", "AMAT", "VZ", "DIS", "PM", "CAT", "IBM", "GE",
    "NOW", "AXP", "PFE", "AMGN", "ISRG", "NEE", "RTX", "UNP", "SPGI", "T",
    "LOW", "GS", "HON", "BKNG", "PLD", "ELV", "SYK", "BLK", "C", "MS",
    "MDT", "TJX", "ADP", "VRTX", "GILD", "LMT", "CB", "MDLZ", "BSX", "DE",
    "ADI", "REGN", "SCHW", "MMC", "CI", "SO", "BMY", "AMT", "ZTS", "MO",
    "DUK", "FI", "SLB", "EOG", "PGR", "BDX", "ITW", "WM", "CL", "TGT",
    "APD", "CME", "MCK", "USB", "EQIX", "NOC", "PNC", "CSX", "FCX", "AON",
    "GD", "HUM", "MU", "EMR", "MAR", "PYPL", "ORLY", "MNST", "NSC", "ROP",
    "FDX", "PSX", "KMB", "GM", "F", "EW", "AEP", "ADSK", "MET", "SBUX",
]
