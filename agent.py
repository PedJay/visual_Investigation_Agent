"""Visual Investigation Agent core.

Pipeline: observe (evidence first, no tools) -> investigate (targeted web search + structured
report) -> validate (deterministic guard-rails) -> follow-up chat. Works for any image; there
are no per-image rules anywhere in this file.
"""
import base64, copy, datetime as dt, io, json, os, re
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from PIL import ExifTags, Image, ImageOps

from prompts import FOLLOWUP_SYSTEM, OBSERVE_SYSTEM, REPAIR_USER, REPORT_SYSTEM

load_dotenv()

ROOT = Path(__file__).parent
DATASET, UPLOADS, OUT = ROOT / "dataset", ROOT / "uploads", ROOT / "outputs"
REPORTS_PATH = OUT / "reports.json"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


class MissingKeyError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- client / config
def model() -> str:
    return os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

def has_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))

def set_api_key(key: str) -> None:
    os.environ["ANTHROPIC_API_KEY"] = key.strip()

_client, _client_key = None, None
def client():
    global _client, _client_key
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise MissingKeyError("ANTHROPIC_API_KEY is not set (add it to .env or paste it in the sidebar).")
    if _client is None or key != _client_key:
        _client, _client_key = anthropic.Anthropic(api_key=key), key
    return _client


# ----------------------------------------------------------------------------- images
def natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]

def list_images():
    files = []
    for folder in (DATASET, UPLOADS):
        if folder.exists():
            files += [p for p in folder.glob("*") if p.suffix.lower() in IMG_EXT]
    return sorted(files, key=natural_key)

def find_image(name: str):
    for folder in (DATASET, UPLOADS):
        p = folder / name
        if p.exists():
            return p
    return None

def save_upload(uploaded) -> Path:
    """Save an uploaded file into uploads/ under a name that never collides with the dataset
    or with a different earlier upload. Re-uploading identical bytes reuses the same file."""
    UPLOADS.mkdir(exist_ok=True)
    data = uploaded.getvalue()
    raw = Path(uploaded.name).name or "upload.jpg"
    stem, suffix = Path(raw).stem, Path(raw).suffix
    n, name = 1, raw
    while True:
        dest = UPLOADS / name
        if (DATASET / name).exists():
            pass                                   # never shadow a dataset image
        elif not dest.exists():
            dest.write_bytes(data)
            return dest
        elif dest.read_bytes() == data:
            return dest                            # same image uploaded again
        n += 1
        name = f"{stem}-upload{n}{suffix}"

def load_image(source) -> Image.Image:
    img = Image.open(source)
    img.load()
    return ImageOps.exif_transpose(img)

def apply_crop(img: Image.Image, frac) -> Image.Image:
    """Centre crop to `frac` of each side. Used to stress-test uncertainty handling."""
    if not frac or frac >= 0.999:
        return img
    w, h = img.size
    cw, ch = max(32, int(w * frac)), max(32, int(h * frac))
    left, top = (w - cw) // 2, (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))

def prepared(source, crop=None) -> Image.Image:
    return apply_crop(load_image(source), crop)

def to_block(img: Image.Image, max_side: int = 1568) -> dict:
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(buf.getvalue()).decode()}}

def exif_summary(source) -> dict:
    """Metadata is weak evidence, passed to the model as a hint only."""
    out = {}
    try:
        raw = Image.open(source).getexif()
        for tag_id, val in raw.items():
            tag = ExifTags.TAGS.get(tag_id, str(tag_id))
            if tag in {"Make", "Model", "Software", "DateTime", "LensModel"}:
                out[tag] = str(val)
        if raw.get_ifd(0x8825):
            out["GPS_present"] = True
    except Exception:
        pass
    return out or {"note": "no EXIF metadata found (common after sharing or stripping)"}


# ----------------------------------------------------------------------------- LLM plumbing
def _tag_json(text: str, tag: str) -> dict:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    if m:
        blob = m.group(1)
    else:
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b < a:
            raise ValueError("no JSON object found in model output")
        blob = text[a:b + 1]
    blob = re.sub(r"^```(?:json)?|```$", "", blob.strip(), flags=re.M).strip()
    return json.loads(blob)

