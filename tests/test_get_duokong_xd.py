"""
线段级别多空隧道状态机单元测试

覆盖四类信号检测:
    1类 - 转多/转空（1破3）
    2类 - 强多/强空
    3类 - 多强/空强
    4类 - 反多/反空

测试 XianDuan_DuoKong_Process 状态机和 _compute_dk_sequences 函数。
使用 SZ.600491 股票数据进行集成测试。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
import datetime
import pandas as pd
from chanlun.cl_interface import (
    FX, BI, XD, FxStatus, BiType, XianDuanType, CLKline,
)
from chanlun.get_duokong_xd import (
    XianDuan_DuoKong_Process,
    XianDuan_DuoKong_Process_Status,
    XianDuan_DuoKong,
    DuoKong_Status,
    get_xd_kline,
)


# ============================================================
# Helper Functions
# ============================================================

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


def _mk_xd(high: float, low: float, xd_type: XianDuanType, index: int = 0,
           start_date: str = "2024-01-01", end_date: str = "2024-01-10") -> XD:
    """Create an XD with given high/low/type."""
    sk = _mk_kline(index, start_date, high, high)
    ek = _mk_kline(index + 1, end_date, low, low)
    if xd_type in (XianDuanType.UP, XianDuanType.VERIFY_UP):
        sfx = _mk_fx(sk, FxStatus.BOTTOM, low, index * 2)
        efx = _mk_fx(ek, FxStatus.TOP, high, index * 2 + 1)
        bi_type = BiType.UP
    else:
        sfx = _mk_fx(sk, FxStatus.TOP, high, index * 2)
        efx = _mk_fx(ek, FxStatus.BOTTOM, low, index * 2 + 1)
        bi_type = BiType.DOWN
    # XD needs start_line (a BI)
    start_bi = _mk_bi(high, low, bi_type, index, start_date, end_date)
    xd = XD(start=sfx, end=efx, start_line=start_bi, _type=xd_type, index=index)
    xd.high = high
    xd.low = low
    return xd


def _mk_xd_klines(xds):
    """
    Create a pandas DataFrame of klines covering all XD date ranges.
    Each XD gets a kline at its start date and end date.
    """
    rows = []
    for xd in xds:
        rows.append({
            'date': xd.start_datetime,
            'h': xd.high, 'l': xd.low,
            'o': xd.low, 'c': xd.high, 'a': 10000,
        })
        rows.append({
            'date': xd.end_datetime,
            'h': xd.high, 'l': xd.low,
            'o': xd.low, 'c': xd.high, 'a': 10000,
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
        proc = XianDuan_DuoKong_Process()
        assert proc.status == XianDuan_DuoKong_Process_Status.START

    def test_start_to_left(self):
        """START → LEFT"""
        proc = XianDuan_DuoKong_Process()
        xd = _mk_xd(10, 6, XianDuanType.UP, 0)
        result = proc.find_duokong_status(xd)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT
        assert proc.start == xd

    def test_left_to_left_after(self):
        """LEFT → LEFT_AFTER (反向线段不创新高/低)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)
        proc.find_duokong_status(xd0)
        result = proc.find_duokong_status(xd1)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT_AFTER
        assert proc.left == xd1

    def test_left_updates_on_extension(self):
        """LEFT: 同向线段创新高/低时更新 start"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)
        xd1 = _mk_xd(12, 7, XianDuanType.UP, 1)  # 新高
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT
        assert proc.start == xd1

    def test_left_after_to_middle(self):
        """LEFT_AFTER → MIDDLE (突破 start.high)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)   # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)   # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)    # h=11 > start.h=10 → MIDDLE
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        result = proc.find_duokong_status(xd2)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.MIDDLE

    def test_left_after_to_left_after_normal(self):
        """LEFT_AFTER → LEFT_AFTER_NORMAL (不突破 start 也不突破 1.618)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)   # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)   # LEFT_AFTER
        xd2 = _mk_xd(9.5, 8, XianDuanType.UP, 2)  # h=9.5 < start.h=10 → LEFT_AFTER_NORMAL
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        result = proc.find_duokong_status(xd2)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT_AFTER_NORMAL

    def test_middle_to_turn_v(self):
        """MIDDLE → TURN_V (突破 start，信号 type1)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)   # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)   # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)    # MIDDLE
        xd3 = _mk_xd(8, 5, XianDuanType.DOWN, 3)   # l=5 < start.l=6 → TURN_V
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        result = proc.find_duokong_status(xd3)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 1
        assert proc.status == XianDuan_DuoKong_Process_Status.TURN_V

    def test_middle_to_three_no_po_one(self):
        """MIDDLE → THREE_NO_PO_ONE (不突破 start)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)   # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)   # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)    # MIDDLE
        xd3 = _mk_xd(9, 7.5, XianDuanType.DOWN, 3) # l=7.5 > start.l=6 → THREE_NO_PO_ONE
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        result = proc.find_duokong_status(xd3)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE

    def test_turn_v_to_left_on_break(self):
        """TURN_V → LEFT (突破 middle，信号 type4)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)   # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)   # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)    # MIDDLE
        xd3 = _mk_xd(8, 5, XianDuanType.DOWN, 3)   # TURN_V (type1 KONG)
        xd4 = _mk_xd(7, 4, XianDuanType.DOWN, 4)   # l=4 < middle.l=5 → LEFT, type4 KONG
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 4
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT

    def test_turn_v_to_left_after_on_no_break(self):
        """TURN_V → LEFT_AFTER (UP方向，h < middle.h)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)   # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)   # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)    # MIDDLE
        xd3 = _mk_xd(8, 5, XianDuanType.DOWN, 3)   # TURN_V (type1 KONG), middle=xd3(h=8)
        xd4 = _mk_xd(7, 6, XianDuanType.UP, 4)     # h=7 < middle.h=8 → LEFT_AFTER
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT_AFTER


# ============================================================
# Signal Type Tests
# ============================================================

class TestClass1ZhuanDuoKong:
    """1类信号：转多/转空"""

    def test_zhuan_duo(self):
        """转多：MIDDLE → TURN_V + DUO(type1)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.DOWN, 0)  # LEFT (DOWN)
        xd1 = _mk_xd(9, 7, XianDuanType.UP, 1)      # LEFT_AFTER (UP, h=9 < start.h=10)
        xd2 = _mk_xd(8, 5, XianDuanType.DOWN, 2)    # MIDDLE (l=5 < start.l=6)
        xd3 = _mk_xd(11, 7, XianDuanType.UP, 3)     # h=11 > start.h=10 → TURN_V, DUO
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        result = proc.find_duokong_status(xd3)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 1
        assert result.compare_price == 10  # start.high

    def test_zhuan_kong(self):
        """转空：MIDDLE → TURN_V + KONG(type1)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)     # LEFT (UP)
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)     # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)      # MIDDLE
        xd3 = _mk_xd(8, 5, XianDuanType.DOWN, 3)     # l=5 < start.l=6 → TURN_V, KONG
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        result = proc.find_duokong_status(xd3)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 1
        assert result.compare_price == 6  # start.low


class TestClass2QiangDuoKong:
    """2类信号：强多/强空"""

    def test_qiang_duo(self):
        """强多：LEFT_AFTER → LEFT + DUO(type2)，突破 1.618"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)     # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)     # LEFT_AFTER
        # position_1618 = xd2.low + (start.high - start.low) * 1.618 = 8 + 4*1.618 = 14.472
        xd2 = _mk_xd(15, 8, XianDuanType.UP, 2)      # h=15 > 14.472 → 强多
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        result = proc.find_duokong_status(xd2)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 2
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT

    def test_qiang_kong(self):
        """强空：LEFT_AFTER → LEFT + KONG(type2)，跌破 1.618"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(12, 8, XianDuanType.DOWN, 0)   # LEFT (DOWN)
        xd1 = _mk_xd(11, 9, XianDuanType.UP, 1)      # LEFT_AFTER (UP, h=11 < start.h=12)
        # position_1618 = xd2.high - (start.high - start.low) * 1.618 = 10 - 4*1.618 = 3.528
        xd2 = _mk_xd(10, 3, XianDuanType.DOWN, 2)    # l=3 < 3.528 → 强空
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        result = proc.find_duokong_status(xd2)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 2
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT

    def test_qiang_duo_not_triggered(self):
        """强多不触发：未突破 1.618"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)
        xd2 = _mk_xd(12, 8, XianDuanType.UP, 2)      # h=12 < 14.472
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        result = proc.find_duokong_status(xd2)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.MIDDLE


