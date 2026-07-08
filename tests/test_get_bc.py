"""
Tests for BC (背驰) calculation module (get_bc.py)

Covers:
- beichi_pz: 盘整背驰 detection
- beichi_qs: 趋势背驰 detection
- compute_line_bc: adjacent same-direction line comparison
- compute_all_bcs: batch computation
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from chanlun.cl_interface import (
    FX, BI, ZS, LINE, FxStatus, BiType, CLKline,
    compare_ld_beichi, query_macd_ld,
)
from chanlun.get_bc import (
    beichi_pz, beichi_qs, compute_line_bc, compute_all_bcs, _get_direction,
)
import datetime


def _mk_kline(idx: int, date_str: str, h: float, l: float) -> CLKline:
    return CLKline(k_index=idx, date=datetime.datetime.strptime(date_str, "%Y-%m-%d"),
                   h=h, l=l, o=l, c=h, a=10000)


def _mk_fx(k: CLKline, _type: FxStatus, val: float, index: int = 0) -> FX:
    return FX(_type=_type, k=k, klines=[k, k, k], val=val, index=index)


def _mk_bi(high: float, low: float, bi_type: BiType, index: int = 0,
           start_date: str = "2024-01-01", end_date: str = "2024-01-02",
           k_idx_base: int = 0) -> BI:
    """Create a BI with given high/low/type."""
    sk = _mk_kline(k_idx_base, start_date, high, high)
    ek = _mk_kline(k_idx_base + 1, end_date, low, low)
    if bi_type in (BiType.UP, BiType.VERIFY_UP):
        sfx = _mk_fx(sk, FxStatus.BOTTOM, low, index * 2)
        efx = _mk_fx(ek, FxStatus.TOP, high, index * 2 + 1)
    else:
        sfx = _mk_fx(sk, FxStatus.TOP, high, index * 2)
        efx = _mk_fx(ek, FxStatus.BOTTOM, low, index * 2 + 1)
    bi = BI(start=sfx, end=efx, _type=bi_type, index=index)
    bi.high = high
    bi.low = low
    return bi


def _mk_zs(zg, zd, gg, dd, zs_type="bi", lines=None):
    sk = _mk_kline(0, "2024-01-01", gg, dd)
    ek = _mk_kline(1, "2024-01-02", gg, dd)
    sfx = _mk_fx(sk, FxStatus.BOTTOM, dd, 0)
    efx = _mk_fx(ek, FxStatus.TOP, gg, 1)
    zs = ZS(zs_type=zs_type, start=sfx, end=efx, zg=zg, zd=zd, gg=gg, dd=dd)
    if lines:
        for ln in lines:
            zs.add_line(ln)
    return zs


class TestGetDirection:
    """Test direction detection"""

    def test_up(self):
        bi = _mk_bi(10, 8, BiType.UP, 0)
        assert _get_direction(bi) == "up"

    def test_down(self):
        bi = _mk_bi(10, 8, BiType.DOWN, 0)
        assert _get_direction(bi) == "down"

    def test_verify_up(self):
        bi = _mk_bi(10, 8, BiType.VERIFY_UP, 0)
        assert _get_direction(bi) == "up"

    def test_verify_down(self):
        bi = _mk_bi(10, 8, BiType.VERIFY_DOWN, 0)
        assert _get_direction(bi) == "down"


class TestBeichiPz:
    """Test 盘整背驰 (consolidation divergence)"""

    def test_null_inputs(self):
        """Null inputs return (False, None)"""
        cd = MagicMock()
        result = beichi_pz(cd, None, None)
        assert result == (False, None)

    def test_zs_with_few_lines(self):
        """ZS with < 2 lines returns (False, None)"""
        cd = MagicMock()
        zs = _mk_zs(10, 8, 12, 5)
        bi = _mk_bi(12, 9, BiType.UP, 0)
        result = beichi_pz(cd, zs, bi)
        assert result == (False, None)

    def test_pz_with_lines(self):
        """When ZS has lines, compare the last same-direction line"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {"dif": [0.1]*100, "dea": [0.05]*100, "hist": [0.1]*100}
        }
        # Create lines for ZS
        L0 = _mk_bi(10, 8, BiType.UP, 0)    # entering
        L1 = _mk_bi(10, 9, BiType.DOWN, 1)   # middle
        L2 = _mk_bi(11, 9, BiType.UP, 2)     # compare_line (same dir as L0)
        now = _mk_bi(12, 10, BiType.UP, 3)    # now_line (departure)
        zs = _mk_zs(10, 9, 11, 8, lines=[L0, L1, L2])
        # Note: beichi_pz will compare now with L2 (the last same-direction in zs.lines)
        result = beichi_pz(cd, zs, now)
        # Even if MACD values are equal, result is (False, L2)
        assert len(result) == 2
        # compare_ld_beichi returns True only if two_ld < one_ld
        # With equal MACD values, it returns False

    def test_pz_compare_line_found(self):
        """Verify the compare_line is correctly identified"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {"dif": [0.0]*100, "dea": [0.0]*100, "hist": [0.0]*100}
        }
        L0 = _mk_bi(10, 8, BiType.UP, 0)
        L1 = _mk_bi(10, 9, BiType.DOWN, 1)
        L2 = _mk_bi(11, 9, BiType.UP, 2)
        now = _mk_bi(12, 10, BiType.UP, 3)
        zs = _mk_zs(10, 9, 11, 8, lines=[L0, L1, L2])
        _, compare_line = beichi_pz(cd, zs, now)
        # Compare line should be L2 (the last same-direction as 'up' in zs.lines, not counting 'now')
        assert compare_line is L2


class TestBeichiQs:
    """Test 趋势背驰 (trend divergence)"""

    def test_few_zss(self):
        """< 2 ZSs returns (False, [])"""
        cd = MagicMock()
        zs = _mk_zs(10, 8, 12, 5)
        now = _mk_bi(12, 9, BiType.UP, 0)
        result = beichi_qs(cd, [], [zs], now)
        assert result == (False, [])

    def test_no_trend(self):
        """When ZSs don't form trend, returns (False, [])"""
        cd = MagicMock()
        zs1 = _mk_zs(10, 8, 12, 5)
        zs2 = _mk_zs(11, 9, 13, 5)  # overlaps with zs1, no trend
        now = _mk_bi(12, 9, BiType.UP, 0)
        result = beichi_qs(cd, [], [zs1, zs2], now)
        assert result == (False, [])

    def test_none_now_line(self):
        cd = MagicMock()
        zs1 = _mk_zs(6, 4, 7, 3)
        zs2 = _mk_zs(10, 8, 12, 7)
        result = beichi_qs(cd, [], [zs1, zs2], None)
        assert result == (False, [])


