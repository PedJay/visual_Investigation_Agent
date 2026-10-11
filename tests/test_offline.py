"""Offline tests: no API key, no network. A fake model client stands in for Anthropic and a stub
stands in for Streamlit, so this checks the agent logic and that every UI view runs end to end.

    python tests/test_offline.py
"""
import copy, json, os, runpy, sys, tempfile, types
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# ---- stubs for packages that may not be installed ---------------------------------------------
try:
    import anthropic  # noqa
except ImportError:
    sys.modules["anthropic"] = types.ModuleType("anthropic")
    sys.modules["anthropic"].Anthropic = object
try:
    import dotenv  # noqa
except ImportError:
    m = types.ModuleType("dotenv"); m.load_dotenv = lambda *a, **k: None; sys.modules["dotenv"] = m

os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
import agent, render  # noqa: E402
from prompts import OBSERVE_SYSTEM, REPORT_SYSTEM  # noqa: E402

OBS = {"summary": "s", "visible_clues": [], "transcribed_text": [], "hypotheses": [],
       "verification_queries": ["q"], "authenticity_cues": {"real_indicators": [], "synthetic_indicators": []}}
GOOD_URL = "https://example.org/page"
REPORT = {
    "image_summary": "A <b>test</b> scene", "primary_subject": "Test monument",
    "visual_clues": [{"clue": "red gates", "status": "verified"}, {"clue": "kanji text", "status": "observed"}],
    "probable_location": {"country": "Japan", "region_city": "Kyoto", "locality": None, "status": "verified"},
    "identified_landmark": {"name": "Test Shrine", "status": "verified"},
    "location_confidence": {"level": "low", "score": 91, "rationale": "r"},
    "alternatives_considered": [{"label": "Other", "outcome": "rejected", "why": "w"}],
    "authenticity": {"verdict": "likely_real", "ai_generated_probability": 100, "confidence": "high",
                     "indicators": ["i"], "notes": None},
    "historical_cultural_context": {"text": "History.", "status": "verified"},
    "reasoning_evidence": "because", "additional_observations": ["o"],
    "sources": [{"title": "Real", "url": GOOD_URL + "/", "supports": "s"},
                {"title": "Fake", "url": "https://made-up.example/x", "supports": "s"}],
}

class FakeMessages:
    def __init__(self, script): self.script, self.calls = script, []
    def create(self, **kw):
        self.calls.append(kw)
        return self.script(kw)

def blocks(text, urls=()):
    content = []
    if urls:
        content.append(NS(type="web_search_tool_result", content=[NS(url=u, title="T " + u) for u in urls]))
    content.append(NS(type="text", text=text))
    return content

def install(script):
    fm = FakeMessages(script)
    fake = NS(messages=fm)
    agent._client, agent._client_key = fake, os.environ["ANTHROPIC_API_KEY"]
    return fm

def normal_script(report=REPORT, urls=(GOOD_URL,)):
    def s(kw):
        if kw["system"] == OBSERVE_SYSTEM:
            return NS(content=blocks(f"<observation>{json.dumps(OBS)}</observation>"), stop_reason="end_turn")
        if kw["system"] == REPORT_SYSTEM:
            return NS(content=blocks(f"<report>{json.dumps(report)}</report>", urls), stop_reason="end_turn")
        return NS(content=blocks("A follow-up answer."), stop_reason="end_turn")
    return s

passed = 0
def check(name, cond, extra=""):
    global passed
    assert cond, f"FAIL: {name} {extra}"
    passed += 1
    print(f"  ok  {name}")

IMG = agent.find_image("img12.jpg") or agent.list_images()[0]

# ------------------------------------------------------------------------------------------------
print("normalize_report guard-rails")
r = agent.normalize_report(copy.deepcopy(REPORT), [{"title": "T", "url": GOOD_URL}])
check("fabricated source removed", [s["url"] for s in r["sources"]] == [GOOD_URL])
check("warning recorded for removed source", any("removed" in w for w in r["_warnings"]))
check("verified kept when a real source exists and confidence is high", r["identified_landmark"]["status"] == "verified")
check("level derived from score (91 -> high)", r["location_confidence"]["level"] == "high")
check("AI probability clamped to 99", r["authenticity"]["ai_generated_probability"] == 99)
check("verdict follows probability", r["authenticity"]["verdict"] == "likely_ai_generated")

r = agent.normalize_report(copy.deepcopy(REPORT), [])
check("no sources: landmark downgraded to inferred", r["identified_landmark"]["status"] == "inferred")
check("no sources: clue downgraded", r["visual_clues"][0]["status"] == "inferred")
check("no sources: context downgraded", r["historical_cultural_context"]["status"] == "inferred")
check("observed clue untouched", r["visual_clues"][1]["status"] == "observed")