class TestClass3DuoQiangKongQiang:
    """3类信号：多强/空强"""

    def test_duoqiang(self):
        """多强：THREE_NO_PO_ONE → DUO(type3)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)       # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)       # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)        # MIDDLE
        xd3 = _mk_xd(9, 7, XianDuanType.DOWN, 3)       # THREE_NO_PO_ONE (l=7 > start.l=6)
        # THREE_NO_PO_ONE: left.low=7, middle.low=8 → 7 < 8 → rotate to MIDDLE
        xd4 = _mk_xd(12, 9, XianDuanType.UP, 4)        # h=12 > middle.h=11 → DUO(type3)
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 3

    def test_kongqiang(self):
        """空强：THREE_NO_PO_ONE → KONG(type3)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(12, 8, XianDuanType.DOWN, 0)     # LEFT (DOWN)
        xd1 = _mk_xd(11, 9, XianDuanType.UP, 1)        # LEFT_AFTER (UP, h=11 < start.h=12)
        xd2 = _mk_xd(10, 7, XianDuanType.DOWN, 2)      # MIDDLE (l=7 < start.l=8)
        xd3 = _mk_xd(11, 8, XianDuanType.UP, 3)        # THREE_NO_PO_ONE (h=11 < start.h=12)
        # THREE_NO_PO_ONE: left.high=11, middle.high=10 → 11 > 10 → rotate to MIDDLE
        xd4 = _mk_xd(9, 5, XianDuanType.DOWN, 4)       # l=5 < middle.l=7 → KONG(type3)
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 3


