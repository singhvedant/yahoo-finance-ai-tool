"""Load tests: 500+ symbols, 5y history, concurrency (marked; run with -m load)."""

from __future__ import annotations

import pytest

from yahoo_finance_ai.bulk import bulk_fetch
from yahoo_finance_ai.client import YahooClient
from yahoo_finance_ai.models import PriceHistory
from yahoo_finance_ai.service import YahooService

pytestmark = pytest.mark.load

US_SYMBOLS = [
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "UNH",
    "XOM", "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
    "LLY", "PEP", "KO", "AVGO", "COST", "WMT", "TMO", "MCD", "CSCO", "ACN",
    "ABT", "ADBE", "CRM", "LIN", "DHR", "TXN", "VZ", "NKE", "NEE", "PM",
    "ORCL", "WFC", "RTX", "BMY", "COP", "UPS", "T", "AMD", "HON", "QCOM",
    "LOW", "UNP", "INTC", "BA", "SPGI", "INTU", "CAT", "GE", "AMAT", "IBM",
    "SBUX", "PLD", "GS", "MS", "BLK", "MDT", "DE", "AXP", "GILD", "ISRG",
    "BKNG", "ADI", "TJX", "MMC", "ADP", "SYK", "VRTX", "CVS", "AMT", "C",
    "LRCX", "MO", "SCHW", "ZTS", "CI", "TMUS", "PGR", "FI", "MU", "BSX",
    "SO", "REGN", "DUK", "EQIX", "BDX", "PYPL", "AON", "CSX", "CL", "ITW",
    "ICE", "CME", "SNPS", "CDNS", "NOC", "EOG", "SLB", "WM", "FCX", "TGT",
    "HUM", "EMR", "MCK", "MPC", "PXD", "ORLY", "APD", "GD", "PSX", "ROP",
    "MMM", "MAR", "KLAC", "AJG", "F", "GM", "NXPI", "ADSK", "MSI", "FTNT",
    "ECL", "PH", "ANET", "MCHP", "TT", "VLO", "TDG", "CARR", "AIG", "HLT",
    "AZO", "SRE", "AEP", "TRV", "CTAS", "WMB", "PCAR", "NUE", "PAYX", "JCI",
    "AFL", "MSCI", "ALL", "OXY", "D", "MET", "KMB", "DXCM", "O", "STZ",
    "TEL", "COF", "ROST", "IDXX", "AME", "EW", "PRU", "BK", "CMG", "EXC",
    "YUM", "HES", "CTSH", "FAST", "IQV", "GEHC", "VRSK", "A", "OTIS", "CNC",
    "KMI", "GIS", "CPRT", "EA", "XEL", "CSGP", "EL", "DOW", "LHX", "RSG",
    "BIIB", "ED", "DD", "MNST", "VICI", "FIS", "ON", "KR", "WEC", "HSY",
    "EFX", "EXR", "MTB", "DG", "CDW", "FANG", "ANSS", "DLR", "AVB", "KEYS",
    "GPN", "TSCO", "PPG", "DVN", "WBD", "AWK", "ZBH", "FTV", "WST", "HPQ",
    "CHD", "RMD", "DAL", "TROW", "MTD", "SBAC", "HIG", "BR", "WY", "DFS",
    "EIX", "VMC", "NTRS", "STT", "ETR", "MLM", "APTV", "EQR", "FE", "PPL",
    "ES", "INVH", "IFF", "CBOE", "DTE", "AEE", "EBAY", "GPC", "TDY", "FITB",
    "CAH", "DOV", "VRSN", "STE", "HPE", "K", "WAB", "ROL", "IR", "CTRA",
    "ULTA", "WAT", "TSN", "PHM", "EXPD", "HBAN", "BAX", "DRI", "RF", "NDAQ",
    "LYB", "CNP", "MKC", "HOLX", "CMS", "CLX", "ATO", "WRB", "OMC", "BALL",
    "TER", "LH", "CINF", "EQT", "FSLR", "J", "CCL", "ARE", "LUV", "TXT",
    "FDS", "MOH", "SWKS", "AVY", "DGX", "AKAM", "ESS", "MAA", "POOL", "RVTY",
    "SYF", "NTAP", "CF", "LDOS", "MAS", "BBY", "PKG", "VTR", "AMCR", "HST",
    "IEX", "BG", "STLD", "SNA", "EXPE", "L", "TRMB", "JBHT", "LVS", "DPZ",
    "GEN", "KIM", "EVRG", "IP", "NDSN", "MGM", "PNR", "TAP", "KMX", "UDR",
    "LNT", "CPT", "JKHY", "CHRW", "ALB", "INCY", "NI", "TECH", "GL", "EMN",
    "CRL", "AOS", "REG", "PEAK", "QRVO", "FFIV", "WDC", "AIZ", "BXP", "RHI",
    "PNW", "JNPR", "UHS", "HSIC", "TPR", "NWSA", "ALLE", "BWA", "HII", "SEE",
    "WYNN", "CZR", "AAL", "MKTX", "FMC", "MOS", "APA", "IVZ", "FRT", "BEN",
    "CPB", "HRL", "PARA", "ETSY", "BIO", "GNRC", "CMA", "ZION", "DVA", "MHK",
    "WHR", "BBWI", "HAS", "VFC", "RL", "XRAY", "NCLH", "AES", "PAYC", "MTCH",
    "UBER", "ABNB", "PLTR", "SNOW", "SHOP", "SQ", "COIN", "RBLX", "NET", "DDOG",
]

