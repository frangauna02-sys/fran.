#!/usr/bin/env python3
"""Descarga los feeds RSS/Atom de feeds.json y genera data/news.json.

Solo usa la biblioteca estándar de Python. Lo ejecuta GitHub Actions
cada 30 minutos (ver .github/workflows/update-news.yml).
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html.entities import name2codepoint
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "feeds.json"
OUT_FILE = ROOT / "data" / "news.json"

MAX_AGE_DAYS = 10        # se descartan noticias más viejas que esto
MAX_ITEMS = 900          # tope total
MAX_PER_FEED = 15        # tope por fuente en cada descarga (se puede cambiar con "max")
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
    for path in ("media:content", "media:thumbnail", "media:group/media:content", "media:group/media:thumbnail"):
        for m in item.findall(path, NS):
            url = m.get("url")
            medium = m.get("medium", "image")
            if url and (medium == "image" or m.tag.endswith("thumbnail")):
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
            summary = text_of(e, "atom:summary") or content or text_of(e, "media:group/media:description")
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


XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
BARE_AMP_RE = re.compile(r"&(?!#\d+;|#x[0-9a-fA-F]+;|[a-zA-Z][a-zA-Z0-9]*;)")
ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]*);")
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def repair_xml(data: bytes) -> bytes:
    """Arregla errores comunes de formato: & sueltos, entidades HTML y caracteres inválidos."""
    text = data.decode("utf-8", errors="replace")
    text = CTRL_RE.sub("", text)
    text = BARE_AMP_RE.sub("&amp;", text)

    def ent(m):
        name = m.group(1)
        if name in XML_ENTITIES:
            return m.group(0)
        cp = name2codepoint.get(name)
        return f"&#{cp};" if cp else f"&amp;{name};"

    return ENTITY_RE.sub(ent, text).encode("utf-8")


ITEM_RE = re.compile(r"<(item|entry)[\s>].*?</\1>", re.S | re.I)


def _tag(block, name):
    m = re.search(rf"<{name}(?:\s[^>]*)?>(.*?)</{name}>", block, re.S | re.I)
    if not m:
        return ""
    val = m.group(1).strip()
    cdata = re.fullmatch(r"<!\[CDATA\[(.*)\]\]>", val, re.S)
    return (cdata.group(1) if cdata else html.unescape(val)).strip()


def parse_lenient(data: bytes):
    """Último recurso para feeds con XML roto: extrae las noticias con expresiones regulares."""
    text = data.decode("utf-8", errors="replace")
    items = []
    for m in ITEM_RE.finditer(text):
        block = m.group(0)
        link = _tag(block, "link")
        if not link:
            lm = re.search(r"<link[^>]+href=[\"']([^\"']+)", block, re.I)
            link = html.unescape(lm.group(1)) if lm else _tag(block, "guid")
        content = _tag(block, "content:encoded") or _tag(block, "content")
        desc = _tag(block, "description") or _tag(block, "summary") or content
        im = re.search(r"<(?:media:content|media:thumbnail|enclosure)[^>]+url=[\"']([^\"']+)", block, re.I)
        image = html.unescape(im.group(1)) if im else ""
        if not image:
            im = IMG_RE.search(content or desc)
            image = html.unescape(im.group(1)) if im else ""
        items.append({
            "title": _tag(block, "title"),
            "link": link.strip(),
            "date": parse_date(_tag(block, "pubDate") or _tag(block, "dc:date") or _tag(block, "published") or _tag(block, "updated")),
            "summary": desc,
            "image": image,
        })
    return items


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (500, 502, 503, 504) and attempt == 0:
                time.sleep(3)  # error momentáneo del servidor: un reintento
                continue
            raise


def fetch(feed, category):
    urls = feed["url"] if isinstance(feed["url"], list) else [feed["url"]]
    raw_items, errors = None, []
    for url in urls:  # direcciones alternativas de la misma fuente
        try:
            data = download(url).lstrip(b"\xef\xbb\xbf \r\n\t")
            try:
                raw_items = parse_feed(data)
            except ET.ParseError:
                try:
                    raw_items = parse_feed(repair_xml(data))
                except ET.ParseError as exc:
                    raw_items = parse_lenient(data)
                    if not raw_items:
                        raise ValueError(f"no es un feed válido ({exc})") from exc
            if raw_items:
                break
            errors.append(f"{url}: sin noticias")
        except Exception as exc:  # noqa: BLE001 - un feed caído no debe romper el resto
            errors.append(f"{url}: {exc}")
    if not raw_items:
        print(f"  ✗ {feed['name']}: " + " | ".join(errors))
        return feed["name"], []

    out = []
    now = datetime.now(timezone.utc)
    for it in raw_items[:feed.get("max", MAX_PER_FEED)]:
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
            "type": feed.get("type", "article"),
        })
    print(f"  ✓ {feed['name']}: {len(out)} noticias")
    return feed["name"], out


STOPWORDS = set("""
a about after again against all also an and any are as at be because been before being between both but by can could did do does
doing down during each few for from further had has have having he her here hers him his how i if in into is it its itself just
me more most my new no nor not now of off on once only or other our out over own same she should so some such than that the their
them then there these they this those through to too under until up very was we were what when where which while who whom why will
with would you your yours how's what's here's says said get gets got make makes made use uses using way ways via vs year years
week weeks day days today first top best guide tips need know want help like one two three 2024 2025 2026 2027 report study
de la el en y a los las del se por un una con para es al lo como más mas pero sus le ya o este esta si sobre entre cuando muy sin
hasta desde también todo nos durante uno les ni contra otros ese eso ante ellos esto mí antes algunos qué unos yo otro otras otra
él tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros mi mis tú te ti tu tus ellas qué
cómo así ser son fue han hay puede pueden nuevo nueva nuevos nuevas años año día días cada según hace hacer tiene tienen será
launch launches launched launching announce announces announced unveils unveiled introduces introducing adds added rolls rolling
out release releases released expands expanding update updates updated brings bring now available could might may want wants
lanza lanzan lanzó anuncia anunció presenta presentó llega llegan permite permiten ahora quiere quieren
""".split())
WORD_RE = re.compile(r"[a-záéíóúñü0-9][a-záéíóúñü0-9\-\.\+]*[a-záéíóúñü0-9+]|[a-z]", re.I)


def _terms(title):
    words = [w.lower().strip(".") for w in WORD_RE.findall(title)]
    words = [w for w in words if len(w) > 1]
    out = set()
    for w in words:
        if w not in STOPWORDS and not w.isdigit() and len(w) > 2:
            out.add(w)
    for a, b in zip(words, words[1:]):
        if a not in STOPWORDS and b not in STOPWORDS and not a.isdigit() and not b.isdigit():
            out.add(f"{a} {b}")
    return out


def compute_trends(items, now, top=18):
    """Temas más mencionados en los últimos 3 días comparados con los 7 anteriores."""
    recent, base = {}, {}
    for it in items:
        age = (now - parse_date(it["date"])).total_seconds() / 86400
        bucket = recent if age <= 3 else base
        for t in _terms(it["title"]):
            bucket.setdefault(t, set()).add(it["source"] + "|" + it["link"])
    total_recent = sum(1 for it in items if (now - parse_date(it["date"])).days < 3) or 1
    scored = []
    for term, refs in recent.items():
        n = len(refs)
        if n > total_recent * 0.25:  # palabra demasiado genérica
            continue
        sources = len({r.split("|")[0] for r in refs})
        if n < 3 or sources < 2:
            continue
        prev = len(base.get(term, ())) * 3 / 7  # normalizado a 3 días
        growth = (n + 1) / (prev + 1)
        scored.append((n * min(growth, 4) * (1.3 if " " in term else 1), term, n, round(growth, 1)))
    scored.sort(reverse=True)
    chosen = []
    for _, term, n, growth in scored:
        # evita repetir "openai" y "openai gpt" a la vez
        if any(term in c["term"] or c["term"] in term for c in chosen):
            continue
        chosen.append({"term": term, "count": n, "growth": growth})
        if len(chosen) >= top:
            break
    return chosen


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
    failed_sources = [name for name, items in results if not items]

    # Fusiona con lo anterior para no perder noticias si un feed falla un rato.
    names = {f["name"] for f, _ in jobs}
    previous = [p for p in previous if p.get("source") in names]  # quita fuentes eliminadas
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
        "sources_failed": failed_sources,
        "count": len(items),
        "trends": compute_trends(items, now),
        "items": items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Listo: {len(items)} noticias de {len(ok_sources)}/{len(jobs)} fuentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
