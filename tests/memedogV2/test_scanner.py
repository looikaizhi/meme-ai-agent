import pytest

from memedogV2.intake import AddressIntake
from memedogV2.scanner import LaunchScanner, is_launch_alert, parse_launch_alerts, parse_open_age_min

CA1 = "So11111111111111111111111111111111111111112"
CA2 = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
LP = "BqnpCdDLPV2pFdAaLnVidmn3G93RP2p5oRdGEY2sJGez"


def test_parse_open_age_units_to_minutes():
    assert parse_open_age_min("Open: 6s ago") == pytest.approx(0.1)
    assert parse_open_age_min("Open: 2min ago") == pytest.approx(2.0)
    assert parse_open_age_min("Open: 1h ago") == pytest.approx(60.0)


def test_launch_classifier_accepts_new_pool_and_rejects_non_launch():
    assert is_launch_alert("New pool created on Solana") is True
    assert is_launch_alert("Dev sold after FDV surge") is False


def test_parse_gmgn_launch_alert_extracts_ca_lp_and_ignores_evm():
    text = (
        "New pool created\n"
        f"CA: {CA1}\n"
        f"Pool: {LP}\n"
        "Open: 6s ago\n"
        "BSC: 0x1111111111111111111111111111111111111111"
    )

    items = parse_launch_alerts(text)

    assert len(items) == 1
    assert items[0].ca_address == CA1
    assert items[0].lp_address == LP
    assert items[0].open_age_min == pytest.approx(0.1)
    assert items[0].source == "gmgn_telegram"
    assert items[0].raw_text == text


def test_parse_launch_alerts_queues_all_new_cas_without_prefiltering():
    text = (
        "New launch batch\n"
        f"CA: {CA1}\n"
        f"Token address: {CA2}\n"
        f"Pool: {LP}\n"
        "liquidity: tiny, volume: unknown"
    )

    items = parse_launch_alerts(text)

    assert [item.ca_address for item in items] == [CA1, CA2]
    assert all(item.lp_address == LP for item in items)


def test_parse_launch_alerts_respects_max_open_age():
    text = f"New pair\nCA: {CA1}\nOpen: 10min ago"

    assert parse_launch_alerts(text, max_open_age_min=5) == []


def test_launch_scanner_enqueues_and_dedups_by_ca():
    intake = AddressIntake()
    scanner = LaunchScanner(intake)
    text = f"New token\nCA: {CA1}\nPool: {LP}"

    first = scanner.enqueue_text(text)
    second = scanner.enqueue_text(text)

    assert len(first) == 1
    assert first[0].enqueued is True
    assert first[0].trace_id
    assert len(second) == 1
    assert second[0].enqueued is False
    assert second[0].trace_id == ""
    assert intake.size() == 1
