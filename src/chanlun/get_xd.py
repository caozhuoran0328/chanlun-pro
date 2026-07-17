from enum import Enum
from typing import List, Union
from chanlun.cl_interface import XD, BI, BiType, XianDuanType, FX
from chanlun.get_src_klines import get_src_klines
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process


class XDProcessType(Enum):
    START = '开始'
    LEFT = '左'
    LEFT_AFTER = '左后'
    LEFT_AFTER_NORMAL = '左后正常'
    LEFT_AFTER_NORMAL_NORMAL = '左后正常正常'
    MIDDLE = '中'
    QUEKOU_MIDDLE = '缺口中'
    QUEKOU_MIDDLE_AFTER = '缺口中后'
    QUEKOU_RIGHT = '缺口右'
    QUEKOU_RIGHT_NORMAL = '缺口右正常'
    MIDDLE_AFTER = '中后'
    RIGHT = '右'
    RIGHT_NORMAL = '右正常'
    RIGHT_NORMAL_NORMAL = '右正常正常'


class XD_Process:
    def __init__(self, config: Union[dict, None] = None):
        self.config = config if config is not None else {}
        self.start = None
        self.stop_bi = None
        self.last_bi = None
        self.xdlist: List[XD] = []
        self.status = XDProcessType.START
        self.left = None
        self.left_after = None
        self.middle = None
        self.middle_after = None
        self.right = None
        self.right_after = None
        self.free = None
        self.free_after = None

    def generate_bi(self, bi1: BI, bi2: BI) -> BI:
        ret_bi = BI(bi1.start, bi2.end)
        # Fix: ensure type and high/low are always set,
        # even when start/end FX types are the same (both BOTTOM or both TOP).
        if ret_bi.type is None:
            if bi2.end.val >= bi1.start.val:
                ret_bi.type = BiType.UP
            else:
                ret_bi.type = BiType.DOWN
        if ret_bi.high == 0:
            ret_bi.high = max(bi1.start.val, bi2.end.val)
        if ret_bi.low == 0:
            ret_bi.low = min(bi1.start.val, bi2.end.val)
        return ret_bi

    def set_xd_from_bi(self, bi1: BI, bi2: BI) -> XD:
        # XD type is determined by bi1.start direction and bi2.end direction.
        # bi1 is_up/down = starts at bottom/top; bi2 is_up/down = ends at top/bottom.
        bi1_is_up = bi1.type in (BiType.UP, BiType.VERIFY_UP)
        bi1_is_down = bi1.type in (BiType.DOWN, BiType.VERIFY_DOWN)
        bi2_is_up = bi2.type in (BiType.UP, BiType.VERIFY_UP)
        bi2_is_down = bi2.type in (BiType.DOWN, BiType.VERIFY_DOWN)

        if bi1_is_up and bi2_is_up:
            # Both upward: overall XD is up. VERIFY if either BI is VERIFY.
            has_verify = (bi1.type == BiType.VERIFY_UP or bi2.type == BiType.VERIFY_UP)
            xd_type = XianDuanType.VERIFY_UP if has_verify else XianDuanType.UP
        elif bi1_is_down and bi2_is_down:
            # Both downward: overall XD is down. VERIFY if either BI is VERIFY.
            has_verify = (bi1.type == BiType.VERIFY_DOWN or bi2.type == BiType.VERIFY_DOWN)
            xd_type = XianDuanType.VERIFY_DOWN if has_verify else XianDuanType.DOWN
        elif bi1_is_up and bi2_is_down:
            # Started up, ended down: verify the top.
            xd_type = XianDuanType.VERIFY_UP
        elif bi1_is_down and bi2_is_up:
            # Started down, ended up: verify the bottom.
            xd_type = XianDuanType.VERIFY_DOWN
        else:
            # Fallback based on price values
            if bi2.end.val >= bi1.start.val:
                xd_type = XianDuanType.VERIFY_UP
            else:
                xd_type = XianDuanType.VERIFY_DOWN

        ret_xd = XD(bi1.start, bi2.end, bi1, bi2, xd_type)
        return ret_xd

    def _get_gap_threshold(self, price: float) -> float:
        """Gap threshold as 0.1% of the reference price."""
        return price * 0.001

    def left_lowhigh_start(self, start: BI, left: BI):
        ret_xd = None
        last_xd = self.get_last_xd()
        if last_xd is None:
            self.start = left
            self.status = XDProcessType.LEFT
        else:
            ret_xd = last_xd
            left_type = left.type
            if left_type == BiType.UP or left_type == BiType.VERIFY_UP:
                if last_xd.low > start.low:
                    ret_xd = self.set_xd_from_bi(start, start)
                    self.start = left
                    self.status = XDProcessType.LEFT
                else:
                    self.left_after = left
                    self.left = self.start
                    self.start = self.generate_bi(last_xd.start_line, last_xd.end_line)
                    self.status = XDProcessType.MIDDLE
                    ret_xd = self.set_xd_from_bi(last_xd.start_line, left)

            elif left_type == BiType.DOWN or left_type == BiType.VERIFY_DOWN:
                if last_xd.high < start.high:
                    ret_xd = self.set_xd_from_bi(start, start)
                    self.start = left
                    self.status = XDProcessType.LEFT
                else:
                    self.left_after = left
                    self.left = self.start
                    self.start = self.generate_bi(last_xd.start_line, last_xd.end_line)
                    self.status = XDProcessType.MIDDLE
                    ret_xd = self.set_xd_from_bi(last_xd.start_line, left)
        return ret_xd

    def middle_lowhigh_start(self, start: BI, left: BI, left_after: BI, middle: BI):
        ret_xd = None
        ret_xd2 = None

        last_xd = self.get_last_xd()
        if last_xd is None:
            self.start = left
            self.left = left_after
            self.left_after = middle
            self.status = XDProcessType.MIDDLE
            ret_xd = self.set_xd_from_bi(left, middle)
        else:
            start_length = start.high - start.low
            last_xd_length = last_xd.high - last_xd.low
            if start_length / last_xd_length > 0.618:
                ret_xd = self.set_xd_from_bi(start, start)
                ret_xd2 = self.set_xd_from_bi(left, middle)
            else:
                ret_xd = self.set_xd_from_bi(last_xd.get_start_bi(), middle)
        return ret_xd, ret_xd2

    def find_xd(self, bi: BI):
        ret_xd = None
        ret_xd2 = None
        ret_xd3 = None
        date_str = bi.end.k.date.strftime('%Y-%m-%d %H:%M:%S')
        bi_type, bi_high, bi_low = bi.type, bi.high, bi.low
        if self.status == XDProcessType.START:
            self.start = bi
            self.status = XDProcessType.LEFT

        elif self.status == XDProcessType.LEFT:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.start.high:
                    ret_xd = self.left_lowhigh_start(self.start, bi)
                else:
                    self.left = bi
                    self.status = XDProcessType.LEFT_AFTER
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.start.low:
                    ret_xd = self.left_lowhigh_start(self.start, bi)
                else:
                    self.left = bi
                    self.status = XDProcessType.LEFT_AFTER

        elif self.status == XDProcessType.LEFT_AFTER:
            self.left_after = bi
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.start.high:
                    self.status = XDProcessType.MIDDLE
                    ret_xd = self.set_xd_from_bi(self.start, bi)
                else:
                    self.status = XDProcessType.LEFT_AFTER_NORMAL
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.start.low:
                    self.status = XDProcessType.MIDDLE
                    ret_xd = self.set_xd_from_bi(self.start, bi)
                else:
                    self.status = XDProcessType.LEFT_AFTER_NORMAL

        elif self.status == XDProcessType.LEFT_AFTER_NORMAL:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.left.high:
                    left_length = bi.high - self.left.low
                    start_length = self.start.high - self.start.low
                    if left_length / start_length > 0.618:
                        ret_xd = self.set_xd_from_bi(self.start, self.start)
                        ret_xd.type = XianDuanType.VERIFY_DOWN
                        self.start = self.left
                        self.left = self.left_after
                        self.left_after = bi
                        self.status = XDProcessType.MIDDLE
                        ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                    else:
                        self.left = self.generate_bi(self.left, bi)
                        self.status = XDProcessType.LEFT_AFTER
                else:
                    self.middle = bi
                    self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.left.low:
                    left_length = self.left.high - bi.low
                    start_length = self.start.high - self.start.low
                    if left_length / start_length > 0.618:
                        ret_xd = self.set_xd_from_bi(self.start, self.start)
                        ret_xd.type = XianDuanType.VERIFY_UP
                        self.start = self.left
                        self.left = self.left_after
                        self.left_after = bi
                        self.status = XDProcessType.MIDDLE
                        ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                    else:
                        self.left = self.generate_bi(self.left, bi)
                        self.status = XDProcessType.LEFT_AFTER
                else:
                    self.middle = bi
                    self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL

        elif self.status == XDProcessType.LEFT_AFTER_NORMAL_NORMAL:
            start_type = self.start.type
            if start_type == BiType.UP or start_type == BiType.VERIFY_UP:
                if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                    if bi_high > self.middle.high:
                        if bi_high > self.start.high:
                            self.left_after = self.generate_bi(self.left_after, bi)
                            self.status = XDProcessType.MIDDLE
                            ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                        else:
                            self.left_after = self.generate_bi(self.left_after, bi)
                            self.status = XDProcessType.LEFT_AFTER_NORMAL
                    else:
                        self.middle_after = bi
                        self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL
                elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                    if bi_low < self.middle.low:
                        self.middle = self.generate_bi(self.middle, bi)
                        if bi_low < self.left.low:
                            ret_xd = self.set_xd_from_bi(self.start, self.start)
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.status = XDProcessType.MIDDLE
                            ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                        else:
                            self.status = XDProcessType.LEFT_AFTER_NORMAL
                    else:
                        self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL
            elif start_type == BiType.DOWN or start_type == BiType.VERIFY_DOWN:
                if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                    if bi_high > self.middle.high:
                        self.middle = self.generate_bi(self.middle, bi)
                        if bi_high > self.left.high:
                            ret_xd = self.set_xd_from_bi(self.start, self.start)
                            self.start = self.left
                            self.left = self.left_after
                            self.left_after = self.middle
                            self.status = XDProcessType.MIDDLE
                            ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                        else:
                            self.status = XDProcessType.LEFT_AFTER_NORMAL
                    else:
                            self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL
                elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                    if bi_low < self.left.low:
                        if bi_low < self.start.low:
                            self.left_after = self.generate_bi(self.left_after, bi)
                            self.status = XDProcessType.MIDDLE

                            ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                        else:
                            self.left_after = self.generate_bi(self.left_after, bi)
                            self.status = XDProcessType.LEFT_AFTER_NORMAL
                    else:
                        self.middle_after = bi
                        self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL

        elif self.status == XDProcessType.MIDDLE:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.start.high:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    self.start = bi
                    self.status = XDProcessType.LEFT
                else:
                    self.middle = bi
                    self.status = XDProcessType.MIDDLE_AFTER
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.start.low:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    self.start = bi
                    self.status = XDProcessType.LEFT
                else:
                    self.middle = bi
                    self.status = XDProcessType.MIDDLE_AFTER

        elif self.status == XDProcessType.MIDDLE_AFTER:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.middle.high:
                    self.start = self.generate_bi(self.start, self.left_after)
                    self.left = self.middle
                    self.left_after = bi
                    self.status = XDProcessType.MIDDLE
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.middle_after = bi
                    self.status = XDProcessType.RIGHT
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.middle.low:
                    self.start = self.generate_bi(self.start, self.left_after)
                    self.left = self.middle
                    self.left_after = bi
                    self.status = XDProcessType.MIDDLE
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.middle_after = bi
                    self.status = XDProcessType.RIGHT

        elif self.status == XDProcessType.RIGHT:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.middle.high:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    ret_xd.type = XianDuanType.VERIFY_DOWN
                    self.start = self.middle
                    self.left = self.middle_after
                    self.left_after = bi
                    self.status = XDProcessType.MIDDLE
                    ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.right = bi
                    self.status = XDProcessType.RIGHT_NORMAL
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.middle.low:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    ret_xd.type = XianDuanType.VERIFY_UP
                    self.start = self.middle
                    self.left = self.middle_after
                    self.left_after = bi
                    self.status = XDProcessType.MIDDLE
                    ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.right = bi
                    self.status = XDProcessType.RIGHT_NORMAL

        elif self.status == XDProcessType.QUEKOU_MIDDLE:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high >= self.right.high:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    ret_xd2 = self.set_xd_from_bi(self.middle, self.right)
                    self.start = bi
                    self.status = XDProcessType.LEFT
                else:
                    self.quekou_middle = bi
                    self.status = XDProcessType.QUEKOU_MIDDLE_AFTER
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.right.low:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    ret_xd2 = self.set_xd_from_bi(self.middle, self.right)
                    self.start = bi
                    self.status = XDProcessType.LEFT
                else:
                    self.quekou_middle = bi
                    self.status = XDProcessType.QUEKOU_MIDDLE_AFTER

        elif self.status == XDProcessType.QUEKOU_MIDDLE_AFTER:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.right.high:
                    gap_threshold = self._get_gap_threshold(self.start.low)
                    if self.right.high <= self.start.low - gap_threshold:
                        self.middle = self.generate_bi(self.middle, self.right)
                        self.middle_after = self.quekou_middle
                        self.right = bi
                        self.status = XDProcessType.QUEKOU_MIDDLE
                    else:
                        ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                        self.start = self.generate_bi(self.middle, self.right)
                        self.left = self.quekou_middle
                        self.left_after = bi
                        self.status = XDProcessType.MIDDLE
                        ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.quekou_middle_after = bi
                    self.status = XDProcessType.QUEKOU_RIGHT

            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.right.low:
                    if self.right.low > self.start.high:
                        self.middle = self.generate_bi(self.middle, self.right)
                        self.middle_after = self.quekou_middle
                        self.right = bi
                        self.status = XDProcessType.QUEKOU_MIDDLE
                    else:
                        ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                        self.start = self.generate_bi(self.middle, self.right)
                        self.left = self.quekou_middle
                        self.left_after = bi
                        self.status = XDProcessType.MIDDLE
                        ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.quekou_middle_after = bi
                    self.status = XDProcessType.QUEKOU_RIGHT

        elif self.status == XDProcessType.QUEKOU_RIGHT:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.quekou_middle.high:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    ret_xd2 = self.set_xd_from_bi(self.middle, self.right)
                    self.start = self.quekou_middle
                    self.left = self.quekou_middle_after
                    self.left_after = bi
                    self.status = XDProcessType.MIDDLE
                    ret_xd3 = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.quekou_right = bi
                    self.status = XDProcessType.QUEKOU_RIGHT_NORMAL

            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.quekou_middle.low:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    ret_xd2 = self.set_xd_from_bi(self.middle, self.right)
                    self.start = self.quekou_middle
                    self.left = self.quekou_middle_after
                    self.left_after = bi
                    self.status = XDProcessType.MIDDLE
                    ret_xd3 = self.set_xd_from_bi(self.start, self.left_after)
                else:
                    self.quekou_right = bi
                    self.status = XDProcessType.QUEKOU_RIGHT_NORMAL

        elif self.status == XDProcessType.QUEKOU_RIGHT_NORMAL:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.quekou_middle.high:
                    self.queckou_middle_after = self.generate_bi(self.quekou_middle_after, bi)
                    if bi_high > self.right.high:
                        self.middle = self.generate_bi(self.middle, self.right)
                        self.middle_after = self.quekou_middle
                        gap_threshold = self._get_gap_threshold(self.start.high)
                        if self.middle.low >= self.start.high + gap_threshold:
                            self.right = self.quekou_middle_after
                            self.status = XDProcessType.QUEKOU_MIDDLE
                        else:
                            ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                            self.start = self.middle
                            self.left = self.middle_after
                            self.left_after = self.middle_after
                            self.status = XDProcessType.MIDDLE
                            ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                    else:
                        self.status = XDProcessType.QUEKOU_RIGHT
                else:
                    self.quekou_right = bi
                    self.status = XDProcessType.RIGHT_NORMAL_NORMAL
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.quekou_middle.low:
                    self.queckou_middle_after = self.generate_bi(self.quekou_middle_after, bi)
                    if bi_low < self.right.low:
                        self.middle = self.generate_bi(self.middle, self.right)
                        self.middle_after = self.quekou_middle
                        gap_threshold = self._get_gap_threshold(self.start.low)
                        if self.middle.high <= self.start.low - gap_threshold:
                            self.right = self.quekou_middle_after
                            self.status = XDProcessType.QUEKOU_MIDDLE
                        else:
                            ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                            self.start = self.middle
                            self.left = self.middle_after
                            self.left_after = self.middle_after
                            self.status = XDProcessType.MIDDLE
                            ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                    else:
                        self.status = XDProcessType.QUEKOU_RIGHT
                else:
                    self.quekou_right = bi
                    self.status = XDProcessType.RIGHT_NORMAL_NORMAL

        elif self.status == XDProcessType.RIGHT_NORMAL:
            if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                if bi_high > self.right.high:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    self.start = self.middle
                    self.left = self.middle_after
                    self.left_after = self.right
                    self.middle = bi
                    self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL
                else:
                    self.right_after = bi
                    self.status = XDProcessType.RIGHT_NORMAL_NORMAL
            elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                if bi_low < self.right.low:
                    ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                    self.start = self.middle
                    self.left = self.middle_after
                    self.left_after = self.right
                    self.middle = bi
                    self.status = XDProcessType.LEFT_AFTER_NORMAL_NORMAL
                else:
                    self.right_after = bi
                    self.status = XDProcessType.RIGHT_NORMAL_NORMAL

        elif self.status == XDProcessType.RIGHT_NORMAL_NORMAL:
            start_type = self.start.type
            if start_type == BiType.UP or start_type == BiType.VERIFY_UP:
                if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                    if bi_high > self.right_after.high:
                        if bi_high > self.right.high:
                            if bi_high > self.middle.high:
                                self.start = self.generate_bi(self.start, self.left_after)
                                self.left = self.middle
                                self.left_after = self.generate_bi(self.middle_after, bi)
                                self.status = XDProcessType.MIDDLE
                                ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                            else:
                                self.middle_after = self.generate_bi(self.middle_after, bi)
                                self.status = XDProcessType.RIGHT
                        else:
                            self.right_after = self.generate_bi(self.right_after, bi)
                            self.status = XDProcessType.RIGHT_NORMAL_NORMAL
                    else:
                        self.status = XDProcessType.RIGHT_NORMAL_NORMAL
                elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                    if bi_low < self.right.low:
                        if bi_low < self.middle.low:
                            self.right = self.generate_bi(self.right, bi)
                            ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                            ret_xd2 = self.set_xd_from_bi(self.middle, self.middle)
                            self.start = self.middle_after
                            self.left = self.right
                            self.left_after = self.generate_bi(self.right_after, bi)
                            self.status = XDProcessType.MIDDLE
                            ret_xd3 = self.set_xd_from_bi(self.start, self.left_after)
                            """
                            self.start = self.middle
                            self.left = self.middle_after
                            self.left_after = self.right
                            self.status = XDProcessType.MIDDLE
                            ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                            """
                        else:
                            self.right = self.generate_bi(self.right, bi)
                            self.status = XDProcessType.RIGHT_NORMAL
                    else:
                        self.status = XDProcessType.RIGHT_NORMAL_NORMAL
            elif start_type == BiType.DOWN or start_type == BiType.VERIFY_DOWN:
                if bi_type == BiType.UP or bi_type == BiType.VERIFY_UP:
                    if bi_high > self.right.high:
                        if bi_high > self.middle.high:
                            ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                            self.start = self.middle
                            self.left = self.middle_after
                            self.left_after = self.generate_bi(self.right, bi)
                            self.status = XDProcessType.MIDDLE
                            ret_xd2 = self.set_xd_from_bi(self.start, self.left_after)
                        else:
                            self.right = self.generate_bi(self.right, bi)
                            self.status = XDProcessType.RIGHT_NORMAL
                    else:
                        self.status = XDProcessType.RIGHT_NORMAL_NORMAL
                elif bi_type == BiType.DOWN or bi_type == BiType.VERIFY_DOWN:
                    if bi_low < self.right.low:
                        if bi_low < self.middle.low:
                            ret_xd = self.set_xd_from_bi(self.start, self.left_after)
                            ret_xd2 = self.set_xd_from_bi(self.middle, self.middle)
                            self.start = self.middle_after
                            self.left = self.right
                            self.left_after = self.generate_bi(self.right_after, bi)
                            self.status = XDProcessType.MIDDLE
                            ret_xd3 = self.set_xd_from_bi(self.start, self.left_after)
                        else:
                            self.middle_after = self.generate_bi(self.middle_after, bi)
                            self.status = XDProcessType.RIGHT
                    else:
                        self.status = XDProcessType.RIGHT_NORMAL_NORMAL

        return ret_xd, ret_xd2, ret_xd3

    def handle(self, bis):
        if len(bis) < 3:
            return self.xdlist
        for bi in bis:
            ret_xd, ret_xd2, ret_xd3 = self.find_xd(bi)
            if ret_xd is None:
                continue
            xd_type = ret_xd.type

            if xd_type in [XianDuanType.VERIFY_UP, XianDuanType.UP]:
                last_xd = self.get_last_xd()
                if last_xd is None:
                    last_xd_type = None
                else:
                    last_xd_type = last_xd.type
                if last_xd_type in [XianDuanType.UP, XianDuanType.VERIFY_UP] and last_xd.start.k.date == ret_xd.start.k.date:
                    self.xdlist.pop()
                self.xdlist.append(ret_xd)
                if ret_xd2 is not None:
                    self.xdlist.append(ret_xd2)
                    if ret_xd3 is not None:
                        self.xdlist.append(ret_xd3)

            elif xd_type in [XianDuanType.VERIFY_DOWN, XianDuanType.DOWN]:
                last_xd = self.get_last_xd()
                if last_xd is None:
                    last_xd_type = None
                else:
                    last_xd_type = last_xd.type
                if last_xd_type in [XianDuanType.DOWN, XianDuanType.VERIFY_DOWN] and last_xd.start.k.date == ret_xd.start.k.date:
                    self.xdlist.pop()
                self.xdlist.append(ret_xd)
                if ret_xd2 is not None:
                    self.xdlist.append(ret_xd2)
                    if ret_xd3 is not None:
                        self.xdlist.append(ret_xd3)

            elif xd_type == XianDuanType.NEW_VERIFY_UP:
                if len(self.xdlist) > 0:
                    self.xdlist.pop()
                self.xdlist.append(ret_xd)
            elif xd_type == XianDuanType.NEW_VERIFY_DOWN:
                if len(self.xdlist) > 0:
                    self.xdlist.pop()
                self.xdlist.append(ret_xd)
        return self.xdlist

    def get_last_xd(self):
        if self.xdlist:
            return self.xdlist[-1]
        else:
            return None


if __name__ == '__main__':
    src_klines = get_src_klines('SZ.002430', '1m', None)
    cl_klines = get_cl_lines(src_klines)
    fx_proc = FX_PROCESS()
    fxlist = fx_proc.find_fenxing(cl_klines)
    bi_process = BI_Process()
    bilist = bi_process.handle(fxlist)
    xd_process = XD_Process()
    xdlist = xd_process.handle(bilist)
    for xd in xdlist:
        print(xd)
