"""
Tests for BI formation (get_bi.py)

Phase 1.3 fixes covered:
- Fix _update_last_bi() stop_fx → end
- Initialize self.start_fx
- Old/new BI rules (min K-line count)
- Gap consideration
- Remove dead code
- Min K-line and amplitude check
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pandas as pd
import pytest
from chanlun.cl_interface import FX, FxStatus, BiType, CLKline, BI
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process


def make_fx(_type: FxStatus, date_str: str, val: float, k_index: int, done: bool = True) -> FX:
    """Helper to create test FX objects"""
    k = CLKline(k_index, pd.Timestamp(date_str), val + 0.1, val - 0.1, val, val, 10000)
    return FX(_type, k, [k], val, k_index, done)


def make_fx_list(pairs: list) -> list:
    """Create FX list from (type, date, val, k_index) tuples"""
    result = []
    for i, (fx_type, date, val, k_idx) in enumerate(pairs):
        result.append(make_fx(fx_type, date, val, k_idx))
    return result


class TestStartFxInit:
    """Test self.start_fx initialization"""

    def test_start_fx_is_none_initially(self):
        bi_proc = BI_Process()
        assert bi_proc.start_fx is None

    def test_handle_empty_list(self):
        bi_proc = BI_Process()
        result = bi_proc.handle([])
        assert result == []

    def test_handle_single_fx(self):
        bi_proc = BI_Process()
        fx = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        result = bi_proc.handle([fx])
        assert result == []  # Need at least 2 FX for a BI


class TestUpdateLastBi:
    """Test _update_last_bi uses .end not .stop_fx"""

    def test_update_last_bi_end_attribute(self):
        """Verify BI.end attribute is accessible"""
        fx1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        fx2 = make_fx(FxStatus.TOP, '2019-01-05', 15.0, 4)
        # BI.end should be the end FX
        from chanlun.cl_interface import BI
        bi = BI(fx1, fx2, BiType.UP, 0)
        assert bi.end == fx2
        assert hasattr(bi, 'end')
        # stop_fx should NOT exist (it was a bug)
        assert not hasattr(bi, 'stop_fx')


class TestMinKlineCount:
    """Test minimum K-line count between FX for BI"""

    def test_kline_count_zero(self):
        """Cover edge case: fx2.k_index == fx1.k_index"""
        bi_proc = BI_Process()
        bi_proc._check_min_kline_count(
            make_fx(FxStatus.BOTTOM, '2019-01-01', 10, 5),
            make_fx(FxStatus.TOP, '2019-01-01', 10, 5)
        )

    def test_kline_count_ok(self):
        bi_proc = BI_Process()
        result = bi_proc._check_min_kline_count(
            make_fx(FxStatus.BOTTOM, '2019-01-01', 10, 0),
            make_fx(FxStatus.TOP, '2019-01-10', 12, 10),
            min_count=5
        )
        assert result == True

    def test_kline_count_too_few(self):
        bi_proc = BI_Process()
        result = bi_proc._check_min_kline_count(
            make_fx(FxStatus.BOTTOM, '2019-01-01', 10, 0),
            make_fx(FxStatus.TOP, '2019-01-03', 12, 2),
            min_count=5
        )
        assert result == False


class TestAmplitudeCheck:
    """Test amplitude validation for BI"""

    def test_amplitude_ok(self):
        bi_proc = BI_Process()
        result = bi_proc._check_amplitude(
            make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0),
            make_fx(FxStatus.TOP, '2019-01-05', 12.0, 4),
            min_amp=0.001
        )
        assert result == True

    def test_amplitude_too_small(self):
        bi_proc = BI_Process()
        result = bi_proc._check_amplitude(
            make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0),
            make_fx(FxStatus.TOP, '2019-01-05', 10.00001, 4),
            min_amp=0.001
        )
        assert result == False

    def test_amplitude_zero_base(self):
        """Edge case: fx1.val == 0"""
        bi_proc = BI_Process()
        result = bi_proc._check_amplitude(
            make_fx(FxStatus.BOTTOM, '2019-01-01', 0.0, 0),
            make_fx(FxStatus.TOP, '2019-01-05', 1.0, 4)
        )
        assert result == False


class TestGapDetection:
    """Test gap consideration in BI formation"""

    def test_gap_between_fx(self):
        bi_proc = BI_Process()
        result = bi_proc._has_gap(
            make_fx(FxStatus.TOP, '2019-01-01', 15.0, 0),
            make_fx(FxStatus.BOTTOM, '2019-01-05', 10.0, 4)
        )
        assert isinstance(result, bool)


class TestFindBi:
    """Test find_bi with various FX patterns"""

    def test_up_bi(self):
        fx1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        fx2 = make_fx(FxStatus.TOP, '2019-01-10', 15.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is not None
        assert result.type == BiType.UP

    def test_down_bi(self):
        fx1 = make_fx(FxStatus.TOP, '2019-01-01', 15.0, 0)
        fx2 = make_fx(FxStatus.BOTTOM, '2019-01-10', 10.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is not None
        assert result.type == BiType.DOWN

    def test_same_direction_no_bi(self):
        """Two tops in a row shouldn't form a valid BI"""
        fx1 = make_fx(FxStatus.TOP, '2019-01-01', 15.0, 0)
        fx2 = make_fx(FxStatus.TOP, '2019-01-10', 18.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is None

    def test_verify_patterns(self):
        """Test VERIFY_TOP/VERIFY_BOTTOM FX types"""
        fx1 = make_fx(FxStatus.VERIFY_TOP, '2019-01-01', 15.0, 0)
        fx2 = make_fx(FxStatus.BOTTOM, '2019-01-10', 10.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is not None
        assert result.type == BiType.VERIFY_DOWN

    def test_verify_top_to_verify_bottom(self):
        """VERIFY_TOP → VERIFY_BOTTOM"""
        fx1 = make_fx(FxStatus.VERIFY_TOP, '2019-01-01', 15.0, 0)
        fx2 = make_fx(FxStatus.VERIFY_BOTTOM, '2019-01-10', 10.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is not None
        assert result.type == BiType.VERIFY_DOWN

    def test_verify_bottom_to_verify_top(self):
        """VERIFY_BOTTOM → VERIFY_TOP"""
        fx1 = make_fx(FxStatus.VERIFY_BOTTOM, '2019-01-01', 10.0, 0)
        fx2 = make_fx(FxStatus.VERIFY_TOP, '2019-01-10', 15.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is not None
        assert result.type == BiType.VERIFY_UP

    def test_verify_bottom_to_top(self):
        """VERIFY_BOTTOM → TOP"""
        fx1 = make_fx(FxStatus.VERIFY_BOTTOM, '2019-01-01', 10.0, 0)
        fx2 = make_fx(FxStatus.TOP, '2019-01-10', 15.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is not None
        assert result.type == BiType.VERIFY_UP

    def test_two_bottoms_no_bi(self):
        """Two bottoms in a row shouldn't form a valid BI"""
        fx1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        fx2 = make_fx(FxStatus.BOTTOM, '2019-01-10', 12.0, 9)
        bi_proc = BI_Process()
        bi_proc.start_fx = fx1
        result = bi_proc.find_bi(fx2)
        assert result is None


class TestIsValidBi:
    """Test _is_valid_bi validation"""

    def test_valid_bi(self):
        fx1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        fx2 = make_fx(FxStatus.TOP, '2019-01-10', 15.0, 9)
        bi_proc = BI_Process()
        assert bi_proc._is_valid_bi(fx1, fx2) == True

    def test_invalid_bi_too_close(self):
        fx1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        fx2 = make_fx(FxStatus.TOP, '2019-01-02', 15.0, 1)
        bi_proc = BI_Process()
        assert bi_proc._is_valid_bi(fx1, fx2) == False


class TestBIStrFormat:
    """Test BI.__str__() output format"""

    def test_down_bi_format(self):
        """下降笔 should format as: N. 下降笔：YYYYMMDD，high，YYYYMMDD，low"""
        fx1 = make_fx(FxStatus.TOP, '2026-01-02', 53.88, 0)
        fx2 = make_fx(FxStatus.BOTTOM, '2026-01-22', 35.6, 20)
        bi = BI(fx1, fx2, BiType.DOWN, 0)
        s = str(bi)
        assert s == "1. 下降笔：20260102，53.88，20260122，35.6"

    def test_up_bi_format(self):
        """上升笔 should format as: N. 上升笔：YYYYMMDD，low，YYYYMMDD，high"""
        fx1 = make_fx(FxStatus.BOTTOM, '2026-01-22', 35.6, 20)
        fx2 = make_fx(FxStatus.TOP, '2026-01-23', 42.5, 21)
        bi = BI(fx1, fx2, BiType.UP, 1)
        s = str(bi)
        assert s == "2. 上升笔：20260122，35.6，20260123，42.5"

    def test_verify_down_bi_format(self):
        """下降笔验证 should also format correctly with start=high, end=low"""
        fx1 = make_fx(FxStatus.VERIFY_TOP, '2026-02-01', 50.0, 5)
        fx2 = make_fx(FxStatus.VERIFY_BOTTOM, '2026-02-10', 30.0, 15)
        bi = BI(fx1, fx2, BiType.VERIFY_DOWN, 2)
        s = str(bi)
        assert s == "3. 下降笔验证：20260201，50.0，20260210，30.0"

    def test_verify_up_bi_format(self):
        """上升笔验证 should format with start=low, end=high"""
        fx1 = make_fx(FxStatus.VERIFY_BOTTOM, '2026-03-01', 30.0, 10)
        fx2 = make_fx(FxStatus.VERIFY_TOP, '2026-03-10', 50.0, 20)
        bi = BI(fx1, fx2, BiType.VERIFY_UP, 3)
        s = str(bi)
        assert s == "4. 上升笔验证：20260301，30.0，20260310，50.0"

    def test_index_starts_from_one(self):
        """Numbering should start from 1, not 0"""
        fx1 = make_fx(FxStatus.TOP, '2026-01-01', 20.0, 0)
        fx2 = make_fx(FxStatus.BOTTOM, '2026-01-10', 10.0, 10)
        bi = BI(fx1, fx2, BiType.DOWN, 0)
        s = str(bi)
        assert s.startswith("1. ")

    def test_index_increments(self):
        """Numbering should increment with bi.index"""
        fx1 = make_fx(FxStatus.TOP, '2026-01-01', 20.0, 0)
        fx2 = make_fx(FxStatus.BOTTOM, '2026-01-10', 10.0, 10)
        bi = BI(fx1, fx2, BiType.DOWN, 9)
        s = str(bi)
        assert s.startswith("10. ")

    def test_date_format_no_separators(self):
        """Date should be YYYYMMDD with no separators"""
        fx1 = make_fx(FxStatus.BOTTOM, '2026-12-25', 10.0, 0)
        fx2 = make_fx(FxStatus.TOP, '2027-01-08', 20.0, 10)
        bi = BI(fx1, fx2, BiType.UP, 0)
        s = str(bi)
        assert "20261225" in s
        assert "20270108" in s
        assert "-" not in s

    def test_sequence_format(self):
        """Test a sequence of BI objects produces correct numbered format"""
        # Simulate a real-like sequence
        fx_top = make_fx(FxStatus.TOP, '2026-01-02', 53.88, 0)
        fx_bot1 = make_fx(FxStatus.BOTTOM, '2026-01-22', 35.6, 20)
        fx_top2 = make_fx(FxStatus.TOP, '2026-01-23', 42.5, 21)
        fx_bot2 = make_fx(FxStatus.BOTTOM, '2026-02-01', 30.0, 30)

        bi1 = BI(fx_top, fx_bot1, BiType.DOWN, 0)
        bi2 = BI(fx_bot1, fx_top2, BiType.UP, 1)
        bi3 = BI(fx_top2, fx_bot2, BiType.DOWN, 2)

        expected = [
            "1. 下降笔：20260102，53.88，20260122，35.6",
            "2. 上升笔：20260122，35.6，20260123，42.5",
            "3. 下降笔：20260123，42.5，20260201，30.0",
        ]
        for bi, exp in zip([bi1, bi2, bi3], expected):
            assert str(bi) == exp


class TestRealData:
    """Test with real CSV data and the full FX→BI pipeline"""

    def test_real_pipeline(self):
        from chanlun.get_src_klines import convert_src_klines
        temp_csv = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        temp_df = pd.read_csv(temp_csv, parse_dates=['date'])
        temp_df = convert_src_klines(temp_df)
        cl_klines = get_cl_lines(temp_df)
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(cl_klines)
        bi_proc = BI_Process()
        bi_list = bi_proc.handle(fx_list)
        assert len(bi_list) > 0
        for bi in bi_list:
            assert bi.start is not None
            assert bi.end is not None
            assert bi.type is not None
            assert bi.index >= 0
