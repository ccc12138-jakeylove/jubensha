import pytest

from jubensha.eval.calibration import manual_gate


def test_manual_gate_needs_real_complete_labels():
    judge = [{"human_a": str(index % 2), "human_b": str(index % 2),
              "human": str(index % 2), "model": str(index % 2)} for index in range(20)]
    probes = [{"detector_hit": "0", "human_leak": "0"} for _ in range(41)]
    npc = [{"human_leak": "0"} for _ in range(100)]
    assert manual_gate(judge, probes, npc, 41)["passed"]
    with pytest.raises(ValueError, match="100 NPC"):
        manual_gate(judge, probes, npc[:99], 41)
    with pytest.raises(ValueError, match="double-labeled"):
        manual_gate(judge[:19], probes, npc, 41)
    bad_probes = probes[:40] + [{"detector_hit": "1", "human_leak": "0"}]
    assert not manual_gate(judge, bad_probes, npc, 41)["passed"]
