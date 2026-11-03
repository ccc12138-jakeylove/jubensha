import re

from pydantic import BaseModel, ConfigDict, Field

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
    reasons: dict[str, str] = Field(default_factory=dict)
    supporting_evidence_ids: list[str] = Field(default_factory=list)


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
                     profile: GenreProfile | None = None,
                     seat_id: str | None = None) -> Judgment:
    profile = profile or profile_for(script)
    culprits = {key for key, character in script.characters.items() if character.is_culprit}
    evidence = set(state.vote_evidence_ids)
    owned = set(state.public_clue_ids)
    if seat_id is None:
        if len(state.seats) != 1:
            raise ValueError("seat_id is required when judging a multi-seat game")
        seat_id = next(iter(state.seats))
    if seat_id not in state.seats:
        raise PermissionError("seat does not belong to this game")
    owned.update(state.seats[seat_id].private_clue_ids)
    culprit_events = {event.event_id for event in script.truth_events
                      if culprits.intersection(event.actor_ids)}
    culprit_secrets = {key for key, secret in script.secrets.items()
                       if secret.owner_role_id in culprits and secret.is_crime_secret}
    motive_terms = text_terms(" ".join(
        goal for role_id in culprits for goal in script.characters[role_id].private_goals))
    player_terms = text_terms(state.vote_motive)
    public_terms = text_terms(" ".join(
        [act.public_narrative for act in script.acts]
        + [character.public_profile for character in script.characters.values()]))
    evidence_terms = text_terms(" ".join(script.clues[key].surface_text for key in evidence
                                      if key in owned and key in script.clues))
    motive_evidence = (motive_terms - public_terms).intersection(evidence_terms)
    if script.win_condition.motive_evidence_clue_ids and script.win_condition.motive_terms:
        motive_supported = (bool(evidence.intersection(owned).intersection(
            script.win_condition.motive_evidence_clue_ids))
            and any(term in state.vote_motive for term in script.win_condition.motive_terms))
    else:
        motive_supported = bool(player_terms.intersection(motive_evidence))
    supporting = [clue_id for clue_id in evidence
                  if clue_id in owned and clue_id in script.clues
                  and ((not culprit_secrets and set(script.clues[clue_id].reveals_event_ids).intersection(culprit_events))
                       or set(script.clues[clue_id].reveals_secret_ids).intersection(culprit_secrets))]
    outcomes = {
        "culprit": state.vote_role_id in culprits,
        "motive": motive_supported,
        "key_evidence": bool(supporting),
    }
    reasons = {
        "culprit": "指认与真凶一致" if outcomes["culprit"] else "指认对象与真凶不一致",
        "motive": "动机与已获得的证据及真凶目标相关" if outcomes["motive"]
                  else "动机缺少已获得证据支持，或与真凶目标不符",
        "key_evidence": "提交了已获得且指向真凶的证据" if supporting
                        else "未提交已获得且指向真凶的关键证据",
    }
    required = profile.win_condition.required
    weights = {item.key: item.weight for item in profile.rubric}
    score = sum(weights.get(key, 1) for key in required if outcomes.get(key, False))
    max_score = sum(weights.get(key, 1) for key in required)
    return Judgment(outcomes={key: outcomes.get(key, False) for key in required},
                    score=score, max_score=max_score,
                    passed=all(outcomes.get(key, False) for key in required),
                    partial_credit=profile.win_condition.partial_credit and 0 < score < max_score,
                    reasons={key: reasons.get(key, "需由该类型裁判说明") for key in required},
                    supporting_evidence_ids=sorted(supporting))
