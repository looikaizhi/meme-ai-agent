from memedogV2.__main__ import _load_candidate_file


def test_load_candidate_file_uses_custom_source(tmp_path):
    path = tmp_path / "candidates.txt"
    path.write_text("CA1 LP1\nCA2\n")

    out = _load_candidate_file(str(path), source="cohort:famous-memes")

    assert [item.ca_address for item in out] == ["CA1", "CA2"]
    assert out[0].lp_address == "LP1"
    assert {item.source for item in out} == {"cohort:famous-memes"}
