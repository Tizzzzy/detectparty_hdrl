"""
Political-speech Republican-vs-Democrat prediction task.

A participant reads a short political speech plus an explanation hint and predicts
whether it was given by a **Republican** or a **Democrat**.

Stimuli come from `speeches_sampled_explanation_hdrl.jsonl` at the repo root: one JSON object per line,
`{text, label, explanation}`, where `label` is `R` (Republican) or `D` (Democrat). A record's
**line position** is its stable id (`stimulus_index`); the file has no id field.

Each participant answers up to TRIALS_PER_USER distinct records, always served
fewest-decisions-first so coverage stays even, and no record is served more than
MAX_DECISIONS times overall. Progress is stored in the database (HDRLPartyGuess, table
`hdrl_party`), so closing the tab and returning resumes where they left off. Users are
identified only by the `political_vsave` cookie -- no username prompt.
"""

import hashlib
import json
import os
import random

from flask import render_template, request, jsonify, make_response, url_for, redirect
from sqlalchemy import func as sqlfunc

from . import app, db
from .models import HDRLPartyGuess
from .helpers import get_user_id, set_user_cookie, get_ip_details


# --- Configuration ---
# Number of trials each participant completes. None => the entire stimulus pool.
TRIALS_PER_USER = 50

# Stop serving a record once this many participants have judged it.
MAX_DECISIONS = 5

# Max hint bullets shown per speech. None => show every bullet in the explanation.
MAX_EXPLANATION_BULLETS = None


# --- Data loading (once at import) ---

# The JSON lives at the repo root (CWD when run.py launches), with a fallback to the
# path relative to this file.
_JSON_REL = 'speeches_sampled_explanation_hdrl.jsonl'
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JSON_PATH = _JSON_REL if os.path.isfile(_JSON_REL) else os.path.join(_repo_root, _JSON_REL)


def clean_stimulus_text(raw):
    """Clean a speech excerpt. Lines may have a leading 'N\\t' index; strip it for
    clean rendering. Preserve paragraph breaks otherwise. (Ported from detectfakesv2.)"""
    cleaned_lines = []
    for line in raw.splitlines():
        stripped = line
        if "\t" in line:
            head, _, tail = line.partition("\t")
            if head.strip().isdigit():
                stripped = tail
        cleaned_lines.append(stripped.rstrip())
    return "\n".join(cleaned_lines).strip()


def parse_explanation_bullets(raw):
    """Parse an explanation string into a list of bullet strings (sans markers and
    indentation). Capped at MAX_EXPLANATION_BULLETS when that is set."""
    bullets = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        for marker in ("- ", "• ", "* "):
            if s.startswith(marker):
                s = s[len(marker):]
                break
        bullets.append(s)
        if MAX_EXPLANATION_BULLETS is not None and len(bullets) >= MAX_EXPLANATION_BULLETS:
            break
    return bullets


