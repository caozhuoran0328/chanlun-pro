"""
Tests for MMD (买卖点) calculation module (get_mmd.py)

Covers:
- compute_mmd: logic for identifying buy/sell points
- _check_1buy, _check_2buy, _check_3buy
- _check_1sell, _check_2sell, _check_3sell
- compute_all_mmds: batch computation
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import MagicMock
from chanlun.cl_interface import FX, BI, ZS, FxStatus, BiType, CLKline
from chanlun.get_mmd import (
    compute_mmd, compute_all_mmds,
    _is_down, _is_up, _get_prev_same_dir, _get_prev_reverse_dir, _line_has_mmd,
    _check_1buy, _check_2buy, _check_3buy,
    _check_1sell, _check_2sell, _check_3sell,
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
    """Create a mock ZS."""
    sk = _mk_kline(0, "2024-01-01", gg, dd)
    ek = _mk_kline(1, "2024-01-02", gg, dd)
    sfx = _mk_fx(sk, FxStatus.BOTTOM, dd, 0)
    efx = _mk_fx(ek, FxStatus.TOP, gg, 1)
    zs = ZS(zs_type=zs_type, start=sfx, end=efx, zg=zg, zd=zd, gg=gg, dd=dd)
    if lines:
        for ln in lines:
            zs.add_line(ln)
    return zs


class TestHelpers:
    """Test internal helper functions"""

    def test_is_down(self):
        bi = _mk_bi(10, 8, BiType.DOWN, 0)
        assert _is_down(bi) is True
        assert _is_up(bi) is False

    def test_is_up(self):
        bi = _mk_bi(10, 8, BiType.UP, 0)
        assert _is_up(bi) is True
        assert _is_down(bi) is False

    def test_is_down_verify(self):
        bi = _mk_bi(8, 10, BiType.VERIFY_DOWN, 0)
        assert _is_down(bi) is True

    def test_is_up_verify(self):
        bi = _mk_bi(8, 10, BiType.VERIFY_UP, 0)
        assert _is_up(bi) is True

    def test_get_prev_same_dir(self):
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(11, 9, BiType.UP, 2),
        ]
        prev, i = _get_prev_same_dir(lines[2], lines, 2)
        assert prev is lines[0]
        assert i == 0

    def test_get_prev_same_dir_none(self):
        lines = [_mk_bi(10, 8, BiType.UP, 0)]
        prev, i = _get_prev_same_dir(lines[0], lines, 0)
        assert prev is None

    def test_get_prev_reverse_dir(self):
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
        ]
        prev, i = _get_prev_reverse_dir(lines[1], lines, 1)
        assert prev is lines[0]
        assert i == 0

    def test_line_has_mmd(self):
        bi = _mk_bi(10, 8, BiType.DOWN, 0)
        zs = _mk_zs(8, 6, 10, 5)
        bi.add_mmd("1buy", zs, "bi")
        assert _line_has_mmd(bi, "1buy", "bi") is True
        assert _line_has_mmd(bi, "2buy", "bi") is False


class TestCheck1Buy:
    """Test first buy point detection"""

    def test_1buy_requires_bc(self):
        """1buy requires BC; line without BC should not get 1buy"""
        bi = _mk_bi(5, 3, BiType.DOWN, 2)
        zs = _mk_zs(8, 6, 10, 5)
        # No BC added to bi
        _check_1buy(bi, [bi], [zs], 2, "bi", MagicMock())
        assert "1buy" not in bi.line_mmds("bi")

    def test_1buy_with_bc_below_zs(self):
        """1buy with BC and price below ZS dd"""
        bi = _mk_bi(5, 2, BiType.DOWN, 2)
        zs = _mk_zs(10, 8, 12, 6)
        # Add BC to bi
        bi.add_bc("qs", zs, None, [], True, "bi")
        # Add a previous same-direction line
        prev_bi = _mk_bi(10, 7, BiType.DOWN, 0)
        lines = [prev_bi, _mk_bi(9, 7, BiType.UP, 1), bi]
        _check_1buy(bi, lines, [zs], 2, "bi", MagicMock())
        assert "1buy" in bi.line_mmds("bi")

    def test_1buy_not_below_zs(self):
        """If line low is NOT below ZS dd, no 1buy"""
        bi = _mk_bi(9, 7, BiType.DOWN, 2)
        zs = _mk_zs(10, 8, 12, 6)  # dd=6, low=7 > 6
        bi.add_bc("qs", zs, None, [], True, "bi")
        prev_bi = _mk_bi(10, 8, BiType.DOWN, 0)
        lines = [prev_bi, _mk_bi(10, 8.5, BiType.UP, 1), bi]
        _check_1buy(bi, lines, [zs], 2, "bi", MagicMock())
        assert "1buy" not in bi.line_mmds("bi")


class TestCheck2Buy:
    """Test second buy point detection"""

    def test_2buy_no_prev_1buy(self):
        """Without previous 1buy, no 2buy"""
        bi = _mk_bi(8, 6, BiType.DOWN, 2)
        zs = _mk_zs(10, 8, 12, 5)
        lines = [
            _mk_bi(10, 7, BiType.DOWN, 0),
            _mk_bi(10, 8, BiType.UP, 1),
            bi,
        ]
        _check_2buy(bi, lines, [zs], 2, "bi")
        assert "2buy" not in bi.line_mmds("bi")

    def test_2buy_with_prev_1buy(self):
        """With previous 1buy and not breaking below, get 2buy"""
        bi = _mk_bi(7, 4, BiType.DOWN, 3)  # next down after 1buy
        zs = _mk_zs(10, 8, 12, 5)
        # First create a line with 1buy
        prev_down = _mk_bi(6, 3, BiType.DOWN, 1)
        prev_down.add_mmd("1buy", zs, "bi")
        lines = [
            _mk_bi(10, 8, BiType.DOWN, 0),
            _mk_bi(10, 8.5, BiType.UP, 1),
            prev_down,  # 1buy
            _mk_bi(8, 5, BiType.UP, 2),
            bi,
        ]
        _check_2buy(bi, lines, [zs], 4, "bi")
        assert "2buy" in bi.line_mmds("bi")

    def test_2buy_breaks_below_1buy(self):
        """If breaking below 1buy low, no 2buy"""
        bi = _mk_bi(6, 2, BiType.DOWN, 3)  # low=2 breaks below 1buy low=3
        zs = _mk_zs(10, 8, 12, 5)
        prev_down = _mk_bi(6, 3, BiType.DOWN, 1)
        prev_down.add_mmd("1buy", zs, "bi")
        lines = [
            _mk_bi(10, 8, BiType.DOWN, 0),
            _mk_bi(10, 8.5, BiType.UP, 1),
            prev_down,
            _mk_bi(8, 5, BiType.UP, 2),
            bi,
        ]
        _check_2buy(bi, lines, [zs], 4, "bi")
        assert "2buy" not in bi.line_mmds("bi")


class TestCheck3Buy:
    """Test third buy point detection"""

    def test_3buy_requires_breakout(self):
        """Previous UP line must break above ZS zg and pullback must stay above zg"""
        bi = _mk_bi(10, 8.5, BiType.DOWN, 2)  # down pullback: low=8.5 > zg=8
        zs = _mk_zs(8, 6, 10, 5)  # zg=8
        prev_up = _mk_bi(12, 7, BiType.UP, 1)  # broke above zg=8
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            prev_up,
            bi,
        ]
        _check_3buy(bi, lines, [zs], 3, "bi")
        assert "3buy" in bi.line_mmds("bi")

    def test_3buy_no_breakout(self):
        """If previous UP line did NOT break zg, no 3buy"""
        bi = _mk_bi(8, 6, BiType.DOWN, 2)
        zs = _mk_zs(10, 8, 12, 5)  # zg=10
        prev_up = _mk_bi(9, 6, BiType.UP, 1)  # high=9 < zg=10
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            prev_up,
        ]
        _check_3buy(bi, lines, [zs], 2, "bi")
        assert "3buy" not in bi.line_mmds("bi")

    def test_3buy_pullback_into_zs(self):
        """If pullback goes back into ZS (low <= zg), no 3buy"""
        bi = _mk_bi(7, 5, BiType.DOWN, 2)  # low=5 <= zg=8
        zs = _mk_zs(8, 6, 10, 5)
        prev_up = _mk_bi(12, 6, BiType.UP, 1)  # broke out
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            prev_up,
        ]
        _check_3buy(bi, lines, [zs], 2, "bi")
        assert "3buy" not in bi.line_mmds("bi")


class TestCheck1Sell:
    """Test first sell point detection"""

    def test_1sell_requires_bc(self):
        bi = _mk_bi(12, 8, BiType.UP, 2)
        zs = _mk_zs(5, 4, 7, 3)
        _check_1sell(bi, [bi], [zs], 2, "bi", MagicMock())
        assert "1sell" not in bi.line_mmds("bi")

    def test_1sell_with_bc_above_zs(self):
        bi = _mk_bi(15, 8, BiType.UP, 2)
        zs = _mk_zs(5, 4, 7, 3)  # gg=7, high=15 > 7
        bi.add_bc("qs", zs, None, [], True, "bi")
        prev_up = _mk_bi(10, 5, BiType.UP, 0)
        lines = [prev_up, _mk_bi(7, 5, BiType.DOWN, 1), bi]
        _check_1sell(bi, lines, [zs], 2, "bi", MagicMock())
        assert "1sell" in bi.line_mmds("bi")


class TestCheck2Sell:
    """Test second sell point detection"""

    def test_2sell_with_prev_1sell(self):
        """Previous UP has 1sell, current UP does not exceed it → 2sell"""
        bi = _mk_bi(8, 6, BiType.UP, 3)  # high=8 <= prev_up.high=8
        zs = _mk_zs(5, 4, 7, 3)
        prev_up = _mk_bi(8, 5, BiType.UP, 1)  # 1sell at high=8
        prev_up.add_mmd("1sell", zs, "bi")
        lines = [
            _mk_bi(6, 4, BiType.UP, 0),
            _mk_bi(6, 4.5, BiType.DOWN, 1),
            prev_up,
            _mk_bi(8, 6, BiType.DOWN, 2),
            bi,
        ]
        _check_2sell(bi, lines, [zs], 4, "bi")
        assert "2sell" in bi.line_mmds("bi")


class TestCheck3Sell:
    """Test third sell point detection"""

    def test_3sell_with_breakdown(self):
        bi = _mk_bi(5, 3, BiType.UP, 3)  # pullback, stays below zd=6
        zs = _mk_zs(8, 6, 10, 5)  # zd=6
        prev_down = _mk_bi(4, 2, BiType.DOWN, 2)  # broke below zd=6
        lines = [
            _mk_bi(10, 8, BiType.DOWN, 0),
            _mk_bi(9, 7, BiType.UP, 1),
            prev_down,
            bi,
        ]
        _check_3sell(bi, lines, [zs], 3, "bi")
        assert "3sell" in bi.line_mmds("bi")


class TestComputeAllMmds:
    """Test batch MMD computation"""

    def test_empty_lines(self):
        """Empty/too-few lines should not crash"""
        compute_all_mmds(MagicMock(), [], [], "bi")
        compute_all_mmds(MagicMock(), [_mk_bi(10, 8, BiType.UP, 0)], [], "bi")

    def test_no_zss(self):
        """Without ZSs, no MMDs should be computed"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(11, 9, BiType.UP, 2),
        ]
        compute_all_mmds(MagicMock(), lines, [], "bi")
        for bi in lines:
            assert bi.line_mmds("bi") == []

    def test_with_config(self):
        """Config should be accepted by compute_all_mmds"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(11, 9, BiType.UP, 2),
        ]
        cfg = {"ZS_WZGX_TYPE": "zs_wzgx_zd"}
        compute_all_mmds(MagicMock(), lines, [], "bi", config=cfg)

    def test_lines_shorter_than_three(self):
        """Lines < 3 should return early without error"""
        lines = [_mk_bi(10, 8, BiType.UP, 0)]
        zs = _mk_zs(8, 6, 10, 5)
        compute_all_mmds(MagicMock(), lines, [zs], "bi")
        assert True  # Should not crash

    def test_compute_mmd_with_confirmed_mmds(self):
        """Integration: full buy/sell cycle should produce MMDs"""
        cd = MagicMock()
        cd.get_idx.return_value = {
            "macd": {"dif": [0.0] * 100, "dea": [0.0] * 100, "hist": [0.0] * 100}
        }

        # Create a sequence: DOWN(BC) → UP → DOWN(1buy) → UP → DOWN(2buy)
        bi0_down = _mk_bi(10, 8, BiType.DOWN, 0, k_idx_base=0)
        bi1_up = _mk_bi(12, 9, BiType.UP, 1, k_idx_base=10)
        bi2_down = _mk_bi(5, 2, BiType.DOWN, 2, k_idx_base=20)
        bi3_up = _mk_bi(8, 4, BiType.UP, 3, k_idx_base=30)
        bi4_down = _mk_bi(5, 3, BiType.DOWN, 4, k_idx_base=40)

        zs = _mk_zs(8, 6, 10, 5, lines=[bi0_down, bi1_up])
        bi2_down.add_bc("qs", zs, None, [], True, "bi")

        lines = [bi0_down, bi1_up, bi2_down, bi3_up, bi4_down]
        compute_mmd(cd, bi2_down, lines, [zs], 2, "bi")
        assert "1buy" in bi2_down.line_mmds("bi")

        compute_mmd(cd, bi4_down, lines, [zs], 4, "bi")
        assert "2buy" in bi4_down.line_mmds("bi")


class TestMMDObject:
    """Test MMD object properties"""

    def test_mmd_creation(self):
        from chanlun.cl_interface import MMD
        zs = _mk_zs(8, 6, 10, 5)
        mmd = MMD("1buy", zs)
        mmd.msg = "第一类买点"
        assert mmd.name == "1buy"
        assert mmd.zs == zs
        assert mmd.msg == "第一类买点"

    def test_mmd_str(self):
        from chanlun.cl_interface import MMD
        zs = _mk_zs(8, 6, 10, 5)
        mmd = MMD("1buy", zs)
        s = str(mmd)
        assert "1buy" in s
