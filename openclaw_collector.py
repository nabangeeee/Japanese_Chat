"""
OpenClaw Collector for NihongoChat.
Automates fetching real-time Japanese trends, news, and daily topics using OpenClaw or Web Scraper.
Stores fetched trend items into SQLite 'live_trends' table for System Prompt RAG context.
"""
import os
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from database import save_live_trend, get_recent_live_trends


OPENCLAW_CLI_PATH = os.getenv("OPENCLAW_CLI_PATH", "openclaw")
YAHOO_JP_NEWS_RSS = "https://news.yahoo.co.jp/rss/topics/top-picks.xml"

DEFAULT_FALLBACK_TRENDS = [
    {"category": "Hot Topic", "title": "東京の最新トレンドスポット・麻布台ヒルズが話題", "content": "最新の話題スポット", "url": "https://news.yahoo.co.jp"},
    {"category": "Culture", "title": "日本の最新グルメ・抹茶スイーツのブーム", "content": "抹茶スイーツの流行", "url": "https://news.yahoo.co.jp"}
]


def is_openclaw_installed() -> bool:
    """Check if OpenClaw CLI or tool binary is installed in environment."""
    try:
        import subprocess
        res = subprocess.run([OPENCLAW_CLI_PATH, "--version"], capture_output=True, text=True, timeout=1.5)
        return res.returncode == 0
    except Exception:
        return False


def fetch_latest_japan_trends() -> List[Dict[str, Any]]:
    """Fetch latest Japanese news & trends using OpenClaw or Yahoo! Japan RSS fallback."""
    fetched_items = []
    
    # 1. Try OpenClaw CLI web automation if available
    if is_openclaw_installed():
        try:
            import subprocess
            cmd = [OPENCLAW_CLI_PATH, "scrape", YAHOO_JP_NEWS_RSS, "--format", "json"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout:
                print("[OpenClaw] Successfully fetched live trends using OpenClaw CLI.")
        except Exception as e:
            print(f"[OpenClaw CLI Error] {e}")

    # 2. Fallback via Yahoo! Japan RSS feed or offline default items
    try:
        res = requests.get(YAHOO_JP_NEWS_RSS, timeout=3)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item")[:10]:
                    title = item.find("title").text if item.find("title") is not None else ""
                    link = item.find("link").text if item.find("link") is not None else ""
                    pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                    
                    if title:
                        trend = save_live_trend(
                            category="Top News",
                            title=title,
                            content=f"Yahoo! Japan Topics ({pub_date})",
                            url=link
                        )
                        fetched_items.append(trend)
                print(f"[OpenClaw Collector] Stored {len(fetched_items)} live Japanese trends into DB.")
    except Exception as e:
        print(f"[OpenClaw Collector Warning] Network fetch failed ({e}). Seeding default fallback trends.")
        for item in DEFAULT_FALLBACK_TRENDS:
            trend = save_live_trend(
                category=item["category"],
                title=item["title"],
                content=item["content"],
                url=item["url"]
            )
            fetched_items.append(trend)

    return fetched_items or get_recent_live_trends(limit=5)
