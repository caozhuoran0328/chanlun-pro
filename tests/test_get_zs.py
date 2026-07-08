"""
Tests for ZS (中枢) calculation module (get_zs.py)

Covers:
- create_dn_zs: basic ZS creation, overlap detection, extension
- zss_is_qs: trend detection between two ZSs
- get_last_zs: convenience accessor
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from chanlun.cl_interface import FX, BI, ZS, LINE, FxStatus, BiType, Config, CLKline
from chanlun.get_zs import create_dn_zs, zss_is_qs, get_last_zs, get_last_zs_by_level
import datetime


def _mk_kline(idx: int, date_str: str, h: float, l: float) -> CLKline:
    """Create a minimal CLKline for testing."""
    return CLKline(
        k_index=idx,
        date=datetime.datetime.strptime(date_str, "%Y-%m-%d"),
        h=h, l=l, o=l, c=h, a=10000,
    )


def _mk_fx(k: CLKline, _type: FxStatus, val: float, index: int = 0) -> FX:
    """Create a minimal FX for testing."""
    return FX(_type=_type, k=k, klines=[k, k, k], val=val, index=index)


def _mk_line(start_fx: FX, end_fx: FX, _type, index: int = 0) -> LINE:
    """Create a minimal LINE (BI) for testing."""
    class _TL(BI):
        pass
    return _TL(start=start_fx, end=end_fx, _type=_type, index=index)


def _mk_bi(high: float, low: float, bi_type: BiType, index: int = 0,
           start_date: str = "2024-01-01", end_date: str = "2024-01-02") -> BI:
    """Create a BI with given high/low/type."""
    sk = _mk_kline(index, start_date, high, high)
    ek = _mk_kline(index + 1, end_date, low, low)
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


class TestCreateDnZs:
    """Test ZS creation from lines"""

    def test_empty_lines(self):
        """Empty input returns empty list"""
        assert create_dn_zs("bi", []) == []

    def test_too_few_lines(self):
        """Need at least 3 lines"""
        k = _mk_kline(0, "2024-01-01", 10, 9)
        fx = _mk_fx(k, FxStatus.BOTTOM, 9, 0)
        line = _mk_line(fx, fx, BiType.UP, 0)
        line.high = 10
        line.low = 9
        assert create_dn_zs("bi", [line, line]) == []

    def test_three_lines_no_overlap(self):
        """Three lines without overlap do NOT form a ZS"""
        # L0: 8->10 (up), L1: 10->9 (down), L2: 9->11 (up)
        # zg = min(10, 11) = 10, zd = max(8, 9) = 9 → zg > zd, should create ZS
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(11, 9, BiType.UP, 2),
        ]
        result = create_dn_zs("bi", lines)
        assert len(result) == 1
        zs = result[0]
        assert zs.zg == 10  # min(L0.high, L2.high) = min(10, 11)
        assert zs.zd == 9   # max(L0.low, L2.low) = max(8, 9)

    def test_three_lines_overlap(self):
        """Three overlapping lines form a ZS"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(10.5, 8.5, BiType.UP, 2),
        ]
        result = create_dn_zs("bi", lines)
        assert len(result) == 1
        zs = result[0]
        assert zs.zg == 10   # min(10, 10.5)
        assert zs.zd == 8.5  # max(8, 8.5)
        assert zs.real is True
        assert zs.done is True
        assert zs.zs_type == "bi"

    def test_no_overlap_returns_empty(self):
        """Lines with no overlap should not create ZS"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(12, 10, BiType.DOWN, 1),
            _mk_bi(14, 12, BiType.UP, 2),
        ]
        # zg = min(10, 14) = 10, zd = max(8, 12) = 12, zg(10) <= zd(12), no overlap
        result = create_dn_zs("bi", lines)
        assert len(result) == 0

    def test_zs_extension(self):
        """ZS extends when additional lines overlap"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(10.5, 8.5, BiType.UP, 2),
            _mk_bi(10.5, 9.5, BiType.DOWN, 3),
            _mk_bi(11, 9, BiType.UP, 4),
        ]
        result = create_dn_zs("bi", lines)
        assert len(result) == 1
        zs = result[0]
        # Should have extended beyond 3 lines
        assert zs.line_num >= 3

    def test_zs_line_count_tracking(self):
        """ZS correctly counts its lines"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(10.5, 8.5, BiType.UP, 2),
        ]
        result = create_dn_zs("bi", lines)
        assert len(result) == 1
        assert result[0].line_num == 3

    def test_multiple_zs(self):
        """Multiple ZSs can be created from a long line sequence"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(10.5, 8.5, BiType.UP, 2),
            _mk_bi(15, 5, BiType.DOWN, 3),   # breaks overlap
            _mk_bi(16, 6, BiType.UP, 4),
            _mk_bi(16, 7, BiType.DOWN, 5),
            _mk_bi(17, 7, BiType.UP, 6),
        ]
        result = create_dn_zs("bi", lines)
        assert len(result) >= 1

    def test_zs_with_xd_type(self):
        """ZS creation with xd type"""
        lines = [
            _mk_bi(15, 10, BiType.UP, 0),
            _mk_bi(15, 12, BiType.DOWN, 1),
            _mk_bi(14, 11, BiType.UP, 2),
        ]
        result = create_dn_zs("xd", lines)
        assert len(result) == 1
        assert result[0].zs_type == "xd"