def _run(system, messages, use_search=False, max_tokens=4000):
    """One logical turn; continues automatically if the server-side search tool pauses."""
    kwargs = dict(model=model(), max_tokens=max_tokens, system=system)
    if use_search:
        kwargs["tools"] = [WEB_SEARCH]
    msgs, urls, text = list(messages), [], ""
    for _ in range(6):
        resp = client().messages.create(messages=msgs, **kwargs)
        for b in resp.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                urls += [{"title": getattr(r, "title", "") or r.url, "url": r.url}
                         for r in b.content if hasattr(r, "url")]
        text += "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason != "pause_turn":
            break
        msgs.append({"role": "assistant", "content": resp.content})
    seen, uniq = set(), []
    for u in urls:
        if u["url"] not in seen:
            seen.add(u["url"])
            uniq.append(u)
    return text, uniq

def _parse_or_repair(system, messages, text, tag):
    """Parse JSON; on failure ask the model once to re-emit valid JSON."""
    try:
        return _tag_json(text, tag)
    except Exception:
        fix = list(messages) + [{"role": "assistant", "content": text.strip() or "(empty)"},
                                {"role": "user", "content": REPAIR_USER.format(tag=tag)}]
        fixed, _ = _run(system, fix, max_tokens=6000)
        return _tag_json(fixed, tag)


# ----------------------------------------------------------------------------- validation
DEFAULTS = {"image_summary": "", "primary_subject": "", "visual_clues": [], "probable_location": {},
            "identified_landmark": {}, "location_confidence": {}, "alternatives_considered": [],
            "authenticity": {}, "historical_cultural_context": {}, "reasoning_evidence": "",
            "additional_observations": [], "sources": []}

def _norm_url(u: str) -> str:
    u = re.sub(r"^https?://(www\.)?", "", str(u).strip().lower())
    return u.split("#")[0].rstrip("/")

def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return None

def level_from_score(score, has_country=True):
    if score is None or not has_country:
        return "undetermined"
    return "high" if score >= 80 else "medium" if score >= 55 else "low" if score >= 25 else "undetermined"

def verdict_from_prob(p):
    return "uncertain" if p is None else "likely_ai_generated" if p >= 65 else "likely_real" if p <= 30 else "uncertain"

def normalize_report(rep: dict, retrieved: list) -> dict:
    """Deterministic guard-rails applied after the model answers:
    - fill missing fields so the UI never crashes
    - drop cited sources whose URL the search tool never returned (anti-fabrication)
    - 'verified' claims require at least one real source, otherwise downgrade to 'inferred'
    - keep confidence level / authenticity verdict consistent with their numeric scores"""
    warnings = []
    for k, default in DEFAULTS.items():
        if not isinstance(rep.get(k), type(default)):
            rep[k] = copy.deepcopy(default)

    # sources
    known = {_norm_url(u["url"]): u for u in retrieved}
    good, seen = [], set()
    for s in rep["sources"]:
        if not isinstance(s, dict):
            continue
        n = _norm_url(s.get("url", ""))
        if n in known and n not in seen:
            seen.add(n)
            s["url"] = known[n]["url"]
            s["title"] = s.get("title") or known[n]["title"]
            good.append(s)
    dropped = len(rep["sources"]) - len(good)
    if dropped:
        warnings.append(f"{dropped} cited source(s) removed: URL was not returned by the search tool.")
    rep["sources"] = good
    has_src = bool(good)

    # status downgrades
    for c in rep["visual_clues"]:
        if isinstance(c, dict) and c.get("status") == "verified" and not has_src:
            c["status"] = "inferred"
    loc, lm, conf = rep["probable_location"], rep["identified_landmark"], rep["location_confidence"]
    ctx, au = rep["historical_cultural_context"], rep["authenticity"]
    if loc.get("status") == "verified" and not has_src:
        loc["status"] = "inferred"
    if lm.get("status") == "verified" and not has_src:
        lm["status"] = "inferred"
        warnings.append("Landmark was marked verified without a retrieved source; downgraded to inferred.")
    if ctx.get("text") and (ctx.get("status") == "verified" and not has_src):
        ctx["status"] = "inferred"
        warnings.append("Historical context is not backed by a retrieved source.")
    if not ctx.get("text"):
        ctx["status"] = "not_available"

    # landmark / confidence consistency
    if not lm.get("name"):
        lm["name"], lm["status"] = None, "unidentified"
    elif lm.get("status") not in {"verified", "inferred"}:
        lm["status"] = "inferred"
    score = _clamp(conf.get("score"), 0, 100)
    conf["score"] = score
    conf["level"] = level_from_score(score, has_country=bool(loc.get("country")))
    if lm.get("status") == "verified" and (score or 0) < 55:
        lm["status"] = "inferred"
    if not loc.get("country"):
        loc["status"] = "undetermined"
    elif loc.get("status") not in {"verified", "inferred"}:
        loc["status"] = "inferred"

    # authenticity: probabilistic, never 0 or 100
    p = _clamp(au.get("ai_generated_probability"), 1, 99)
    au["ai_generated_probability"] = p
    au["verdict"] = verdict_from_prob(p)
    if au.get("confidence") not in {"low", "medium", "high"}:
        au["confidence"] = "low"
    if not isinstance(au.get("indicators"), list):
        au["indicators"] = []

    rep["_warnings"] = warnings
    return rep


