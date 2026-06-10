"""퀀트 라이브 스크리너 — Streamlit 대시보드.

실행:  streamlit run app.py
구조:  사이드바(전략·필터) → 캐시된 기초데이터 적재 → 종합점수/랭킹 →
       st.fragment 로 근실시간 시세만 주기적 폴링.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

import config
from quant.datasource import get_source
from quant.factors import build_factor_panel
from quant.screener import compute_scores, apply_filters
from quant.strategies import PRESETS, PRESET_NOTES, CUSTOM_LABEL, FactorWeights
from quant import behavioral

st.set_page_config(page_title="퀀트 라이브 스크리너", page_icon="📈", layout="wide")


# ════════════════════════════════════════════════════════════
#  캐시된 기초데이터 적재 (무거운 일봉·펀더멘털 — 6시간 캐시)
# ════════════════════════════════════════════════════════════
@st.cache_data(ttl=config.BASE_CACHE_TTL, show_spinner=False)
def load_base(market: str, size: int) -> dict:
    """유니버스→일봉→펀더멘털→팩터패널까지 한 번에 적재해 캐시한다."""
    ds = get_source(market)
    universe = ds.get_universe(size)
    tickers = list(universe.index)
    prices = ds.get_price_history(tickers, config.PRICE_HISTORY_DAYS)
    fundamentals = ds.get_fundamentals(tickers)
    panel = build_factor_panel(prices, fundamentals, universe)
    return {
        "panel": panel,
        "currency": ds.currency,
        "price_decimals": ds.price_decimals,
        "n_prices": int(prices.shape[1]) if not prices.empty else 0,
        "loaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ════════════════════════════════════════════════════════════
#  표시 헬퍼
# ════════════════════════════════════════════════════════════
def fmt_mktcap(val: float, market: str) -> str:
    if pd.isna(val):
        return "-"
    if market == config.MARKET_KR:
        if val >= 1e12:
            return f"{val/1e12:.1f}조"
        return f"{val/1e8:.0f}억"
    # US (USD)
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    return f"${val/1e6:.0f}M"


def fmt_price(val: float, mkt: str) -> str:
    """행별 시장에 맞춰 통화 기호와 소수 자리를 붙인다."""
    if pd.isna(val):
        return "-"
    if mkt == config.MARKET_KR:
        return f"₩{val:,.0f}"
    return f"${val:,.2f}"


def _blend(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_css(series: pd.Series) -> list[str]:
    """낮음(빨강)→중간(노랑)→높음(초록) 연한 배경 CSS 리스트."""
    s = pd.to_numeric(series, errors="coerce")
    vmin, vmax = s.min(), s.max()
    lo, mid, hi = (235, 110, 110), (245, 225, 130), (110, 200, 130)
    out = []
    for v in s:
        if pd.isna(v) or vmax == vmin:
            out.append("")
            continue
        t = (v - vmin) / (vmax - vmin)
        rgb = _blend(lo, mid, t * 2) if t < 0.5 else _blend(mid, hi, (t - 0.5) * 2)
        out.append(f"background-color: rgba({rgb[0]},{rgb[1]},{rgb[2]},0.55)")
    return out


def change_css(series: pd.Series) -> list[str]:
    out = []
    for v in pd.to_numeric(series, errors="coerce"):
        if pd.isna(v) or v == 0:
            out.append("")
        elif v > 0:
            out.append("color:#d11; font-weight:600")   # 한국식: 상승=빨강
        else:
            out.append("color:#1565c0; font-weight:600")  # 하락=파랑
    return out


# ════════════════════════════════════════════════════════════
#  사이드바 — 전략 / 필터 / 폴링
# ════════════════════════════════════════════════════════════
st.sidebar.title("📈 퀀트 라이브 스크리너")
st.sidebar.caption("KOSPI·KOSDAQ · NYSE·NASDAQ | 멀티팩터 + 행동재무")

_market_labels = list(config.MARKET_LABELS.keys())
market_label = st.sidebar.selectbox(
    "🌐 시장", _market_labels,
    index=_market_labels.index(config.DEFAULT_MARKET_LABEL),
)
market = config.MARKET_LABELS[market_label]

universe_size = st.sidebar.slider("유니버스 크기 (시총 상위 N)", 30, 200,
                                  config.DEFAULT_UNIVERSE_SIZE, step=10)

st.sidebar.subheader("🎯 전략")
preset_name = st.sidebar.selectbox("프리셋", list(PRESETS.keys()) + [CUSTOM_LABEL])
if preset_name == CUSTOM_LABEL:
    st.sidebar.caption("팩터 가중치를 직접 조립하세요 (자동 정규화)")
    c1, c2 = st.sidebar.columns(2)
    wv = c1.slider("가치", 0.0, 1.0, 0.25, 0.05)
    wm = c2.slider("모멘텀", 0.0, 1.0, 0.25, 0.05)
    wq = c1.slider("퀄리티", 0.0, 1.0, 0.25, 0.05)
    wl = c2.slider("저변동성", 0.0, 1.0, 0.25, 0.05)
    weights = FactorWeights(wv, wm, wq, wl)
else:
    weights = PRESETS[preset_name]
    st.sidebar.info(PRESET_NOTES.get(preset_name, ""))

st.sidebar.subheader("🔎 필터")
max_per = st.sidebar.number_input("최대 PER (0=해제)", 0.0, 500.0, 0.0, step=1.0)
min_div = st.sidebar.number_input("최소 배당수익률 % (0=해제)", 0.0, 20.0, 0.0, step=0.5)
exclude_traps = st.sidebar.checkbox("⚠️ 가치함정 의심 종목 제외", value=False)

st.sidebar.subheader("⏱️ 실시간")
auto = st.sidebar.toggle("자동 새로고침", value=True)
poll = st.sidebar.slider("폴링 주기(초)", config.MIN_POLL_SECONDS, config.MAX_POLL_SECONDS,
                         config.DEFAULT_POLL_SECONDS, step=5, disabled=not auto)
top_n = st.sidebar.slider("표시 종목 수", 10, 100, 30, step=5)

if st.sidebar.button("♻️ 데이터 새로 적재 (캐시 비우기)"):
    load_base.clear()
    st.rerun()


# ════════════════════════════════════════════════════════════
#  기초데이터 적재 + 점수 계산
# ════════════════════════════════════════════════════════════
norm = weights.normalized()
st.title("📈 퀀트 라이브 스크리너")
st.caption(
    f"전략: **{preset_name}**  ·  가중치 → 가치 {norm.value:.0%} · 모멘텀 {norm.momentum:.0%} · "
    f"퀄리티 {norm.quality:.0%} · 저변동성 {norm.lowvol:.0%}"
)

with st.spinner(f"📥 {market_label} 기초데이터 적재 중… (최초 1회만, 이후 캐시되어 빠릅니다)"):
    try:
        base = load_base(market, universe_size)
    except Exception as e:
        if market == config.MARKET_KR:
            st.error(
                "🇰🇷 한국(KRX) 데이터를 불러오지 못했습니다.\n\n"
                "이 화면이 **해외(클라우드) 서버**에서 돌고 있다면, KRX·네이버가 해외 IP를 "
                "차단하기 때문입니다(코드 문제가 아닙니다).\n\n"
                "👉 왼쪽 사이드바에서 **시장을 ‘미국 (NYSE/NASDAQ)’** 로 바꾸면 바로 동작합니다.\n"
                "한국 데이터는 **국내 PC에서 실행**할 때(run.bat / share.bat)만 안정적으로 받아집니다."
            )
        else:
            st.error(f"데이터 적재 실패: {e}")
        with st.expander("기술 상세 보기"):
            st.code(str(e))
        st.stop()

panel = base["panel"]
currency = base["currency"]
price_decimals = base["price_decimals"]

if panel.empty or base["n_prices"] == 0:
    st.warning("표시할 데이터가 없습니다. 네트워크 연결 또는 휴장 여부를 확인하고 캐시를 비워보세요.")
    st.stop()

scored = compute_scores(panel, weights)

# 섹터 필터(데이터가 있을 때만)
sectors_available = sorted([s for s in scored["sector"].dropna().unique() if s])
sel_sectors = st.sidebar.multiselect("섹터", sectors_available, default=[]) if sectors_available else []

filtered = apply_filters(
    scored,
    max_per=max_per or None,
    min_dividend=min_div or None,
    sectors=sel_sectors or None,
    exclude_value_traps=exclude_traps,
)
if filtered.empty:
    st.warning("필터 조건을 만족하는 종목이 없습니다. 조건을 완화해 보세요.")
    st.stop()


# ════════════════════════════════════════════════════════════
#  실시간 시세 폴링용 소스 (가벼운 인스턴스)
# ════════════════════════════════════════════════════════════
quote_source = get_source(market)


def build_view(disp_panel: pd.DataFrame) -> pd.DataFrame:
    """랭킹 패널 + 실시간 시세 → 화면 표시용 테이블."""
    tickers = list(disp_panel.index)
    try:
        quotes = quote_source.get_quotes(tickers)
    except Exception:
        quotes = pd.DataFrame(index=tickers, columns=["price", "change_pct"], dtype=float)
    v = disp_panel.join(quotes)
    # 행별 시장 코드: 통합은 KR/US, 단일 시장은 전역 market
    if "mkt" in v.columns and v["mkt"].notna().any():
        row_mkt = v["mkt"].fillna(market)
    else:
        row_mkt = pd.Series(market, index=v.index)

    tbl = pd.DataFrame(index=v.index)
    tbl["순위"] = v["rank"].astype(int)
    tbl["티커"] = v.index
    tbl["종목"] = v["name"]
    if market == config.MARKET_BOTH:
        tbl["시장"] = row_mkt.map({"KR": "🇰🇷 KR", "US": "🇺🇸 US"}).fillna(row_mkt)
    tbl["섹터"] = v["sector"]
    tbl["현재가"] = [fmt_price(p, m) for p, m in zip(v["price"], row_mkt)]
    tbl["등락률%"] = v["change_pct"]
    tbl["종합점수"] = v["composite"]
    tbl["백분위"] = v["percentile"]
    tbl["가치"] = v["z_value"]
    tbl["모멘텀"] = v["z_momentum"]
    tbl["퀄리티"] = v["z_quality"]
    tbl["저변동성"] = v["z_lowvol"]
    tbl["PER"] = v["per"]
    tbl["PBR"] = v["pbr"]
    tbl["배당%"] = v["dividend_yield"]
    tbl["ROE%"] = v["roe"]
    tbl["12-1수익%"] = v["mom_12_1"] * 100.0
    tbl["변동성%"] = v["vol_6m"] * 100.0
    tbl["시총"] = [fmt_mktcap(c, m) for c, m in zip(v["market_cap"], row_mkt)]
    tbl["행동신호"] = v["flags"]
    return tbl


def style_table(tbl: pd.DataFrame):
    # 현재가·시총은 build_view에서 이미 통화 기호 붙은 문자열로 만들어짐
    fmt = {
        "등락률%": lambda x: "-" if pd.isna(x) else f"{x:+.2f}%",
        "종합점수": "{:.2f}", "백분위": "{:.0f}",
        "가치": "{:+.2f}", "모멘텀": "{:+.2f}", "퀄리티": "{:+.2f}", "저변동성": "{:+.2f}",
        "PER": "{:.1f}", "PBR": "{:.2f}", "배당%": "{:.2f}", "ROE%": "{:.1f}",
        "12-1수익%": "{:+.1f}", "변동성%": "{:.1f}",
    }
    styler = (
        tbl.style
        .format(fmt, na_rep="-")
        .apply(lambda s: gradient_css(s), subset=["종합점수"])
        .apply(lambda s: gradient_css(s), subset=["백분위"])
        .apply(lambda s: change_css(s), subset=["등락률%"])
    )
    return styler


# ════════════════════════════════════════════════════════════
#  상단 요약 + 행동경제학 코멘트 + 차트
# ════════════════════════════════════════════════════════════
top_row = filtered.iloc[0]
k1, k2, k3, k4 = st.columns(4)
k1.metric("유니버스", f"{len(scored)} 종목", help="시총 상위 N에서 가격 데이터 확보분")
k2.metric("필터 후", f"{len(filtered)} 종목")
k3.metric("1위 종목", str(top_row["name"]),
          help=f"종합점수 {top_row['composite']:.2f} · 백분위 {top_row['percentile']:.0f}")
flagged = int((filtered["flags"].fillna("") != "").sum())
k4.metric("행동신호 감지", f"{flagged} 종목", help="과열·복권형·가치함정 등")

st.info("🧠 " + behavioral.top_pick_commentary(top_row, weights))

ch1, ch2 = st.columns([3, 2])
with ch1:
    st.markdown("##### 종합점수 상위")
    bar_src = filtered.head(min(top_n, 20)).reset_index()
    bar = (
        alt.Chart(bar_src)
        .mark_bar()
        .encode(
            x=alt.X("composite:Q", title="종합점수"),
            y=alt.Y("name:N", sort="-x", title=None),
            color=alt.Color("composite:Q", scale=alt.Scale(scheme="redyellowgreen"),
                            legend=None),
            tooltip=["name", alt.Tooltip("composite:Q", format=".2f"),
                     alt.Tooltip("percentile:Q", format=".0f")],
        )
        .properties(height=max(220, min(top_n, 20) * 22))
    )
    st.altair_chart(bar, width="stretch")
with ch2:
    st.markdown("##### 섹터 분포 (상위 종목)")
    sec = (filtered.head(top_n)["sector"].replace("", "기타").fillna("기타")
           .value_counts().reset_index())
    sec.columns = ["섹터", "종목수"]
    pie = (
        alt.Chart(sec)
        .mark_arc(innerRadius=45)
        .encode(theta="종목수:Q",
                color=alt.Color("섹터:N", legend=alt.Legend(orient="bottom", columns=2)),
                tooltip=["섹터", "종목수"])
        .properties(height=260)
    )
    st.altair_chart(pie, width="stretch")


# ════════════════════════════════════════════════════════════
#  실시간 스크리너 테이블 (st.fragment 로 시세만 주기 폴링)
# ════════════════════════════════════════════════════════════
st.markdown("### 🔴 실시간 스크리너")


@st.fragment(run_every=(poll if auto else None))
def live_block():
    view = filtered.head(top_n)
    tbl = build_view(view)
    stamp = datetime.now().strftime("%H:%M:%S")
    badge = "🟢 자동" if auto else "⏸️ 수동"
    up = int((tbl["등락률%"] > 0).sum())
    down = int((tbl["등락률%"] < 0).sum())
    st.caption(f"{badge} · 최근 시세 {stamp} · 폴링 {poll}s · "
               f"상승 {up} / 하락 {down}  ·  통화 {currency or '₩+$'}")
    st.dataframe(
        style_table(tbl),
        width="stretch", hide_index=True,
        height=min(720, 80 + len(tbl) * 35),
        column_config={
            "백분위": st.column_config.NumberColumn(help="종합점수 백분위(0~100, 클수록 우수)"),
            "행동신호": st.column_config.TextColumn(width="medium"),
        },
    )
    if not auto and st.button("🔄 지금 새로고침", key="manual_refresh"):
        st.rerun(scope="fragment")


live_block()


# ════════════════════════════════════════════════════════════
#  행동편향 위험 종목 + 팩터 해설
# ════════════════════════════════════════════════════════════
risky = filtered[filtered["flags"].fillna("") != ""].head(top_n)
if not risky.empty:
    with st.expander(f"⚠️ 행동편향 위험 신호 ({len(risky)} 종목) — 클릭하여 코멘트 보기"):
        for tkr, r in risky.iterrows():
            st.markdown(f"- **{r['name']}** ({tkr}) &nbsp; {r['flags']} — {r['flag_detail']}")

with st.expander("🧠 행동경제학으로 읽는 4대 팩터 — 왜 이 이상현상은 사라지지 않는가"):
    st.caption(
        "효율적 시장이라면 아래 초과수익은 0이어야 합니다. 수십 년간 지속된다는 사실 자체가 "
        "가격이 '합리적 기대'가 아니라 '편향된 다수의 심리'로 형성됨을 시사합니다."
    )
    for key in ["value", "momentum", "quality", "lowvol"]:
        info = behavioral.FACTOR_BEHAVIOR[key]
        st.markdown(
            f"#### {info['factor_kr']} 팩터 — *{info['bias']}*\n"
            f"{info['mechanism']}\n\n"
            f"<small>📚 {info['ref']}</small>",
            unsafe_allow_html=True,
        )

st.divider()
st.caption(
    f"데이터 적재 시각: {base['loaded_at']} · 무료 데이터(FinanceDataReader/pykrx/yfinance) 기반, "
    "지연·결측이 있을 수 있습니다. 본 화면은 투자 권유가 아니라 리서치 도구입니다."
)
