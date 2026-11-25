"""Universe definition: asset classes -> groups -> instruments.

Edit this file to add or remove instruments. Tickers are Yahoo Finance symbols.
Crypto members are not listed here: they are the live top-10 by market cap
(see sources.fetch_crypto) and are filled in at run time.
"""

BENCHMARK = "ACWI"  # world equities, base for class-level relative strength
CASH = "BIL"

# Each class: id, name, proxy (the instrument that represents the class),
# items: list of instruments; an item may have "items" of its own (sector -> stocks).
# "noagg": shown in drill-down but excluded from breadth / flow aggregates.
CLASSES = [
    {
        "id": "us_eq", "name": "US Equities", "proxy": "SPY",
        "items": [
            {"t": "SPY", "n": "S&P 500", "noagg": True},
            {"t": "RSP", "n": "S&P 500 equal-weight", "noagg": True},
            {"t": "QQQ", "n": "Nasdaq 100", "noagg": True},
            {"t": "IWM", "n": "Russell 2000 (small caps)", "noagg": True},
            {"t": "XLK", "n": "Technology", "items": [
                {"t": "NVDA", "n": "NVIDIA"}, {"t": "AAPL", "n": "Apple"}, {"t": "MSFT", "n": "Microsoft"},
                {"t": "AVGO", "n": "Broadcom"}, {"t": "ORCL", "n": "Oracle"}, {"t": "AMD", "n": "AMD"}]},
            {"t": "XLF", "n": "Financials", "items": [
                {"t": "BRK-B", "n": "Berkshire Hathaway"}, {"t": "JPM", "n": "JPMorgan"}, {"t": "V", "n": "Visa"},
                {"t": "MA", "n": "Mastercard"}, {"t": "BAC", "n": "Bank of America"}, {"t": "GS", "n": "Goldman Sachs"}]},
            {"t": "XLV", "n": "Health care", "items": [
                {"t": "LLY", "n": "Eli Lilly"}, {"t": "UNH", "n": "UnitedHealth"}, {"t": "JNJ", "n": "Johnson & Johnson"},
                {"t": "ABBV", "n": "AbbVie"}, {"t": "MRK", "n": "Merck"}, {"t": "ISRG", "n": "Intuitive Surgical"}]},
            {"t": "XLY", "n": "Consumer discretionary", "items": [
                {"t": "AMZN", "n": "Amazon"}, {"t": "TSLA", "n": "Tesla"}, {"t": "HD", "n": "Home Depot"},
                {"t": "MCD", "n": "McDonald's"}, {"t": "BKNG", "n": "Booking"}]},
            {"t": "XLC", "n": "Communication services", "items": [
                {"t": "META", "n": "Meta"}, {"t": "GOOGL", "n": "Alphabet"}, {"t": "NFLX", "n": "Netflix"},
                {"t": "DIS", "n": "Disney"}, {"t": "TMUS", "n": "T-Mobile US"}]},
            {"t": "XLI", "n": "Industrials", "items": [
                {"t": "GE", "n": "GE Aerospace"}, {"t": "CAT", "n": "Caterpillar"}, {"t": "RTX", "n": "RTX"},
                {"t": "UBER", "n": "Uber"}, {"t": "HON", "n": "Honeywell"}, {"t": "BA", "n": "Boeing"}]},
            {"t": "XLE", "n": "Energy", "items": [
                {"t": "XOM", "n": "Exxon Mobil"}, {"t": "CVX", "n": "Chevron"}, {"t": "COP", "n": "ConocoPhillips"},
                {"t": "SLB", "n": "SLB"}, {"t": "EOG", "n": "EOG Resources"}]},
            {"t": "XLP", "n": "Consumer staples", "items": [
                {"t": "WMT", "n": "Walmart"}, {"t": "COST", "n": "Costco"}, {"t": "PG", "n": "Procter & Gamble"},
                {"t": "KO", "n": "Coca-Cola"}, {"t": "PEP", "n": "PepsiCo"}]},
            {"t": "XLU", "n": "Utilities", "items": [
                {"t": "NEE", "n": "NextEra Energy"}, {"t": "SO", "n": "Southern Co"}, {"t": "DUK", "n": "Duke Energy"},
                {"t": "CEG", "n": "Constellation Energy"}]},
            {"t": "XLB", "n": "Materials", "items": [
                {"t": "LIN", "n": "Linde"}, {"t": "SHW", "n": "Sherwin-Williams"}, {"t": "FCX", "n": "Freeport-McMoRan"},
                {"t": "NEM", "n": "Newmont"}]},
            {"t": "XLRE", "n": "Real estate", "items": [
                {"t": "PLD", "n": "Prologis"}, {"t": "AMT", "n": "American Tower"}, {"t": "EQIX", "n": "Equinix"},
                {"t": "WELL", "n": "Welltower"}]},
        ],
    },
    {
        "id": "dm_eq", "name": "DM Equities", "proxy": "EFA",
        "items": [
            {"t": "EFA", "n": "Developed ex-US", "noagg": True},
            {"t": "VGK", "n": "Europe"}, {"t": "EWJ", "n": "Japan"}, {"t": "EWU", "n": "United Kingdom"},
            {"t": "EWG", "n": "Germany"}, {"t": "EWC", "n": "Canada"}, {"t": "EWA", "n": "Australia"},
        ],
    },
    {
        "id": "em_eq", "name": "EM Equities", "proxy": "EEM",
        "items": [
            {"t": "EEM", "n": "Emerging markets", "noagg": True},
            {"t": "MCHI", "n": "China"}, {"t": "INDA", "n": "India"}, {"t": "EWT", "n": "Taiwan"},
            {"t": "EWY", "n": "South Korea"}, {"t": "EWZ", "n": "Brazil"}, {"t": "EWW", "n": "Mexico"},
        ],
    },
    {
        "id": "govt", "name": "Treasuries", "proxy": "IEF",
        "items": [
            {"t": "SHY", "n": "1–3 year"}, {"t": "IEI", "n": "3–7 year"}, {"t": "IEF", "n": "7–10 year"},
            {"t": "TLT", "n": "20+ year"}, {"t": "TIP", "n": "Inflation-linked (TIPS)"}, {"t": "BWX", "n": "World ex-US govt"},
        ],
    },
    {
        "id": "credit", "name": "Credit", "proxy": "HYG",
        "items": [
            {"t": "LQD", "n": "Investment grade"}, {"t": "HYG", "n": "High yield"},
            {"t": "EMB", "n": "EM sovereign debt"}, {"t": "BKLN", "n": "Leveraged loans"},
        ],
    },
    {
        "id": "precious", "name": "Precious metals", "proxy": "GLD",
        "items": [
            {"t": "GLD", "n": "Gold"}, {"t": "SLV", "n": "Silver"}, {"t": "PPLT", "n": "Platinum"},
            {"t": "PALL", "n": "Palladium"}, {"t": "GDX", "n": "Gold miners"}, {"t": "GDXJ", "n": "Junior gold miners"},
        ],
    },
    {
        "id": "indmet", "name": "Industrial metals", "proxy": "CPER",
        "items": [
            {"t": "CPER", "n": "Copper"}, {"t": "DBB", "n": "Base metals basket"},
            {"t": "COPX", "n": "Copper miners"}, {"t": "LIT", "n": "Lithium & battery"},
        ],
    },
    {
        "id": "energy", "name": "Energy", "proxy": "USO",
        "items": [
            {"t": "USO", "n": "Crude oil (WTI)"}, {"t": "BNO", "n": "Crude oil (Brent)"},
            {"t": "UNG", "n": "Natural gas"}, {"t": "URA", "n": "Uranium"},
        ],
    },
    {
        "id": "agri", "name": "Agriculture", "proxy": "DBA",
        "items": [
            {"t": "DBA", "n": "Agriculture basket"}, {"t": "CORN", "n": "Corn"}, {"t": "WEAT", "n": "Wheat"},
            {"t": "SOYB", "n": "Soybeans"}, {"t": "KC=F", "n": "Coffee (futures)"}, {"t": "SB=F", "n": "Sugar (futures)"},
            {"t": "CC=F", "n": "Cocoa (futures)"},
        ],
    },
    {
        "id": "fx", "name": "FX", "proxy": "UUP",
        "items": [
            {"t": "UUP", "n": "US dollar (ETF)"}, {"t": "DX-Y.NYB", "n": "US dollar index (DXY)", "noagg": True},
            {"t": "EURUSD=X", "n": "EUR/USD"}, {"t": "USDJPY=X", "n": "USD/JPY"}, {"t": "GBPUSD=X", "n": "GBP/USD"},
            {"t": "AUDUSD=X", "n": "AUD/USD"}, {"t": "CNY=X", "n": "USD/CNY"},
        ],
    },
    {
        "id": "crypto", "name": "Crypto", "proxy": "CRYPTO10",
        # items are filled at run time with the live top-10; these two are always added
        "items": [],
        "extra": [
            {"t": "IBIT", "n": "Spot BTC ETF (IBIT)", "noagg": True},
            {"t": "ETHA", "n": "Spot ETH ETF (ETHA)", "noagg": True},
        ],
    },
]

