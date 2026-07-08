"""
BI 级别多空隧道状态机单元测试

覆盖四类信号检测:
    1类 - 转多/转空（1破3）
    2类 - 强多/强空
    3类 - 多强/空强
    4类 - 反多/反空

测试 Bi_DuoKong_Process 状态机和 compute_duokong_bi 函数。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
import datetime
import pandas as pd
from chanlun.cl_interface import FX, BI, FxStatus, BiType, CLKline
from chanlun.get_duokong_bi import (
    Bi_DuoKong_Process,
    Bi_DuoKong_Process_Status,
    Bi_DuoKong,
    DuoKong_Status,
    get_bi_kline,
)


def _mk_kline(idx: int, date_str: str, h: float, l: float,
              o: float = None, c: float = None) -> CLKline:
    """Create a minimal CLKline for testing."""
    if o is None:
        o = l
    if c is None:
        c = h
    return CLKline(
        k_index=idx,
        date=datetime.datetime.strptime(date_str, "%Y-%m-%d"),
        h=h, l=l, o=o, c=c, a=10000,
    )


def _mk_fx(k: CLKline, _type: FxStatus, val: float, index: int = 0) -> FX:
    """Create a minimal FX for testing."""
    return FX(_type=_type, k=k, klines=[k, k, k], val=val, index=index)


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


def _mk_bi_klines(bis):
    """
    Create a pandas DataFrame of klines covering all BI date ranges.
    Each BI gets a kline at its start date and end date.
    """
    rows = []
    idx = 0
    for bi in bis:
        rows.append({
            'date': bi.start_datetime,
            'h': bi.high, 'l': bi.low,
            'o': bi.low, 'c': bi.high, 'a': 10000,
        })
        rows.append({
            'date': bi.end_datetime,
            'h': bi.high, 'l': bi.low,
            'o': bi.low, 'c': bi.high, 'a': 10000,
        })
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
    return df


# ============================================================
# State Machine Unit Tests
# ============================================================

class TestStateMachineStates:
    """状态机状态转移测试"""

    def test_initial_state_is_start(self):
        """初始状态为 START"""
        proc = Bi_DuoKong_Process()
        assert proc.status == Bi_DuoKong_Process_Status.START

    def test_start_to_left(self):
        """START → LEFT"""
        proc = Bi_DuoKong_Process()
        bi = _mk_bi(10, 6, BiType.UP, 0)
        result = proc.find_duokong_status(bi)
        assert result is None
        assert proc.status == Bi_DuoKong_Process_Status.LEFT
        assert proc.start == bi

    def test_left_to_left_after(self):
        """LEFT → LEFT_AFTER (反向笔不创新高/低)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)
        proc.find_duokong_status(bi0)
        result = proc.find_duokong_status(bi1)
        assert result is None
        assert proc.status == Bi_DuoKong_Process_Status.LEFT_AFTER
        assert proc.left == bi1

    def test_left_updates_on_extension(self):
        """LEFT: 同向笔创新高/低时更新 start"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)
        bi1 = _mk_bi(12, 7, BiType.UP, 1)  # 新高
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        assert proc.status == Bi_DuoKong_Process_Status.LEFT
        assert proc.start == bi1

    def test_left_after_to_middle(self):
        """LEFT_AFTER → MIDDLE (突破 start.high)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)   # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)   # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)    # h=11 > start.h=10 → MIDDLE
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        result = proc.find_duokong_status(bi2)
        assert result is None
        assert proc.status == Bi_DuoKong_Process_Status.MIDDLE

    def test_left_after_to_left_after_normal(self):
        """LEFT_AFTER → LEFT_AFTER_NORMAL (不突破 start 也不突破 1.618)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)   # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)   # LEFT_AFTER
        bi2 = _mk_bi(9.5, 8, BiType.UP, 2)  # h=9.5 < start.h=10 → LEFT_AFTER_NORMAL
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        result = proc.find_duokong_status(bi2)
        assert result is None
        assert proc.status == Bi_DuoKong_Process_Status.LEFT_AFTER_NORMAL

    def test_middle_to_turn_v(self):
        """MIDDLE → TURN_V (突破 start，信号 type1)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)   # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)   # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)    # MIDDLE
        bi3 = _mk_bi(8, 5, BiType.DOWN, 3)   # l=5 < start.l=6 → TURN_V
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        result = proc.find_duokong_status(bi3)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 1
        assert proc.status == Bi_DuoKong_Process_Status.TURN_V

    def test_middle_to_three_no_po_one(self):
        """MIDDLE → THREE_NO_PO_ONE (不突破 start)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)   # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)   # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)    # MIDDLE
        bi3 = _mk_bi(9, 7.5, BiType.DOWN, 3) # l=7.5 > start.l=6 → THREE_NO_PO_ONE
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        result = proc.find_duokong_status(bi3)
        assert result is None
        assert proc.status == Bi_DuoKong_Process_Status.THREE_NO_PO_ONE

    def test_turn_v_to_left_on_break(self):
        """TURN_V → LEFT (突破 middle，信号 type4)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)   # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)   # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)    # MIDDLE
        bi3 = _mk_bi(8, 5, BiType.DOWN, 3)   # TURN_V (type1 KONG)
        bi4 = _mk_bi(7, 4, BiType.DOWN, 4)   # l=4 < middle.l=8 → LEFT, type4 KONG
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        proc.find_duokong_status(bi3)
        result = proc.find_duokong_status(bi4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 4
        assert proc.status == Bi_DuoKong_Process_Status.LEFT

    def test_turn_v_to_left_after_on_no_break(self):
        """TURN_V → LEFT (UP方向，h < middle.h → 但代码进入else: start=middle, left=bi, status=LEFT_AFTER)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)   # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)   # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)    # MIDDLE
        bi3 = _mk_bi(8, 5, BiType.DOWN, 3)   # TURN_V (type1 KONG), middle=bi3(h=8)
        # After TURN_V: middle=bi3(h=8,l=5). bi4 UP h=7 < middle.h=8 → LEFT_AFTER
        bi4 = _mk_bi(7, 6, BiType.UP, 4)     # h=7 < middle.h=8 → LEFT_AFTER
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        proc.find_duokong_status(bi3)
        result = proc.find_duokong_status(bi4)
        assert result is None
        assert proc.status == Bi_DuoKong_Process_Status.LEFT_AFTER


# ============================================================
# Signal Type Tests
# ============================================================

class TestClass1ZhuanDuoKong:
    """1类信号：转多/转空"""

    def test_zhuan_duo(self):
        """转多：MIDDLE → TURN_V + DUO(type1)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.DOWN, 0)   # LEFT (DOWN)
        bi1 = _mk_bi(9, 7, BiType.UP, 1)       # LEFT_AFTER (UP, h=9 < start.h=10)
        bi2 = _mk_bi(8, 5, BiType.DOWN, 2)     # MIDDLE (DOWN, l=5 < start.l=6? No: start is DOWN so start.low=end.val=6)
        # Wait, let me re-think. For DOWN start: start.high=10, start.low=6
        # bi1 UP: h=9 < start.high=10 → LEFT_AFTER
        # bi2 DOWN: l=5 < start.low=6 → MIDDLE? No...
        # Actually in LEFT_AFTER state, bi2 DOWN: l=5 < start.low=6 → MIDDLE
        # Then bi3 UP: h > start.high=10 → TURN_V + DUO(type1)
        bi3 = _mk_bi(11, 7, BiType.UP, 3)     # h=11 > start.h=10 → TURN_V, DUO
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        result = proc.find_duokong_status(bi3)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 1
        assert result.compare_price == 10  # start.high

    def test_zhuan_kong(self):
        """转空：MIDDLE → TURN_V + KONG(type1)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)     # LEFT (UP)
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)     # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)      # MIDDLE (h=11 > start.h=10? No: in LEFT_AFTER, UP h=11 > start.h=10 → MIDDLE)
        bi3 = _mk_bi(8, 5, BiType.DOWN, 3)     # l=5 < start.l=6 → TURN_V, KONG
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        result = proc.find_duokong_status(bi3)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 1
        assert result.compare_price == 6  # start.low


class TestClass2QiangDuoKong:
    """2类信号：强多/强空"""

    def test_qiang_duo(self):
        """强多：LEFT_AFTER → LEFT + DUO(type2)，突破 1.618"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)     # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)     # LEFT_AFTER
        # position_1618 = bi2.low + (start.high - start.low) * 1.618 = 8 + 4*1.618 = 14.472
        bi2 = _mk_bi(15, 8, BiType.UP, 2)      # h=15 > 14.472 → 强多
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        result = proc.find_duokong_status(bi2)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 2
        assert proc.status == Bi_DuoKong_Process_Status.LEFT

    def test_qiang_kong(self):
        """强空：LEFT_AFTER → LEFT + KONG(type2)，跌破 1.618"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(12, 8, BiType.DOWN, 0)   # LEFT (DOWN)
        bi1 = _mk_bi(11, 9, BiType.UP, 1)      # LEFT_AFTER (UP, h=11 < start.h=12)
        # position_1618 = bi2.high - (start.high - start.low) * 1.618 = 10 - 4*1.618 = 3.528
        bi2 = _mk_bi(10, 3, BiType.DOWN, 2)    # l=3 < 3.528 → 强空
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        result = proc.find_duokong_status(bi2)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 2
        assert proc.status == Bi_DuoKong_Process_Status.LEFT

    def test_qiang_duo_not_triggered(self):
        """强多不触发：未突破 1.618"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)
        bi2 = _mk_bi(12, 8, BiType.UP, 2)      # h=12 < 12.472
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        result = proc.find_duokong_status(bi2)
        assert result is None
        assert proc.status == Bi_DuoKong_Process_Status.MIDDLE