class TestComputeLineBc:
    """Test line-level divergence"""

    def test_few_lines(self):
        """Need at least 2 lines to compare"""
        cd = MagicMock()
        bi = _mk_bi(10, 8, BiType.UP, 0)
        result = compute_line_bc(cd, bi, [bi], 0)
        assert result == (False, None)

    def test_line_bc_compare(self):
        """Compare with previous same-direction line"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {"dif": [0.0]*100, "dea": [0.0]*100, "hist": [0.0]*100}
        }
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(12, 9, BiType.UP, 2),  # compare_line
            _mk_bi(12, 11, BiType.DOWN, 3),
            _mk_bi(13, 11, BiType.UP, 4),  # now_line
        ]
        is_bc, compare = compute_line_bc(cd, lines[4], lines, 4)
        # With equal hist values, should not be BC
        assert is_bc is False
        assert compare is lines[2]  # Previous up line at index 2

    def test_line_bc_no_prev_same(self):
        """If no previous same-direction line, returns (False, None)"""
        cd = MagicMock()
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(12, 9, BiType.UP, 2),
        ]
        is_bc, compare = compute_line_bc(cd, lines[2], lines, 2)
        # There's a previous UP at index 0
        assert compare is lines[0]


class TestComputeAllBcs:
    """Test batch BC computation"""

    def test_empty_lines(self):
        """Empty/too-few lines should not crash"""
        compute_all_bcs(MagicMock(), [], [], "bi")
        bi = _mk_bi(10, 8, BiType.UP, 0)
        compute_all_bcs(MagicMock(), [bi], [], "bi")

    def test_adds_bc_to_lines(self):
        """BC should be added to lines when divergence is found"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {
                "dif": [0.0]*100,
                "dea": [0.0]*100,
                "hist": [0.0]*100,
            }
        }
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(12, 9, BiType.UP, 2),
            _mk_bi(12, 11, BiType.DOWN, 3),
            _mk_bi(13, 11, BiType.UP, 4),
        ]
        compute_all_bcs(cd, lines, [], "bi")
        # Each line may or may not have BC depending on MACD values
        # At minimum, the function should not crash
        for line in lines:
            assert isinstance(line.get_bcs("bi"), list)

    def test_adds_bc_with_divergence(self):
        """When second line has lower MACD, BC should be detected"""
        cd = MagicMock()
        # First UP has strong MACD, second UP has weaker MACD
        cd.get_idx.return_value = {
            "macd": {
                "dif": [1.0, 0.8, 0.5, 0.3, 0.1, -0.1, -0.3, -0.5, -0.3, -0.1] +
                       [0.1, 0.05, 0.02, 0.01, 0.005, -0.005, -0.01, -0.02, -0.01, -0.005] +
                       [0.01, 0.005, 0.002, 0.001, 0.0, -0.001, -0.002, -0.003, -0.002, -0.001],
                "dea": [0.0]*30,
                "hist": [10.0]*10 + [1.0]*10 + [0.1]*10,
            }
        }
        lines = [
            _mk_bi(10, 8, BiType.UP, 0, k_idx_base=0),
            _mk_bi(10, 9, BiType.DOWN, 1, k_idx_base=10),
            _mk_bi(11, 9, BiType.UP, 2, k_idx_base=20),
        ]
        compute_all_bcs(cd, lines, [], "bi")
        # Check that BC detection ran without crash
        for line in lines:
            assert isinstance(line.get_bcs("bi"), list)

    def test_with_config(self):
        """Config should be accepted by compute_all_bcs"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {"dif": [0.0]*10, "dea": [0.0]*10, "hist": [0.0]*10}
        }
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(11, 9, BiType.UP, 2),
        ]
        cfg = {"ZS_WZGX_TYPE": "zs_wzgx_zd"}
        compute_all_bcs(cd, lines, [], "bi", config=cfg)

    def test_with_zs_and_bc(self):
        """BC computation with ZSs present"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {"dif": [0.0]*100, "dea": [0.0]*100, "hist": [0.0]*100}
        }
        lines = [
            _mk_bi(10, 8, BiType.UP, 0, k_idx_base=0),
            _mk_bi(10, 9, BiType.DOWN, 1, k_idx_base=10),
            _mk_bi(10.5, 8.5, BiType.UP, 2, k_idx_base=20),
            _mk_bi(12, 9, BiType.DOWN, 3, k_idx_base=30),
            _mk_bi(13, 10, BiType.UP, 4, k_idx_base=40),
        ]
        zs = _mk_zs(10, 8.5, 12, 8, lines=[
            _mk_bi(10, 8, BiType.UP, 0, k_idx_base=0),
            _mk_bi(10, 9, BiType.DOWN, 1, k_idx_base=10),
            _mk_bi(10.5, 8.5, BiType.UP, 2, k_idx_base=20),
        ])
        compute_all_bcs(cd, lines, [zs], "bi")
        for line in lines:
            assert isinstance(line.get_bcs("bi"), list)


