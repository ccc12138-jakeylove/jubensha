from jubensha.agents.referee import (
    affirmed_mentions,
    clause_is_negated,
    judge_submission,
    negated_mentions,
)


def configure(script, terms, evidence_ids):
    script = script.model_copy(deep=True)
    script.win_condition.motive_terms = terms
    script.win_condition.motive_evidence_clue_ids = evidence_ids
    return script


def test_negated_motive_keywords_do_not_pass(script, state):
    """交接中复现的误判：关键词出现，但整句是否定。"""
    script = configure(script, ["自保", "毒酒"], ["C09"])
    state.vote_role_id = "lin_suyun"
    state.vote_evidence_ids = ["C09"]
    state.public_clue_ids.append("C09")
    state.vote_motive = "并非为了自保，也没有发现毒酒"
    result = judge_submission(script, state)
    assert not result.outcomes["motive"]
    assert "否定" in result.reasons["motive"]


def test_affirmative_clause_after_negation_still_passes(script, state):
    script = configure(script, ["自保", "欠条"], ["C04"])
    state.vote_role_id = "lin_suyun"
    state.vote_evidence_ids = ["C04"]
    state.seats["seat_1"].private_clue_ids.append("C04")
    state.vote_motive = "并非为了自保，而是为了拿回欠条"
    assert judge_submission(script, state).outcomes["motive"]


def test_double_negation_is_treated_as_affirmative(script, state):
    script = configure(script, ["欠条"], ["C04"])
    state.vote_role_id = "lin_suyun"
    state.vote_evidence_ids = ["C04"]
    state.seats["seat_1"].private_clue_ids.append("C04")
    state.vote_motive = "并非不是为了欠条"
    assert judge_submission(script, state).outcomes["motive"]


def test_motive_requires_matching_evidence(script, state):
    script = configure(script, ["欠条"], ["C04"])
    state.vote_role_id = "lin_suyun"
    state.vote_motive = "为了拿回欠条"
    assert not judge_submission(script, state).outcomes["motive"]


def test_motive_requires_correct_culprit(script, state):
    script = configure(script, ["毒酒"], ["C09"])
    state.vote_role_id = "a_dai"
    state.vote_evidence_ids = ["C09"]
    state.public_clue_ids.append("C09")
    state.vote_motive = "为了毒酒"
    result = judge_submission(script, state)
    assert not result.outcomes["motive"]
    assert "真凶" in result.reasons["motive"]


def test_default_goal_terms_are_negation_aware(script, state):
    state.vote_role_id = "lin_suyun"
    state.vote_evidence_ids = ["C04"]
    state.seats["seat_1"].private_clue_ids.append("C04")
    state.vote_motive = "欠条"
    assert judge_submission(script, state).outcomes["motive"]
    state.vote_motive = "我没有拿到欠条"
    assert not judge_submission(script, state).outcomes["motive"]


def test_clause_helpers_handle_common_chinese_patterns():
    assert clause_is_negated("并非为了自保")
    assert clause_is_negated("没有发现毒酒")
    assert not clause_is_negated("而是为了拿回欠条")
    assert not clause_is_negated("不得不拿回欠条")
    assert not clause_is_negated("不只是为了欠条")
    assert affirmed_mentions("并非为了自保，而是为了欠条", ["自保", "欠条"]) == ["欠条"]
    assert negated_mentions("并非为了自保，也没有发现毒酒", ["自保", "毒酒"]) == ["自保", "毒酒"]
