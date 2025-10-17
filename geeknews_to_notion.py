import os
import time
from datetime import datetime
from typing import Optional, List

import feedparser
from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup


def isoformat(dt_struct):
    try:
        return datetime(*dt_struct[:6]).isoformat()
    except Exception:
        return None


def summarize_with_openai(title: str, url: str, description: Optional[str] = None, lang: str = "ko") -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        # Lazy import to avoid hard dependency if user doesn't set a key
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        content_hint = f"\n본문: {description[:800]}" if description else ""
        prompt = (
            f"다음 링크의 기사 내용을 {lang}로 2~3문장으로 간결히 요약해 주세요.\n"
            f"제목: {title}\n링크: {url}{content_hint}"
        )

        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "당신은 핵심만 간결히 정리하는 요약 비서입니다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=180,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None


def notion_find_by_url(notion: NotionClient, database_id: str, url: str) -> bool:
    try:
        res = notion.databases.query(
            **{
                "database_id": database_id,
                "filter": {"property": "URL", "url": {"equals": url}},
                "page_size": 1,
            }
        )
        return len(res.get("results", [])) > 0
    except APIResponseError as e:
        print(f"[warn] Notion query failed: {e}")
        return False


def notion_create_page(
    notion: NotionClient,
    database_id: str,
    *,
    title: str,
    url: str,
    summary: Optional[str],
    published_iso: Optional[str],
    tags: Optional[List[str]],
    source_label: str = "GeekNews",
):
    properties: dict = {
        "Name": {"title": [{"text": {"content": title or "Untitled"}}]},
        "URL": {"url": url},
        "Source": {"select": {"name": source_label}},
    }
    if summary:
        properties["Summary"] = {"rich_text": [{"text": {"content": summary}}]}
    if published_iso:
        properties["Published"] = {"date": {"start": published_iso}}
    if tags:
        properties["Tags"] = {"multi_select": [{"name": t} for t in tags[:10]]}

    return notion.pages.create(parent={"database_id": database_id}, properties=properties)


