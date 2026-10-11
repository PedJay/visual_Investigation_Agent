"""Run the agent over the whole dataset (resumable).

  python batch.py                 # analyse every image in ./dataset and ./uploads not yet done
  python batch.py --force         # redo everything
  python batch.py --crop 0.4      # stress test: only the centre 40% of each image

Writes outputs/reports.json (the UI reads this), outputs/reports.md and outputs/summary.csv.
"""
import argparse, time

from agent import (OUT, REPORTS_PATH, friendly_error, has_key, investigate, list_images,
                   load_reports, report_key, save_reports)
from render import reports_to_csv, reports_to_markdown

ap = argparse.ArgumentParser()
ap.add_argument("--force", action="store_true")
ap.add_argument("--crop", type=float, default=None, help="keep this fraction of each side (0.3-1.0)")
args = ap.parse_args()

if not has_key():
    raise SystemExit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

OUT.mkdir(exist_ok=True)
reports, failed = load_reports(), {}
files = list_images()
print(f"{len(files)} images found, {len(reports)} already analysed.")
for i, p in enumerate(files, 1):
    key = report_key(p.name, args.crop)
    if key in reports and not args.force:
        print(f"[{i}/{len(files)}] {key}: cached, skipping")
        continue
    print(f"[{i}/{len(files)}] analysing {key} ...", flush=True)
    t = time.time()
    try:
        reports[key] = investigate(p, crop=args.crop)
        save_reports(reports)           # save after every image so a crash loses nothing
        r = reports[key]
        print(f"    {r['identified_landmark'].get('name') or 'unidentified'} | "
              f"{r['location_confidence'].get('level')} | AI {r['authenticity'].get('ai_generated_probability')}% "
              f"| {len(r['sources'])} sources | {time.time() - t:.0f}s")
    except Exception as e:
        failed[key] = friendly_error(e)
        print("    FAILED:", failed[key])

(OUT / "reports.md").write_text(reports_to_markdown(reports), encoding="utf-8")
(OUT / "summary.csv").write_text(reports_to_csv(reports), encoding="utf-8-sig", newline="")  # BOM so Excel reads ₹ etc.
print(f"\nDone: {len(reports)} reports, {len(failed)} failed. Saved to {OUT}/ ({REPORTS_PATH.name}, reports.md, summary.csv)")
for k, v in failed.items():
    print(f"  - {k}: {v}")