class TestClass4FanDuoKong:
    """4类信号：反多/反空"""

    def test_fan_duo(self):
        """反多：TURN_V (type1 KONG) → LEFT + DUO(type4)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)       # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)       # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)        # MIDDLE
        xd3 = _mk_xd(8, 5, XianDuanType.DOWN, 3)       # TURN_V (type1 KONG), middle=xd3(h=8)
        xd4 = _mk_xd(9, 6, XianDuanType.UP, 4)         # h=9 > middle.h=8 → type4 DUO
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is not None
        assert result.status == DuoKong_Status.DUO
        assert result.typeNum == 4
        assert result.compare_price == 8   # middle.high (xd3.high)
        assert result.duokong_price == 6   # xd4.low

    def test_fan_kong(self):
        """反空：TURN_V (type1 DUO) → LEFT + KONG(type4)"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)       # LEFT (UP)
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)       # LEFT_AFTER
        xd2 = _mk_xd(11, 8, XianDuanType.UP, 2)        # MIDDLE
        # xd3 UP: h=12 > start.h=10 → TURN_V, DUO(type1). middle=xd3(h=12)
        xd3 = _mk_xd(12, 7, XianDuanType.UP, 3)        # TURN_V (type1 DUO), middle=xd3
        xd4 = _mk_xd(8, 3, XianDuanType.DOWN, 4)       # l=3 < middle.l=7 → type4 KONG
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 4
        assert result.compare_price == 7   # middle.low (xd3.low)
        assert result.duokong_price == 8   # xd4.high


# ============================================================
# Verify Types
# ============================================================

class TestVerifyXdTypes:
    """验证 VERIFY_UP/VERIFY_DOWN 类型"""

    def test_verify_up_treated_as_up(self):
        """VERIFY_UP 应被视为上升线段"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.VERIFY_UP, 0)
        xd1 = _mk_xd(9, 7, XianDuanType.VERIFY_DOWN, 1)
        xd2 = _mk_xd(11, 8, XianDuanType.VERIFY_UP, 2)
        xd3 = _mk_xd(8, 5, XianDuanType.VERIFY_DOWN, 3)
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        result = proc.find_duokong_status(xd3)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 1

    def test_verify_down_treated_as_down(self):
        """VERIFY_DOWN 应被视为下降线段"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(12, 8, XianDuanType.VERIFY_DOWN, 0)
        xd1 = _mk_xd(11, 9, XianDuanType.VERIFY_UP, 1)
        xd2 = _mk_xd(10, 7, XianDuanType.VERIFY_DOWN, 2)
        xd3 = _mk_xd(11, 8, XianDuanType.VERIFY_UP, 3)
        xd4 = _mk_xd(9, 5, XianDuanType.VERIFY_DOWN, 4)
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 3


