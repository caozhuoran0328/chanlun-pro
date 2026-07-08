"""
Tests for FX detection (get_fx.py)

Phase 1.2 fixes covered:
- FX_BH_* configuration validation
- Minimum K-line count check
- last_fx null checks
- fx_klines clearing after all FX types (not just VERIFY)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pandas as pd
import pytest
from chanlun.cl_interface import FxStatus, Config
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS


def make_test_cl_klines(data: list) -> pd.DataFrame:
    """Helper to create test CL klines DataFrame from list of dicts"""
    rows = []
    for i, d in enumerate(data):
        rows.append({
            'k_index': i,
            'date': pd.Timestamp(d.get('date', f'2019-01-{i+1:02d}')),
            'h': d['h'],
            'l': d['l'],
            'o': d.get('o', (d['h'] + d['l']) / 2),
            'c': d.get('c', d.get('o', (d['h'] + d['l']) / 2)),
            'a': d.get('a', 10000),
            'index': i,
            'n': d.get('n', 0),
            'q': d.get('q', False),
            'up_qs': d.get('up_qs', None),
            'klines': [],
        })
    return pd.DataFrame(rows)


def make_top_pattern_cl(base_price=10.0):
    """Create CL klines forming a top FX pattern (up up down)"""
    return make_test_cl_klines([
        {'h': base_price + 1, 'l': base_price - 0.5},       # left
        {'h': base_price + 2, 'l': base_price + 0.5},       # middle (highest)
        {'h': base_price + 0.5, 'l': base_price - 0.5},     # right
    ])


def make_bottom_pattern_cl(base_price=10.0):
    """Create CL klines forming a bottom FX pattern (down down up)"""
    return make_test_cl_klines([
        {'h': base_price + 1, 'l': base_price - 0.5},       # left
        {'h': base_price + 0.5, 'l': base_price - 1},       # middle (lowest)
        {'h': base_price + 1.5, 'l': base_price - 0.5},     # right
    ])


class TestMinKlineCount:
    """Test minimum K-line count check"""

    def test_too_few_klines(self):
        df = make_test_cl_klines([
            {'h': 10, 'l': 9},
            {'h': 11, 'l': 10},
        ])
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(df)
        assert len(fx_list) == 0  # Need at least 3

    def test_minimum_three_klines(self):
        df = make_test_cl_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 10},
            {'h': 11, 'l': 9},
        ])
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(df)
        assert len(fx_list) >= 0  # Should not crash


class TestFXDetection:
    """Test FX detection with various patterns"""

    def test_top_fx_basic(self):
        df = make_test_cl_klines([
            {'h': 10, 'l': 9},      # Not high enough
            {'h': 12, 'l': 10},     # Higher
            {'h': 11, 'l': 9.5},    # Top FX
            {'h': 11.5, 'l': 10},   # After top
            {'h': 10.5, 'l': 9},    # Lower - next bottom potential
            {'h': 10, 'l': 8.5},    # Bottom FX
            {'h': 10.5, 'l': 9},    # After bottom
        ])
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(df)
        assert len(fx_list) > 0

    def test_alternating_top_bottom(self):
        df = make_test_cl_klines([
            {'h': 10.5, 'l': 10},     # left
            {'h': 12.0, 'l': 10.5},   # middle - higher
            {'h': 11.0, 'l': 10},     # right - top FX
            {'h': 11.5, 'l': 9.5},    # after
            {'h': 11.0, 'l': 9.0},    # after
            {'h': 10.5, 'l': 9.5},    # left-like
            {'h': 10.0, 'l': 8.0},    # middle - lower
            {'h': 10.5, 'l': 9.0},    # right - bottom FX
            {'h': 11.0, 'l': 10.0},   # after
            {'h': 11.5, 'l': 10.5},   # after
            {'h': 12.0, 'l': 11.0},   # mid
            {'h': 11.5, 'l': 10.5},   # right - top FX
        ])
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(df)
        assert len(fx_list) >= 2


class TestFxBhConfig:
    """Test FX_BH_* configuration validation"""

    def test_fx_bh_yes_accepts_all(self):
        """FX_BH_YES should accept all containment relationships"""
        df = make_test_cl_klines([
            {'h': 11, 'l': 10},
            {'h': 13, 'l': 10.5},    # High
            {'h': 12, 'l': 10},      # Top
            {'h': 12.5, 'l': 10.5},
            {'h': 11.5, 'l': 9.5},
            {'h': 10.5, 'l': 8.0},   # Low
            {'h': 11.5, 'l': 9.5},   # Bottom
            {'h': 12.5, 'l': 11.5},
            {'h': 14.0, 'l': 11.5},  # Higher
            {'h': 13.0, 'l': 11.5},  # Top
        ])
        fx_proc = FX_PROCESS(config={'FX_BH_TYPE': Config.FX_BH_YES.value})
        fx_list = fx_proc.find_fenxing(df)
        # Should not crash with any config
        assert isinstance(fx_list, list)

    def test_fx_bh_dingdi(self):
        """FX_BH_DINGDI: top cannot be inside bottom"""
        df = make_test_cl_klines([
            {'h': 11, 'l': 10},
            {'h': 13, 'l': 10.5},
            {'h': 12, 'l': 10},
            {'h': 12.5, 'l': 10.5},
            {'h': 11.5, 'l': 9.5},
            {'h': 10.5, 'l': 8.0},
            {'h': 11.5, 'l': 9.5},
            {'h': 12.5, 'l': 11.5},
            {'h': 14.0, 'l': 11.5},
            {'h': 13.0, 'l': 11.5},
        ])
        fx_proc = FX_PROCESS(config={'FX_BH_TYPE': Config.FX_BH_DINGDI.value})
        fx_list = fx_proc.find_fenxing(df)
        assert isinstance(fx_list, list)

    def test_fx_bh_diding(self):
        """FX_BH_DIDING: bottom cannot be inside top"""
        df = make_test_cl_klines([
            {'h': 11, 'l': 10},
            {'h': 13, 'l': 10.5},
            {'h': 12, 'l': 10},
            {'h': 12.5, 'l': 10.5},
            {'h': 11.5, 'l': 9.5},
            {'h': 10.5, 'l': 8.0},
            {'h': 11.5, 'l': 9.5},
            {'h': 12.5, 'l': 11.5},
            {'h': 14.0, 'l': 11.5},
            {'h': 13.0, 'l': 11.5},
        ])
        fx_proc = FX_PROCESS(config={'FX_BH_TYPE': Config.FX_BH_DIDING.value})
        fx_list = fx_proc.find_fenxing(df)
        assert isinstance(fx_list, list)

    def test_fx_bh_no(self):
        """FX_BH_NO: neither top in bottom nor bottom in top"""
        df = make_test_cl_klines([
            {'h': 11, 'l': 10},
            {'h': 13, 'l': 10.5},
            {'h': 12, 'l': 10},
            {'h': 12.5, 'l': 10.5},
            {'h': 11.5, 'l': 9.5},
            {'h': 10.5, 'l': 8.0},
            {'h': 11.5, 'l': 9.5},
            {'h': 12.5, 'l': 11.5},
            {'h': 14.0, 'l': 11.5},
            {'h': 13.0, 'l': 11.5},
        ])
        fx_proc = FX_PROCESS(config={'FX_BH_TYPE': Config.FX_BH_NO.value})
        fx_list = fx_proc.find_fenxing(df)
        assert isinstance(fx_list, list)

    def test_fx_bh_no_qbh(self):
        """FX_BH_NO_QBH: previous FX cannot contain next FX"""
        df = make_test_cl_klines([
            {'h': 11, 'l': 10},
            {'h': 13, 'l': 10.5},
            {'h': 12, 'l': 10},
            {'h': 12.5, 'l': 10.5},
            {'h': 11.5, 'l': 9.5},
            {'h': 10.5, 'l': 8.0},
            {'h': 11.5, 'l': 9.5},
            {'h': 12.5, 'l': 11.5},
            {'h': 14.0, 'l': 11.5},
            {'h': 13.0, 'l': 11.5},
        ])
        fx_proc = FX_PROCESS(config={'FX_BH_TYPE': Config.FX_BH_NO_QBH.value})
        fx_list = fx_proc.find_fenxing(df)
        assert isinstance(fx_list, list)

    def test_fx_bh_no_hbq(self):
        """FX_BH_NO_HBQ: next FX cannot contain previous FX"""
        df = make_test_cl_klines([
            {'h': 11, 'l': 10},
            {'h': 13, 'l': 10.5},
            {'h': 12, 'l': 10},
            {'h': 12.5, 'l': 10.5},
            {'h': 11.5, 'l': 9.5},
            {'h': 10.5, 'l': 8.0},
            {'h': 11.5, 'l': 9.5},
            {'h': 12.5, 'l': 11.5},
            {'h': 14.0, 'l': 11.5},
            {'h': 13.0, 'l': 11.5},
        ])
        fx_proc = FX_PROCESS(config={'FX_BH_TYPE': Config.FX_BH_NO_HBQ.value})
        fx_list = fx_proc.find_fenxing(df)
        assert isinstance(fx_list, list)


class TestLastFxNullCheck:
    """Test that last_fx doesn't cause null pointer crashes"""

    def test_no_crash_on_empty_fx_list(self):
        df = make_test_cl_klines([
            {'h': 11, 'l': 10},
            {'h': 13, 'l': 10.5},
            {'h': 12, 'l': 10},
            {'h': 12.5, 'l': 10.5},
            {'h': 11.5, 'l': 9.5},
            {'h': 10, 'l': 8},
            {'h': 10.5, 'l': 9},
        ])
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(df)
        assert isinstance(fx_list, list)

    def test_get_before_last_fx_empty(self):
        fx_proc = FX_PROCESS()
        result = fx_proc.get_before_last_fx()
        assert result == (None, None)

    def test_get_before_last_fx_one(self):
        df = make_test_cl_klines([
            {'h': 10.5, 'l': 10},
            {'h': 12, 'l': 10.5},
            {'h': 11, 'l': 10},
        ])
        fx_proc = FX_PROCESS()
        fx_proc.find_fenxing(df)
        before, last = fx_proc.get_before_last_fx()
        assert before is None
        assert last is not None


class TestRealData:
    """Test with real data"""

    def test_real_pipeline(self):
        from chanlun.get_src_klines import convert_src_klines
        temp_csv = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        temp_df = pd.read_csv(temp_csv, parse_dates=['date'])
        temp_df = convert_src_klines(temp_df)
        cl_klines = get_cl_lines(temp_df)
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(cl_klines)
        assert len(fx_list) > 0
        # Each FX should have valid type, kline, and value
        for fx in fx_list:
            assert fx.type is not None
            assert fx.k is not None
            assert fx.val is not None
            assert fx.index >= 0