weird = {"identified_landmark": "oops", "sources": None, "authenticity": {"ai_generated_probability": "n/a"}}
r = agent.normalize_report(weird, [])
check("garbage input becomes a safe, renderable report", r["identified_landmark"]["status"] == "unidentified"
      and r["authenticity"]["verdict"] == "uncertain" and r["location_confidence"]["level"] == "undetermined")
html_ok = all(callable(f) and isinstance(f(r), str) for f in (render.hero_html, render.clues_html, render.context_html,
              render.sources_html, render.authenticity_html, render.alternatives_html))
check("all renderers accept a minimal report", html_ok)

lowconf = copy.deepcopy(REPORT); lowconf["location_confidence"]["score"] = 30
r = agent.normalize_report(lowconf, [{"title": "T", "url": GOOD_URL}])
check("verified landmark with low score downgraded", r["identified_landmark"]["status"] == "inferred")

# ------------------------------------------------------------------------------------------------
print("pipeline with fake model")
fm = install(normal_script())
rep = agent.investigate(IMG, crop=0.4)
check("two model calls (observe, report)", len(fm.calls) == 2)
check("observe stage has no tools", "tools" not in fm.calls[0])
check("report stage has web search", fm.calls[1].get("tools", [{}])[0].get("name") == "web_search")
check("crop recorded in meta", rep["_meta"]["crop"] == 0.4)
check("only retrieved URLs survive", [s["url"] for s in rep["sources"]] == [GOOD_URL])
check("audit trail stored", rep["_retrieved_urls"][0]["url"] == GOOD_URL)
check("cropped image is smaller", agent.prepared(IMG, 0.4).size[0] < agent.prepared(IMG).size[0])

print("JSON repair")
state = {"n": 0}
def broken_then_fixed(kw):
    if kw["system"] == REPORT_SYSTEM:
        state["n"] += 1
        txt = "<report>{not json</report>" if state["n"] == 1 else f"<report>{json.dumps(REPORT)}</report>"
        return NS(content=blocks(txt, (GOOD_URL,)), stop_reason="end_turn")
    return normal_script()(kw)
fm = install(broken_then_fixed)
rep = agent.investigate(IMG)
check("repaired after invalid JSON", rep["identified_landmark"]["name"] == "Test Shrine" and state["n"] == 2)

def always_broken(kw):
    if kw["system"] == REPORT_SYSTEM:
        return NS(content=blocks("no json at all"), stop_reason="end_turn")
    return normal_script()(kw)
install(always_broken)
try:
    agent.investigate(IMG); check("persistent garbage raises", False)
except ValueError as e:
    check("persistent garbage raises ValueError", isinstance(e, ValueError))
    check("friendly error mentions parsing", "parsed" in agent.friendly_error(e))

print("pause_turn continuation")
turns = {"n": 0}
def pausing(kw):
    if kw["system"] == REPORT_SYSTEM:
        turns["n"] += 1
        if turns["n"] == 1:
            return NS(content=blocks("", (GOOD_URL,)), stop_reason="pause_turn")
        return NS(content=blocks(f"<report>{json.dumps(REPORT)}</report>"), stop_reason="end_turn")
    return normal_script()(kw)
install(pausing)
rep = agent.investigate(IMG)
check("continues after pause_turn and keeps URLs from the first turn", turns["n"] == 2 and rep["sources"])