def _load_stimuli():
    """Load the JSONL into a list of render-ready stimulus dicts, one per line. A bad
    label raises instead of skipping, because skipping would shift every later index."""
    stimuli = []
    with open(_JSON_PATH, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            label = str(rec.get('label', '')).strip().upper()
            if label not in ('R', 'D'):
                raise ValueError(f"line {line_no}: unexpected label {rec.get('label')!r}")
            raw_text = str(rec.get('text', ''))
            stimuli.append({
                'index': len(stimuli),
                'label': label,
                'text_sha1': hashlib.sha1(raw_text.encode('utf-8')).hexdigest(),
                'text_body': clean_stimulus_text(raw_text),
                'hint_bullets': parse_explanation_bullets(str(rec.get('explanation', ''))),
            })
    return stimuli


STIMULI = _load_stimuli()
N_STIMULI = len(STIMULI)
print(f"[PARTY] Loaded {N_STIMULI} speeches from {_JSON_PATH}")


def total_trials():
    """How many trials a participant completes."""
    if TRIALS_PER_USER is None:
        return N_STIMULI
    return min(TRIALS_PER_USER, N_STIMULI)


def user_seed(user_id):
    """Deterministic per-user seed (user_id is normally an md5 hex string)."""
    try:
        return int(str(user_id)[:8], 16)
    except (ValueError, TypeError):
        return abs(hash(str(user_id))) % (2 ** 31)


def _completed_count(user_id):
    return HDRLPartyGuess.query.filter_by(user_id=user_id).count()


def _decision_counts():
    """stimulus_index -> number of decisions recorded so far."""
    rows = (db.session.query(HDRLPartyGuess.stimulus_index, sqlfunc.count(HDRLPartyGuess.id))
            .group_by(HDRLPartyGuess.stimulus_index).all())
    return {int(idx): int(c) for idx, c in rows}


def _answered_indices(user_id):
    rows = db.session.query(HDRLPartyGuess.stimulus_index).filter_by(user_id=user_id).all()
    return {int(r[0]) for r in rows}


def eligible_candidates(user_id):
    """(count, idx) for every stimulus this user may still answer: below the cap
    (< MAX_DECISIONS) and not yet answered by this user. Empty once the user has done
    their TRIALS_PER_USER trials. Fewest-decisions-first."""
    if _completed_count(user_id) >= total_trials():
        return []
    counts = _decision_counts()
    answered = _answered_indices(user_id)
    cands = []
    for stim in STIMULI:
        idx = stim['index']
        c = counts.get(idx, 0)
        if c < MAX_DECISIONS and idx not in answered:
            cands.append((c, idx))
    cands.sort(key=lambda t: t[0])
    return cands


def pick_candidate(cands, seed):
    """Choose the eligible stimulus with the fewest decisions. Ties are broken with a
    per-user RNG so concurrent participants spread across different stimuli rather than
    all landing on the same one."""
    if not cands:
        return None
    min_c = cands[0][0]
    least = [idx for c, idx in cands if c == min_c]
    return random.Random(f"{seed}-{min_c}-{len(least)}").choice(least)


# Cookie that records a first-time visitor has read the welcome + consent page.
CONSENT_COOKIE = 'party_hdrl_consent'
CONSENT_MAX_AGE = 60 * 60 * 24 * 365  # one year


@app.errorhandler(404)
def not_found(_e):
    return render_template('404.html'), 404


# --- Static informational pages (mirrors political_decision routes.py) ---

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/informed-consent')
def informed_consent():
    return render_template('informed-consent.html')


@app.route('/instructions')
def instructions():
    return render_template('instructions.html')


@app.route('/', methods=['GET'])
def text_home():
    user_id = get_user_id()

    # First-time visitors must read the welcome + consent page before starting. We
    # remember their agreement with a cookie so they skip it when they return.
    if request.cookies.get(CONSENT_COOKIE) != '1':
        resp = make_response(render_template('welcome-text.html'))
        set_user_cookie(resp, user_id)  # preserve id until they consent
        return resp

    completed = _completed_count(user_id)
    cands = eligible_candidates(user_id)

    # Finished when the user hit their trial cap, or nothing is left to serve them
    # (every remaining stimulus is already answered by them or fully covered).
    if not cands:
        score = HDRLPartyGuess.query.filter_by(user_id=user_id, correct=True).count()
        resp = make_response(render_template(
            'finish-text.html',
            n_seen=completed,
            max_stimuli=completed,
            score=score,
        ))
        set_user_cookie(resp, user_id)
        return resp

    idx = pick_candidate(cands, user_seed(user_id))
    # Progress denominator: what this user has done plus what still remains for them,
    # never more than their trial cap.
    total = min(total_trials(), completed + len(cands))
    stim = STIMULI[idx]

    resp = make_response(render_template(
        'text-version.html',
        text_body=stim['text_body'],
        hint_bullets=stim['hint_bullets'],
        current_trial=completed + 1,
        total=total,
        stimulus_index=idx,
    ))
    set_user_cookie(resp, user_id)
    return resp


@app.route('/text-consent', methods=['POST'])
def text_consent():
    """Record the welcome-page agreement and send the user into the task."""
    user_id = get_user_id()
    resp = make_response(redirect(url_for('text_home')))
    set_user_cookie(resp, user_id)
    resp.set_cookie(CONSENT_COOKIE, '1', max_age=CONSENT_MAX_AGE)
    return resp


@app.route('/text-guess', methods=['POST'])
def text_guess():
    try:
        data = request.get_json(force=True)
        guess_raw = (data.get('guess') or '').strip().lower()
        guess_map = {'republican': 'R', 'democrat': 'D'}
        if guess_raw not in guess_map:
            return jsonify({'success': False, 'error': 'Invalid guess'}), 400
        guess = guess_map[guess_raw]

        try:
            stimulus_index = int(data.get('stimulus_index'))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid stimulus_index'}), 400

        user_id = get_user_id()

        # Idempotency: if this stimulus was already answered by this user, return the
        # stored result instead of creating a duplicate.
        existing = HDRLPartyGuess.query.filter_by(
            user_id=user_id, stimulus_index=stimulus_index).first()
        if existing:
            score = HDRLPartyGuess.query.filter_by(user_id=user_id, correct=True).count()
            current = HDRLPartyGuess.query.filter_by(user_id=user_id).count()
            done = not eligible_candidates(user_id)
            return jsonify({
                'success': True,
                'correct': bool(existing.correct),
                'truth': str(existing.label_truth),
                'score_correct': score,
                'score_total': current,
                'redirect': url_for('text_home') if done else None,
            })

        # We trust the displayed index -- it is what the participant actually judged, even
        # if concurrent answers have since nudged its decision count. Only a malformed or
        # tampered index is rejected; silently recording it against some other stimulus
        # would attribute the decision to a text the participant never saw.
        if not 0 <= stimulus_index < N_STIMULI:
            return jsonify({'success': False, 'error': 'Unknown stimulus_index'}), 400

        completed = _completed_count(user_id)
        stim = STIMULI[stimulus_index]
        truth = stim['label']
        is_correct = (guess == truth)

        ua = request.user_agent
        new_guess = HDRLPartyGuess(
            user_id=user_id,
            trial_num=completed + 1,
            stimulus_index=stimulus_index,
            text_sha1=stim['text_sha1'],
            label_truth=truth,
            guess=guess,
            correct=is_correct,
            ip=get_ip_details(),
            user_platform=str(ua.platform),
            user_browser=str(ua.browser),
            user_version=str(ua.version),
            user_language=str(ua.language),
        )
        db.session.add(new_guess)
        db.session.commit()

        score = HDRLPartyGuess.query.filter_by(user_id=user_id, correct=True).count()
        current = completed + 1
        done = not eligible_candidates(user_id)
        redirect_url = url_for('text_home') if done else None

        return jsonify({
            'success': True,
            'correct': is_correct,
            'truth': truth,
            'score_correct': score,
            'score_total': current,
            'redirect': redirect_url,
        })
    except Exception:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Server error'}), 500