# ----------------------------------------------------------------------------- main pipeline
def investigate(source, crop=None) -> dict:
    """source: path / file-like. crop: None or fraction (0.3-1.0) of each side to keep (centre)."""
    exif = exif_summary(source)
    block = to_block(prepared(source, crop))

    obs_msgs = [{"role": "user", "content": [block, {"type": "text",
                 "text": "Record the visible evidence and competing hypotheses for this image."
                         + (" NOTE: this is a deliberately cropped partial view." if crop and crop < 0.999 else "")}]}]
    obs_text, _ = _run(OBSERVE_SYSTEM, obs_msgs)
    observation = _parse_or_repair(OBSERVE_SYSTEM, obs_msgs, obs_text, "observation")

    ctx = (f"OBSERVATION RECORD:\n{json.dumps(observation, ensure_ascii=False)}\n\n"
           f"EXIF HINTS:\n{json.dumps(exif)}\n\nProduce the investigation report.")
    rep_msgs = [{"role": "user", "content": [block, {"type": "text", "text": ctx}]}]
    rep_text, retrieved = _run(REPORT_SYSTEM, rep_msgs, use_search=True, max_tokens=6000)
    report = _parse_or_repair(REPORT_SYSTEM, rep_msgs, rep_text, "report")

    report = normalize_report(report, retrieved)
    report["_retrieved_urls"] = retrieved          # audit trail of what search actually returned
    report["_exif"] = exif
    report["_observation"] = observation
    report["_meta"] = {"model": model(), "crop": crop if crop and crop < 0.999 else None,
                       "analyzed_at": dt.datetime.now().isoformat(timespec="seconds")}
    return report


def follow_up(source, report: dict, history: list, question: str) -> str:
    """history: previous follow-up turns as [{"role","content"(str)}]."""
    crop = (report.get("_meta") or {}).get("crop")
    block = to_block(prepared(source, crop))
    clean = {k: v for k, v in report.items() if not k.startswith("_")}
    first = {"role": "user", "content": [block, {"type": "text",
             "text": "Here is the image and my earlier investigation report:\n"
                     + json.dumps(clean, ensure_ascii=False)}]}
    ack = {"role": "assistant", "content": "Understood. Ask me anything about this image."}
    msgs = [first, ack] + list(history) + [{"role": "user", "content": question}]
    text, _ = _run(FOLLOWUP_SYSTEM, msgs, use_search=True, max_tokens=2000)
    return text.strip()


# ----------------------------------------------------------------------------- persistence
def save_reports(reports: dict, path: Path = REPORTS_PATH) -> None:
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def load_reports(path: Path = REPORTS_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict) and "error" not in v}
    except Exception:
        return {}

def report_key(name: str, crop=None) -> str:
    return f"{name}::crop{int(round(crop * 100))}" if crop and crop < 0.999 else name

def split_key(key: str):
    base, _, c = key.partition("::crop")
    return base, (int(c) / 100 if c else None)

def friendly_error(e: Exception) -> str:
    n = type(e).__name__
    if isinstance(e, MissingKeyError):
        return str(e)
    if n == "AuthenticationError":
        return "The API key was rejected. Check ANTHROPIC_API_KEY."
    if n == "PermissionDeniedError":
        return "Permission denied. Is web search enabled for your organisation in the Console?"
    if n == "RateLimitError":
        return "Rate limited. Wait a moment and retry."
    if n in {"BadRequestError", "APIStatusError"}:
        return f"The API rejected the request: {e}"
    if isinstance(e, (ValueError, json.JSONDecodeError)):
        return f"The model returned output that could not be parsed even after a repair attempt ({e})."
    return f"{n}: {e}"