print("follow-up")
fm = install(normal_script())
ans = agent.follow_up(IMG, {**rep, "_meta": {"crop": 0.5}}, [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}], "q2")
msgs = fm.calls[0]["messages"]
check("follow-up returns text", ans == "A follow-up answer.")
check("history and question are sent in order", [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant", "user"])
check("image is attached to the first message", msgs[0]["content"][0]["type"] == "image")
check("report is clean of private _fields", "_retrieved_urls" not in msgs[0]["content"][1]["text"])

print("persistence & keys")
with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "reports.json"
    agent.save_reports({"a.jpg": rep, "bad": {"error": "x"}}, p)
    back = agent.load_reports(p)
    check("round-trip keeps good reports and drops error entries", list(back) == ["a.jpg"])
check("report_key / split_key round-trip", agent.split_key(agent.report_key("x.jpg", 0.4)) == ("x.jpg", 0.4)
      and agent.report_key("x.jpg", None) == "x.jpg")
check("natural sort puts img2 before img10", [p.name for p in agent.list_images()][:3] == ["img1.jpg", "img2.jpg", "img3.jpg"]
      or len(agent.list_images()) == 0)
os.environ.pop("ANTHROPIC_API_KEY"); agent._client = None
try:
    agent.client(); check("missing key raises", False)
except agent.MissingKeyError:
    check("missing key raises MissingKeyError", True)
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"

print("rendering")
evil = copy.deepcopy(rep)
evil["image_summary"] = "<script>alert(1)</script>"
evil["identified_landmark"]["name"] = "<img src=x onerror=alert(1)>"
evil["sources"] = [{"title": "<b>t</b>", "url": "javascript:alert(1)", "supports": "x"},
                   {"title": "ok", "url": "https://example.org/a?b=1&c=2", "supports": "<i>"}]
out = render.hero_html(evil) + render.sources_html(evil) + render.card("t", f"<p>{render.E(evil['image_summary'])}</p>")
check("model text is HTML-escaped", "<script>" not in out and "<img src=x" not in out)
check("javascript: URLs are not linked", "javascript:" not in out)
check("https URLs are linked", 'href="https://example.org/a?b=1&amp;c=2"' in out)
md = render.reports_to_markdown({"a.jpg": rep}); csvt = render.reports_to_csv({"a.jpg": rep})
check("markdown export has all report fields", all(s in md for s in
      ["Image Summary", "Primary Subject", "Important Visual Clues", "Probable Location", "Identified Landmark",
       "Location Confidence", "Image Authenticity", "Historical & Cultural Context", "Reasoning & Evidence",
       "Additional Observations", "Sources / References"]))
check("csv export has a header row and a data row", csvt.count("\n") >= 2)

# ------------------------------------------------------------------------------------------------
print("UI smoke test (stubbed Streamlit)")
class AttrDict(dict):
    __getattr__ = lambda s, k: s[k] if k in s else (_ for _ in ()).throw(AttributeError(k))
    __setattr__ = dict.__setitem__

def make_st(view):
    st = MagicMock(name="streamlit")
    st.session_state = AttrDict()
    st.session_state["view"] = view
    st.button.return_value = False
    st.chat_input.return_value = None
    st.file_uploader.return_value = None
    st.text_input.return_value = ""
    st.slider.return_value = 100
    st.columns.side_effect = lambda spec, **k: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs.side_effect = lambda labels: [MagicMock() for _ in labels]
    st.radio.side_effect = lambda label, opts, **k: st.session_state.get(k.get("key"), opts[0])
    st.selectbox.side_effect = lambda label, opts, **k: st.session_state.get(k.get("key")) or opts[k.get("index") or 0]
    return st

names = [p.name for p in agent.list_images()]
fake_reports = {n: copy.deepcopy(rep) for n in names[:3]}
if names:
    fake_reports[agent.report_key(names[0], 0.4)] = {**copy.deepcopy(rep), "_meta": {"crop": 0.4}}
agent.load_reports = lambda *a, **k: copy.deepcopy(fake_reports)
agent.save_reports = lambda *a, **k: None          # never touch outputs/ from tests

for has in (True, False):
    if has: os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
    else: os.environ.pop("ANTHROPIC_API_KEY", None)
    for view in ("Dataset", "Investigate", "Export"):
        st = make_st(view)
        if view == "Investigate" and names:
            st.session_state["current"] = names[0]
        sys.modules["streamlit"] = st
        runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
        check(f"app runs: view={view}, api_key={'yes' if has else 'no'}", st.markdown.called)
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"

# analysing from the UI: button pressed -> analyse() runs the fake pipeline and stores the report
saved = {}
agent.save_reports = lambda reports, *a, **k: saved.update(reports)
install(normal_script())
st = make_st("Investigate")
if names:
    st.session_state["current"] = names[-1]
    st.button.side_effect = lambda label, **k: label.startswith("Analyse")
    sys.modules["streamlit"] = st
    runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
    check("clicking Analyse stores and saves a report", names[-1] in saved)

print("upload flow")
class FakeUpload:
    def __init__(self, name, data): self.name, self._d = name, data
    def getvalue(self): return self._d

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "dataset").mkdir()
    (d / "dataset" / "img1.jpg").write_bytes(b"dataset-bytes")
    old_up, old_ds = agent.UPLOADS, agent.DATASET
    agent.UPLOADS, agent.DATASET = d / "uploads", d / "dataset"
    try:
        a = agent.save_upload(FakeUpload("photo.jpg", b"AAA"))
        check("new upload is saved under its own name", a.name == "photo.jpg" and a.read_bytes() == b"AAA")
        check("re-uploading identical bytes reuses the file", agent.save_upload(FakeUpload("photo.jpg", b"AAA")) == a)
        b = agent.save_upload(FakeUpload("photo.jpg", b"BBB"))
        check("same name with different content gets a new name", b != a and b.read_bytes() == b"BBB" and a.read_bytes() == b"AAA")
        c = agent.save_upload(FakeUpload("img1.jpg", b"mine"))
        check("a name that exists in dataset/ never shadows it", c.name != "img1.jpg" and (d / "dataset" / "img1.jpg").read_bytes() == b"dataset-bytes")
        e = agent.save_upload(FakeUpload("../../evil.jpg", b"x"))
        check("path components in the filename are stripped", e.parent == d / "uploads")
    finally:
        agent.UPLOADS, agent.DATASET = old_up, old_ds

saved2 = {}
agent.save_reports = lambda reports, *a, **k: saved2.update(reports)
agent.save_upload = lambda up: IMG                 # pretend the upload landed as an existing image
agent.load_reports = lambda *a, **k: {}
install(normal_script())
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
class Rerun(Exception):
    pass

def run_app(st):
    """Emulate Streamlit: st.rerun() stops the script and starts it again."""
    reruns = 0
    for _ in range(5):
        try:
            runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
            return reruns
        except Rerun:
            reruns += 1
    raise AssertionError("app keeps rerunning")

st = make_st("Dataset")
st.rerun.side_effect = Rerun
calls = {"n": 0}
def composer(text="", with_file=True):
    """chat_input stand-in: the first call returns a submitted message, later calls return nothing."""
    def f(*a, **k):
        calls["n"] += 1
        if calls["n"] > 1:
            return None
        return {"text": text, "files": [FakeUpload("new.jpg", b"x")] if with_file else []}
    return f
st.chat_input.side_effect = composer()
sys.modules["streamlit"] = st
reruns = run_app(st)                                           # user attaches a file with ＋ in the chat box
check("chat box is created with file attachments enabled", st.chat_input.call_args.kwargs.get("accept_file") is True)
check("there is no separate upload widget any more", not st.popover.called and not st.file_uploader.called)
check("picking a file triggers exactly one rerun", reruns == 1)
check("rerun opens the Investigate view on the new image", st.session_state["view"] == "Investigate"
      and st.session_state["current"] == IMG.name)
check("the new image is analysed automatically and saved", IMG.name in saved2)
check("auto-run flag is cleared", "auto_run" not in st.session_state)

os.environ.pop("ANTHROPIC_API_KEY"); agent._client = None
saved2.clear()
st = make_st("Dataset"); calls["n"] = 0
st.rerun.side_effect = Rerun
st.chat_input.side_effect = composer()
sys.modules["streamlit"] = st
run_app(st)
check("without an API key the upload is kept but not analysed, with a warning", not saved2 and st.warning.called)

# text-only question typed while on the Dataset view -> jumps to the image and answers
os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"; agent._client = None
fm = install(normal_script())
saved2.clear()
agent.load_reports = lambda *a, **k: {IMG.name: copy.deepcopy(rep)}
st = make_st("Dataset"); calls["n"] = 0
st.rerun.side_effect = Rerun
st.session_state["current"] = IMG.name
st.chat_input.side_effect = composer("Why not the runner-up?", with_file=False)
sys.modules["streamlit"] = st
reruns = run_app(st)
check("a question typed in the Dataset view jumps to Investigate", reruns == 1 and st.session_state["view"] == "Investigate")
check("the question is sent to the model with the image's history", any(
      m.get("content") == "Why not the runner-up?" for c in fm.calls for m in c["messages"] if isinstance(m, dict)))
check("the pending question is consumed", "pending_q" not in st.session_state)

# image + text together -> analyse first, then ask
fm = install(normal_script()); agent.load_reports = lambda *a, **k: {}
saved2.clear()
st = make_st("Dataset"); calls["n"] = 0
st.rerun.side_effect = Rerun
st.chat_input.side_effect = composer("What is this?", with_file=True)
sys.modules["streamlit"] = st
run_app(st)
systems = [c["system"] for c in fm.calls]
check("image plus text: analysed first, then the question is asked",
      IMG.name in saved2 and systems.index(OBSERVE_SYSTEM) < len(systems) - 1 and "What is this?" in json.dumps(fm.calls[-1]["messages"]))

# "Analyze this image..." typed with nothing analysed yet -> analyses the selected image
fm = install(normal_script()); agent.load_reports = lambda *a, **k: {}
saved2.clear()
st = make_st("Investigate"); calls["n"] = 0
st.rerun.side_effect = Rerun
st.session_state["current"] = IMG.name
st.chat_input.side_effect = composer("Analyze this image and identify the monument, its location, and any relevant historical context", with_file=False)
sys.modules["streamlit"] = st
reruns = run_app(st)
check("typing an analyse request analyses the selected image", IMG.name in saved2 and reruns == 1)

# older Streamlit without accept_file falls back to a plain text box
st = make_st("Investigate"); st.session_state["current"] = IMG.name
def old_chat_input(placeholder, **k):
    if k: raise TypeError("unexpected keyword argument 'accept_file'")
    return None
st.chat_input.side_effect = old_chat_input
sys.modules["streamlit"] = st
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
check("falls back to a text-only chat box on older Streamlit", True)

print(f"\nALL {passed} CHECKS PASSED")