# ============================================================
# get_xd_kline Helper Tests
# ============================================================

class TestGetXdKline:
    """get_xd_kline 辅助函数测试"""

    def test_filters_by_date_range(self):
        """按 XD 日期范围过滤 K 线"""
        xd = _mk_xd(10, 6, XianDuanType.UP, 0, "2024-01-01", "2024-01-05")
        klines = pd.DataFrame([
            {'date': datetime.datetime(2024, 1, 1), 'h': 10, 'l': 6, 'o': 6, 'c': 10, 'a': 100},
            {'date': datetime.datetime(2024, 1, 2), 'h': 9, 'l': 7, 'o': 7, 'c': 9, 'a': 100},
            {'date': datetime.datetime(2024, 1, 3), 'h': 10, 'l': 8, 'o': 8, 'c': 10, 'a': 100},
            {'date': datetime.datetime(2024, 1, 4), 'h': 11, 'l': 9, 'o': 9, 'c': 11, 'a': 100},
            {'date': datetime.datetime(2024, 1, 5), 'h': 12, 'l': 10, 'o': 10, 'c': 12, 'a': 100},
            {'date': datetime.datetime(2024, 1, 6), 'h': 13, 'l': 11, 'o': 11, 'c': 13, 'a': 100},
        ])
        result = get_xd_kline(klines, xd)
        assert len(result) == 5  # Jan 1-5

    def test_empty_result(self):
        """日期范围内无 K 线"""
        xd = _mk_xd(10, 6, XianDuanType.UP, 0, "2099-01-01", "2099-01-02")
        klines = pd.DataFrame([
            {'date': datetime.datetime(2024, 1, 1), 'h': 10, 'l': 6, 'o': 6, 'c': 10, 'a': 100},
        ])
        result = get_xd_kline(klines, xd)
        assert len(result) == 0


# ============================================================
# Integration Tests (compute_dk_sequences)
# ============================================================

class TestComputeDkSequences:
    """_compute_dk_sequences 集成测试"""

    def test_empty_xds(self):
        """空线段列表返回空字典列表"""
        proc = XianDuan_DuoKong_Process()
        klines = pd.DataFrame([
            {'date': datetime.datetime(2024, 1, 1), 'h': 10, 'l': 6, 'o': 6, 'c': 10, 'a': 100},
        ])
        high, low = proc._compute_dk_sequences([], klines)
        assert len(high) == 0
        assert len(low) == 0

    def test_duo_signal_sets_low(self):
        """DUO 信号生成包含 dict 的列表"""
        proc = XianDuan_DuoKong_Process()
        xds = [
            _mk_xd(10, 6, XianDuanType.UP, 0, "2024-01-01", "2024-01-05"),
            _mk_xd(9, 7, XianDuanType.DOWN, 1, "2024-01-06", "2024-01-10"),
            _mk_xd(11, 8, XianDuanType.UP, 2, "2024-01-11", "2024-01-15"),
            _mk_xd(8, 5, XianDuanType.DOWN, 3, "2024-01-16", "2024-01-20"),
            _mk_xd(12, 7, XianDuanType.UP, 4, "2024-01-21", "2024-01-25"),
        ]
        klines = _mk_xd_klines(xds)
        high, low = proc._compute_dk_sequences(xds, klines)
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
        proc = XianDuan_DuoKong_Process()
        xds = [
            _mk_xd(10, 6, XianDuanType.UP, 0, "2024-01-01", "2024-01-05"),
            _mk_xd(9, 7, XianDuanType.DOWN, 1, "2024-01-06", "2024-01-10"),
        ]
        klines = _mk_xd_klines(xds)
        high, low = proc._compute_dk_sequences(xds, klines)
        assert isinstance(high, list)
        assert isinstance(low, list)


