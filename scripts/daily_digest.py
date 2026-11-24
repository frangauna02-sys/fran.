#!/usr/bin/env python3
"""Arma el resumen diario con Claude para mostrarlo en la página.

Lee data/news.json y escribe data/digest.json (último resumen + archivo de 14 días).

Variables de entorno (todas opcionales):
  ANTHROPIC_API_KEY             clave de la API de Claude
  DIGEST_TZ                     zona horaria (por defecto America/Argentina/Buenos_Aires)
  DIGEST_HOUR                   hora local a partir de la cual se arma (por defecto 7)
  FORCE_DIGEST=1                rehace el resumen aunque ya exista el de hoy
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
NEWS_FILE = ROOT / "data" / "news.json"
DIGEST_FILE = ROOT / "data" / "digest.json"

TZ = ZoneInfo(os.environ.get("DIGEST_TZ") or "America/Argentina/Buenos_Aires")
HOUR = int(os.environ.get("DIGEST_HOUR") or 7)
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
        except Exception as exc:  # noqa: BLE001 - si falla la IA, se usa el básico
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
