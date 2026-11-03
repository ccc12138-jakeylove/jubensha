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
    for phrase in re.findall(r"[一-鿿]+", text):
        words.update(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return words


# 动机裁判不接受“没有发现/并非为了/不是为了”这类只出现关键词的表述。
# 先移除双重否定和“不仅/不但”等非否定用法，再按奇偶判断否定作用域。
_NEGATION_MARKERS = (
    "并没有", "不是", "没有", "没能", "并非", "并不", "并未", "不曾",
    "未曾", "从未", "尚未", "绝不", "绝非", "毫无", "否认", "未必",
    "没", "未", "不",
)
_DOUBLE_NEGATIONS = (
    "不得不", "不能不", "不是不", "并非不", "并非没有", "并没有不",
    "没有不", "未尝不", "不无", "无不",
)
_NON_NEGATING = (
    "不仅", "不但", "不只", "不光", "不过", "不错", "不少", "不久",
    "不断", "不同", "不幸", "不料", "不免", "不妨", "不禁", "不由得",
    "忍不住", "恨不得", "巴不得", "差不多", "了不起", "没准", "没错",
    "没关系", "没事", "不安", "不悦", "不慌不忙", "未来",
)
# 默认动机词来自角色目标的二字切片；过滤高频虚词，避免“发现/自己”这类
# 泛词把无关句误判为命中。正式剧本仍建议配置 motive_terms。
_GENERIC_TERMS = {
    "自己", "别人", "不要", "不能", "必须", "一定", "发现", "知道", "关系",
    "事情", "时候", "已经", "需要", "为了", "因为", "所以", "但是", "如果",
    "可以", "没有", "不是", "什么", "怎么", "如何", "现在", "之后", "之前",
    "一个", "我们", "他们", "你们", "这个", "那个", "东西", "出来", "进行",
}
_CLAUSE_SPLIT = re.compile(r"[，,。；;！？!?\n]+|而是|但是|可是|然而|不过")


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT.split(text) if part.strip()]


def _negation_count(clause: str) -> int:
    text = clause
    for phrase in _DOUBLE_NEGATIONS:
        text = text.replace(phrase, "")
    for phrase in _NON_NEGATING:
        text = text.replace(phrase, "")
    count = 0
    for marker in sorted(_NEGATION_MARKERS, key=len, reverse=True):
        # 长标记优先替换，避免“并没有”同时被“没有”和“没”重复计数。
        count += text.count(marker)
        text = text.replace(marker, "")
    return count


def clause_is_negated(clause: str) -> bool:
    return _negation_count(clause) % 2 == 1


def affirmed_mentions(text: str, terms: list[str]) -> list[str]:
    """只返回出现在肯定子句里的动机词。"""
    return [term for term in terms
            if term and any(term in clause and not clause_is_negated(clause)
                            for clause in _clauses(text))]


def negated_mentions(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms
            if term and any(term in clause and clause_is_negated(clause)
                            for clause in _clauses(text))]


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
    submitted = evidence.intersection(owned).intersection(script.clues)
    public_terms = text_terms(" ".join(
        [act.public_narrative for act in script.acts]
        + [character.public_profile for character in script.characters.values()]))
    goal_terms = sorted(text_terms(" ".join(
        goal for role_id in culprits for goal in script.characters[role_id].all_goals()
    )) - public_terms - _GENERIC_TERMS)
    configured_terms = [term.strip() for term in script.win_condition.motive_terms
                        if term.strip()]
    terms = configured_terms or goal_terms
    affirmed = affirmed_mentions(state.vote_motive, terms)
    negated = negated_mentions(state.vote_motive, terms)
    motive_evidence_ids = (set(script.win_condition.motive_evidence_clue_ids)
                           if configured_terms else set())
    if motive_evidence_ids:
        accepted_evidence = submitted.intersection(motive_evidence_ids)
    else:
        accepted_evidence = submitted
    evidence_terms = text_terms(" ".join(script.clues[key].surface_text
                                         for key in accepted_evidence))
    # 未配置显式动机条款时，动机词还必须能从已提交证据中找到对应文字依据。
    linked_to_evidence = bool(set(affirmed).intersection(evidence_terms)) if not configured_terms else True
    if state.vote_role_id not in culprits:
        motive_supported = False
        motive_reason = "指认对象与真凶不一致，动机不成立"
    elif not accepted_evidence:
        motive_supported = False
        motive_reason = ("未提交约定的动机证据" if motive_evidence_ids
                         else "未提交能支持动机的已获线索")
    elif not affirmed:
        motive_supported = False
        motive_reason = ("动机表述是否定或未确认的；裁判不接受“没有发现/并非为了”等表述"
                         if negated else "动机表述未包含真凶目标或剧本约定的动机词")
    elif not linked_to_evidence:
        motive_supported = False
        motive_reason = "动机表述与已提交证据缺少语义关联"
    else:
        motive_supported = True
        motive_reason = "动机表述为肯定判断，且有已获得的证据支持"
    supporting = [clue_id for clue_id in submitted
                  if ((not culprit_secrets and set(script.clues[clue_id].reveals_event_ids).intersection(culprit_events))
                      or set(script.clues[clue_id].reveals_secret_ids).intersection(culprit_secrets))]
    outcomes = {
        "culprit": state.vote_role_id in culprits,
        "motive": motive_supported,
        "key_evidence": bool(supporting),
    }
    reasons = {
        "culprit": "指认与真凶一致" if outcomes["culprit"] else "指认对象与真凶不一致",
        "motive": motive_reason,
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
