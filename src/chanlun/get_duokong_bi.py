"""
笔级别多空隧道状态机 (BI-Level DuoKong State Machine)

基于笔（BI）关系，通过状态机实现四类多空隧道信号检测：
    1类 - 转多/转空（TURN_V 状态突破）
    2类 - 强多/强空（LEFT_AFTER 状态 1.618 扩展突破）
    3类 - 多强/空强（THREE_NO_PO_ONE 状态突破）
    4类 - 反多/反空（TURN_V 后连续突破）

镜像 get_duokong_xd.py 的 XianDuan_DuoKong_Process，但操作 BI 对象。
"""

from enum import Enum
from typing import List, Union

import pandas as pd

from chanlun.cl_interface import BI, BiType
from chanlun.get_src_klines import get_src_klines
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process


class DuoKong_Status(Enum):
    DUO = "多"
    KONG = '空'
    NONE = '无'


class Bi_DuoKong:
    """BI 级别多空信号对象"""
    def __init__(self, duokong, typeNum, compare_price, duokong_price, stop_date=None):
        self.status = duokong
        self.typeNum = typeNum
        self.compare_price = compare_price
        self.duokong_price = duokong_price
        self.stop_date = stop_date


class Bi_DuoKong_Process_Status(Enum):
    START = '开始'
    LEFT = '左'
    LEFT_AFTER = '左后'
    LEFT_AFTER_NORMAL = '左后Normal'
    MIDDLE = '中'
    MIDDLE_AFTER = '中后'
    TURN_V = 'V反'
    THREE_NO_PO_ONE = '三不破一'


def get_bi_kline(klines, bi: BI):
    """获取 BI 时间范围内的 K 线（兼容 pandas DataFrame）"""
    klines['date'] = pd.to_datetime(klines['date'])
    start_dt = getattr(bi, 'start_datetime', bi.start.k.date)
    end_dt = getattr(bi, 'end_datetime', bi.end.k.date)
    condition = (klines['date'] >= start_dt) & (klines['date'] <= end_dt)
    return klines[condition].copy()

def get_last_kline(klines, start_date):
    klines['date'] = pd.to_datetime(klines['date'])
    condition = klines['date'] >= start_date
    return klines[condition].copy()


