"""
Tests for XD (segment) determination (get_xd.py)

Phase 2 fixes covered:
- Remove 8 dead XDProcessType enum values
- Remove caculate_radio dead function
- Fix set_xd_from_bi type inference (or -> and)
- Fix generate_bi incomplete BI construction
- Fix gap threshold (0.01 -> percentage-based)
- Remove print(bi) from handle()
- Add minimum bi count check (>=3)
- Config propagation

Current test: test_enums_removed + additional module-level imports
Future test: test_XD_Process_calculate_connect_nodes,
test_XD_Process_handle (pending full pipeline test data)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import pandas as pd
import pytest
from chanlun.cl_interface import (
    BI, FX, FxStatus, BiType, XianDuanType, CLKline,
)
from chanlun.get_xd import XD_Process, XDProcessType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_fx(_type: FxStatus, date_str: str, val: float, k_index: int, done: bool = True) -> FX:
    """Helper to create test FX objects"""
    k = CLKline(k_index, pd.Timestamp(date_str), val + 0.1, val - 0.1, val, val, 10000)
    return FX(_type, k, [k], val, k_index, done)


def make_bi(start_fx: FX, end_fx: FX, bi_type: BiType) -> BI:
    """Helper to create a BI object with proper type/high/low set"""
    return BI(start_fx, end_fx, bi_type, 0)


# ---------------------------------------------------------------------------
# Test: Dead enum values removed
# ---------------------------------------------------------------------------

class TestEnumValuesRemoved:
    """Verify 8 dead XDProcessType enum values are removed"""

    def test_no_dead_states(self):
        """Check that dead states are not in the enum"""
        dead_names = [
            'START_LEFTAFTER_NORMAL',
            'LONGXIANDUAN',
            'LONGXIANDUAN_HIGH',
            'LONGXIANDUAN_NORMAL',
            'LONGXIANDUAN_NORMAL_NORMAL',
            'QUEKOU_MIDDLE_AFTER_NORMAL',
            'QUEKOU_MIDDLE_AFTER_NORMAL_NORMAL',
            'QUEKOU_RIGHT_NORMAL_NORMAL',
        ]
        for name in dead_names:
            assert not hasattr(XDProcessType, name), f'Dead enum {name} should be removed'

    def test_enum_count(self):
        """Expected: 14 live states (22 original - 8 dead)"""
        names = [e.name for e in XDProcessType]
        assert len(names) == 14, f'Expected 14 live states, got {len(names)}: {names}'

    def test_live_states_exist(self):
        """Verify all live states are present"""
        live_names = {
            'START', 'LEFT', 'LEFT_AFTER', 'LEFT_AFTER_NORMAL',
            'LEFT_AFTER_NORMAL_NORMAL', 'MIDDLE', 'QUEKOU_MIDDLE',
            'QUEKOU_MIDDLE_AFTER', 'QUEKOU_RIGHT', 'QUEKOU_RIGHT_NORMAL',
            'MIDDLE_AFTER', 'RIGHT', 'RIGHT_NORMAL', 'RIGHT_NORMAL_NORMAL',
        }
        actual = {e.name for e in XDProcessType}
        assert live_names == actual


# ---------------------------------------------------------------------------
# Test: caculate_radio removed
# ---------------------------------------------------------------------------

class TestDeadFunctionsRemoved:
    """Verify dead functions are removed"""

    def test_caculate_radio_removed(self):
        """caculate_radio should no longer exist"""
        xd = XD_Process()
        assert not hasattr(xd, 'caculate_radio')


# ---------------------------------------------------------------------------
# Test: Config propagation
# ---------------------------------------------------------------------------

class TestConfigPropagation:
    """Test config is accepted and stored"""

    def test_default_config(self):
        xd = XD_Process()
        assert xd.config == {}

    def test_custom_config(self):
        cfg = {'XD_QJ_TYPE': 'xd_qj_dd'}
        xd = XD_Process(config=cfg)
        assert xd.config == cfg

    def test_config_not_shared(self):
        """config should not be shared between instances"""
        cfg1 = {'key': 'value1'}
        cfg2 = {'key': 'value2'}
        xd1 = XD_Process(config=cfg1)
        xd2 = XD_Process(config=cfg2)
        assert xd1.config != xd2.config


# ---------------------------------------------------------------------------
# Test: generate_bi — incomplete BI construction fix
# ---------------------------------------------------------------------------

class TestGenerateBi:
    """Test generate_bi correctly handles edge cases"""

    def test_generate_bi_same_direction_up_up(self):
        """UP + UP: both bottoms-to-tops, result should be UP"""
        fx_bot = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        fx_top = make_fx(FxStatus.TOP, '2019-01-05', 20.0, 4)
        fx_bot2 = make_fx(FxStatus.BOTTOM, '2019-01-08', 15.0, 7)
        fx_top2 = make_fx(FxStatus.TOP, '2019-01-12', 25.0, 11)
        bi1 = make_bi(fx_bot, fx_top, BiType.UP)
        bi2 = make_bi(fx_bot2, fx_top2, BiType.UP)
        xd = XD_Process()
        result = xd.generate_bi(bi1, bi2)
        assert result.start == fx_bot
        assert result.end == fx_top2
        assert result.type is not None
        assert result.high > 0
        assert result.low > 0

    def test_generate_bi_same_direction_down_down(self):
        """DOWN + DOWN: both tops-to-bottoms, result should be DOWN"""
        fx_top = make_fx(FxStatus.TOP, '2019-01-01', 25.0, 0)
        fx_bot = make_fx(FxStatus.BOTTOM, '2019-01-05', 15.0, 4)
        fx_top2 = make_fx(FxStatus.TOP, '2019-01-08', 20.0, 7)
        fx_bot2 = make_fx(FxStatus.BOTTOM, '2019-01-12', 10.0, 11)
        bi1 = make_bi(fx_top, fx_bot, BiType.DOWN)
        bi2 = make_bi(fx_top2, fx_bot2, BiType.DOWN)
        xd = XD_Process()
        result = xd.generate_bi(bi1, bi2)
        assert result.start == fx_top
        assert result.end == fx_bot2
        assert result.type is not None
        assert result.high > 0
        assert result.low > 0

    def test_generate_bi_both_bottom_fx(self):
        """When both start and end are BOTTOM FX (same type),
        type should be inferred from values, not left as None"""
        fx_bot1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10.0, 0)
        fx_bot2 = make_fx(FxStatus.BOTTOM, '2019-01-10', 12.0, 9)
        # Create BI where start=BOTTOM, end=TOP (UP)
        bi1 = make_bi(fx_bot1,
                      make_fx(FxStatus.TOP, '2019-01-05', 18.0, 4),
                      BiType.UP)
        # Create BI where start=TOP, end=BOTTOM (DOWN)
        bi2 = make_bi(make_fx(FxStatus.TOP, '2019-01-08', 18.0, 7),
                      fx_bot2,
                      BiType.DOWN)
        xd = XD_Process()
        result = xd.generate_bi(bi1, bi2)
        # start.fx is BOTTOM(10), end.fx is BOTTOM(12)
        # type should NOT be None — this was the bug
        assert result.type is not None, 'BI.type should not be None for same-type FX'
        assert result.high > 0, 'BI.high should be set'
        assert result.low > 0, 'BI.low should be set'
        # Since end.val (12) > start.val (10), should be UP
        assert result.type == BiType.UP

    def test_generate_bi_both_top_fx(self):
        """When both start and end are TOP FX, type should be inferred"""
        fx_top1 = make_fx(FxStatus.TOP, '2019-01-01', 25.0, 0)
        fx_top2 = make_fx(FxStatus.TOP, '2019-01-10', 20.0, 9)
        # BI: start=TOP, end=BOTTOM (DOWN)
        bi1 = make_bi(fx_top1,
                      make_fx(FxStatus.BOTTOM, '2019-01-05', 18.0, 4),
                      BiType.DOWN)
        # BI: start=BOTTOM, end=TOP (UP)
        bi2 = make_bi(make_fx(FxStatus.BOTTOM, '2019-01-08', 18.0, 7),
                      fx_top2,
                      BiType.UP)
        xd = XD_Process()
        result = xd.generate_bi(bi1, bi2)
        assert result.type is not None, 'BI.type should not be None for same-type FX'
        assert result.high > 0
        assert result.low > 0
        # end.val (20) < start.val (25), should be DOWN
        assert result.type == BiType.DOWN


# ---------------------------------------------------------------------------
# Test: set_xd_from_bi — type inference fix
# ---------------------------------------------------------------------------

class TestSetXdFromBi:
    """Test set_xd_from_bi type inference with all combinations"""

    def _make_up_bi_components(self, bot_val=10.0, top_val=20.0):
        """Create start/end FX for an UP BI"""
        bot = make_fx(FxStatus.BOTTOM, '2019-01-01', bot_val, 0)
        top = make_fx(FxStatus.TOP, '2019-01-05', top_val, 4)
        return bot, top

    def _make_down_bi_components(self, top_val=20.0, bot_val=10.0):
        """Create start/end FX for a DOWN BI"""
        top = make_fx(FxStatus.TOP, '2019-01-01', top_val, 0)
        bot = make_fx(FxStatus.BOTTOM, '2019-01-05', bot_val, 4)
        return top, bot

    def test_both_up_confirmed(self):
        """BiType.UP + BiType.UP -> XianDuanType.UP"""
        bot1, top1 = self._make_up_bi_components(10, 20)
        bot2, top2 = self._make_up_bi_components(15, 25)
        bi1 = make_bi(bot1, top1, BiType.UP)
        bi2 = make_bi(bot2, top2, BiType.UP)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.type == XianDuanType.UP

    def test_both_down_confirmed(self):
        """BiType.DOWN + BiType.DOWN -> XianDuanType.DOWN"""
        top1, bot1 = self._make_down_bi_components(25, 15)
        top2, bot2 = self._make_down_bi_components(20, 10)
        bi1 = make_bi(top1, bot1, BiType.DOWN)
        bi2 = make_bi(top2, bot2, BiType.DOWN)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.type == XianDuanType.DOWN

    def test_up_then_down(self):
        """UP + DOWN -> VERIFY_UP (started up, ended down = verify top)"""
        bot1, top1 = self._make_up_bi_components(10, 20)
        top2, bot2 = self._make_down_bi_components(20, 12)
        bi1 = make_bi(bot1, top1, BiType.UP)
        bi2 = make_bi(top2, bot2, BiType.DOWN)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.type == XianDuanType.VERIFY_UP

    def test_down_then_up(self):
        """DOWN + UP -> VERIFY_DOWN (started down, ended up = verify bottom)"""
        top1, bot1 = self._make_down_bi_components(25, 15)
        bot2, top2 = self._make_up_bi_components(15, 22)
        bi1 = make_bi(top1, bot1, BiType.DOWN)
        bi2 = make_bi(bot2, top2, BiType.UP)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.type == XianDuanType.VERIFY_DOWN

    def test_verify_up_and_up(self):
        """VERIFY_UP + UP -> VERIFY_UP (one tentative)"""
        fx_bot1 = make_fx(FxStatus.VERIFY_BOTTOM, '2019-01-01', 10, 0)
        fx_top1 = make_fx(FxStatus.VERIFY_TOP, '2019-01-05', 20, 4)
        bi1 = make_bi(fx_bot1, fx_top1, BiType.VERIFY_UP)
        bot2, top2 = self._make_up_bi_components(15, 25)
        bi2 = make_bi(bot2, top2, BiType.UP)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.type == XianDuanType.VERIFY_UP

    def test_up_and_verify_up(self):
        """UP + VERIFY_UP -> VERIFY_UP (one tentative)"""
        bot1, top1 = self._make_up_bi_components(10, 20)
        bi1 = make_bi(bot1, top1, BiType.UP)
        fx_bot2 = make_fx(FxStatus.VERIFY_BOTTOM, '2019-01-08', 15, 7)
        fx_top2 = make_fx(FxStatus.VERIFY_TOP, '2019-01-12', 25, 11)
        bi2 = make_bi(fx_bot2, fx_top2, BiType.VERIFY_UP)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.type == XianDuanType.VERIFY_UP

    def test_verify_down_and_down(self):
        """VERIFY_DOWN + DOWN -> VERIFY_DOWN"""
        fx_top1 = make_fx(FxStatus.VERIFY_TOP, '2019-01-01', 25, 0)
        fx_bot1 = make_fx(FxStatus.VERIFY_BOTTOM, '2019-01-05', 15, 4)
        bi1 = make_bi(fx_top1, fx_bot1, BiType.VERIFY_DOWN)
        top2, bot2 = self._make_down_bi_components(20, 10)
        bi2 = make_bi(top2, bot2, BiType.DOWN)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.type == XianDuanType.VERIFY_DOWN

    def test_xd_high_low_correct(self):
        """XD high/low should reflect start and end values"""
        bot1, top1 = self._make_up_bi_components(10, 20)
        bot2, top2 = self._make_up_bi_components(15, 25)
        bi1 = make_bi(bot1, top1, BiType.UP)
        bi2 = make_bi(bot2, top2, BiType.UP)
        xd = XD_Process()
        result = xd.set_xd_from_bi(bi1, bi2)
        assert result.high == top2.val  # end is top, UP: high = end.val
        assert result.low == bot1.val  # start is bottom, UP: low = start.val


# ---------------------------------------------------------------------------
# Test: Gap threshold
# ---------------------------------------------------------------------------

class TestGapThreshold:
    """Test percentage-based gap threshold"""

    def test_gap_threshold_is_percentage(self):
        """Verify _get_gap_threshold returns 0.1% of price"""
        xd = XD_Process()
        assert xd._get_gap_threshold(100.0) == 0.1
        assert xd._get_gap_threshold(10.0) == 0.01
        assert xd._get_gap_threshold(1.0) == 0.001
        assert xd._get_gap_threshold(0.01) == 0.00001
        assert xd._get_gap_threshold(0.0) == 0.0

    def test_gap_threshold_no_hardcoded_001(self):
        """Verify 0.01 is no longer hardcoded in gap comparisons"""
        import inspect
        source = inspect.getsource(XD_Process.find_xd)
        assert '0.01' not in source, 'Hardcoded 0.01 should be replaced by percentage'

    def test_gap_threshold_method_accessible(self):
        """_get_gap_threshold should exist"""
        xd = XD_Process()
        assert hasattr(xd, '_get_gap_threshold')
        assert callable(xd._get_gap_threshold)


# ---------------------------------------------------------------------------
# Test: Minimum BI count check
# ---------------------------------------------------------------------------

class TestMinimumBiCount:
    """Test handle() rejects insufficient BIs"""

    def test_handle_empty(self):
        xd = XD_Process()
        result = xd.handle([])
        assert result == []

    def test_handle_one_bi(self):
        bot, top = make_fx(FxStatus.BOTTOM, '2019-01-01', 10, 0), \
                   make_fx(FxStatus.TOP, '2019-01-05', 20, 4)
        bi = make_bi(bot, top, BiType.UP)
        xd = XD_Process()
        result = xd.handle([bi])
        assert result == []

    def test_handle_two_bis(self):
        bot1, top1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10, 0), \
                     make_fx(FxStatus.TOP, '2019-01-05', 20, 4)
        top2, bot2 = make_fx(FxStatus.TOP, '2019-01-08', 20, 7), \
                     make_fx(FxStatus.BOTTOM, '2019-01-12', 12, 11)
        bi1 = make_bi(bot1, top1, BiType.UP)
        bi2 = make_bi(top2, bot2, BiType.DOWN)
        xd = XD_Process()
        result = xd.handle([bi1, bi2])
        assert result == []

    def test_handle_three_bis_does_not_crash(self):
        """With 3 BIs, handle() should process without errors"""
        fx_bot1 = make_fx(FxStatus.BOTTOM, '2019-01-01', 10, 0)
        fx_top1 = make_fx(FxStatus.TOP, '2019-01-05', 20, 4)
        fx_bot2 = make_fx(FxStatus.BOTTOM, '2019-01-08', 15, 7)
        fx_top2 = make_fx(FxStatus.TOP, '2019-01-12', 25, 11)
        fx_bot3 = make_fx(FxStatus.BOTTOM, '2019-01-15', 20, 14)
        fx_top3 = make_fx(FxStatus.TOP, '2019-01-20', 30, 19)
        bi1 = make_bi(fx_bot1, fx_top1, BiType.UP)
        bi2 = make_bi(fx_bot2, fx_top2, BiType.UP)
        bi3 = make_bi(fx_bot3, fx_top3, BiType.UP)
        xd = XD_Process()
        result = xd.handle([bi1, bi2, bi3])
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Test: No print in handle()
# ---------------------------------------------------------------------------

class TestNoPrintInHandle:
    """Verify print(bi) is removed from handle()"""

    def test_no_print_in_handle(self):
        """Inspect handle source for print statement"""
        import inspect
        source = inspect.getsource(XD_Process.handle)
        assert 'print(bi)' not in source, 'print(bi) should be removed from handle()'


# ---------------------------------------------------------------------------
# Test: End-to-end with real data
# ---------------------------------------------------------------------------

class TestXDRealData:
    """Test full FX->BI->XD pipeline"""

    def test_real_pipeline(self):
        from chanlun.get_src_klines import convert_src_klines
        from chanlun.get_cl_klines import get_cl_lines
        from chanlun.get_fx import FX_PROCESS
        from chanlun.get_bi import BI_Process
        csv_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        df = pd.read_csv(csv_path, parse_dates=['date'])
        df = convert_src_klines(df)
        cl_klines = get_cl_lines(df)
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(cl_klines)
        bi_proc = BI_Process()
        bi_list = bi_proc.handle(fx_list)
        xd_proc = XD_Process()
        xd_list = xd_proc.handle(bi_list)
        assert isinstance(xd_list, list)
        # XD list may be empty if BI count < 3, or may contain segments
        for xd in xd_list:
            assert xd.start is not None
            assert xd.end is not None
            assert xd.type is not None

    def test_pipeline_with_config(self):
        """Config should propagate to XD_Process"""
        from chanlun.get_src_klines import convert_src_klines
        from chanlun.get_cl_klines import get_cl_lines
        from chanlun.get_fx import FX_PROCESS
        from chanlun.get_bi import BI_Process
        cfg = {'XD_QJ_TYPE': 'xd_qj_dd'}
        csv_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        df = pd.read_csv(csv_path, parse_dates=['date'])
        df = convert_src_klines(df)
        cl_klines = get_cl_lines(df)
        fx_proc = FX_PROCESS()
        fx_list = fx_proc.find_fenxing(cl_klines)
        bi_proc = BI_Process()
        bi_list = bi_proc.handle(fx_list)
        xd_proc = XD_Process(config=cfg)
        assert xd_proc.config == cfg
        xd_list = xd_proc.handle(bi_list)
        assert isinstance(xd_list, list)


# ---------------------------------------------------------------------------
# Test: get_last_xd
# ---------------------------------------------------------------------------

class TestGetLastXd:
    """Test get_last_xd()"""

    def test_get_last_xd_empty(self):
        xd = XD_Process()
        assert xd.get_last_xd() is None

    def test_get_last_xd_not_crashing(self):
        """get_last_xd should not crash after processing"""
        from chanlun.get_src_klines import convert_src_klines
        from chanlun.get_cl_klines import get_cl_lines
        from chanlun.get_fx import FX_PROCESS
        from chanlun.get_bi import BI_Process
        csv_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'sample_klines.csv')
        df = pd.read_csv(csv_path, parse_dates=['date'])
        df = convert_src_klines(df)
        cl_klines = get_cl_lines(df)
        fx_list = FX_PROCESS().find_fenxing(cl_klines)
        bi_list = BI_Process().handle(fx_list)
        xd_proc = XD_Process()
        xd_proc.handle(bi_list)
        result = xd_proc.get_last_xd()
        assert result is None or hasattr(result, 'type')