# Extra Yahoo series used by the overview (not shown as rows)
AUX = ["ACWI", "BIL", "DBC", "^VIX", "^MOVE"]

# FRED series
FRED = {
    "WALCL": "Fed balance sheet",
    "WTREGEN": "Treasury General Account",
    "RRPONTSYD": "Reverse repo",
    "DFII10": "10Y real yield",
    "T10YIE": "10Y breakeven inflation",
    "T10Y2Y": "10Y-2Y curve",
    "BAMLH0A0HYM2": "HY credit spread",
}

# Crypto: excluded from the top-10 (stablecoins, wrapped / staked copies)
CRYPTO_EXCLUDE_IDS = {
    "tether", "usd-coin", "ethena-usde", "dai", "first-digital-usd", "usds", "paypal-usd", "usd1-wlfi",
    "true-usd", "binance-usd", "falcon-usd", "global-dollar", "ripple-usd", "blackrock-usd-institutional-digital-liquidity-fund",
    "staked-ether", "wrapped-steth", "wrapped-bitcoin", "weth", "wrapped-beacon-eth", "coinbase-wrapped-btc",
    "wrapped-eeth", "rocket-pool-eth", "jito-staked-sol", "binance-bridged-usdt-bnb-smart-chain",
    "ethena-staked-usde", "lombard-staked-btc", "solv-btc", "wrapped-solana", "binance-staked-sol",
    "susds", "bitcoin-avalanche-bridged-btc-b", "kelp-dao-restaked-eth", "mantle-staked-ether",
}
CRYPTO_EXCLUDE_IDS |= {"figure-heloc"}
CRYPTO_EXCLUDE_SYMBOL_HINTS = ("usd", "eur")  # symbols containing these are treated as stablecoins
# names containing these are tokenized loans / treasuries / funds, not crypto assets
CRYPTO_EXCLUDE_NAME_HINTS = ("heloc", "treasury", "treasuries", "tokenized", "money market", "institutional digital liquidity")
CRYPTO_TOP_N = 10
CRYPTO_EXIT_RANK = 12  # hysteresis: a member leaves only when it falls below this rank


def all_yahoo_tickers():
    out = set(AUX)
    def walk(items):
        for it in items:
            out.add(it["t"])
            walk(it.get("items", []))
    for c in CLASSES:
        if c["proxy"] != "CRYPTO10":
            out.add(c["proxy"])
        walk(c["items"])
        walk(c.get("extra", []))
    return sorted(out)