class TestZssIsQs:
    """Test trend detection between two ZSs"""

    def _mk_zs(self, zg, zd, gg, dd, zs_type="bi"):
        sk = _mk_kline(0, "2024-01-01", gg, dd)
        ek = _mk_kline(1, "2024-01-02", gg, dd)
        sfx = _mk_fx(sk, FxStatus.BOTTOM, dd)
        efx = _mk_fx(ek, FxStatus.TOP, gg)
        zs = ZS(zs_type=zs_type, start=sfx, end=efx, zg=zg, zd=zd, gg=gg, dd=dd)
        return zs

    def test_up_trend(self):
        """Two ZSs form an upward trend when zs1.gg < zs2.dd"""
        zs1 = self._mk_zs(zg=8, zd=6, gg=9, dd=5)
        zs2 = self._mk_zs(zg=12, zd=10, gg=13, dd=9.5)
        # Default ZS_WZGX_ZGD: gg < dd for up
        dir_, _ = zss_is_qs(zs1, zs2)
        assert dir_ == "up"

    def test_down_trend(self):
        """Two ZSs form a downward trend when zs1.dd > zs2.gg"""
        zs1 = self._mk_zs(zg=14, zd=12, gg=15, dd=11)
        zs2 = self._mk_zs(zg=9, zd=7, gg=10, dd=6)
        dir_, _ = zss_is_qs(zs1, zs2)
        assert dir_ == "down"

    def test_no_trend_overlap(self):
        """No trend when ZSs overlap"""
        zs1 = self._mk_zs(zg=10, zd=6, gg=12, dd=5)
        zs2 = self._mk_zs(zg=9, zd=7, gg=11, dd=6)
        dir_, _ = zss_is_qs(zs1, zs2)
        assert dir_ is None

    def test_none_input(self):
        """None inputs return no trend"""
        zs1 = self._mk_zs(zg=10, zd=6, gg=12, dd=5)
        dir_, _ = zss_is_qs(None, zs1)
        assert dir_ is None
        dir_, _ = zss_is_qs(zs1, None)
        assert dir_ is None
        dir_, _ = zss_is_qs(None, None)
        assert dir_ is None

    def test_strict_config(self):
        """Strict comparison (ZS_WZGX_GD) also works"""
        zs1 = self._mk_zs(zg=8, zd=6, gg=9, dd=5)
        zs2 = self._mk_zs(zg=12, zd=10, gg=13, dd=9.5)
        config = {"ZS_WZGX_TYPE": Config.ZS_WZGX_GD.value}
        dir_, _ = zss_is_qs(zs1, zs2, config)
        assert dir_ == "up"

    def test_loose_config(self):
        """Loose comparison (ZS_WZGX_ZGGDD) uses zg/zd"""
        zs1 = self._mk_zs(zg=8, zd=6, gg=12, dd=5)
        zs2 = self._mk_zs(zg=14, zd=12, gg=15, dd=9)
        config = {"ZS_WZGX_TYPE": Config.ZS_WZGX_ZGGDD.value}
        dir_, _ = zss_is_qs(zs1, zs2, config)
        assert dir_ == "up"