class TestClass3DuoQiangKongQiang:
    """3类信号：多强/空强"""

    def test_duoqiang(self):
        """多强：THREE_NO_PO_ONE → DUO(type3)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)       # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)       # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)        # MIDDLE
        bi3 = _mk_bi(9, 7, BiType.DOWN, 3)       # THREE_NO_PO_ONE (l=7 > start.l=6)
        # THREE_NO_PO_ONE: left.low=7, middle.low=8 → 7 < 8 → rotate to MIDDLE
        bi4 = _mk_bi(12, 9, BiType.UP, 4)        # h=12 > middle.h=11 → DUO(type3)
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        proc.find_duokong_status(bi3)
        result = proc.find_duokong_status(bi4)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 3

    def test_kongqiang(self):
        """空强：THREE_NO_PO_ONE → KONG(type3)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(12, 8, BiType.DOWN, 0)     # LEFT (DOWN)
        bi1 = _mk_bi(11, 9, BiType.UP, 1)        # LEFT_AFTER (UP, h=11 < start.h=12)
        bi2 = _mk_bi(10, 7, BiType.DOWN, 2)      # MIDDLE (l=7 < start.l=8? Yes)
        bi3 = _mk_bi(11, 8, BiType.UP, 3)        # THREE_NO_PO_ONE (h=11 < start.h=12)
        # THREE_NO_PO_ONE: left.high=11, middle.high=10 → 11 > 10 → rotate to MIDDLE
        bi4 = _mk_bi(9, 5, BiType.DOWN, 4)       # l=5 < middle.l=7 → KONG(type3)
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        proc.find_duokong_status(bi3)
        result = proc.find_duokong_status(bi4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 3


class TestClass4FanDuoKong:
    """4类信号：反多/反空"""

    def test_fan_duo(self):
        """反多：TURN_V (type1 KONG) → LEFT + DUO(type4)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)       # LEFT
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)       # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)        # MIDDLE
        bi3 = _mk_bi(8, 5, BiType.DOWN, 3)       # TURN_V (type1 KONG), middle=bi3(h=8)
        bi4 = _mk_bi(9, 6, BiType.UP, 4)         # h=9 > middle.h=8 → type4 DUO
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        proc.find_duokong_status(bi3)
        result = proc.find_duokong_status(bi4)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 4
        assert result.compare_price == 8   # middle.high (bi3.high)
        assert result.duokong_price == 6   # bi4.low

    def test_fan_kong(self):
        """反空：TURN_V (type1 DUO) → LEFT + KONG(type4)"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.UP, 0)       # LEFT (UP)
        bi1 = _mk_bi(9, 7, BiType.DOWN, 1)       # LEFT_AFTER
        bi2 = _mk_bi(11, 8, BiType.UP, 2)        # MIDDLE
        # bi3 UP: h=12 > start.h=10 → TURN_V, DUO(type1). middle=bi3(h=12)
        bi3 = _mk_bi(12, 7, BiType.UP, 3)        # TURN_V (type1 DUO), middle=bi3
        bi4 = _mk_bi(8, 3, BiType.DOWN, 4)       # l=3 < middle.l=7 → type4 KONG
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        proc.find_duokong_status(bi3)
        result = proc.find_duokong_status(bi4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 4
        assert result.compare_price == 7   # middle.low (bi3.low)
        assert result.duokong_price == 8   # bi4.high


# ============================================================
# Verify Types
# ============================================================

class TestVerifyBiTypes:
    """验证 VERIFY_UP/VERIFY_DOWN 类型"""

    def test_verify_up_treated_as_up(self):
        """VERIFY_UP 应被视为上升笔"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(10, 6, BiType.VERIFY_UP, 0)
        bi1 = _mk_bi(9, 7, BiType.VERIFY_DOWN, 1)
        bi2 = _mk_bi(11, 8, BiType.VERIFY_UP, 2)
        bi3 = _mk_bi(8, 5, BiType.VERIFY_DOWN, 3)
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        result = proc.find_duokong_status(bi3)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 1

    def test_verify_down_treated_as_down(self):
        """VERIFY_DOWN 应被视为下降笔"""
        proc = Bi_DuoKong_Process()
        bi0 = _mk_bi(12, 8, BiType.VERIFY_DOWN, 0)
        bi1 = _mk_bi(11, 9, BiType.VERIFY_UP, 1)
        bi2 = _mk_bi(10, 7, BiType.VERIFY_DOWN, 2)
        bi3 = _mk_bi(11, 8, BiType.VERIFY_UP, 3)
        bi4 = _mk_bi(9, 5, BiType.VERIFY_DOWN, 4)
        proc.find_duokong_status(bi0)
        proc.find_duokong_status(bi1)
        proc.find_duokong_status(bi2)
        proc.find_duokong_status(bi3)
        result = proc.find_duokong_status(bi4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 3


# ============================================================
# get_bi_kline Helper Tests
# ============================================================

class TestGetBiKline:
    """get_bi_kline 辅助函数测试"""

    def test_filters_by_date_range(self):
        """按 BI 日期范围过滤 K 线"""
        bi = _mk_bi(10, 6, BiType.UP, 0, "2024-01-01", "2024-01-03")
        klines = pd.DataFrame([
            {'date': datetime.datetime(2024, 1, 1), 'h': 10, 'l': 6, 'o': 6, 'c': 10, 'a': 100},
            {'date': datetime.datetime(2024, 1, 2), 'h': 9, 'l': 7, 'o': 7, 'c': 9, 'a': 100},
            {'date': datetime.datetime(2024, 1, 3), 'h': 10, 'l': 8, 'o': 8, 'c': 10, 'a': 100},
            {'date': datetime.datetime(2024, 1, 4), 'h': 11, 'l': 9, 'o': 9, 'c': 11, 'a': 100},
        ])
        result = get_bi_kline(klines, bi)
        assert len(result) == 3  # Jan 1, 2, 3

    def test_empty_result(self):
        """日期范围内无 K 线"""
        bi = _mk_bi(10, 6, BiType.UP, 0, "2099-01-01", "2099-01-02")
        klines = pd.DataFrame([
            {'date': datetime.datetime(2024, 1, 1), 'h': 10, 'l': 6, 'o': 6, 'c': 10, 'a': 100},
        ])
        result = get_bi_kline(klines, bi)
        assert len(result) == 0


# ============================================================
# Integration Tests (compute_dk_sequences)
# ============================================================

class TestComputeDkSequences:
    """_compute_dk_sequences 集成测试"""

    def test_empty_bis(self):
        """空笔列表返回空字典列表"""
        proc = Bi_DuoKong_Process()
        klines = pd.DataFrame([
            {'date': datetime.datetime(2024, 1, 1), 'h': 10, 'l': 6, 'o': 6, 'c': 10, 'a': 100},
        ])
        high, low = proc._compute_dk_sequences([], klines)
        assert len(high) == 0
        assert len(low) == 0

    def test_duo_signal_sets_low(self):
        """DUO 信号生成包含 dict 的列表"""
        proc = Bi_DuoKong_Process()
        bis = [
            _mk_bi(10, 6, BiType.UP, 0, "2024-01-01", "2024-01-02"),
            _mk_bi(9, 7, BiType.DOWN, 1, "2024-01-03", "2024-01-04"),
            _mk_bi(11, 8, BiType.UP, 2, "2024-01-05", "2024-01-06"),
            _mk_bi(8, 5, BiType.DOWN, 3, "2024-01-07", "2024-01-08"),
            _mk_bi(12, 7, BiType.UP, 4, "2024-01-09", "2024-01-10"),
        ]
        klines = _mk_bi_klines(bis)
        high, low = proc._compute_dk_sequences(bis, klines)
        assert isinstance(high, list)
        assert isinstance(low, list)
        # Each entry should be a dict with 'index' and 'price' keys
        for item in high:
            assert isinstance(item, dict)
            assert 'index' in item
            assert 'price' in item
        for item in low:
            assert isinstance(item, dict)
            assert 'index' in item
            assert 'price' in item

    def test_sequence_returns_dict_lists(self):
        """返回值为字典列表，每个字典包含 date/index/price"""
        proc = Bi_DuoKong_Process()
        bis = [
            _mk_bi(10, 6, BiType.UP, 0, "2024-01-01", "2024-01-02"),
            _mk_bi(9, 7, BiType.DOWN, 1, "2024-01-03", "2024-01-04"),
        ]
        klines = _mk_bi_klines(bis)
        high, low = proc._compute_dk_sequences(bis, klines)
        assert isinstance(high, list)
        assert isinstance(low, list)