class Bi_DuoKong_Process:
    """
    BI 级别多空隧道状态机

    镜像 XianDuan_DuoKong_Process，使用 BiType 替代 XianDuanType。
    状态转移完全一致，仅类型检查和字段访问使用 BI 的属性。
    """

    def __init__(self, config: Union[dict, None] = None):
        self.config = config if config is not None else {}
        self.start = None
        self.left = None
        self.left_after = None
        self.middle = None
        self.middle_after = None
        self.status = Bi_DuoKong_Process_Status.START
        self.dksd_high_line = []
        self.dksd_low_line = []
        self.high = None
        self.low = None
        self.start_high = None
        self.start_high_date = None
        self.start_low = None
        self.start_low_date = None

    def _append_dksd_line(self, line_list, price, start_date, stop_date):
        """Append a single duokong tunnel line with an index key."""
        line_list.append({
            'index': self._line_index,
            'price': price,
            'start_date': start_date,
            'stop_date': stop_date,
        })
        self._line_index += 1

    def find_duokong_status(self, bi: BI):
        """
        Public entry point: process one BI and return a visible DuoKong signal.
        Internal bookkeeping signals (typeNum == 0) are not exposed.
        """
        sig = self._find_duokong_status_internal(bi)
        if sig is not None and sig.typeNum == 0:
            return None
        return sig

    def _find_duokong_status_internal(self, bi: BI):
        date_str = bi.start.k.date.strftime('%Y-%m-%d %H:%M:%S')
        if self.status == Bi_DuoKong_Process_Status.START:
            self.start = bi
            self.status = Bi_DuoKong_Process_Status.LEFT

        elif self.status == Bi_DuoKong_Process_Status.LEFT:
            if bi.type in [BiType.UP, BiType.VERIFY_UP]:
                if bi.high > self.start.high:
                    self.start = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT
                else:
                    self.left = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT_AFTER
            else:
                if bi.low < self.start.low:
                    self.start = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT
                else:
                    self.left = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT_AFTER

        elif self.status == Bi_DuoKong_Process_Status.LEFT_AFTER:
            if bi.type in [BiType.UP, BiType.VERIFY_UP]:
                start_length = self.start.high - self.start.low
                position_1618 = bi.low + start_length * 1.618
                if bi.high > position_1618:
                    self.start = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT
                    return Bi_DuoKong(DuoKong_Status.DUO, 2, position_1618, self.start.low, None)
                elif bi.high > self.start.high:
                    self.left_after = bi
                    self.status = Bi_DuoKong_Process_Status.MIDDLE
                else:
                    self.left_after = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT_AFTER_NORMAL
            else:
                start_length = self.start.high - self.start.low
                position_1618 = bi.high - start_length * 1.618
                if bi.low < position_1618:
                    self.start = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT
                    return Bi_DuoKong(DuoKong_Status.KONG, 2, position_1618, self.start.high, None)
                elif bi.low < self.start.low:
                    self.left_after = bi
                    self.status = Bi_DuoKong_Process_Status.MIDDLE
                else:
                    self.left_after = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT_AFTER_NORMAL

        elif self.status == Bi_DuoKong_Process_Status.MIDDLE:
            if bi.type in [BiType.UP, BiType.VERIFY_UP]:
                if bi.high > self.start.high:
                    self.middle = bi
                    self.status = Bi_DuoKong_Process_Status.TURN_V
                    return Bi_DuoKong(DuoKong_Status.DUO, 1, self.start.high, bi.low, None)
                else:
                    self.middle = bi
                    self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE
            else:
                if bi.low < self.start.low:
                    self.middle = bi
                    self.status = Bi_DuoKong_Process_Status.TURN_V
                    return Bi_DuoKong(DuoKong_Status.KONG, 1, self.start.low, bi.high, None)
                else:
                    self.middle = bi
                    self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE

        elif self.status == Bi_DuoKong_Process_Status.LEFT_AFTER_NORMAL:
            if bi.type in [BiType.UP, BiType.VERIFY_UP]:
                if bi.high > self.start.high:
                    self.start = self.left
                    self.left = self.left_after
                    self.left_after = bi
                    self.status = Bi_DuoKong_Process_Status.MIDDLE
                    #return Bi_DuoKong(DuoKong_Status.DUO, 0, None, self.start.low, self.start.start_datetime)
                else:
                    self.middle = bi
                    self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE
            else:
                if bi.low < self.start.low:
                    self.start = self.left
                    self.left = self.left_after
                    self.left_after = bi
                    self.status = Bi_DuoKong_Process_Status.MIDDLE
                    #return Bi_DuoKong(DuoKong_Status.KONG, 0, None, self.start.high, self.start.start_datetime)
                else:
                    self.middle = bi
                    self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE

        elif self.status == Bi_DuoKong_Process_Status.THREE_NO_PO_ONE:
            if bi.type in [BiType.UP, BiType.VERIFY_UP]:
                if self.start.high < self.left_after.high:
                    # 从Middle转过来的
                    low_price = self.start.low
                    compare_price = self.left_after.high
                    if bi.high > self.left_after.high:
                        if bi.low < self.left.low:
                            self.start = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = bi
                            self.status = Bi_DuoKong_Process_Status.MIDDLE
                        return Bi_DuoKong(DuoKong_Status.DUO, 3, compare_price, low_price, None)
                    else:
                        if bi.low < self.left.low:
                            self.start = self.middle
                            self.left = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT_AFTER
                            #return Bi_DuoKong(DuoKong_Status.KONG, 0, None, self.middle.high, self.middle.end_datetime)
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT_AFTER_NORMAL
                            # return Bi_DuoKong(DuoKong_Status.DUO, 0, None, self.left_after.low, self.left_after.end_datetime)
                else:
                    #从left_after_normal跳转过来的
                    if self.middle.low < self.left.low:
                        if bi.high > self.start.high:
                            high_price = self.start.high
                            self.start = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT
                            return Bi_DuoKong(DuoKong_Status.DUO, 1, high_price, bi.low, None)
                        elif bi.high > self.left_after.high:
                            low_price = self.start.low
                            self.start = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT
                            return Bi_DuoKong(DuoKong_Status.DUO, 3, self.left_after.high, low_price, None)
                        else:
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = bi
                            self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE
                            #return Bi_DuoKong(DuoKong_Status.KONG, 0, None, self.start.high, self.start.end_datetime)
                    else:
                        left_after_length = self.left_after.high - self.left_after.low
                        position_1618 = bi.low + left_after_length * 1.618
                        if bi.high > position_1618:
                            low_price = self.start.low
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = bi
                            self.status = Bi_DuoKong_Process_Status.MIDDLE
                            #return Bi_DuoKong(DuoKong_Status.DUO, 0, None, low_price, self.start.end_datetime)
                        else:
                            high_price = self.start.high
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = bi
                            self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE
                            #return Bi_DuoKong(DuoKong_Status.KONG, 0, None, high_price, self.start.start_datetime)
            else:
                # 笔方向向下
                if self.left_after.low < self.start.low:
                    # 从middle转过来
                    high_price = self.start.high
                    compare_price = self.left_after.low
                    if bi.low < self.left_after.low:
                        if bi.high > self.left.high:
                            self.start = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = bi
                            self.status = Bi_DuoKong_Process_Status.MIDDLE
                        return Bi_DuoKong(DuoKong_Status.KONG, 3, compare_price, high_price, None)
                    else:
                        if bi.high > self.left.high:
                            self.start = self.middle
                            self.left = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT_AFTER
                            #return Bi_DuoKong(DuoKong_Status.DUO, 0, None, self.middle.low, self.middle.end_datetime)
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT_AFTER_NORMAL
                            #return Bi_DuoKong(DuoKong_Status.KONG, 0, None, self.left_after.high, self.left_after.end_datetime)
                else:
                    # 从left_after_normal跳转过来
                    if self.middle.high > self.left.high:
                        if bi.low < self.start.low:
                            low_price = self.start.low
                            self.start = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT
                            return Bi_DuoKong(DuoKong_Status.KONG, 1, low_price, bi.high, None)
                        elif bi.low < self.left_after.low:
                            high_price = self.start.high
                            self.start = bi
                            self.status = Bi_DuoKong_Process_Status.LEFT
                            return Bi_DuoKong(DuoKong_Status.KONG, 3, self.left_after.low, high_price, None)
                        else:
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = bi
                            self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE
                            #return Bi_DuoKong(DuoKong_Status.DUO, 0, None, self.start.low, self.start.end_datetime)
                    else:
                        left_after_length = self.left_after.high - self.left_after.low
                        position_1618 = bi.high - left_after_length * 1.618
                        if bi.low < position_1618:
                            high_price = self.start.high
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = bi
                            self.status = Bi_DuoKong_Process_Status.MIDDLE
                            #return Bi_DuoKong(DuoKong_Status.KONG, 0, None, high_price, self.start.end_datetime)
                        else:
                            low_price = self.start.low
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = bi
                            self.status = Bi_DuoKong_Process_Status.THREE_NO_PO_ONE
                            #return Bi_DuoKong(DuoKong_Status.DUO, 0, None, low_price, self.start.end_datetime)

        elif self.status == Bi_DuoKong_Process_Status.TURN_V:
            if bi.type in [BiType.UP, BiType.VERIFY_UP]:
                if bi.high > self.middle.high:
                    self.start = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT
                    return Bi_DuoKong(DuoKong_Status.DUO, 4, self.middle.high, bi.low, None)
                else:
                    self.start = self.middle
                    self.left = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT_AFTER
            else:
                if bi.low < self.middle.low:
                    self.start = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT
                    return Bi_DuoKong(DuoKong_Status.KONG, 4, self.middle.low, bi.high, None)
                else:
                    self.start = self.middle
                    self.left = bi
                    self.status = Bi_DuoKong_Process_Status.LEFT_AFTER

        return None

    def process_duokong_suidao(self, status: DuoKong_Status, bi: BI, compare_price: float, duokong_price: float, klines):
        bi_klines = get_bi_kline(klines, bi)
        if status == DuoKong_Status.NONE:
            if self.start_high_date:
                for index, row in bi_klines.iterrows():
                    if row['h'] > self.start_high:
                        self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, row['date'])
                        self.start_high = row['h']
                        self.start_high_date = row['date']
            if self.start_low_date:
                for index, row in bi_klines.iterrows():
                    if row['l'] < self.start_low:
                        self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, row['date'])
                        self.start_low = row['l']
                        self.start_low_date = row['date']
        elif status == DuoKong_Status.DUO:
            # 多信号：当价格突破 compare_price 时，生成一条从 duokong_price 开始的低线
            first_status = True
            for index, row in bi_klines.iterrows():
                if row['h'] > compare_price and first_status:
                    # 记录前一条低线（如果有）
                    if self.start_low_date is not None:
                        self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, row['date'])
                    # 新的低线从 duokong_price 开始
                    if self.start.low > self.start_low:
                        self.start_low = self.start.low
                    else:
                        self.start_low = duokong_price
                    self.start_low_date = row['date']
                    first_status = False
                elif self.start_low_date is not None and row['l'] < self.start_low:
                    # 更新当前低线
                    self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, row['date'])
                    self.start_low = row['l']
                    self.start_low_date = row['date']
                elif self.start_high_date is not None and row['h'] > self.start_high:
                    # 更新高线
                    self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, row['date'])
                    self.start_high = row['h']
                    self.start_high_date = row['date']
        elif status == DuoKong_Status.KONG:
            # 空信号：当价格跌破 compare_price 时，生成一条从 duokong_price 开始的高线
            first_status = True
            for index, row in bi_klines.iterrows():
                if row['l'] < compare_price and first_status:
                    # 记录前一条高线（如果有）
                    if self.start_high_date is not None:
                        self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, row['date'])
                    # 新的高线从 duokong_price 开始
                    if self.start.high < self.start_high:
                        self.start_high = self.start.high
                    else:
                        self.start_high = duokong_price
                    self.start_high_date = row['date']
                    first_status = False
                elif self.start_high_date is not None and row['h'] > self.start_high:
                    # 更新当前高线
                    self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, row['date'])
                    self.start_high = row['h']
                    self.start_high_date = row['date']
                elif self.start_low_date is not None and row['l'] < self.start_low:
                    # 更新低线
                    self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, row['date'])
                    self.start_low = row['l']
                    self.start_low_date = row['date']

    def _compute_dk_sequences(self, bis, klines):
        """
        计算笔级别的多空隧道序列数据

        使用 Bi_DuoKong_Process 状态机逐个处理BI，检测四类信号。
        生成 dksd_high 和 dksd_low 序列。

        Args:
            bis: 已完成笔列表
            klines: K线对象列表

        Returns:
            (dksd_high, dksd_low)
        """
        self.dksd_high_line = []
        self.dksd_low_line = []
        self._line_index = 0

        # 初始化追踪变量：用实际K线数据初始化，而不是固定值10000
        self.start_high = 0
        self.start_high_date = None
        self.start_low = 10000
        self.start_low_date = None

        for i, bi in enumerate(bis):
            sig = self._find_duokong_status_internal(bi)
            if sig is None:
                self.process_duokong_suidao(DuoKong_Status.NONE, bi, 0, 0, klines)
            elif sig.status == DuoKong_Status.DUO:
                if sig.compare_price:
                    self.process_duokong_suidao(DuoKong_Status.DUO, bi, sig.compare_price, sig.duokong_price, klines)
                else:
                    # Internal bookkeeping: close current low line and start a new one
                    if self.start_low_date is not None:
                        self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, sig.stop_date)
                    self.start_low = sig.duokong_price
                    self.start_low_date = sig.stop_date
            elif sig.status == DuoKong_Status.KONG:
                if sig.compare_price:
                    self.process_duokong_suidao(DuoKong_Status.KONG, bi, sig.compare_price, sig.duokong_price, klines)
                else:
                    # Internal bookkeeping: close current high line and start a new one
                    if self.start_high_date is not None:
                        self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, sig.stop_date)
                    self.start_high = sig.duokong_price
                    self.start_high_date = sig.stop_date
            else:
                pass

        # 处理最后未闭合的线段：将最后追踪到的高低点延伸到最后一根K线
        start_date = bi.end.k.date
        last_klines = get_last_kline(klines, start_date)
        for index, row in last_klines.iterrows():
            if row['h'] > self.start_high:
                self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, row['date'])
                self.start_high = row['h']
                self.start_high_date = row['date']
            if row['l'] < self.start_low:
                self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, row['date'])
                self.start_low = row['l']
                self.start_low_date = row['date']

        return self.dksd_high_line, self.dksd_low_line


if __name__ == '__main__':
    src_klines = get_src_klines('SZ.300491', 'd', None)
    cl_klines = get_cl_lines(src_klines)
    fx_proc = FX_PROCESS()
    fxlist = fx_proc.find_fenxing(cl_klines)
    bi_process = BI_Process()
    bilist = bi_process.handle(fxlist)

    bi_duokong_process = Bi_DuoKong_Process()
    high_list, low_list = bi_duokong_process._compute_dk_sequences(bilist, src_klines)

    print('Bi High List:')
    for bi_high in high_list:
        print(bi_high)
    print('Bi Low List:')
    for bi_low in low_list:
        print(bi_low)
