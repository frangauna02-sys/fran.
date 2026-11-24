#!/usr/bin/env python3
"""Arma el resumen diario con Claude y lo envía por Telegram y/o email.

Lee data/news.json y escribe data/digest.json (último resumen + archivo de 14 días).

Variables de entorno (todas opcionales salvo la clave de Claude para el resumen con IA):
  ANTHROPIC_API_KEY             clave de la API de Claude
  DIGEST_TZ                     zona horaria (por defecto America/Argentina/Buenos_Aires)
  DIGEST_HOUR                   hora local a partir de la cual se arma (por defecto 7)
  SITE_URL                      link a la página, para incluirlo en los mensajes
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  SMTP_USER, SMTP_PASSWORD, EMAIL_TO, SMTP_HOST (smtp.gmail.com), SMTP_PORT (465)
  FORCE_DIGEST=1                rehace el resumen aunque ya exista el de hoy
"""
import html
import json
import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
NEWS_FILE = ROOT / "data" / "news.json"
DIGEST_FILE = ROOT / "data" / "digest.json"

TZ = ZoneInfo(os.environ.get("DIGEST_TZ") or "America/Argentina/Buenos_Aires")
HOUR = int(os.environ.get("DIGEST_HOUR") or 7)
SITE_URL = os.environ.get("SITE_URL", "")
MODEL = "claude-opus-5-5"
KEEP_DAYS = 14

SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {"type": "string"},
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title_es": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                },
                "required": ["id", "title_es", "summary", "why_it_matters"],
                "additionalProperties": False,
            },
        },
        "trend_note": {"type": "string"},
        "action_idea": {"type": "string"},
    },
    "required": ["intro", "stories", "trend_note", "action_idea"],
    "additionalProperties": False,
}

SYSTEM = """Sos el editor de un briefing diario para un profesional de marketing hispanohablante que quiere \
mantenerse al día con la inteligencia artificial y el marketing digital. Escribís en español neutro, claro y \
directo, sin relleno ni exageraciones. Tu lector tiene poco tiempo: cada noticia tiene que enseñarle algo útil."""

PROMPT = """Estas son las noticias de las últimas horas (id | categoría | fuente | titular | resumen):

{news}

Temas en tendencia esta semana: {trends}

Elegí las 10 noticias más importantes y útiles para alguien que trabaja en marketing (mezclá IA y marketing; \
priorizá lanzamientos relevantes, cambios en plataformas como Google, Meta, TikTok o WhatsApp, datos y \
tendencias accionables; evitá notas repetidas, de relleno o puramente técnicas sin impacto práctico).

Para cada una:
- id: el número de la lista.
- title_es: titular en español, máximo 12 palabras.
- summary: qué pasó, en 2 oraciones.
- why_it_matters: por qué le importa a un marketer y qué podría hacer con esto, en 1 o 2 oraciones.

Además:
- intro: una frase que resuma el día.
- trend_note: 2 oraciones sobre qué patrón ves en las noticias de la semana.
- action_idea: una idea concreta para probar hoy en su trabajo, basada en las noticias."""


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def pick_candidates(items, now):
    recent = [i for i in items if now - datetime.fromisoformat(i["date"]) <= timedelta(hours=30)]
    if len(recent) < 15:
        recent = [i for i in items if now - datetime.fromisoformat(i["date"]) <= timedelta(hours=72)]
    # máximo 6 por fuente para que ninguna domine
    per_source, out = {}, []
    for it in recent:
        n = per_source.get(it["source"], 0)
        if n < 6:
            per_source[it["source"]] = n + 1
            out.append(it)
    return out[:120]


def ai_digest(candidates, trends):
    import anthropic  # instalado en el workflow

    news = "\n".join(
        f"{n} | {c['category']} | {c['source']} | {c['title']} | {c.get('summary', '')[:220]}"
        for n, c in enumerate(candidates)
    )
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": PROMPT.format(
            news=news, trends=", ".join(t["term"] for t in trends[:12]) or "—")}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("El modelo no generó el resumen (refusal).")
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    stories = []
    for s in data["stories"]:
        if 0 <= s["id"] < len(candidates):
            c = candidates[s["id"]]
            stories.append({
                "title": s["title_es"], "summary": s["summary"], "why": s["why_it_matters"],
                "link": c["link"], "source": c["source"], "category": c["category"],
                "original_title": c["title"],
            })
    return {"intro": data["intro"], "stories": stories,
            "trend_note": data["trend_note"], "action_idea": data["action_idea"], "ai": True}


def basic_digest(candidates):
    """Sin clave de API: los titulares más recientes, 5 de IA y 5 de marketing."""
    out = []
    for cat in ("ia", "marketing"):
        for c in [c for c in candidates if c["category"] == cat and c.get("type", "article") == "article"][:5]:
            out.append({"title": c["title"], "summary": c.get("summary", ""), "why": "",
                        "link": c["link"], "source": c["source"], "category": c["category"],
                        "original_title": c["title"]})
    return {"intro": "Los titulares más recientes de IA y marketing.", "stories": out,
            "trend_note": "", "action_idea": "", "ai": False}


# ---------- envío ----------