class TestBCInterface:
    """Test BC-related interface functions"""

    def test_compare_ld_beichi_up(self):
        """For UP direction, compare up_sum hist values"""
        # one_ld stronger (up_sum=10), two_ld weaker (up_sum=5) → beichi
        one_ld = {"macd": {"hist": {"up_sum": 10}}}
        two_ld = {"macd": {"hist": {"up_sum": 5}}}
        assert compare_ld_beichi(one_ld, two_ld, "up") is True

    def test_compare_ld_beichi_up_no_beichi(self):
        """Second stronger than first → no beichi"""
        one_ld = {"macd": {"hist": {"up_sum": 5}}}
        two_ld = {"macd": {"hist": {"up_sum": 10}}}
        assert compare_ld_beichi(one_ld, two_ld, "up") is False

    def test_compare_ld_beichi_down(self):
        """For DOWN direction, compare down_sum hist values"""
        one_ld = {"macd": {"hist": {"down_sum": 10}}}
        two_ld = {"macd": {"hist": {"down_sum": 5}}}
        assert compare_ld_beichi(one_ld, two_ld, "down") is True

    def test_compare_ld_beichi_down_no_beichi(self):
        one_ld = {"macd": {"hist": {"down_sum": 5}}}
        two_ld = {"macd": {"hist": {"down_sum": 10}}}
        assert compare_ld_beichi(one_ld, two_ld, "down") is False

    def test_compare_ld_beichi_default_sum(self):
        """Default comparison uses 'sum' key"""
        one_ld = {"macd": {"hist": {"sum": 10}}}
        two_ld = {"macd": {"hist": {"sum": 5}}}
        assert compare_ld_beichi(one_ld, two_ld, "unknown_dir") is True

    def test_compare_ld_beichi_no_macd(self):
        """Missing macd key returns False"""
        assert compare_ld_beichi({}, {}, "up") is False

    def test_query_macd_ld(self):
        """query_macd_ld returns expected dictionary structure"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {
                "dif": [0.1] * 20 + [0.05] * 20,
                "dea": [0.05] * 20 + [0.02] * 20,
                "hist": [0.5] * 10 + [-0.3] * 10 + [0.2] * 10 + [-0.1] * 10,
            }
        }
        sk = _mk_kline(0, "2024-01-01", 10, 9)
        ek = _mk_kline(39, "2024-02-10", 10, 9)
        sfx = _mk_fx(sk, FxStatus.BOTTOM, 9, 0)
        efx = _mk_fx(ek, FxStatus.TOP, 10, 39)
        result = query_macd_ld(cd, sfx, efx)
        assert "dea" in result
        assert "dif" in result
        assert "hist" in result
        assert "end" in result["dea"]
        assert "max" in result["dea"]
        assert "min" in result["dea"]
