#!/usr/bin/env python3
"""Traduce al español rioplatense los titulares y resúmenes de las noticias en inglés.

Lee y actualiza data/news.json agregando "title_es" y "summary_es".
Necesita la variable ANTHROPIC_API_KEY; sin ella no hace nada.
TRANSLATE_MODEL permite elegir otro modelo (por defecto claude-opus-5-5).
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEWS_FILE = ROOT / "data" / "news.json"

MODEL = os.environ.get("TRANSLATE_MODEL") or "claude-opus-5-5"
BATCH = 25            # noticias por pedido
MAX_PER_RUN = 200     # tope por ejecución, para controlar el costo
MAX_AGE_HOURS = 72    # solo se traducen noticias recientes

SYSTEM = """Sos traductor de un portal de noticias argentino sobre inteligencia artificial y marketing.
Traducís del inglés al español de Argentina (rioplatense): natural, claro y con tono periodístico.
Reglas:
- Usá voseo cuando haya segunda persona ("podés", "tenés", "mirá").
- No traduzcas nombres propios, marcas, productos ni empresas (OpenAI, ChatGPT, Google Ads, TikTok Shop, Gemini…).
- Mantené en inglés los términos que los profesionales de marketing en Argentina usan en inglés (SEO, engagement, branding, leads, funnel, ROAS, CTR, retail media, creators…).
- El titular tiene que sonar como un titular de un diario argentino, no como una traducción literal.
- Si el resumen viene vacío, devolvé el resumen vacío.
- No agregues información que no esté en el original."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["id", "title", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def translate_batch(client, batch):
    payload = [{"id": n, "title": it["title"], "summary": it.get("summary", "")} for n, it in enumerate(batch)]
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": "Traducí estas noticias. Devolvé cada una con su mismo id.\n\n"
                   + json.dumps(payload, ensure_ascii=False)}],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"respuesta incompleta ({response.stop_reason})")
    text = next(b.text for b in response.content if b.type == "text")
    done = 0
    for tr in json.loads(text)["items"]:
        if 0 <= tr["id"] < len(batch) and tr["title"].strip():
            batch[tr["id"]]["title_es"] = tr["title"].strip()
            batch[tr["id"]]["summary_es"] = tr["summary"].strip()
            done += 1
    return done


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Traducción: falta ANTHROPIC_API_KEY, se omite.")
        return 0
    import anthropic  # instalado en el workflow

    data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    todo = [it for it in data["items"]
            if it.get("lang", "en") != "es" and not it.get("title_es")
            and datetime.fromisoformat(it["date"]) >= cutoff][:MAX_PER_RUN]
    if not todo:
        print("Traducción: no hay noticias nuevas para traducir.")
        return 0

    client = anthropic.Anthropic()
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]

    def work(batch):
        try:
            return translate_batch(client, batch)
        except Exception as exc:  # noqa: BLE001 - si un lote falla, se reintenta en la próxima ejecución
            print(f"  Lote con error: {exc}", file=sys.stderr)
            return 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        done = sum(pool.map(work, batches))

    NEWS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Traducción: {done}/{len(todo)} noticias traducidas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