INDIA_SYMBOLS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "BAJFINANCE.NS",
    "HCLTECH.NS", "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS",
    "NESTLEIND.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "M&M.NS",
    "TATAMOTORS.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "ADANIENT.NS", "ADANIPORTS.NS",
    "COALINDIA.NS", "BAJAJFINSV.NS", "HDFCLIFE.NS", "SBILIFE.NS", "GRASIM.NS",
    "TECHM.NS", "INDUSINDBK.NS", "HINDALCO.NS", "DRREDDY.NS", "CIPLA.NS",
    "EICHERMOT.NS", "BRITANNIA.NS", "APOLLOHOSP.NS", "DIVISLAB.NS", "TATACONSUM.NS",
    "BPCL.NS", "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "UPL.NS", "SHREECEM.NS",
    "VEDL.NS", "GODREJCP.NS", "DABUR.NS", "PIDILITIND.NS", "SIEMENS.NS",
    "HAVELLS.NS", "AMBUJACEM.NS", "DLF.NS", "GAIL.NS", "BANKBARODA.NS",
    "IOC.NS", "ZOMATO.NS", "PAYTM.NS", "NYKAA.NS", "IRCTC.NS",
    "INDIGO.NS", "PNB.NS", "CANBK.NS", "UNIONBANK.NS", "IDFCFIRSTB.NS",
    "FEDERALBNK.NS", "LUPIN.NS", "AUROPHARMA.NS", "BIOCON.NS", "TORNTPHARM.NS",
    "MUTHOOTFIN.NS", "CHOLAFIN.NS", "LICHSGFIN.NS", "PFC.NS", "RECLTD.NS",
    "TVSMOTOR.NS", "ASHOKLEY.NS", "BHARATFORG.NS", "MOTHERSON.NS", "BOSCHLTD.NS",
    "BERGEPAINT.NS", "MARICO.NS", "COLPAL.NS", "PGHH.NS", "GILLETTE.NS",
    "PERSISTENT.NS", "COFORGE.NS", "LTIM.NS", "MPHASIS.NS", "OFSS.NS",
    "RELIANCE.BO", "TCS.BO", "HDFCBANK.BO", "INFY.BO", "ICICIBANK.BO",
    "SBIN.BO", "ITC.BO", "TATAMOTORS.BO", "TATASTEEL.BO", "WIPRO.BO",
]

ALL_SYMBOLS = US_SYMBOLS + INDIA_SYMBOLS


def _success_rate(results: dict) -> float:
    ok = sum(1 for v in results.values() if isinstance(v, PriceHistory))
    return ok / max(1, len(results))


@pytest.mark.timeout(1800)
async def test_bulk_price_500_symbols_5y() -> None:
    """500 symbols (US + NSE/BSE), 5 years daily history, concurrency 8."""
    assert len(ALL_SYMBOLS) >= 500
    client = YahooClient(rate=6.0, burst=10)
    async with YahooService(client=client) as service:
        results = await bulk_fetch(
            service, ALL_SYMBOLS, dataset="price", range_="5y", interval="1d", concurrency=8
        )
    assert len(results) == len(ALL_SYMBOLS)
    rate = _success_rate(results)
    failures = {s: v for s, v in results.items() if not isinstance(v, PriceHistory)}
    print(f"\nload: {len(results)} symbols, success rate {rate:.1%}, failures: {len(failures)}")
    for s, v in list(failures.items())[:10]:
        print(f"  {s}: {v}")
    assert rate >= 0.80
    # spot-check depth: AAPL should have ~1250 daily candles over 5y
    aapl = results.get("AAPL")
    if isinstance(aapl, PriceHistory):
        assert len(aapl.candles) > 1000


@pytest.mark.timeout(900)
async def test_bulk_snapshot_25_symbols() -> None:
    """Heavier per-symbol dataset on a 25-symbol US+India mix."""
    symbols = US_SYMBOLS[:15] + INDIA_SYMBOLS[:10]
    async with YahooService(client=YahooClient(rate=4.0, burst=8)) as service:
        results = await bulk_fetch(service, symbols, dataset="snapshot", concurrency=5)
    ok = sum(1 for v in results.values() if not (isinstance(v, dict) and "error" in v))
    print(f"\nsnapshot load: {ok}/{len(symbols)} succeeded")
    assert ok / len(symbols) >= 0.8