def main():
    load_dotenv()

    notion_token = os.getenv("NOTION_TOKEN")

    def normalize_db_id(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return raw
        s = raw.strip()
        # If it's a full URL, pick the 32-hex id part
        import re
        m = re.search(r"([0-9a-fA-F]{32})", s.replace("-", ""))
        if m:
            return m.group(1)
        return s

    database_id = normalize_db_id(os.getenv("NOTION_DATABASE_ID"))
    feed_url = os.getenv("FEED_URL", "https://news.hada.io/rss")
    summary_lang = os.getenv("SUMMARY_LANGUAGE", "ko")
    max_items = int(os.getenv("MAX_ITEMS", "30"))

    if not notion_token or not database_id:
        print("[error] NOTION_TOKEN 또는 NOTION_DATABASE_ID가 설정되지 않았습니다 (.env 확인)")
        raise SystemExit(1)

    notion = NotionClient(auth=notion_token)

    def fetch_items(url: str):
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
                    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
                },
                timeout=15,
                allow_redirects=True,
            )
            resp.raise_for_status()
            f = feedparser.parse(resp.text)
        except Exception as ex:
            print(f"[warn] feed request failed: {ex}")
            return []
        entries = getattr(f, "entries", []) or []
        if getattr(f, "bozo", 0) and getattr(f, "bozo_exception", None):
            print(f"[warn] feed parse warning: {getattr(f, 'bozo_exception')}")
        return entries

    candidates = [
        feed_url,
        feed_url.rstrip("/") + "/",
        feed_url.replace("https://", "http://"),
        feed_url.replace("https://", "http://").rstrip("/") + "/",
    ]
    items = []
    for u in candidates:
        print(f"[info] Fetching feed: {u}")
        items = fetch_items(u)
        if items:
            break
    if not items:
        # Fallback: scrape HTML pages
        def scrape(url: str):
            try:
                r = requests.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Referer": "https://news.hada.io/",
                    },
                    timeout=15,
                    allow_redirects=True,
                )
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                rows = soup.select("div.topics div.topic_row")
                parsed = []
                for row in rows:
                    a = row.select_one("div.topictitle a[href]")
                    if not a:
                        continue
                    title = a.get_text(strip=True)
                    link = a.get("href")
                    # points
                    points = None
                    pts = row.select_one("div.topicinfo span[id^='tp']")
                    if pts:
                        try:
                            points = int(pts.get_text(strip=True))
                        except Exception:
                            points = None
                    # desc snippet
                    desc_a = row.select_one("div.topicdesc a")
                    snippet = None
                    if desc_a:
                        snippet = desc_a.get_text(" ", strip=True)
                    # Internal topic id
                    topic_anchor = row.select_one("div.topicdesc a[href*='topic?id=']")
                    topic_url = None
                    if topic_anchor:
                        href = topic_anchor.get("href")
                        if href and not href.startswith("http"):
                            topic_url = f"https://news.hada.io/{href.lstrip('/')}"
                    parsed.append({
                        "title": title,
                        "link": link,
                        "topic": topic_url,
                        "points": points,
                        "snippet": snippet,
                    })
                return parsed
            except Exception as ex:
                print(f"[warn] scrape failed for {url}: {ex}")
                return []

        items = scrape("https://news.hada.io/new")
        if not items:
            items = scrape("https://news.hada.io/")

        # Map to feed-like dicts
        items = [
            {
                "title": it["title"],
                "link": it["link"],
                "summary": it.get("snippet"),
                "description": it.get("snippet"),
                "topic": it.get("topic"),
                "points": it.get("points"),
            }
            for it in items
        ]

    items = items[:max_items]
    print(f"[info] {len(items)} items fetched")

    def get(entry, key, alt_keys=None):
        alt_keys = alt_keys or []
        if isinstance(entry, dict):
            for k in [key] + alt_keys:
                if k in entry and entry[k] is not None:
                    return entry[k]
            return None
        else:
            for k in [key] + alt_keys:
                v = getattr(entry, k, None)
                if v is not None:
                    return v
            return None

    # Filters
    include_keywords = [s.strip() for s in os.getenv("INCLUDE_KEYWORDS", "").split(",") if s.strip()]
    exclude_keywords = [s.strip() for s in os.getenv("EXCLUDE_KEYWORDS", "").split(",") if s.strip()]
    try:
        min_points = int(os.getenv("MIN_POINTS", "0"))
    except ValueError:
        min_points = 0

    def passes_filters(title: Optional[str], description: Optional[str], points: Optional[int]) -> bool:
        hay = ((title or "") + " " + (description or "")).lower()
        if include_keywords:
            if not any(k.lower() in hay for k in include_keywords):
                return False
        if exclude_keywords:
            if any(k.lower() in hay for k in exclude_keywords):
                return False
        if min_points and (points or 0) < min_points:
            return False
        return True

    created = 0
    for i, entry in enumerate(items, start=1):
        link = get(entry, "link")
        title = get(entry, "title")
        description = get(entry, "summary", ["description"]) or None
        published = get(entry, "published_parsed")
        tags = None
        maybe_tags = get(entry, "tags")
        if maybe_tags:
            try:
                tags = [t.get("term") for t in maybe_tags if t.get("term")] or None
            except Exception:
                tags = None

        if not link:
            continue

        print(f"[info] [{i}] {title}")

        # Filters
        pts = get(entry, "points")
        if not passes_filters(title, description, pts):
            print("  ↳ skip by filters")
            continue

        # Skip if exists
        if notion_find_by_url(notion, database_id, link):
            print("  ↳ already exists, skip")
            continue

        # Summarize (optional)
        summary = summarize_with_openai(title or "", link, description, lang=summary_lang)

        # Date
        published_iso = isoformat(published) if published else None

        # Create
        try:
            notion_create_page(
                notion,
                database_id,
                title=title or link,
                url=link,
                summary=summary,
                published_iso=published_iso,
                tags=tags,
            )
            created += 1
            print("  ↳ Notion page created")
        except APIResponseError as e:
            print(f"  ↳ [error] Notion error: {e}")
            # Basic backoff if rate limited
            if getattr(e, "status", None) == 429:
                time.sleep(2)

    print(f"[done] Created {created} new pages")


if __name__ == "__main__":
    main()
