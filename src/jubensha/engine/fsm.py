from enum import Enum


class Phase(str, Enum):
    ENTRY = "entry"
    READ = "read"
    ACT_OPEN = "act_open"
    SEARCH = "search"
    PRIVATE = "private"
    CONFRONT = "confront"
    VOTE = "vote"
    RECAP = "recap"
    END = "end"


TRANSITIONS = {
    Phase.ENTRY: {Phase.READ},
    Phase.READ: {Phase.ACT_OPEN},
    Phase.ACT_OPEN: {Phase.SEARCH, Phase.PRIVATE, Phase.CONFRONT},
    Phase.SEARCH: {Phase.ACT_OPEN},
    Phase.PRIVATE: {Phase.ACT_OPEN},
    Phase.CONFRONT: {Phase.ACT_OPEN, Phase.VOTE},
    Phase.VOTE: {Phase.READ, Phase.RECAP},
    Phase.RECAP: {Phase.END},
    Phase.END: set(),
}


def transition(current: Phase, target: Phase, *, last_act: bool = True,
               requires_vote: bool = True) -> Phase:
    # 非投票幕允许从对质阶段直接进入下一幕，其余转移仍按 TRANSITIONS 校验。
    advancing_without_vote = (
        current == Phase.CONFRONT and target == Phase.READ
        and not last_act and not requires_vote)
    if target not in TRANSITIONS[current] and not advancing_without_vote:
        raise ValueError(f"illegal phase transition: {current} -> {target}")
    if current == Phase.VOTE and (target == Phase.RECAP) != last_act:
        raise ValueError("vote transition does not match act position")
    return target