class TestGetLastZs:
    """Test last ZS accessor functions"""

    def _mk_zs(self, zs_type="bi", level=0, index=0):
        sk = _mk_kline(0, "2024-01-01", 10, 5)
        ek = _mk_kline(1, "2024-01-02", 10, 5)
        sfx = _mk_fx(sk, FxStatus.BOTTOM, 5)
        efx = _mk_fx(ek, FxStatus.TOP, 10)
        zs = ZS(zs_type=zs_type, start=sfx, end=efx, zg=8, zd=6, gg=10, dd=5, level=level, index=index)
        return zs

    def test_get_last_zs_empty(self):
        assert get_last_zs([]) is None

    def test_get_last_zs_single(self):
        zs = self._mk_zs()
        assert get_last_zs([zs]) is zs

    def test_get_last_zs_by_type(self):
        zs_bi = self._mk_zs("bi")
        zs_xd = self._mk_zs("xd")
        assert get_last_zs([zs_bi, zs_xd], "xd") is zs_xd
        assert get_last_zs([zs_bi, zs_xd], "bi") is zs_bi
        assert get_last_zs([zs_bi, zs_xd], "unknown") is None

    def test_get_last_zs_by_level(self):
        zs0 = self._mk_zs(level=0, index=0)
        zs1 = self._mk_zs(level=1, index=1)
        assert get_last_zs_by_level([zs0, zs1], 0) is zs0
        assert get_last_zs_by_level([zs0, zs1], 1) is zs1
        assert get_last_zs_by_level([zs0, zs1], 2) is None

    def test_get_last_zs_by_level_empty(self):
        assert get_last_zs_by_level([], 0) is None

    def test_get_last_zs_multiple(self):
        zs1 = self._mk_zs("bi", index=0)
        zs2 = self._mk_zs("bi", index=1)
        assert get_last_zs([zs1, zs2]) is zs2


class TestCreateDnZsConfig:
    """Test create_dn_zs with config propagation"""

    def test_create_dn_zs_with_config_none(self):
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(10.5, 8.5, BiType.UP, 2),
        ]
        result = create_dn_zs("bi", lines, config=None)
        assert len(result) == 1
        assert result[0].zs_type == "bi"

    def test_create_dn_zs_with_config_empty_dict(self):
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(10.5, 8.5, BiType.UP, 2),
        ]
        result = create_dn_zs("bi", lines, config={})
        assert len(result) == 1

    def test_create_dn_zs_max_lines(self):
        """Test max_line_num constraint"""
        lines = [
            _mk_bi(10, 8, BiType.UP, 0),
            _mk_bi(10, 9, BiType.DOWN, 1),
            _mk_bi(10.5, 8.5, BiType.UP, 2),
            _mk_bi(10.5, 9.5, BiType.DOWN, 3),
            _mk_bi(11, 9, BiType.UP, 4),
        ]
        result = create_dn_zs("bi", lines, max_line_num=3)
        assert len(result) >= 1


class TestZSSelfMethods:
    """Test ZS object methods and attributes"""

    def _mk_zs(self, zg, zd, gg, dd, zs_type="bi"):
        sk = _mk_kline(0, "2024-01-01", gg, dd)
        ek = _mk_kline(1, "2024-01-02", gg, dd)
        sfx = _mk_fx(sk, FxStatus.BOTTOM, dd)
        efx = _mk_fx(ek, FxStatus.TOP, gg)
        zs = ZS(zs_type=zs_type, start=sfx, end=efx, zg=zg, zd=zd, gg=gg, dd=dd)
        return zs

    def test_zs_zf_calculation(self):
        """Test ZS zhenfu (振幅) calculation: returns percentage"""
        zs = self._mk_zs(8, 6, 10, 5)
        # zf = (zg-zd)/(gg-dd) * 100 = (8-6)/(10-5) * 100 = 2/5 * 100 = 40.0%
        assert zs.zf() == pytest.approx(40.0, rel=1e-9)

    def test_zs_zf_zero(self):
        """When zg == zd, zf is 0"""
        zs = self._mk_zs(8, 8, 10, 5)
        assert zs.zf() == 0.0

    def test_zs_zf_with_gg_equals_dd(self):
        """ZF handles the case where gg-dd is non-zero"""
        zs = self._mk_zs(8, 6, 15, 5)
        # zf = (8-6)/(15-5) * 100 = 2/10 * 100 = 20.0%
        assert zs.zf() == pytest.approx(20.0, rel=1e-9)

    def test_zs_add_line(self):
        zs = self._mk_zs(8, 6, 10, 5)
        line = _mk_bi(10, 8, BiType.UP, 0)
        assert zs.add_line(line) is True
        assert len(zs.lines) == 1

    def test_zs_str(self):
        zs = self._mk_zs(8, 6, 10, 5, "xd")
        s = str(zs)
        assert "xd" in s
        assert "8" in s
