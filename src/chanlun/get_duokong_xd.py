from enum import Enum
from typing import List, Union
from chanlun.cl_interface import XD, XianDuanType
from chanlun.get_src_klines import get_src_klines
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process
from chanlun.get_xd import XD_Process

import pandas as pd

class DuoKong_Status(Enum):
    DUO = "多"
    KONG = '空'
    NONE = '无'

class XianDuan_DuoKong:
    def __init__(self, duokong, typeNum, compare_price, duokong_price, stop_date):
        self.status = duokong
        self.typeNum = typeNum
        self.compare_price = compare_price
        self.duokong_price = duokong_price
        self.stop_date = stop_date

class XianDuan_DuoKong_Process_Status(Enum):
    START = '开始'
    LEFT = '左'
    LEFT_AFTER = '左后'
    LEFT_AFTER_NORMAL = '左后Normal'
    MIDDLE= '中'
    MIDDLE_AFTER = '中后'
    TURN_V = 'V反'
    THREE_NO_PO_ONE = '三不破一'

def get_xd_kline(klines, xd: XD):
    klines['date'] = pd.to_datetime(klines['date'])
    start_dt = getattr(xd, 'start_datetime', xd.start.k.date)
    end_dt = getattr(xd, 'end_datetime', xd.end.k.date)
    condition = (klines['date'] >= start_dt) & (klines['date'] <= end_dt)
    return klines[condition].copy()

def get_last_kline(klines, start_date):
    klines['date'] = pd.to_datetime(klines['date'])
    condition = klines['date'] >= start_date
    return klines[condition].copy()

