import re

from pydantic import BaseModel, ConfigDict

from jubensha.schema.genre import GenreProfile, RubricItem
from jubensha.schema.ir import Script
from jubensha.schema.state import GameState


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcomes: dict[str, bool]
    score: float
    max_score: float
    passed: bool
    partial_credit: bool


def profile_for(script: Script) -> GenreProfile:
    if script.genre not in ("本格", "变格"):
        raise ValueError(f"genre {script.genre} has no V1 profile")
    return GenreProfile(
        genre=script.genre, win_condition=script.win_condition, dm_tone=script.tone,
        rubric=[RubricItem(key=key, weight=1, description=key)
                for key in script.win_condition.required],
        parser_expectations=[],
    )


def text_terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return words


def judge_submission(script: Script, state: GameState,
                     profile: GenreProfile | None = None) -> Judgment:
    profile = profile or profile_for(script)
    culprits = {key for key, character in script.characters.items() if character.is_culprit}
    evidence = set(state.vote_evidence_ids)
    owned = set(state.public_clue_ids)
    for seat in state.seats.values():
        owned.update(seat.private_clue_ids)
    culprit_events = {event.event_id for event in script.truth_events
                      if culprits.intersection(event.actor_ids)}
    culprit_secrets = {key for key, secret in script.secrets.items()
                       if secret.owner_role_id in culprits}
    motive_terms = text_terms(" ".join(
        goal for role_id in culprits for goal in script.characters[role_id].private_goals))
    player_terms = text_terms(state.vote_motive)
    public_terms = text_terms(" ".join(
        [act.public_narrative for act in script.acts]
        + [character.public_profile for character in script.characters.values()]))
    evidence_terms = text_terms(" ".join(script.clues[key].surface_text for key in evidence
                                      if key in owned and key in script.clues))
    motive_evidence = (motive_terms - public_terms).intersection(evidence_terms)
    outcomes = {
        "culprit": state.vote_role_id in culprits,
        "motive": bool(player_terms.intersection(motive_evidence)),
        "key_evidence": any(
            clue_id in owned and clue_id in script.clues
            and (set(script.clues[clue_id].reveals_event_ids).intersection(culprit_events)
                 or set(script.clues[clue_id].reveals_secret_ids).intersection(culprit_secrets))
            for clue_id in evidence),
    }
    required = profile.win_condition.required
    weights = {item.key: item.weight for item in profile.rubric}
    score = sum(weights.get(key, 1) for key in required if outcomes.get(key, False))
    max_score = sum(weights.get(key, 1) for key in required)
    return Judgment(outcomes={key: outcomes.get(key, False) for key in required},
                    score=score, max_score=max_score,
                    passed=all(outcomes.get(key, False) for key in required),
                    partial_credit=profile.win_condition.partial_credit and 0 < score < max_score)
