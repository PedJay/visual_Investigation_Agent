"""Visual Investigation Agent: Streamlit UI.   Run:  streamlit run app.py"""
import json
import os

import pandas as pd
import streamlit as st # type: ignore

import agent
from agent import (MissingKeyError, find_image, follow_up, friendly_error, has_key, investigate,
                   list_images, load_reports, prepared, report_key, save_reports, save_upload,
                   set_api_key, split_key)
from render import (CSS, alternatives_html, authenticity_html, card, clues_html, context_html,
                    hero_html, legend, masthead, reports_to_csv, reports_to_markdown, short_row,
                    sources_html, thumb_caption, warnings_html, E)

st.set_page_config(page_title="Visual Investigation Agent", page_icon="🔎", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

ss = st.session_state
if "reports" not in ss:
    ss.reports = load_reports()          # results saved by batch.py or earlier sessions
ss.setdefault("chats", {})
ss.setdefault("errors", {})
ss.setdefault("view", "Dataset")
ss.setdefault("current", None)
if "nav_to" in ss:                      # navigation requested on the previous run, applied before widgets exist
    ss.view, ss.current = ss.pop("nav_to")

SUGGESTED = ["What single extra photo would confirm this location?",
             "Why did you rule out the runner-up hypothesis?",
             "How sure are you this is a real photograph, and why?",
             "What would change your mind about the identification?"]


# ------------------------------------------------------------------ actions
def go(view, name=None):
    ss.view = view
    if name:
        ss.current = name

def analyse(path, crop=None, show_spinner=True):
    key = report_key(path.name, crop)
    try:
        if show_spinner:
            with st.spinner(f"Investigating {path.name}: observing, hypothesising, verifying..."):
                ss.reports[key] = investigate(path, crop=crop)
        else:
            ss.reports[key] = investigate(path, crop=crop)
        ss.errors.pop(key, None)
        ss.chats[key] = []
        save_reports(ss.reports)
        return True
    except Exception as e:
        ss.errors[key] = friendly_error(e)
        return False

def analyse_all(files):
    bar = st.progress(0.0, text="Starting...")
    ok = bad = 0
    for i, p in enumerate(files):
        if p.name in ss.reports:
            continue
        bar.progress(i / len(files), text=f"Analysing {p.name} ({i + 1}/{len(files)})")
        try:
            analyse(p, show_spinner=False)
        except MissingKeyError:
            break
        if p.name in ss.reports:
            ok += 1
        else:
            bad += 1
            if "API key" in ss.errors.get(p.name, ""):
                break
    bar.progress(1.0, text="Finished")
    st.toast(f"Analysed {ok} image(s), {bad} failed")


# ------------------------------------------------------------------ sidebar
files = list_images()
with st.sidebar:
    st.markdown("#### Setup")

    if has_key():
        st.success("API key loaded")
    else:
        k = st.text_input("Anthropic API key", type="password", placeholder="sk-ant-...",
                          help="Held in memory for this session only. Or put it in .env")
        if k:
            set_api_key(k)
            st.rerun()
        st.warning("Add your key to analyse images. Saved reports can still be browsed.")

    st.selectbox("Model", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
                 index=0, key="model_choice",
                 on_change=lambda: os.environ.__setitem__("CLAUDE_MODEL", ss.model_choice))

    st.divider()
    st.markdown("**Stress test**")
    crop_pct = st.slider("Show only the centre …% of the image", 30, 100, 100, step=10,
                         help="Crops each side to test how the agent handles partial evidence.")
    crop = None if crop_pct >= 100 else crop_pct / 100

    st.divider()
    all_clicked = st.button("Analyse entire dataset", width="stretch", disabled=not files or not has_key())
    st.caption(f"{len(ss.reports)} reports saved · {len(files)} images")


# ------------------------------------------------------------------ header + nav
st.markdown(masthead(), unsafe_allow_html=True)
st.markdown(legend(), unsafe_allow_html=True)
st.radio("View", ["Dataset", "Investigate", "Export"], key="view", horizontal=True, label_visibility="collapsed")

if all_clicked:
    analyse_all(files)

# ---- chat box, pinned to the bottom of every view. The ＋ inside it attaches an image from your computer.
COMPOSER_HINT = "Add an image with ＋, or ask a follow-up about the selected image"
try:
    _msg = st.chat_input(COMPOSER_HINT, accept_file=True, file_type=["jpg", "jpeg", "png", "webp"])
except TypeError:                                # Streamlit older than 1.43: text only
    _msg = st.chat_input(COMPOSER_HINT)
ask_q, _attached = None, []
if isinstance(_msg, str):
    ask_q = _msg.strip() or None
elif _msg:
    ask_q = (_msg.get("text") or "").strip() or None
    _attached = list(_msg.get("files") or [])

if _attached:                                    # new image: save it, open it, analyse it
    saved = save_upload(_attached[0])
    ss.nav_to = ("Investigate", saved.name)
    ss.auto_run = saved.name
    if ask_q:
        ss.pending_q = ask_q                     # asked once the analysis exists
    st.rerun()
elif ask_q and not any(split_key(k)[0] == (ss.current or (files[0].name if files else None)) for k in ss.reports) \
        and (ss.current or files):                # nothing analysed yet: the message is the request to analyse it
    _target = ss.current or files[0].name
    ss.nav_to = ("Investigate", _target)
    ss.auto_run = _target
    st.rerun()
elif ask_q and ss.view != "Investigate":         # a question from another view: jump to the selected image
    _target = ss.current or (files[0].name if files else None)
    if _target:
        ss.nav_to = ("Investigate", _target)
        ss.pending_q = ask_q
        st.rerun()

if ss.get("auto_run"):
    _name = ss.pop("auto_run")
    _path = find_image(_name)
    if _path is not None and report_key(_name) not in ss.reports:
        if has_key():
            if not analyse(_path):
                ss.pop("pending_q", None)        # don't ask it later about some other image
        else:
            ss.pop("pending_q", None)
            st.warning("Add your API key in the sidebar (or in .env), then send again or click Analyse image.")


# ------------------------------------------------------------------ views
@st.cache_data(show_spinner=False, max_entries=500)
def thumbnail(path: str, mtime: float):
    """Decoding 20 full-size photos on every rerun made the grid slow; mtime busts the cache."""
    im = prepared(path)
    im.thumbnail((480, 480))
    return im

def view_dataset():
    base_reports = {k: v for k, v in ss.reports.items() if "::crop" not in k}
    n = len(files)
    done = [base_reports[p.name] for p in files if p.name in base_reports]
    ident = sum(1 for r in done if r["identified_landmark"].get("name"))
    low = sum(1 for r in done if r["location_confidence"].get("level") in {"low", "undetermined"})
    synth = sum(1 for r in done if r["authenticity"].get("verdict") == "likely_ai_generated")
    c = st.columns(4)
    c[0].metric("Analysed", f"{len(done)} / {n}")
    c[1].metric("Landmark identified", ident)
    c[2].metric("Low / undetermined confidence", low)
    c[3].metric("Likely AI-generated", synth)
    if not files:
        st.info("Put images in the `dataset/` folder, or add one with ＋ in the chat box below.")
        return
    cols = st.columns(4)
    for i, p in enumerate(files):
        with cols[i % 4]:
            try:
                st.image(thumbnail(str(p), p.stat().st_mtime), width="stretch")
            except Exception:
                st.caption("(unreadable image)")
            st.markdown(f'<div class="thumbcap">{thumb_caption(base_reports.get(p.name))}</div>', unsafe_allow_html=True)
            st.button("Open", key=f"open_{p.name}", on_click=go, args=("Investigate", p.name), width="stretch")


def view_investigate():
    names = [p.name for p in files]
    if not names:
        st.info("No images yet. Add files to `dataset/`, or add one with ＋ in the chat box below.")
        return
    if ss.current not in names:
        ss.current = names[0]
    # Not keyed on "current": Streamlit drops a widget's state when the widget isn't drawn,
    # which would forget the selected image whenever the Dataset or Export view is shown.
    name = st.selectbox("Image", names, index=names.index(ss.current))
    ss.current = name
    path = find_image(name)

    variants = [k for k in ss.reports if split_key(k)[0] == name]
    wanted = report_key(name, crop)
    if wanted in ss.reports:
        key = wanted
    elif len(variants) > 0:
        key = variants[0]
    else:
        key = None
    if len(variants) > 1:
        labels = {k: ("Full image" if "::crop" not in k else f"Centre {int(split_key(k)[1] * 100)}% crop") for k in variants}
        key = st.radio("Version", variants, index=variants.index(key), format_func=labels.get, horizontal=True)

    left, right = st.columns([1, 1.5], gap="large")
    with left:
        shown_crop = split_key(key)[1] if key else crop
        try:
            st.image(prepared(path, shown_crop), width="stretch")
        except Exception:
            st.warning("Image file could not be opened.")
        if shown_crop:
            st.caption(f"Showing only the centre {int(shown_crop * 100)}% of the image.")
        label = "Re-analyse" if wanted in ss.reports else ("Analyse this crop" if crop else "Analyse image")
        if st.button(label, type="primary", width="stretch", disabled=not has_key()):
            if analyse(path, crop):
                st.rerun()
        if not has_key():
            st.caption("Add your API key in the sidebar to analyse.")
        if wanted in ss.errors:
            st.error(ss.errors[wanted])

    with right:
        if key is None:
            st.info("This image has not been analysed yet. Click **Analyse image**.")
            if ask_q:
                st.warning("Analyse this image first, then ask your follow-up.")
            return
        r = ss.reports[key]
        st.markdown(hero_html(r), unsafe_allow_html=True)
        st.markdown(warnings_html(r), unsafe_allow_html=True)
        t1, t2, t3, t4 = st.tabs(["Findings", "Evidence & reasoning", "Authenticity", "Sources"])
        with t1:
            st.markdown(card("Image summary", f"<p>{E(r['image_summary'])}</p>"), unsafe_allow_html=True)
            st.markdown(clues_html(r), unsafe_allow_html=True)
            st.markdown(context_html(r), unsafe_allow_html=True)
        with t2:
            st.markdown(card("Reasoning & evidence", f"<p>{E(r['reasoning_evidence'])}</p>"), unsafe_allow_html=True)
            st.markdown(alternatives_html(r), unsafe_allow_html=True)
            obs = r["additional_observations"]
            if obs:
                st.markdown(card("Additional observations", "<ul style='margin:0 0 0 18px'>"
                            + "".join(f"<li>{E(o)}</li>" for o in obs) + "</ul>"), unsafe_allow_html=True)
            conf = r["location_confidence"]
            st.markdown(card("Why this confidence", f"<p>{E(conf.get('rationale'))}</p>"), unsafe_allow_html=True)
        with t3:
            st.markdown(authenticity_html(r), unsafe_allow_html=True)
            with st.expander("Metadata (EXIF) hints passed to the model"):
                st.json(r.get("_exif", {}))
        with t4:
            st.markdown(sources_html(r), unsafe_allow_html=True)
            with st.expander("Raw evidence stage and search audit trail"):
                st.json({k: r[k] for k in ("_observation", "_retrieved_urls", "_meta") if k in r})

    st.divider()
    if key is None:
        return
    r = ss.reports[key]
    st.markdown("#### Ask a follow-up")
    hist = ss.chats.setdefault(key, [])
    for m in hist:
        st.chat_message(m["role"]).write(m["content"])
    if not hist:
        qcols = st.columns(len(SUGGESTED))
        for i, q in enumerate(SUGGESTED):
            qcols[i].button(q, key=f"sug{i}", on_click=lambda q=q: ss.__setitem__("pending_q", q), width="stretch")
    q = ask_q or ss.pop("pending_q", None)
    if q and not has_key():
        st.warning("Add your API key in the sidebar to ask follow-up questions.")
        q = None
    if q:
        st.chat_message("user").write(q)
        try:
            with st.spinner("Thinking..."):
                a = follow_up(path, r, hist, q)
            st.chat_message("assistant").write(a)
            hist += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        except Exception as e:
            st.error(friendly_error(e))


def view_export():
    if not ss.reports:
        st.info("Nothing to export yet. Analyse some images first.")
        return
    rows = [short_row(k, r) for k, r in ss.reports.items()]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    c = st.columns(4)
    c[0].download_button("Reports (JSON)", json.dumps(ss.reports, indent=2, ensure_ascii=False), "reports.json", width="stretch")
    c[1].download_button("Reports (Markdown)", reports_to_markdown(ss.reports), "reports.md", width="stretch")
    c[2].download_button("Summary (CSV)", reports_to_csv(ss.reports), "summary.csv", width="stretch")
    c[3].download_button("Chats (JSON)", json.dumps(ss.chats, indent=2, ensure_ascii=False), "chats.json", width="stretch")
    st.caption("Reports are also saved automatically to outputs/reports.json.")


{"Dataset": view_dataset, "Investigate": view_investigate, "Export": view_export}[ss.view]()
