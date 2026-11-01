import json
from pathlib import Path

from jubensha.schema.ir import Script


def test_fixture_valid():
    script = Script.model_validate(json.loads(Path("fixtures/wugang_01.json").read_text(encoding="utf-8")))
    assert len(script.locations) == 6
    assert set(script.leak_surfaces) == set(script.secrets)
    assert len(script.characters) == 4
