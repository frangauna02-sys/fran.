#!/usr/bin/env python3
"""Descarga los feeds RSS/Atom de feeds.json y genera data/news.json.

Solo usa la biblioteca estándar de Python. Lo ejecuta GitHub Actions
cada 30 minutos (ver .github/workflows/update-news.yml).
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "feeds.json"
OUT_FILE = ROOT / "data" / "news.json"

MAX_AGE_DAYS = 10        # se descartan noticias más viejas que esto
MAX_ITEMS = 600          # tope total
MAX_PER_FEED = 40        # tope por fuente en cada descarga
SUMMARY_LEN = 280
UA = "Mozilla/5.0 (compatible; NewsRadar/1.0; +https://github.com)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text).strip()
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    # quita colas típicas de WordPress: "The post X appeared first on Y."
    text = re.sub(r"\s*(The post|El post|La entrada) .* (appeared first on|aparece primero en|se publicó primero en) .*$", "", text)
    if len(text) > SUMMARY_LEN:
        text = text[:SUMMARY_LEN].rsplit(" ", 1)[0] + "…"
    return text


def parse_date(value: str):
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def text_of(el, path):
    found = el.find(path, NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def find_image(item, *html_blobs):
    for path in ("media:content", "media:thumbnail", "media:group/media:content"):
        for m in item.findall(path, NS):
            url = m.get("url")
            medium = m.get("medium", "image")
            if url and medium == "image":
                return url
    for enc in item.findall("enclosure"):
        if enc.get("type", "").startswith("image") and enc.get("url"):
            return enc.get("url")
    for blob in html_blobs:
        if blob:
            m = IMG_RE.search(blob)
            if m:
                return html.unescape(m.group(1))
    return ""


def parse_feed(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    tag = root.tag.lower()
    items = []
    if tag.endswith("feed"):  # Atom
        for e in root.findall("atom:entry", NS):
            link = ""
            for l in e.findall("atom:link", NS):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            content = text_of(e, "atom:content")
            summary = text_of(e, "atom:summary") or content
            items.append({
                "title": text_of(e, "atom:title"),
                "link": link,
                "date": parse_date(text_of(e, "atom:published") or text_of(e, "atom:updated")),
                "summary": summary,
                "image": find_image(e, content, summary),
            })
    else:  # RSS 2.0 / RDF
        nodes = root.findall("./channel/item") or root.findall(".//item") \
            or root.findall(".//{http://purl.org/rss/1.0/}item")
        for it in nodes:
            def g(name):
                v = it.find(name)
                if v is None:
                    v = it.find("{http://purl.org/rss/1.0/}" + name)
                return (v.text or "").strip() if v is not None and v.text else ""
            content = text_of(it, "content:encoded")
            desc = g("description")
            items.append({
                "title": g("title"),
                "link": g("link") or g("guid"),
                "date": parse_date(g("pubDate") or text_of(it, "dc:date")),
                "summary": desc or content,
                "image": find_image(it, content, desc),
            })
    return items


def fetch(feed, category):
    req = urllib.request.Request(feed["url"], headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
        raw_items = parse_feed(data.lstrip(b"\xef\xbb\xbf \r\n\t"))
    except Exception as exc:  # noqa: BLE001 - un feed caído no debe romper el resto
        print(f"  ✗ {feed['name']}: {exc}", file=sys.stderr)
        return feed["name"], []

    out = []
    now = datetime.now(timezone.utc)
    for it in raw_items[:MAX_PER_FEED]:
        if not it["title"] or not it["link"]:
            continue
        dt = it["date"] or now
        if dt > now + timedelta(hours=2):
            dt = now
        out.append({
            "title": clean_text(it["title"]),
            "link": it["link"],
            "date": dt.isoformat(),
            "summary": clean_text(it["summary"]),
            "image": it["image"],
            "source": feed["name"],
            "category": category,
            "lang": feed.get("lang", "en"),
        })
    print(f"  ✓ {feed['name']}: {len(out)} noticias")
    return feed["name"], out


def main():
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    jobs = [(f, cat) for cat, lst in feeds.items() for f in lst]

    previous = []
    if OUT_FILE.exists():
        try:
            previous = json.loads(OUT_FILE.read_text(encoding="utf-8")).get("items", [])
        except (json.JSONDecodeError, AttributeError):
            previous = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: fetch(*j), jobs))

    fresh = [item for _, items in results for item in items]
    ok_sources = [name for name, items in results if items]

    # Fusiona con lo anterior para no perder noticias si un feed falla un rato.
    merged = {}
    for item in previous + fresh:  # lo nuevo pisa lo viejo
        key = item["link"].split("?")[0].rstrip("/").lower()
        old = merged.get(key)
        if old and not item.get("image"):
            item["image"] = old.get("image", "")
        if old and old.get("first_seen"):
            item["first_seen"] = old["first_seen"]
        merged[key] = item

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    items = []
    seen_titles = set()
    for item in sorted(merged.values(), key=lambda x: x["date"], reverse=True):
        if parse_date(item["date"]) < cutoff:
            continue
        tkey = re.sub(r"\W+", "", item["title"].lower())[:80]
        if tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        item.setdefault("first_seen", now.isoformat())
        items.append(item)
    items = items[:MAX_ITEMS]

    if not fresh and previous:
        print("Ningún feed respondió; se conserva el archivo anterior.", file=sys.stderr)
        return 0

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "updated": now.isoformat(),
        "sources_ok": len(ok_sources),
        "sources_total": len(jobs),
        "count": len(items),
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Listo: {len(items)} noticias de {len(ok_sources)}/{len(jobs)} fuentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
