from . import db
from datetime import datetime


class HDRLPartyGuess(db.Model):
    """One row per answered speech per participant, for the speeches_sampled_explanation_hdrl.jsonl
    stimulus pool: the participant's Republican-vs-Democrat decision.
    Labels and guesses use the JSONL's codes: 'R' = Republican, 'D' = Democrat."""
    __tablename__ = 'hdrl_party'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(150), index=True)
    trial_num = db.Column(db.Integer)             # 1-based position in this user's session
    stimulus_index = db.Column(db.Integer)        # 0-based line number in the JSONL (stable id)
    text_sha1 = db.Column(db.String(40))          # sha1 of the speech text (the JSONL has no id field)
    label_truth = db.Column(db.String(1))         # 'R' or 'D', from the JSONL's `label`
    guess = db.Column(db.String(1))               # 'R' or 'D'
    correct = db.Column(db.Boolean)
    ip = db.Column(db.String(150))
    user_platform = db.Column(db.String(150))
    user_browser = db.Column(db.String(150))
    user_version = db.Column(db.String(150))
    user_language = db.Column(db.String(150))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<HDRLPartyGuess {self.user_id} trial={self.trial_num} idx={self.stimulus_index}>'