class XianDuan_DuoKong_Process:
    def __init__(self, config: Union[dict, None] = None):
        self.config = config if config is not None else {}
        self.start = None
        self.left = None
        self.left_after = None
        self.middle = None
        self.middle_after = None
        self.status = XianDuan_DuoKong_Process_Status.START
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

    def find_duokong_status(self, xd: XD):
        """
        Public entry point: process one XD and return a visible DuoKong signal.
        Internal bookkeeping signals (typeNum == 0) are not exposed.
        """
        sig = self._find_duokong_status_internal(xd)
        if sig is not None and sig.typeNum == 0:
            return None
        return sig

    def _find_duokong_status_internal(self, xd: XD):
        date_str = xd.start.k.date.strftime('%Y-%m-%d %H:%M:%S')
        if self.status == XianDuan_DuoKong_Process_Status.START:
            self.start = xd
            self.status = XianDuan_DuoKong_Process_Status.LEFT

        elif self.status == XianDuan_DuoKong_Process_Status.LEFT:
            if xd.type in [XianDuanType.UP, XianDuanType.VERIFY_UP]:
                if xd.high > self.start.high:
                    self.start = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT
                else:
                    self.left = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER
            else:
                if xd.low < self.start.low:
                    self.start = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT
                else:
                    self.left = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER

        elif self.status == XianDuan_DuoKong_Process_Status.LEFT_AFTER:
            if xd.type in [XianDuanType.UP, XianDuanType.VERIFY_UP]:
                start_length = self.start.high - self.start.low
                position_1618 = xd.low + start_length * 1.618
                if xd.high > position_1618:
                    self.start = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT
                    return XianDuan_DuoKong(DuoKong_Status.DUO, 2, position_1618, self.start.low, None)
                elif xd.high > self.start.high:
                    self.left_after = xd
                    self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                else:
                    self.left_after = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER_NORMAL
            else:
                start_length = self.start.high - self.start.low
                position_1618 = xd.high - start_length * 1.618
                if xd.low < position_1618:
                    self.start = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT
                    return XianDuan_DuoKong(DuoKong_Status.KONG, 2, position_1618, self.start.high, None)
                elif xd.low < self.start.low:
                    self.left_after = xd
                    self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                else:
                    self.left_after = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER_NORMAL

        elif self.status == XianDuan_DuoKong_Process_Status.MIDDLE:
            if xd.type in [XianDuanType.UP, XianDuanType.VERIFY_UP]:
                if xd.high > self.start.high:
                    self.middle = xd
                    self.status = XianDuan_DuoKong_Process_Status.TURN_V
                    return XianDuan_DuoKong(DuoKong_Status.DUO, 1, self.start.high, xd.low, None)
                else:
                    self.middle = xd
                    self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE
            else:
                if xd.low < self.start.low:
                    self.middle = xd
                    self.status = XianDuan_DuoKong_Process_Status.TURN_V
                    return XianDuan_DuoKong(DuoKong_Status.KONG, 1, self.start.low, xd.high, None)
                else:
                    self.middle = xd
                    self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE
        
        elif self.status == XianDuan_DuoKong_Process_Status.LEFT_AFTER_NORMAL:
            if xd.type in [XianDuanType.UP, XianDuanType.VERIFY_UP]:
                if xd.high > self.start.high:
                    self.start = self.left
                    self.left = self.left_after
                    self.left_after = xd
                    self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                    return XianDuan_DuoKong(DuoKong_Status.DUO, 0, None, self.start.low, self.start.start_datetime)
                else:
                    self.middle = xd
                    self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE
            else:
                if xd.low < self.start.low:
                    self.start = self.left
                    self.left = self.left_after
                    self.left_after = xd
                    self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                    return XianDuan_DuoKong(DuoKong_Status.KONG, 0, None, self.start.high, self.start.start_datetime)
                else:
                    self.middle = xd
                    self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE

        elif self.status == XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE:
            if xd.type in [XianDuanType.UP, XianDuanType.VERIFY_UP]:
                if self.start.high < self.left_after.high:
                    # 从Middle转过来的
                    low_price = self.start.low
                    if xd.high > self.left_after.high:
                        if xd.low < self.left.low:
                            self.start = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = xd
                            self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                        return XianDuan_DuoKong(DuoKong_Status.DUO, 3, self.left.high, low_price, None)
                    else:
                        if xd.low < self.left.low:
                            self.start = self.middle
                            self.left = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER
                            return XianDuan_DuoKong(DuoKong_Status.KONG, 0, None, self.middle.high, self.middle.end_datetime)
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER_NORMAL
                            return XianDuan_DuoKong(DuoKong_Status.DUO, 0, None, self.left_after.low, self.left_after.end_datetime)
                else:
                    #从Left_after_normal转过来的
                    if self.middle.low < self.left.low:
                        if xd.high > self.start.high:
                            low_price = self.start.low
                            self.start = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT
                            return XianDuan_DuoKong(DuoKong_Status.DUO, 1, self.start.high, low_price, None)
                        elif xd.high > self.left_after.high:
                            low_price = self.start.low
                            self.start = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT
                            return XianDuan_DuoKong(DuoKong_Status.DUO, 3, self.left_after.high, low_price, None)
                        else:
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = xd
                            self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE
                            return XianDuan_DuoKong(DuoKong_Status.KONG, 0, None, self.start.high, self.start.end_datetime)
                    else:
                        left_after_length = self.left_after.high - self.left_after.low
                        position_1618 = xd.low + left_after_length * 1.618
                        if xd.high > position_1618:
                            low_price = self.start.low
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = xd
                            self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                            return XianDuan_DuoKong(DuoKong_Status.DUO, 0, None, low_price, self.start.end_datetime)
                        else:
                            high_price = self.start.high
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = xd
                            self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE
                            return XianDuan_DuoKong(DuoKong_Status.KONG, 0, None, high_price, self.start.start_datetime)
            else:
                # 线段方向向下
                if self.left_after.low < self.start.low:
                    # 从middle转过来
                    high_price = self.start.high
                    if xd.low < self.left_after.low:
                        if xd.high > self.left.high:
                            self.start = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = xd
                            self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                        return XianDuan_DuoKong(DuoKong_Status.KONG, 3, self.left.low, high_price, None)
                    else:
                        if xd.high > self.left.high:
                            self.start = self.middle
                            self.left = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER
                            return XianDuan_DuoKong(DuoKong_Status.DUO, 0, None, self.middle.low, self.middle.end_datetime)
                        else:
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER_NORMAL
                            return XianDuan_DuoKong(DuoKong_Status.KONG, 0, None, self.left_after.high, self.left_after.end_datetime)
                else:
                    # 从left_after_normal跳转过来
                    if self.middle.high > self.left.high:
                        if xd.low < self.start.low:
                            high_price = self.start.high
                            self.start = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT
                            return XianDuan_DuoKong(DuoKong_Status.KONG, 1, self.start.low, high_price, None)
                        elif xd.low < self.left_after.low:
                            high_price = self.start.high
                            self.start = xd
                            self.status = XianDuan_DuoKong_Process_Status.LEFT
                            return XianDuan_DuoKong(DuoKong_Status.KONG, 3, self.left_after.low, high_price, None)
                        else:
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = xd
                            self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE
                            return XianDuan_DuoKong(DuoKong_Status.DUO, 0, None, self.start.low, self.start.end_datetime)
                    else:
                        left_after_length = self.left_after.high - self.left_after.low
                        position_1618 = xd.high - left_after_length * 1.618
                        if xd.low < position_1618:
                            high_price = self.start.high
                            self.start = self.left_after
                            self.left = self.middle
                            self.left_after = xd
                            self.status = XianDuan_DuoKong_Process_Status.MIDDLE
                            return XianDuan_DuoKong(DuoKong_Status.KONG, 0, None, high_price, self.start.end_datetime)
                        else:
                            low_price = self.start.low
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.middle = xd
                            self.status = XianDuan_DuoKong_Process_Status.THREE_NO_PO_ONE
                            return XianDuan_DuoKong(DuoKong_Status.DUO, 0, None, low_price, self.start.end_datetime)

        elif self.status == XianDuan_DuoKong_Process_Status.TURN_V:
            if xd.type in [XianDuanType.UP, XianDuanType.VERIFY_UP]:
                if xd.high > self.middle.high:
                    self.start = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT
                    return XianDuan_DuoKong(DuoKong_Status.DUO, 4, self.middle.high, xd.low, None)
                else:
                    self.start = self.middle
                    self.left = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER
            else:
                if xd.low < self.middle.low:
                    self.start = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT
                    return XianDuan_DuoKong(DuoKong_Status.KONG, 4, self.middle.low, xd.high, None)
                else:
                    self.start = self.middle
                    self.left = xd
                    self.status = XianDuan_DuoKong_Process_Status.LEFT_AFTER

        return None

    def process_duokong_suidao(self, status:DuoKong_Status, xd:XD, compare_price:float, duokong_price:float, klines):
        xd_klines = get_xd_kline(klines, xd)
        if status == DuoKong_Status.NONE:
            if self.start_high_date:
                for index, row in xd_klines.iterrows():
                    if row['h'] > self.start_high:
                        self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, row['date'])
                        self.start_high = row['h']
                        self.start_high_date = row['date']
            if self.start_low_date:
                for index, row in xd_klines.iterrows():
                    if row['l'] < self.start_low:
                        self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, row['date'])
                        self.start_low = row['l']
                        self.start_low_date = row['date']
        elif status == DuoKong_Status.DUO:
            # 多信号：当价格突破 compare_price 时，生成一条从 duokong_price 开始的低线
            first_status = True
            for index, row in xd_klines.iterrows():
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
            for index, row in xd_klines.iterrows():
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


    def _compute_dk_sequences(self, xds, klines):
        """
        计算线段级别的多空隧道序列数据

        使用 XianDuan_DuoKong_Process 状态机逐个处理XD，检测四类信号。
        生成 dksd_high 和 dksd_low 序列。

        Args:
            xds: 已完成线段列表
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

        for i, xd in enumerate(xds):
            sig = self._find_duokong_status_internal(xd)
            if sig is None:
                self.process_duokong_suidao(DuoKong_Status.NONE, xd, 0, 0, klines)
            elif sig.status == DuoKong_Status.DUO:
                if sig.compare_price:
                    self.process_duokong_suidao(DuoKong_Status.DUO, xd, sig.compare_price, sig.duokong_price, klines)
                else:
                    # Internal bookkeeping: close current low line and start a new one
                    if self.start_low_date is not None:
                        self._append_dksd_line(self.dksd_low_line, self.start_low, self.start_low_date, sig.stop_date)
                    self.start_low = sig.duokong_price
                    self.start_low_date = sig.stop_date
            elif sig.status == DuoKong_Status.KONG:
                if sig.compare_price:
                    self.process_duokong_suidao(DuoKong_Status.KONG, xd, sig.compare_price, sig.duokong_price, klines)
                else:
                    # Internal bookkeeping: close current high line and start a new one
                    if self.start_high_date is not None:
                        self._append_dksd_line(self.dksd_high_line, self.start_high, self.start_high_date, sig.stop_date)
                    self.start_high = sig.duokong_price
                    self.start_high_date = sig.stop_date
            else:
                pass

        # 处理最后未闭合的线段：将最后追踪到的高低点延伸到最后一根K线
        start_date = xd.end.k.date
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
    xd_process = XD_Process()
    xdlist = xd_process.handle(bilist)
    xd_duokong_process = XianDuan_DuoKong_Process()
    """
    xd_duokong_list = xd_duokong_process.handle(xdlist, src_klines)
    if xd_duokong_list:
        for xd_dk in xd_duokong_list:
            print(xd_dk)
    """
    high_list, low_list = xd_duokong_process._compute_dk_sequences(xdlist, src_klines)
    
    print('High:')
    for h_line in high_list:
        print(h_line)
    
    print('Low:')
    for l_line in low_list:
        print(l_line)