# ============================================================
# SZ.600491 真实数据集成测试
# ============================================================

class TestSZ600491Integration:
    """使用 SZ.300491 股票数据的集成测试"""

    @pytest.fixture(scope="class")
    def chanlun_data(self):
        """获取 SZ.600491 的缠论数据（整个测试类共享）"""
        try:
            from chanlun.get_src_klines import get_src_klines
            from chanlun.get_cl_klines import get_cl_lines
            from chanlun.get_fx import FX_PROCESS
            from chanlun.get_bi import BI_Process
            from chanlun.get_xd import XD_Process
        except ImportError as e:
            pytest.skip(f"缺少依赖模块: {e}")

        try:
            src_klines = get_src_klines('SZ.300491', 'd', None)
        except Exception as e:
            pytest.skip(f"获取 SZ.300491 数据失败: {e}")
        if src_klines is None or len(src_klines) == 0:
            pytest.skip("无法获取 SZ.600491 数据（网络不可用或数据源返回空）")
        cl_klines = get_cl_lines(src_klines)
        fx_proc = FX_PROCESS()
        fxlist = fx_proc.find_fenxing(cl_klines)
        bi_process = BI_Process()
        bilist = bi_process.handle(fxlist)
        xd_process = XD_Process()
        xdlist = xd_process.handle(bilist)
        return {
            'src_klines': src_klines,
            'cl_klines': cl_klines,
            'fxlist': fxlist,
            'bilist': bilist,
            'xdlist': xdlist,
        }

    def test_src_klines_not_empty(self, chanlun_data):
        """SZ.600491 原始K线数据不为空"""
        assert len(chanlun_data['src_klines']) > 0

    def test_xdlist_not_empty(self, chanlun_data):
        """SZ.600491 线段列表不为空"""
        assert len(chanlun_data['xdlist']) > 0

    def test_compute_dk_sequences_returns_dict_lists(self, chanlun_data):
        """_compute_dk_sequences 返回字典列表"""
        proc = XianDuan_DuoKong_Process()
        xds = chanlun_data['xdlist']
        klines = chanlun_data['src_klines']
        high, low = proc._compute_dk_sequences(xds, klines)
        assert isinstance(high, list)
        assert isinstance(low, list)

    def test_compute_dk_sequences_has_signals(self, chanlun_data):
        """SZ.600491 应产生至少一个多空隧道信号"""
        proc = XianDuan_DuoKong_Process()
        xds = chanlun_data['xdlist']
        klines = chanlun_data['src_klines']
        high, low = proc._compute_dk_sequences(xds, klines)
        assert len(high) > 0 or len(low) > 0, "SZ.600491 应产生至少一个 dksd_high 或 dksd_low 信号"

    def test_compute_dk_sequences_values_are_positive(self, chanlun_data):
        """多空隧道值应为正数"""
        proc = XianDuan_DuoKong_Process()
        xds = chanlun_data['xdlist']
        klines = chanlun_data['src_klines']
        high, low = proc._compute_dk_sequences(xds, klines)
        for item in high:
            assert item['price'] > 0, f"dksd_high 值应为正数，实际为 {item['price']}"
        for item in low:
            assert item['price'] > 0, f"dksd_low 值应为正数，实际为 {item['price']}"

    def test_compute_dk_sequences_entries_have_valid_keys(self, chanlun_data):
        """每个字典条目应包含 date/index/price 键"""
        proc = XianDuan_DuoKong_Process()
        xds = chanlun_data['xdlist']
        klines = chanlun_data['src_klines']
        high, low = proc._compute_dk_sequences(xds, klines)
        for item in high:
            assert 'index' in item, "dksd_high 条目应包含 'index' 键"
            assert 'price' in item, "dksd_high 条目应包含 'price' 键"
            assert isinstance(item['index'], int), f"index 应为 int，实际为 {type(item['index'])}"
            assert isinstance(item['price'], (int, float)), f"price 应为数值，实际为 {type(item['price'])}"
        for item in low:
            assert 'index' in item, "dksd_low 条目应包含 'index' 键"
            assert 'price' in item, "dksd_low 条目应包含 'price' 键"
            assert isinstance(item['index'], int), f"index 应为 int，实际为 {type(item['index'])}"
            assert isinstance(item['price'], (int, float)), f"price 应为数值，实际为 {type(item['price'])}"

    def test_compute_dk_sequences_signal_count(self, chanlun_data):
        """应至少产生一个隧道值"""
        proc = XianDuan_DuoKong_Process()
        xds = chanlun_data['xdlist']
        klines = chanlun_data['src_klines']
        high, low = proc._compute_dk_sequences(xds, klines)
        assert len(high) > 0 or len(low) > 0, "应至少产生一个隧道值"

    def test_state_machine_processes_all_xds(self, chanlun_data):
        """状态机应能处理所有线段而不报错"""
        proc = XianDuan_DuoKong_Process()
        xds = chanlun_data['xdlist']
        klines = chanlun_data['src_klines']
        # Should not raise any exception
        high, low = proc._compute_dk_sequences(xds, klines)
        assert isinstance(high, list)
        assert isinstance(low, list)

    def test_find_duokong_status_returns_signals(self, chanlun_data):
        """find_duokong_status 应在线段列表中检测到信号"""
        proc = XianDuan_DuoKong_Process()
        xds = chanlun_data['xdlist']
        signals = []
        for xd in xds:
            sig = proc.find_duokong_status(xd)
            if sig is not None:
                signals.append(sig)
        assert len(signals) > 0, "SZ.600491 应产生至少一个多空信号"
        # Verify signal structure
        for sig in signals:
            assert isinstance(sig, XianDuan_DuoKong)
            assert sig.status in (DuoKong_Status.DUO, DuoKong_Status.KONG)
            assert sig.typeNum in (1, 2, 3, 4)
            assert isinstance(sig.compare_price, (int, float))
            assert isinstance(sig.duokong_price, (int, float))


