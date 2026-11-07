# detectparty_hdrl

A political-speech **Republican-vs-Democrat** prediction study. Participants read a short speech
plus an explanation hint and predict whether it was given by a Republican or a Democrat.

Built from the sibling `detectfake_rlvr` app: plain Flask + SQLite, deployable on any VPS via
uWSGI/Gunicorn.

## How it works

- **Anonymous users** — identified by a `political_vsave` cookie (no login).
- **Data** lives in `speeches_sampled_explanation_hdrl.jsonl` at the repo root: one JSON object per line,
  `{text, label, explanation}`, 500 records (250 `R`, 250 `D`). The file has no id field, so a
  record's **line position** is its stable id (`stimulus_index`) and a `text_sha1` is stored
  with each answer.
- **Balanced coverage** — each participant answers up to `TRIALS_PER_USER` distinct speeches,
  fewest-decisions-first, and no speech is served more than `MAX_DECISIONS` times overall.
- **Resumable** — progress lives in the database.
- **Database** is the SQLite file shared with `detectfake_rlvr` (`../detectfake_rlvr/webapp/detectfakesv3.db`
  by default; set `DETECTFAKE_DB_PATH` to point elsewhere). This app adds one table,
  `HDRLPartyGuess` (`hdrl_party`, one row per answer), and never touches the existing tables. `label_truth`
  and `guess` use the JSONL's codes: `R` = Republican, `D` = Democrat.

## Run locally

```bash
pip install -r requirements.txt
python run.py          # serves on http://localhost:5002
```

## Deploy (uWSGI + nginx)

Edit the paths/user in `detectparty_hdrl.ini`, then `uwsgi --ini detectparty_hdrl.ini`, or:

```bash
gunicorn -w 4 -b 0.0.0.0:5002 wsgi:application
```

## Configuration knobs (`webapp/text_routes.py`)

- `TRIALS_PER_USER` — trials per participant (default `50`); `None` = the whole pool.
- `MAX_DECISIONS` — stop serving a speech once this many participants have judged it (default 5).
- `MAX_EXPLANATION_BULLETS` — max hint bullets shown; `None` (default) shows all.
