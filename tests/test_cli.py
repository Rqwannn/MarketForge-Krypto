import argparse

import pytest

from binance_bot.cli import build_parser, params_from, parse_ranks


def test_parse_ranks_keeps_order_and_drops_duplicates() -> None:
    assert parse_ranks("1, 3,2,3") == [1, 3, 2]


@pytest.mark.parametrize("text", ["", "0", "6", "a", "1,,x"])
def test_parse_ranks_rejects_invalid(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_ranks(text)


def test_single_maps_sop_parameters() -> None:
    args = build_parser().parse_args(
        [
            "single",
            "--ranks",
            "1,2",
            "--modal",
            "1000",
            "--risiko",
            "2",
            "--sl",
            "4",
            "--target",
            "3",
            "--jumlah",
            "75",
            "--sinyal",
            "data",
            "--no-fill",
        ]
    )
    params = params_from(args)
    assert args.ranks == [1, 2] and args.no_fill
    assert (params.capital_usdt, params.risk_pct, params.stop_pct, params.target_pct) == (
        1000,
        2,
        4,
        3,
    )
    assert (params.quantity, params.signal_source) == (75, "data")


def test_sop_defaults_match_the_pdf() -> None:
    params = params_from(build_parser().parse_args(["single"]))
    assert (params.min_gain_pct, params.min_signs, params.stop_pct, params.target_pct) == (
        30,
        2,
        5,
        4,
    )
    assert (params.risk_pct, params.max_hold_h, params.fee_pct) == (1, 4, 0.5)


def test_leader_and_follower_arguments() -> None:
    parser = build_parser()
    leader = parser.parse_args(["leader", "--ranks", "1,2,3", "--interval", "5"])
    assert (leader.ranks, leader.interval, leader.min_naik) == ([1, 2, 3], 5.0, 30)
    follower = parser.parse_args(
        ["follower", "--hub", "http://10.0.0.2:8765", "--rank", "2", "--modal", "500"]
    )
    assert (follower.hub, follower.rank, follower.modal) == ("http://10.0.0.2:8765", 2, 500)