# ============================================================
# Supplementary Tests (Initialization / Output Format / Internal API)
# ============================================================

class TestProcessInitialization:
    """状态机初始化属性测试"""

    def test_tracking_attributes_initialized_to_none(self):
        """所有追踪属性应初始化为 None，避免 AttributeError"""
        proc = XianDuan_DuoKong_Process()
        assert proc.start_high is None
        assert proc.start_high_date is None
        assert proc.start_low is None
        assert proc.start_low_date is None

    def test_line_lists_initialized_empty(self):
        """dksd_high_line 和 dksd_low_line 初始为空列表"""
        proc = XianDuan_DuoKong_Process()
        assert proc.dksd_high_line == []
        assert proc.dksd_low_line == []
        assert proc.status == XianDuan_DuoKong_Process_Status.START


class TestOutputFormat:
    """输出格式兼容性测试"""

    def test_dksd_lines_have_index_price_and_dates(self):
        """dksd_high / dksd_low 条目同时包含 index/price 与 start_date/stop_date"""
        proc = XianDuan_DuoKong_Process()
        xds = [
            _mk_xd(10, 6, XianDuanType.UP, 0, "2024-01-01", "2024-01-05"),
            _mk_xd(9, 7, XianDuanType.DOWN, 1, "2024-01-06", "2024-01-10"),
            _mk_xd(11, 8, XianDuanType.UP, 2, "2024-01-11", "2024-01-15"),
            _mk_xd(8, 5, XianDuanType.DOWN, 3, "2024-01-16", "2024-01-20"),
            _mk_xd(12, 7, XianDuanType.UP, 4, "2024-01-21", "2024-01-25"),
        ]
        klines = _mk_xd_klines(xds)
        high, low = proc._compute_dk_sequences(xds, klines)
        for item in high + low:
            assert 'index' in item
            assert 'price' in item
            assert 'start_date' in item
            assert 'stop_date' in item
            assert isinstance(item['index'], int)
            assert isinstance(item['price'], (int, float))

    def test_dksd_indices_are_sequential_and_unique(self):
        """dksd_high 与 dksd_low 的 index 连续且不重复"""
        proc = XianDuan_DuoKong_Process()
        xds = [
            _mk_xd(10, 6, XianDuanType.UP, 0, "2024-01-01", "2024-01-05"),
            _mk_xd(9, 7, XianDuanType.DOWN, 1, "2024-01-06", "2024-01-10"),
            _mk_xd(11, 8, XianDuanType.UP, 2, "2024-01-11", "2024-01-15"),
            _mk_xd(8, 5, XianDuanType.DOWN, 3, "2024-01-16", "2024-01-20"),
            _mk_xd(12, 7, XianDuanType.UP, 4, "2024-01-21", "2024-01-25"),
        ]
        klines = _mk_xd_klines(xds)
        high, low = proc._compute_dk_sequences(xds, klines)
        indices = [item['index'] for item in high + low]
        assert indices == sorted(indices)
        assert len(indices) == len(set(indices))


