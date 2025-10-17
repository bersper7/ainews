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
try:
    from readability import Document  # type: ignore
except Exception:
    Document = None


def isoformat(dt_struct):
    try:
        return datetime(*dt_struct[:6]).isoformat()
    except Exception:
        return None


def summarize_with_openai(title: str, url: str, description: Optional[str] = None, lang: str = "ko", mode: str = "short") -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        # Lazy import to avoid hard dependency if user doesn't set a key
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        content_hint = f"\n본문 요약/발췌: {description[:1200]}" if description else ""
        if mode == "detailed":
            prompt = (
                f"다음 링크의 콘텐츠를 {lang}로 핵심 정리해 주세요.\n"
                f"- 형식: 4~7개 불릿 포인트, 가능한 한 구체적으로.\n"
                f"- 불필요한 수식어 최소화, 핵심 내용 위주.\n"
                f"제목: {title}\n링크: {url}{content_hint}"
            )
        elif mode == "translate":
            prompt = (
                f"다음 링크의 글 주요 내용을 {lang}로 자연스럽게 번역·정리해 주세요.\n"
                f"- 형식: 문단 중심, 핵심 주제별로 3~6개 문단.\n"
                f"- 과한 의역은 피하고, 맥락은 유지해서 읽기 쉽게.\n"
                f"제목: {title}\n링크: {url}{content_hint}"
            )
        else:
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


def fetch_main_text(url: str, timeout: int = 20) -> Optional[str]:
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://news.hada.io/",
            },
            timeout=timeout,
            allow_redirects=True,
        )
        r.raise_for_status()
    except Exception:
        return None
    try:
        if Document is not None:
            doc = Document(r.text)
            html = doc.summary(html_partial=True)
            soup = BeautifulSoup(html, "lxml")
            text = "\n\n".join(p.get_text(" ", strip=True) for p in soup.find_all(["p", "li"]))
        else:
            soup = BeautifulSoup(r.text, "lxml")
            candidates = soup.select("article, main, .post, .content, .entry, #content")
            if not candidates:
                candidates = [soup]
            best = max(candidates, key=lambda el: len(el.get_text(" ", strip=True)))
            text = "\n\n".join(p.get_text(" ", strip=True) for p in best.find_all(["p", "li"]))
        text = (text or "").strip()
        if len(text) > 8000:
            text = text[:8000]
        return text or None
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

    # Page content blocks (children)
    children = []
    # Bookmark to original link
    if url:
        children.append({
            "object": "block",
            "type": "bookmark",
            "bookmark": {"url": url},
        })

    # Detailed KR translation/summary section
    add_content = os.getenv("ADD_PAGE_CONTENT", "true").lower() in ("1", "true", "yes")
    page_mode = os.getenv("PAGE_CONTENT_MODE", "translate").lower()  # translate | detailed | short
    if add_content:
        generated_text = None
        mode_for_llm = "translate" if page_mode in ("translate", "translation") else ("detailed" if page_mode == "detailed" else "short")
        seed_text = summary or None
        if mode_for_llm == "translate":
            seed_text = fetch_main_text(url) or summary or None
        generated_text = summarize_with_openai(title or "", url, seed_text, lang=os.getenv("SUMMARY_LANGUAGE", "ko"), mode=mode_for_llm)

        heading_label = "번역 (KR)" if mode_for_llm == "translate" else "요약 (KR)"
        if generated_text:
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading_label}}]},
            })
            # If translate mode, prefer paragraphs; else bullet lines
            if mode_for_llm == "translate":
                for para in [p.strip() for p in (generated_text.split("\n\n") or []) if p.strip()]:
                    children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": para}}]},
                    })
            else:
                for line in [l.strip("- •\t ") for l in (generated_text.splitlines() or []) if l.strip()]:
                    children.append({
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line}}]},
                    })
        elif summary:
            # Fallback to a single paragraph with short summary
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading_label}}]},
            })
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary}}]},
            })

    return notion.pages.create(parent={"database_id": database_id}, properties=properties, children=children or None)


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

        # Summarize (optional): only for property Summary (1-line)
        short_summary = summarize_with_openai(title or "", link, description, lang=summary_lang, mode="short")

        # Date
        published_iso = isoformat(published) if published else None

        # Create
        try:
            notion_create_page(
                notion,
                database_id,
                title=title or link,
                url=link,
                summary=short_summary or (description or None),
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

def backfill_page_content(notion: NotionClient, database_id: str, limit: int = 20):
    # Query recent pages and add content if missing
    try:
        res = notion.databases.query(
            **{
                "database_id": database_id,
                "page_size": min(100, max(1, limit)),
                "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            }
        )
    except APIResponseError as e:
        print(f"[warn] backfill query failed: {e}")
        return
    for page in res.get("results", []):
        pid = page.get("id")
        props = page.get("properties", {})
        title = None
        if "Name" in props and props["Name"].get("title"):
            title = props["Name"]["title"][0].get("plain_text")
        url = None
        if "URL" in props and props["URL"].get("url"):
            url = props["URL"]["url"]
        if not pid or not url:
            continue
        try:
            blocks = notion.blocks.children.list(block_id=pid, page_size=20)
            has_translation = False
            for b in blocks.get("results", []):
                t = b.get("type")
                if t == "heading_2":
                    texts = b.get(t, {}).get("rich_text", [])
                    label = "".join([x.get("plain_text", "") for x in texts])
                    if "번역" in label:
                        has_translation = True
                        break
            if has_translation:
                continue
        except APIResponseError as e:
            print(f"[warn] backfill blocks list failed: {e}")
            continue

        # Generate translation content
        page_mode = os.getenv("PAGE_CONTENT_MODE", "translate").lower()
        mode_for_llm = "translate" if page_mode in ("translate", "translation") else ("detailed" if page_mode == "detailed" else "short")
        seed_text = None
        if mode_for_llm == "translate":
            seed_text = fetch_main_text(url)
        text = summarize_with_openai(title or "", url, seed_text, lang=os.getenv("SUMMARY_LANGUAGE", "ko"), mode=mode_for_llm)
        if not text:
            continue
        heading_label = "번역 (KR)" if mode_for_llm == "translate" else "요약 (KR)"
        children = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading_label}}]},
            }
        ]
        if mode_for_llm == "translate":
            for para in [p.strip() for p in (text.split("\n\n") or []) if p.strip()]:
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": para}}]},
                })
        else:
            for line in [l.strip("- •\t ") for l in (text.splitlines() or []) if l.strip()]:
                children.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line}}]},
                })
        try:
            notion.blocks.children.append(block_id=pid, children=children)
            print(f"  ↳ backfilled content for page: {title}")
        except APIResponseError as e:
            print(f"  ↳ [warn] backfill append failed: {e}")


if __name__ == "__main__":
    main()
    # Optional backfill for existing pages
    try:
        if os.getenv("BACKFILL_EXISTING", "false").lower() in ("1", "true", "yes"):
            limit = int(os.getenv("BACKFILL_LIMIT", "20"))
            notion = NotionClient(auth=os.getenv("NOTION_TOKEN"))
            dbid = os.getenv("NOTION_DATABASE_ID")
            # normalize
            import re
            m = re.search(r"([0-9a-fA-F]{32})", (dbid or "").replace("-", ""))
            if m:
                dbid = m.group(1)
            if notion and dbid:
                backfill_page_content(notion, dbid, limit)
    except Exception:
        pass