def telegram_text(d, date_label):
    e = html.escape
    lines = [f"<b>☀️ Radar IA &amp; Marketing — {e(date_label)}</b>", "", f"<i>{e(d['intro'])}</i>", ""]
    for n, s in enumerate(d["stories"], 1):
        tag = "🤖" if s["category"] == "ia" else "📣"
        lines.append(f"{tag} <b>{n}. <a href=\"{e(s['link'])}\">{e(s['title'])}</a></b>")
        if s["summary"]:
            lines.append(e(s["summary"]))
        if s["why"]:
            lines.append(f"👉 <i>{e(s['why'])}</i>")
        lines.append("")
    if d.get("trend_note"):
        lines += [f"📈 <b>Tendencia:</b> {e(d['trend_note'])}", ""]
    if d.get("action_idea"):
        lines += [f"💡 <b>Para probar hoy:</b> {e(d['action_idea'])}", ""]
    if SITE_URL:
        lines.append(f"<a href=\"{e(SITE_URL)}\">Ver todas las noticias →</a>")
    return "\n".join(lines)


def send_telegram(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram: sin configurar, se omite.")
        return
    # Telegram admite hasta 4096 caracteres por mensaje: se corta por párrafos.
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > 3900:
            chunks.append(cur)
            cur = ""
        cur += para + "\n\n"
    chunks.append(cur)
    for chunk in chunks:
        body = urllib.parse.urlencode({"chat_id": chat, "text": chunk.strip(), "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30) as r:
            r.read()
    print(f"Telegram: enviado ({len(chunks)} mensaje/s).")


def email_html(d, date_label):
    e = html.escape
    rows = []
    for n, s in enumerate(d["stories"], 1):
        color = "#5b4cf0" if s["category"] == "ia" else "#e0582b"
        label = "IA" if s["category"] == "ia" else "MARKETING"
        why = (f'<p style="margin:6px 0 0;padding:8px 12px;background:#f6f5f1;border-radius:8px;color:#333">'
               f'<b>Por qué importa:</b> {e(s["why"])}</p>') if s["why"] else ""
        rows.append(f"""<tr><td style="padding:18px 0;border-bottom:1px solid #eee">
<div style="font:700 11px Arial;color:{color};letter-spacing:.05em">{label} · {e(s['source'])}</div>
<a href="{e(s['link'])}" style="font:700 18px Georgia,serif;color:#17171a;text-decoration:none">{n}. {e(s['title'])}</a>
<p style="margin:6px 0 0;color:#555;font:15px/1.5 Arial">{e(s['summary'])}</p>{why}</td></tr>""")
    extra = ""
    if d.get("trend_note"):
        extra += f'<p style="font:15px/1.5 Arial"><b>📈 Tendencia:</b> {e(d["trend_note"])}</p>'
    if d.get("action_idea"):
        extra += f'<p style="font:15px/1.5 Arial"><b>💡 Para probar hoy:</b> {e(d["action_idea"])}</p>'
    link = f'<p><a href="{e(SITE_URL)}" style="color:#5b4cf0">Ver todas las noticias →</a></p>' if SITE_URL else ""
    return f"""<div style="max-width:640px;margin:auto;padding:24px;font-family:Arial;color:#17171a">
<h1 style="font:700 28px Georgia,serif;margin:0">Radar IA &amp; Marketing</h1>
<p style="color:#888;margin:4px 0 16px">{e(date_label)}</p>
<p style="font:italic 16px Georgia,serif">{e(d['intro'])}</p>
<table width="100%" cellspacing="0" cellpadding="0">{''.join(rows)}</table>{extra}{link}</div>"""


def send_email(d, date_label):
    user, pwd, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD"), os.environ.get("EMAIL_TO")
    if not user or not pwd or not to:
        print("Email: sin configurar, se omite.")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"☀️ Radar IA & Marketing — {date_label}"
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText(email_html(d, date_label), "html", "utf-8"))
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    print("Email: enviado.")


def main():
    now_local = datetime.now(TZ)
    today = now_local.date().isoformat()
    store = load_json(DIGEST_FILE, {"latest": None, "archive": []})
    force = os.environ.get("FORCE_DIGEST") == "1"

    if not force:
        if store.get("latest") and store["latest"].get("date") == today:
            print("El resumen de hoy ya existe.")
            return 0
        if now_local.hour < HOUR:
            print(f"Todavía no son las {HOUR}:00 ({TZ.key}).")
            return 0

    news = load_json(NEWS_FILE, {"items": []})
    candidates = pick_candidates(news.get("items", []), datetime.now(timezone.utc))
    if len(candidates) < 5:
        print("No hay suficientes noticias para el resumen.")
        return 0

    digest = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            digest = ai_digest(candidates, news.get("trends", []))
        except Exception as exc:  # noqa: BLE001 - si falla la IA, se manda igual el básico
            print(f"Resumen con IA falló, se usa el básico: {exc}", file=sys.stderr)
    if digest is None:
        digest = basic_digest(candidates)

    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
              "septiembre", "octubre", "noviembre", "diciembre"]
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    label = f"{days[now_local.weekday()]} {now_local.day} de {months[now_local.month - 1]}"
    digest.update({"date": today, "label": label, "created": datetime.now(timezone.utc).isoformat()})

    archive = [d for d in store.get("archive", []) if d.get("date") != today]
    archive.insert(0, digest)
    DIGEST_FILE.write_text(json.dumps({"latest": digest, "archive": archive[:KEEP_DAYS]},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Resumen guardado ({len(digest['stories'])} noticias, IA={digest['ai']}).")

    for sender in (lambda: send_telegram(telegram_text(digest, label)), lambda: send_email(digest, label)):
        try:
            sender()
        except Exception as exc:  # noqa: BLE001 - un canal caído no frena al otro
            print(f"Error al enviar: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
