# Requirement checklist (UC04)

Legend: ✅ implemented and covered by offline tests · 🟡 implemented, but its quality depends on the
live model and has not been run end to end · 👤 you must do this step.

## Objective: the agent should be able to ...
| Requirement | Where | Status |
|---|---|---|
| Accept and analyse images from the dataset | `agent.list_images`, `investigate`, UI grid, `batch.py` | ✅ |
| Identify primary monument/subject | report field `primary_subject`, `identified_landmark` | 🟡 |
| Extract visual clues (style, inscriptions, symbols, surroundings, materials) | observe stage, `visual_clues` | 🟡 |
| Estimate country / city-region / locality | `probable_location` | 🟡 |
| Decide whether a specific landmark can be identified | `identified_landmark.name` may be null; status `unidentified` | ✅ |
| Historical / cultural context | `historical_cultural_context`, downgraded if no retrieved source | ✅ guard / 🟡 content |
| Real vs AI-generated, probabilistic | `authenticity` (probability clamped 1-99, confidence level, verdict derived from the score) | ✅ guard / 🟡 judgement |
| Explain reasoning and evidence | `reasoning_evidence`, `alternatives_considered` | 🟡 |
| Use external information selectively | web search only in stage 2, max 5 uses, queries come from the clues | 🟡 |
| Handle undeterminable location | partial answers allowed, level `undetermined`, stress-test crop | ✅ / 🟡 |
| Answer follow-ups about an analysed image | `follow_up`, chat UI, suggested questions | ✅ |
| Concise structured output | fixed JSON schema, cards in UI | ✅ |

## Key considerations
| Consideration | Implementation |
|---|---|
| Independent analysis, no pre-assumptions, no hard-coding | Prompts and code contain no landmark names or per-image rules |
| Evidence first | Stage 1 sees the image with no tools and no search results |
| Inference-driven, progressive detail | Hypotheses at `landmark / site_type / region` level; report can stop at region |
| Observed vs inferred vs verified | Status on every clue, location, landmark and context; coloured pills in the UI |
| "Verified" must be backed | `normalize_report` downgrades verified claims when no source was retrieved (tested) |
| Targeted verification | Stage 2 queries are derived from the observation record |
| Reasoning provided | Reasoning card + hypotheses considered |
| Uncertainty handling | Confidence level derived from the score; low scores can't be "verified" (tested) |
| Hypothesis evaluation | `alternatives_considered` shown with outcome kept / rejected / unresolved |
| Authenticity probabilistic with confidence | Probability and confidence shown; EXIF treated as weak evidence |
| No fabricated history or sources | Sources not returned by the search tool are removed and flagged (tested) |
| Partial utility | Region / style-level answers are valid output |
| Interactive context | Follow-up keeps image, report and chat history |
| Generalisability | Same pipeline for every image and for uploads |
| Quality over volume | "Be concise" rules in prompts; fixed schema |

## Submission requirements
| Item | Status |
|---|---|
| Whole provided dataset demonstrated | 👤 run **Analyse entire dataset** with your key (all 20 images are in `dataset/`) |
| Unfamiliar / non-obvious monuments | 👤 show the ghat image; upload extra obscure sites |
| Case where the location can't be determined | 👤 use the stress-test slider (30-50%) on any image, or the Paris street image |
| Follow-up interaction requiring reasoning | 👤 e.g. "Why not <runner-up>?" or "What would change your mind?" |
| Screenshots / demo | 👤 take them from the UI |
| Source code, project files, configuration | ✅ this folder (`.env.example`, `requirements.txt`, `.streamlit/config.toml`) |
| Setup and execution instructions | ✅ `README.md` |

## What has and hasn't been verified
- ✅ Offline: `python tests/test_offline.py` runs 62 checks with a fake model client and a stubbed Streamlit
  (guard-rails, JSON repair, search pause/resume, crop, follow-up payload, persistence, HTML escaping,
  every UI view with and without an API key, and the Analyse button flow).
- 🟡 Not yet run: calls to the real API and web search, and rendering in a real Streamlit server
  (neither was possible in the authoring environment). Expect small fixes after the first live run.
- Image authenticity is a visual judgement from the model, not a forensic detector. Present it as such.
