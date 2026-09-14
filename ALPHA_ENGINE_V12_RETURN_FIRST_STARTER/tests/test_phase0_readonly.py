from pathlib import Path

def test_phase0_has_no_forward_or_cloud_mutation_code():
    root=Path(__file__).resolve().parents[1]
    text="\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (root/"scripts").glob("*.py"))
    forbidden=["requests.post(", "ForwardRemote(", "send_status(", "operation_append", "cash_adjustment_append"]
    for token in forbidden:
        assert token not in text