class TestPublicPrivateApiSplit:
    """find_duokong_status 与 _find_duokong_status_internal 的行为差异"""

    def test_public_api_filters_type_num_zero(self):
        """公共 API 不暴露 typeNum == 0 的内部 bookkeeping 信号"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)   # LEFT
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)   # LEFT_AFTER
        xd2 = _mk_xd(9, 8, XianDuanType.UP, 2)     # LEFT_AFTER_NORMAL
        xd3 = _mk_xd(11, 9, XianDuanType.UP, 3)    # LEFT_AFTER_NORMAL -> MIDDLE, typeNum 0 internally
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        public_sig = proc.find_duokong_status(xd3)
        assert public_sig is None
        assert proc.status == XianDuan_DuoKong_Process_Status.MIDDLE

    def test_internal_api_returns_type_num_zero(self):
        """内部 API 返回 typeNum == 0 以支持高/低线切换"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.UP, 0)
        xd1 = _mk_xd(9, 7, XianDuanType.DOWN, 1)
        xd2 = _mk_xd(9, 8, XianDuanType.UP, 2)
        xd3 = _mk_xd(11, 9, XianDuanType.UP, 3)
        proc._find_duokong_status_internal(xd0)
        proc._find_duokong_status_internal(xd1)
        proc._find_duokong_status_internal(xd2)
        internal_sig = proc._find_duokong_status_internal(xd3)
        assert internal_sig is not None
        assert internal_sig.typeNum == 0
        assert internal_sig.status == DuoKong_Status.DUO


class TestTurnVFix:
    """TURN_V DOWN 分支修复测试"""

    def test_turn_v_down_break_returns_type4_kong(self):
        """TURN_V 后 DOWN 线段创新低应返回 type4 KONG"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.DOWN, 0)   # LEFT (DOWN)
        xd1 = _mk_xd(9, 8, XianDuanType.UP, 1)        # LEFT_AFTER (h=9 < start.h=10)
        xd2 = _mk_xd(7, 5, XianDuanType.DOWN, 2)      # MIDDLE (l=5 < start.l=6)
        xd3 = _mk_xd(11, 8, XianDuanType.UP, 3)       # TURN_V DUO type1, middle=xd3
        xd4 = _mk_xd(7, 3, XianDuanType.DOWN, 4)      # l=3 < middle.l=8 -> type4 KONG
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is not None
        assert result.status == DuoKong_Status.KONG
        assert result.typeNum == 4

    def test_turn_v_down_no_break_returns_none(self):
        """TURN_V 后 DOWN 线段不创新低应返回 None"""
        proc = XianDuan_DuoKong_Process()
        xd0 = _mk_xd(10, 6, XianDuanType.DOWN, 0)
        xd1 = _mk_xd(9, 8, XianDuanType.UP, 1)        # LEFT_AFTER (h=9 < start.h=10)
        xd2 = _mk_xd(7, 5, XianDuanType.DOWN, 2)      # MIDDLE (l=5 < start.l=6)
        xd3 = _mk_xd(11, 8, XianDuanType.UP, 3)       # TURN_V DUO type1, middle=xd3
        xd4 = _mk_xd(7, 8.5, XianDuanType.DOWN, 4)  # l=8.5 > middle.l=8 -> no break
        proc.find_duokong_status(xd0)
        proc.find_duokong_status(xd1)
        proc.find_duokong_status(xd2)
        proc.find_duokong_status(xd3)
        result = proc.find_duokong_status(xd4)
        assert result is None
        assert proc.status == XianDuan_DuoKong_Process_Status.LEFT_AFTER
