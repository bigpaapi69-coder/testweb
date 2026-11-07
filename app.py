"""
Early Memecoin Finder & Checker App
Based on signals from r/memecoins and r/pumpfun posts:
- Volume acceleration
- Buy pressure (buys > sells)
- Liquidity / holders / market cap checks
- Basic risk scoring via RugCheck + DEXScreener

Run with: streamlit run memecoin_finder_app.py
Requires: pip install streamlit requests pandas
No API keys needed for core features.
DISCLAIMER: Not financial advice. Most memecoins go to zero. DYOR. Risk only what you can lose.
"""

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone
import time

st.set_page_config(
    page_title="Early Memecoin Finder",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------- Helpers ----------
@st.cache_data(ttl=30)
def fetch_dexscreener_token(chain: str, address: str):
    """Fetch pair data for a token address from DEXScreener (free, no key)."""
    url = f"https://api.dexscreener.com/tokens/v1/{chain}/{address}"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get("pairs", [])
        return []
    except Exception as e:
        st.error(f"DEXScreener error: {e}")
        return []

@st.cache_data(ttl=60)
def fetch_dexscreener_search(query: str):
    """Search pairs by name/symbol/CA."""
    url = f"https://api.dexscreener.com/latest/dex/search?q={query}"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return r.json().get("pairs", [])
        return []
    except Exception as e:
        st.error(f"Search error: {e}")
        return []

@st.cache_data(ttl=60)
def fetch_rugcheck(mint: str):
    """Basic risk report from RugCheck (free)."""
    url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None

def compute_signals(pair: dict) -> dict:
    """Compute the key signals from the Reddit posts."""
    signals = {
        "volume_accel": False,
        "buy_pressure": False,
        "liquidity_ok": False,
        "age_hours": None,
        "mcap": None,
        "score": 0,
        "notes": []
    }

    txns = pair.get("txns", {})
    volume = pair.get("volume", {})
    liquidity = pair.get("liquidity", {})
    price_change = pair.get("priceChange", {})

    # Age
    created = pair.get("pairCreatedAt")
    if created:
        age_ms = datetime.now(timezone.utc).timestamp() * 1000 - created
        signals["age_hours"] = round(age_ms / 3600000, 2)

    # Market cap / FDV
    signals["mcap"] = pair.get("marketCap") or pair.get("fdv")

    # Liquidity
    liq_usd = liquidity.get("usd") or 0
    signals["liquidity_ok"] = liq_usd >= 5000  # basic threshold
    if liq_usd < 2000:
        signals["notes"].append("⚠️ Very low liquidity – high slippage risk")
    elif liq_usd >= 10000:
        signals["score"] += 1
        signals["notes"].append("✅ Decent liquidity")

    # Buy pressure (h1 or m5)
    h1 = txns.get("h1", {})
    buys = h1.get("buys", 0)
    sells = h1.get("sells", 0)
    total = buys + sells
    if total >= 20:
        buy_ratio = buys / total
        signals["buy_pressure"] = buy_ratio >= 0.55
        if buy_ratio >= 0.65:
            signals["score"] += 2
            signals["notes"].append(f"✅ Strong buy pressure ({buy_ratio*100:.0f}% buys)")
        elif buy_ratio >= 0.55:
            signals["score"] += 1
            signals["notes"].append(f"🟡 Mild buy pressure ({buy_ratio*100:.0f}% buys)")
        else:
            signals["notes"].append(f"🔴 Sell pressure ({buy_ratio*100:.0f}% buys)")

    # Volume acceleration (h1 volume vs proportion of h24)
    vol_h1 = volume.get("h1") or 0
    vol_h24 = volume.get("h24") or 0
    if vol_h24 > 0 and vol_h1 > 0:
        # Rough: if h1 is > 1/12 of h24, accelerating
        if vol_h1 > (vol_h24 / 8):  # more aggressive than average
            signals["volume_accel"] = True
            signals["score"] += 2
            signals["notes"].append("✅ Volume accelerating (h1 strong vs h24)")
        elif vol_h1 > (vol_h24 / 20):
            signals["score"] += 1
            signals["notes"].append("🟡 Some volume activity in last hour")

    # Price change positive short term
    pc_h1 = price_change.get("h1") or 0
    if pc_h1 > 20:
        signals["score"] += 1
        signals["notes"].append(f"✅ Strong 1h move (+{pc_h1:.0f}%)")

    # Age bonus for early
    if signals["age_hours"] is not None:
        if signals["age_hours"] < 2:
            signals["score"] += 2
            signals["notes"].append("🔥 Very early (<2h)")
        elif signals["age_hours"] < 12:
            signals["score"] += 1
            signals["notes"].append("🟡 Relatively early (<12h)")

    return signals

def format_usd(val):
    if val is None:
        return "N/A"
    if val >= 1_000_000:
        return f"${val/1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val/1_000:.1f}K"
    return f"${val:.0f}"

# ---------- UI ----------
st.title("🚀 Early Memecoin Finder")
st.caption("Apply the signals from the Reddit guides: volume acceleration • buy pressure • liquidity • early age • basic risk. Not financial advice.")

with st.sidebar:
    st.header("How to use")
    st.markdown("""
    1. Paste a **Solana token CA** (or search by name/symbol).
    2. Or open [DEXScreener Solana New Pairs](https://dexscreener.com/solana?rankBy=pairAge&order=asc) / [pump.fun](https://pump.fun) and copy interesting CAs here.
    3. Check the **Signals** score and notes.
    4. Always verify holders on Bubblemaps / Solscan and run your own exit plan.
    
    **Key signals scored:**
    - Volume accelerating (h1 strong)
    - Buyers > sellers recent
    - Liquidity ≥ $5k–10k
    - Age < few hours
    - Positive short-term move
    """)
    st.divider()
    st.markdown("**Useful links**")
    st.markdown("- [DEXScreener New Pairs](https://dexscreener.com/solana?rankBy=pairAge&order=asc)")
    st.markdown("- [pump.fun](https://pump.fun)")
    st.markdown("- [Onchain Circle (callout monitors)](https://onchaincircle.app)")
    st.markdown("- [Bubblemaps](https://app.bubblemaps.io)")
    st.markdown("- [RugCheck](https://rugcheck.xyz)")
    st.divider()
    st.warning("Most memecoins die. Size small. DYOR.")

tab1, tab2, tab3 = st.tabs(["🔍 Token Checker", "🔎 Search", "📋 Signal Checklist"])

with tab1:
    st.subheader("Check a specific token (Solana)")
    ca = st.text_input("Token Contract Address (mint)", placeholder="e.g. 7dDnR136jiK3UDi7FpdRVueerDz8tvo1YgEEuvVHpump", key="ca_input")
    
    if st.button("Analyze", type="primary") or ca:
        if not ca or len(ca) < 32:
            st.info("Paste a valid Solana mint address.")
        else:
            with st.spinner("Fetching DEXScreener + RugCheck..."):
                pairs = fetch_dexscreener_token("solana", ca.strip())
                rug = fetch_rugcheck(ca.strip())

            if not pairs:
                st.warning("No pairs found on DEXScreener yet. Token may be brand new on bonding curve only (check pump.fun).")
            else:
                # Prefer the highest liquidity pair
                pair = max(pairs, key=lambda p: (p.get("liquidity", {}) or {}).get("usd") or 0)
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Price USD", pair.get("priceUsd", "N/A"))
                with col2:
                    st.metric("Market Cap / FDV", format_usd(pair.get("marketCap") or pair.get("fdv")))
                with col3:
                    st.metric("Liquidity", format_usd((pair.get("liquidity") or {}).get("usd")))
                with col4:
                    age_h = None
                    if pair.get("pairCreatedAt"):
                        age_h = round((datetime.now(timezone.utc).timestamp()*1000 - pair["pairCreatedAt"]) / 3600000, 1)
                    st.metric("Age (hours)", age_h if age_h is not None else "N/A")

                signals = compute_signals(pair)
                st.subheader(f"Signal Score: {signals['score']} / ~8")
                for note in signals["notes"]:
                    st.write(note)

                # Txns & Volume table
                st.subheader("Recent Activity")
                txns = pair.get("txns", {})
                vol = pair.get("volume", {})
                pc = pair.get("priceChange", {})
                df = pd.DataFrame({
                    "Window": ["5m", "1h", "6h", "24h"],
                    "Buys": [txns.get("m5", {}).get("buys"), txns.get("h1", {}).get("buys"), txns.get("h6", {}).get("buys"), txns.get("h24", {}).get("buys")],
                    "Sells": [txns.get("m5", {}).get("sells"), txns.get("h1", {}).get("sells"), txns.get("h6", {}).get("sells"), txns.get("h24", {}).get("sells")],
                    "Volume USD": [vol.get("m5"), vol.get("h1"), vol.get("h6"), vol.get("h24")],
                    "Price Change %": [pc.get("m5"), pc.get("h1"), pc.get("h6"), pc.get("h24")],
                })
                st.dataframe(df, use_container_width=True)

                st.markdown(f"**Pair URL:** [{pair.get('url', '')}]({pair.get('url', '')})")
                st.markdown(f"**Base:** {pair.get('baseToken', {}).get('name')} ({pair.get('baseToken', {}).get('symbol')})")

            # RugCheck summary
            if rug:
                st.subheader("RugCheck Snapshot")
                risks = rug.get("risks", [])
                score = rug.get("score") or rug.get("score_normalised")
                st.write(f"Score: **{score}**")
                if risks:
                    for r in risks[:8]:
                        st.write(f"- {r.get('name', '')}: {r.get('description', '')} (level: {r.get('level', '')})")
                else:
                    st.write("No major risks flagged in the report (still check manually).")
                top_holders = rug.get("topHolders", [])[:5]
                if top_holders:
                    st.write("Top holders (sample):")
                    for h in top_holders:
                        st.write(f"- {h.get('address', '')[:8]}... : {h.get('pct', 0):.1f}%")

with tab2:
    st.subheader("Quick Search (DEXScreener)")
    q = st.text_input("Search by name, symbol or partial CA", placeholder="e.g. HODL or duge or pump")
    if st.button("Search") or q:
        if q:
            results = fetch_dexscreener_search(q)
            if not results:
                st.info("No results.")
            else:
                # Filter Solana and sort by liquidity or volume
                sol_pairs = [p for p in results if p.get("chainId") == "solana"]
                sol_pairs = sorted(sol_pairs, key=lambda p: (p.get("liquidity", {}) or {}).get("usd") or 0, reverse=True)[:20]
                
                rows = []
                for p in sol_pairs:
                    sig = compute_signals(p)
                    rows.append({
                        "Symbol": p.get("baseToken", {}).get("symbol"),
                        "Name": p.get("baseToken", {}).get("name"),
                        "Price": p.get("priceUsd"),
                        "MCap": format_usd(p.get("marketCap") or p.get("fdv")),
                        "Liq": format_usd((p.get("liquidity") or {}).get("usd")),
                        "Age h": sig["age_hours"],
                        "Score": sig["score"],
                        "URL": p.get("url"),
                        "CA": p.get("baseToken", {}).get("address"),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, column_config={
                    "URL": st.column_config.LinkColumn("DEXScreener"),
                    "CA": st.column_config.TextColumn("CA (copy to checker)"),
                })

with tab3:
    st.subheader("Manual Signal Checklist (from the Reddit posts)")
    st.markdown("""
    ### Trader / Callout Signals
    - [ ] Several independent traders / influencers buying the same coin
    - [ ] Callers entered at low market cap and are **still holding**
    - [ ] Position sizes show real conviction (not dust)
    - [ ] Multiple sites (pump.fun / FOMO / Axiom) showing callouts

    ### On-chain / Chart Signals
    - [ ] **Volume speeding up** (recent window much stronger than earlier)
    - [ ] Buyers clearly outnumber sellers in last 5–60 minutes (many trades)
    - [ ] Known / tracked wallets buying quietly before social posts
    - [ ] The meme / phrase was trending **before** the coin was launched

    ### Token Health
    - [ ] Liquidity not paper-thin (enough to exit without massive slippage)
    - [ ] Holder concentration not extreme (check Bubblemaps / top holders)
    - [ ] No obvious mint / freeze authority still active (RugCheck / Solscan)
    - [ ] Volume comes from many makers, not a few wallets washing

    ### Kill signals
    - Creator launched many coins this week
    - Chart only moves in neat steps (possible no real sells)
    - Callers already fully dumped
    - Market cap already multiplied many times since first callouts
    """)
    st.info("Use the Token Checker tab to auto-score volume acceleration, buy pressure, liquidity and age. Combine with the manual checklist and Onchain Circle monitors.")

st.divider()
st.caption("Built for educational purposes from the public signals in the shared Reddit posts. Data from public DEXScreener & RugCheck APIs. Always verify on-chain and never risk more than you can afford to lose.")
