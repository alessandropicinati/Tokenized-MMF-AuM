# Tokenized MMF — AuM Tracker

A self-updating chart of assets under management (AuM) across the major tokenized
money market funds / tokenized treasuries. Data comes from the free
[DeFiLlama API](https://api-docs.defillama.com/) (no API key, no cost). A GitHub
Action refreshes the data every Monday and commits it; GitHub Pages serves the
interactive chart at a public URL you can screenshot for slides.

```
.
├── index.html               # the chart (open this / serve via Pages)
├── funds.json               # the ONLY file you edit to add/remove funds
├── data/
│   └── aum_history.json     # the data file (auto-updated weekly)
├── scripts/
│   └── fetch_data.py        # the weekly fetcher (Python stdlib only)
└── .github/workflows/
    └── update.yml           # the weekly cron job
```

The repo ships with **sample data** so the page renders immediately. A yellow
"sample data" banner appears until the first live run replaces it (Step 5).

---

## One-time setup (~10 minutes)

These steps must be done by you — they involve your GitHub account, which I can't act on.

### 1. Create the repository
On GitHub: **New repository** → name it e.g. `tokenized-mmf-aum` → **Public**
(Pages is free on public repos) → **Create**.

### 2. Add these files
Easiest: on the new repo page click **uploading an existing file**, then drag in
everything from the folder I gave you (keep the folder structure — `data/`,
`scripts/`, and `.github/workflows/` must stay as-is). Commit to `main`.

*Or* with git:
```bash
git init && git add . && git commit -m "initial"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 3. Let the Action write to the repo
**Settings → Actions → General → Workflow permissions** →
select **Read and write permissions** → **Save**.
(This lets the weekly job commit the refreshed data file.)

### 4. Turn on GitHub Pages
**Settings → Pages → Build and deployment → Source: Deploy from a branch** →
Branch: **main**, folder: **/ (root)** → **Save**.
After a minute your chart is live at:
`https://<you>.github.io/<repo>/`

### 5. Run the update once, now
**Actions** tab → **Update AuM data** → **Run workflow** → **Run**.
When it finishes (~1 min), it commits real data and the sample banner disappears.
From then on it runs automatically every Monday.

### 6. Read the run log once (important)
Open the finished run → the `Fetch latest AuM data` step prints a **SUMMARY**:
- **resolved** — funds that loaded fine.
- **missing** — funds it couldn't find. If a fund here printed
  `resolved '<fund>' via keyword match -> slug '<x>'`, copy that slug into the
  matching `defillama_slug` in `funds.json` to lock it in.
- **POSSIBLE NEW ENTRANTS** — funds above your threshold not yet in your list.
  Add any you want (see below). Nothing is added automatically, by design.

---

## Day-to-day

**Add a fund:** add one line to `funds.json` and commit:
```json
{ "key": "newfund", "name": "Issuer (TICK)", "ticker": "TICK",
  "color": "#3366CC", "defillama_slug": "best-guess-slug", "match": ["issuer","tick"] }
```
If the slug is wrong, the next run resolves it by keyword and tells you the right one.

**Remove a fund:** delete its entry from `funds.json`.

**Change which funds show / the new-entrant sensitivity:** edit `min_aum_usd`
in `funds.json` (default $50M).

**Change the cadence:** edit the `cron` line in `.github/workflows/update.yml`
(`0 6 * * 1` = Mondays 06:00 UTC).

**Get a slide image:** open the chart and click **⤓ Download PNG** (exports at 3×
for crisp slides). You can also toggle the total-market line, switch to log scale,
toggle individual funds in the legend, and drag the slider to set the date range.

---

## Notes & limits
- AuM is approximated by on-chain value (DeFiLlama TVL); it tracks the trend
  faithfully but won't match issuer / rwa.xyz figures to the dollar. Good for
  market-awareness, not for reporting NAV.
- If a fund temporarily drops out of the API, the script keeps its last known
  history (marked `stale`) rather than blanking the line.
- GitHub pauses scheduled Actions after ~60 days with no repo activity — just
  open the repo or re-run the workflow to resume.
- Everything here is free tier: DeFiLlama open API + GitHub Actions + GitHub Pages.
```
