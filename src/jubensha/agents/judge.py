import json

from pydantic import BaseModel, ConfigDict, Field

from jubensha.llm.gateway import configured, generate
from jubensha.storage.events import EventStore


class JudgeScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_character: int = Field(ge=0, le=5)
    consistent: int = Field(ge=0, le=5)
    grounded: int = Field(ge=0, le=5)
    natural: int = Field(ge=0, le=5)
    reason: str


def judge_response(store: EventStore, game_id: str, public_profile: str,
                   authorized_knowledge: list[str], dialogue: list[str], response: str) -> JudgeScore:
    if not configured():
        raise RuntimeError("LLM_MODEL is required for model judging")
    messages = [
        {"role": "system", "content": "只评价角色一致性、对话一致性、授权知识依据与自然度，各给0到5分。你不掌握案件真相，不要判定秘密是否泄露。只输出JSON：in_character,consistent,grounded,natural,reason。"},
        {"role": "user", "content": json.dumps({"public_profile": public_profile,
                                                "authorized_knowledge": authorized_knowledge,
                                                "dialogue": dialogue[-8:], "response": response}, ensure_ascii=False)},
    ]
    raw = generate(store, game_id, "eval_judge", "eval.judge.v1", messages,
                   max_tokens=300, json_mode=True)
    return JudgeScore.model_validate_json(raw)
