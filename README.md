# Visual Investigation Agent (UC04)

An LLM agent (Claude vision + web search) that turns a monument photo into an evidence-based
investigation report, keeps **observed / inferred / verified** facts separate, assesses whether the
image is real or AI-generated (probabilistically), and answers follow-up questions about it.

`ui_preview.html` is only a static design mock-up with sample data: it cannot analyse images.
Run the real app with `streamlit run app.py` (see Setup).
The UI uses a dark blue theme (`.streamlit/config.toml` plus the CSS in `render.py`). Fonts load from
Google Fonts; offline it falls back to system sans-serif fonts with no loss of function.

## Setup
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env          # paste your key into .env (never into .env.example): console.anthropic.com -> API Keys
streamlit run app.py          # UI (you can also paste the key in the sidebar instead of .env)
python batch.py               # optional: analyse the whole dataset from the terminal
python tests/test_offline.py  # optional: offline tests, no key or network needed
```
Images live in `dataset/` (your 20 are already there). Web search must be enabled for your
Anthropic organisation in the Console. Default model `claude-sonnet-5-5` (change in the sidebar or `CLAUDE_MODEL`).

## Using the UI
- **Dataset** tab: thumbnail grid with landmark, status and confidence per image; summary counters.
  Sidebar: **Analyse entire dataset** (resumable, saves after every image).
- **Investigate** tab: image + hero summary (landmark, location, confidence meter, AI-probability meter),
  then tabs for Findings, Evidence & reasoning, Authenticity, Sources. Follow-up chat below, with suggested questions.
- **Stress test** (sidebar slider): analyse only the centre 30-90% of an image to show how the agent
  handles partial evidence and low confidence. Crops are stored as separate versions next to the full image.
- **Export** tab: JSON, Markdown, CSV. Reports are also auto-saved to `outputs/reports.json`.
- **＋ in the chat box** (pinned at the bottom of every view): attach any image from your computer. It is saved to
  `uploads/`, opened in Investigate and analysed automatically. Add text with it to ask a question straight after the analysis.
  Typing a question without an image asks about the selected image. Needs Streamlit 1.43 or newer (older versions get a text-only box).

## How it works
1. **Observe (no tools):** records only what is visible, transcribes text, lists competing hypotheses
   (including "unidentifiable") and authenticity cues, before any search.
2. **Investigate (web search on):** searches are built from the visual clues to verify or reject
   hypotheses, then a structured report is produced.
3. **Validate (deterministic code, `normalize_report`):** drops cited URLs the search tool never returned,
   downgrades any "verified" claim that has no retrieved source, keeps the confidence level and authenticity
   verdict consistent with their scores, never allows 0% or 100% certainty, repairs invalid JSON once.
4. **Follow-up chat:** image and report stay in context; the model may search again.

No per-image rules exist anywhere. See `CONSTRAINTS.md` for a requirement-by-requirement checklist.

## Demo checklist for the submission
1. Run **Analyse entire dataset**; screenshot the Dataset tab.
2. Screenshot an obscure/partial case (for example the ghat image, or the Paris street image) and a stress-test crop showing low confidence.
3. Ask a follow-up (for example "What single extra photo would confirm the location?") and screenshot the chat.
4. Include `outputs/reports.json`, `reports.md` and the screenshots in your submission.
