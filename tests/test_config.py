"""Config construction: CLI flags must build instances, never mutate the class."""

import dataclasses

import pytest

from quantum_alpha.config import Config
from quantum_alpha.engine import build_arg_parser, config_from_args


def test_horizon_flag_builds_new_instance():
    args = build_arg_parser().parse_args(["--horizon", "42"])
    cfg = config_from_args(args)
    assert cfg.prediction_horizon_days == 42
    # The class default must be untouched (the old --horizon bug mutated it).
    assert Config().prediction_horizon_days == 21


def test_default_horizon_unchanged():
    args = build_arg_parser().parse_args([])
    cfg = config_from_args(args)
    assert cfg.prediction_horizon_days == 21


def test_config_is_frozen():
    cfg = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.prediction_horizon_days = 99


def test_cache_dir_flag():
    args = build_arg_parser().parse_args(["--cache-dir", "/tmp/somewhere"])
    cfg = config_from_args(args)
    assert cfg.cache_dir == "/tmp/somewhere"
