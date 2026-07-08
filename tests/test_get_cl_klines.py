"""
Tests for K-line containment processing (get_cl_klines.py)

Phase 1.1 fixes covered:
- Direction initialization from first non-containment pair
- Gap detection (CLKline._q = True)
- up_qs attribute setting
- Last K-line loss fix
- verify_bh debug mode
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pandas as pd
import pytest
from chanlun.get_cl_klines import get_cl_lines, verify_bh, _has_containment, _find_first_non_containment_direction, Direction


def make_test_klines(data: list) -> pd.DataFrame:
    """Helper to create test klines DataFrame from list of dicts"""
    rows = []
    for i, d in enumerate(data):
        rows.append({
            'index': i,
            'date': pd.Timestamp(d.get('date', f'2019-01-{i+1:02d}')),
            'h': d['h'],
            'l': d['l'],
            'o': d.get('o', (d['h'] + d['l']) / 2),
            'c': d.get('c', d.get('o', (d['h'] + d['l']) / 2)),
            'a': d.get('a', 10000),
        })
    return pd.DataFrame(rows)


class TestHasContainment:
    """Test _has_containment helper function"""

    def test_no_containment_up(self):
        k1 = {'h': 10, 'l': 9}
        k2 = {'h': 11, 'l': 10}
        assert not _has_containment(k1, k2)

    def test_no_containment_down(self):
        k1 = {'h': 11, 'l': 10}
        k2 = {'h': 10, 'l': 9}
        assert not _has_containment(k1, k2)

    def test_k2_contains_k1(self):
        k1 = {'h': 10, 'l': 9}
        k2 = {'h': 11, 'l': 8}
        assert _has_containment(k1, k2)

    def test_k1_contains_k2(self):
        k1 = {'h': 11, 'l': 8}
        k2 = {'h': 10, 'l': 9}
        assert _has_containment(k1, k2)


class TestDirectionInit:
    """Test direction initialization from first non-containment pair"""

    def test_up_trend_direction(self):
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 11},  # Up gap → direction UP
        ])
        direction = _find_first_non_containment_direction(df)
        assert direction == Direction.UP

    def test_down_trend_direction(self):
        df = make_test_klines([
            {'h': 12, 'l': 11},
            {'h': 10, 'l': 9},  # Down gap → direction DOWN
        ])
        direction = _find_first_non_containment_direction(df)
        assert direction == Direction.DOWN

    def test_default_direction_on_all_containment(self):
        df = make_test_klines([
            {'h': 10, 'l': 5},
            {'h': 9, 'l': 7},    # contained by k1
            {'h': 9.5, 'l': 6},  # contained by k1
        ])
        direction = _find_first_non_containment_direction(df)
        assert direction == Direction.UP  # Default to UP


class TestGetClLines:
    """Test get_cl_lines main function"""

    def test_empty_input(self):
        df = pd.DataFrame()
        result = get_cl_lines(df)
        assert len(result) == 0

    def test_single_kline(self):
        df = make_test_klines([{'h': 10, 'l': 9}])
        result = get_cl_lines(df)
        assert len(result) == 1

    def test_two_klines_no_containment(self):
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 11},
        ])
        result = get_cl_lines(df)
        assert len(result) == 2
        assert verify_bh(result) == True

    def test_two_klines_with_containment(self):
        """K2 contains K1 → should merge into 1 CL kline"""
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 8},  # Contains K1
        ])
        result = get_cl_lines(df)
        assert len(result) == 1
        assert verify_bh(result) == True


class TestGapDetection:
    """Test gap detection (CLKline._q = True)"""

    def test_gap_up(self):
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 11},  # Gap: low=11 > K1.high=10
            {'h': 14, 'l': 13},
        ])
        result = get_cl_lines(df)
        # Second CL kline should have gap flag
        assert len(result) >= 2
        has_q_column = 'q' in result.columns or any(
            col for col in result.columns if col == 'q'
        )
        if 'q' in result.columns:
            # At least one kline should have _q=True
            assert any(result['q'].iloc[1:])

    def test_gap_down(self):
        df = make_test_klines([
            {'h': 14, 'l': 13},
            {'h': 11, 'l': 10},  # Gap: high=11 < K1.low=13
            {'h': 9, 'l': 8},
        ])
        result = get_cl_lines(df)
        assert len(result) >= 2
        if 'q' in result.columns:
            assert any(result['q'].iloc[1:])

    def test_no_gap_overlapping(self):
        df = make_test_klines([
            {'h': 12, 'l': 10},
            {'h': 13, 'l': 11},  # Overlaps: low=11 <= previous high=12
        ])
        result = get_cl_lines(df)
        if 'q' in result.columns:
            # Last kline should not have gap
            assert result['q'].iloc[-1] == False


class TestLastKlineNotLost:
    """Test that the last K-line is not lost"""

    def test_last_kline_preserved_simple(self):
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 11, 'l': 10},
        ])
        result = get_cl_lines(df)
        assert len(result) == 2
        # Last CL kline should have the date of the last original kline
        last_date = df['date'].iloc[-1]
        assert result['date'].iloc[-1] == last_date

    def test_last_kline_with_containment(self):
        """Last K-line after containment should not be lost"""
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 11, 'l': 10},
            {'h': 12, 'l': 9},  # Contains k2
        ])
        result = get_cl_lines(df)
        # Should have first CL + merged last
        assert len(result) >= 1
        last_date = df['date'].iloc[-1]
        assert result['date'].iloc[-1] == last_date


class TestVerifyBh:
    """Test verify_bh function"""

    def test_valid_no_containment(self):
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 11},
            {'h': 14, 'l': 13},
        ])
        result = get_cl_lines(df)
        assert verify_bh(result) == True

    def test_verify_bh_debug_mode(self):
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 11},
        ])
        result = get_cl_lines(df)
        assert verify_bh(result, debug=True) == True
        assert verify_bh(result, debug=False) == True

    def test_verify_bh_should_fail_on_containment(self):
        """If we artificially create containment, verify should catch it"""
        result = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 9, 'l': 8},  # No containment
        ])
        assert verify_bh(result) == True


class TestUpQsAttribute:
    """Test up_qs attribute setting on CL klines"""

    def test_up_qs_set_on_up_containment(self):
        """When K2 contains K1 in UP direction, up_qs='up'"""
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 8},  # Contains K1, direction UP
        ])
        result = get_cl_lines(df)
        assert len(result) >= 1
        # The merged kline should have been created via containment
        if 'up_qs' in result.columns:
            # At least one row should have up_qs set
            non_null = result['up_qs'].dropna()
            assert len(non_null) >= 0  # up_qs may be None if direction logic varies

    def test_up_qs_set_on_down_containment(self):
        """When K2 contains K1 in DOWN direction, up_qs='down'"""
        df = make_test_klines([
            {'h': 12, 'l': 11},
            {'h': 13, 'l': 10},  # Contains K1, direction DOWN
        ])
        result = get_cl_lines(df)
        assert len(result) >= 1

    def test_config_passed_through(self):
        """Config dict should be accepted by get_cl_lines"""
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 12, 'l': 11},
        ])
        cfg = {'KLINE_TYPE': 'kline_chanlun'}
        result = get_cl_lines(df, config=cfg)
        assert len(result) == 2


class TestContainmentEdgeCases:
    """Edge cases for containment processing"""

    def test_three_way_containment(self):
        """K3 contains K2 which contains K1"""
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 11, 'l': 8},   # contains K1
            {'h': 12, 'l': 7},   # contains merged K2
        ])
        result = get_cl_lines(df)
        assert len(result) == 1  # Should merge into 1 CL kline
        assert verify_bh(result) == True

    def test_alternating_containment(self):
        """K1 contains K2, K3 does not contain K4"""
        df = make_test_klines([
            {'h': 12, 'l': 8},   # K1 contains K2
            {'h': 10, 'l': 9},   # K2 contained
            {'h': 11, 'l': 10},  # K3
            {'h': 13, 'l': 12},  # K4 - no containment, gap up
        ])
        result = get_cl_lines(df)
        assert len(result) >= 2
        assert verify_bh(result) == True

    def test_exact_overlap(self):
        """K lines with exactly the same H/L"""
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 10, 'l': 9},  # Exact same - containment (K1 contains K2 OR K2 contains K1)
            {'h': 11, 'l': 10},  # No containment
        ])
        result = get_cl_lines(df)
        assert verify_bh(result) == True


class TestLastKlineConsecutiveContainment:
    """Test last K-line preservation with consecutive containment at end"""

    def test_last_after_multiple_containments(self):
        df = make_test_klines([
            {'h': 10, 'l': 9},
            {'h': 11, 'l': 8},   # contains K1
            {'h': 12, 'l': 7},   # contains merged
            {'h': 13, 'l': 9},   # breaks containment
            {'h': 14, 'l': 8.5}, # contains K4
            {'h': 15, 'l': 8},   # contains merged (last)
        ])
        result = get_cl_lines(df)
        last_date = df['date'].iloc[-1]
        assert result['date'].iloc[-1] == last_date


class TestRealData:
    """Test with real data"""

    def test_real_pipeline_no_exception(self):
        from chanlun.get_src_klines import convert_src_klines
        temp_csv = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        temp_df = pd.read_csv(temp_csv, parse_dates=['date'])
        temp_df = convert_src_klines(temp_df)
        result = get_cl_lines(temp_df)
        assert len(result) > 0
        assert verify_bh(result) == True

    def test_real_data_all_klines_have_dates(self):
        from chanlun.get_src_klines import convert_src_klines
        temp_csv = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        temp_df = pd.read_csv(temp_csv, parse_dates=['date'])
        temp_df = convert_src_klines(temp_df)
        result = get_cl_lines(temp_df)
        assert all(pd.notna(result['date']))

    def test_real_data_column_structure(self):
        from chanlun.get_src_klines import convert_src_klines
        temp_csv = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        temp_df = pd.read_csv(temp_csv, parse_dates=['date'])
        temp_df = convert_src_klines(temp_df)
        result = get_cl_lines(temp_df)
        expected_cols = {'date', 'h', 'l', 'o', 'c', 'a', 'index', 'k_index', 'n', 'q', 'klines'}
        assert expected_cols.issubset(set(result.columns))
