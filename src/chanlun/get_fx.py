from pandas import DataFrame 
import pandas as pd
from enum import Enum
from chanlun.cl_interface import FX, CLKline, Kline, FxStatus, Config
from datetime import datetime
from chanlun.get_src_klines import get_src_klines
from chanlun.get_cl_klines import get_cl_lines


class FenXingProcessStatus(Enum):
    LEFT = '左边K线'
    MIDDLE = '中间K线'
    RIGHT = '右边K线'
    FREE = '自由K线'
    NEXT_LEFT = '下一个左边K线'
    NEXT_MIDDLE = '下一个中间K线'
    

class FX_PROCESS:
    def __init__(self, config: dict = None):
        self.left = None
        self.middle = None
        self.right = None
        self.free = None
        self.next_left = None
        self.next_middle = None
        self.status = FenXingProcessStatus.LEFT
        self.fx_lists = []
        self.config = config if config is not None else {}
        self.fx_bh = self.config.get('FX_BH_TYPE', Config.FX_BH_YES.value)

    def _validate_fx_bh(self, new_fx: FX) -> bool:
        """
        根据 FX_BH_* 配置验证分型包含关系
        - FX_BH_YES: 不判断顶底关系
        - FX_BH_DINGDI: 顶不可以在底中，但底可以在顶中
        - FX_BH_DIDING: 底不可以在顶中，但顶可以在底中
        - FX_BH_NO_QBH: 不允许前一个分型包含后一个分型
        - FX_BH_NO_HBQ: 不允许后一个分型包含前一个分型
        - FX_BH_NO: 顶不可以在底中，底不可以在顶中
        """
        if self.fx_bh == Config.FX_BH_YES.value:
            return True
        if len(self.fx_lists) == 0:
            return True

        last_fx = self.fx_lists[-1]
        if last_fx is None:
            return True

        if self.fx_bh == Config.FX_BH_NO.value:
            # 顶不可以在底中，底不可以在顶中
            if new_fx.type in (FxStatus.TOP, FxStatus.VERIFY_TOP):
                if last_fx.type in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM) and new_fx.val > last_fx.val:
                    return True
                return False
            if new_fx.type in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM):
                if last_fx.type in (FxStatus.TOP, FxStatus.VERIFY_TOP) and new_fx.val < last_fx.val:
                    return True
                return False
        elif self.fx_bh == Config.FX_BH_DINGDI.value:
            # 顶不可以在底中
            if new_fx.type in (FxStatus.TOP, FxStatus.VERIFY_TOP):
                if last_fx.type not in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM):
                    return True
                if new_fx.val > last_fx.val:
                    return True
                return False
        elif self.fx_bh == Config.FX_BH_DIDING.value:
            # 底不可以在顶中
            if new_fx.type in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM):
                if last_fx.type not in (FxStatus.TOP, FxStatus.VERIFY_TOP):
                    return True
                if new_fx.val < last_fx.val:
                    return True
                return False
        elif self.fx_bh == Config.FX_BH_NO_QBH.value:
            # 不允许前一个分型包含后一个分型
            if last_fx.type in (FxStatus.TOP, FxStatus.VERIFY_TOP):
                if new_fx.type in (FxStatus.TOP, FxStatus.VERIFY_TOP) and new_fx.val > last_fx.val:
                    return False
            elif last_fx.type in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM):
                if new_fx.type in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM) and new_fx.val < last_fx.val:
                    return False
        elif self.fx_bh == Config.FX_BH_NO_HBQ.value:
            # 不允许后一个分型包含前一个分型
            if new_fx.type in (FxStatus.TOP, FxStatus.VERIFY_TOP):
                if last_fx.type in (FxStatus.TOP, FxStatus.VERIFY_TOP) and new_fx.val < last_fx.val:
                    return False
            elif new_fx.type in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM):
                if last_fx.type in (FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM) and new_fx.val > last_fx.val:
                    return False
        return True

    def find_fenxing(self, in_df: DataFrame):
        df = in_df.copy()
        # 添加最小 K 线数量检查
        if len(df) < 3:
            return self.fx_lists

        fx_klines = []
        for index, row in df.iterrows():
            fx_status, middle = self.find_gd_high_low(row)
            if fx_status:
                fx_klines.append(df.loc[index])
                if fx_status == FxStatus.TOP:
                    fx = FX(FxStatus.TOP, middle, fx_klines, middle.h, middle.k_index, False)
                    if self._validate_fx_bh(fx):
                        self.fx_lists.append(fx)
                    fx_klines = []  # 分型后清除 fx_klines
                elif fx_status == FxStatus.BOTTOM:
                    fx = FX(FxStatus.BOTTOM, middle, fx_klines, middle.l, middle.k_index, False)
                    if self._validate_fx_bh(fx):
                        self.fx_lists.append(fx)
                    fx_klines = []  # 分型后清除 fx_klines
                elif fx_status == FxStatus.VERIFY_TOP:
                    last_fx = self.get_before_last_fx()[1]
                    if last_fx is not None and last_fx.type == FxStatus.TOP and last_fx.k.date == middle.date:
                        self.fx_lists.pop()
                    fx = FX(FxStatus.VERIFY_TOP, middle, fx_klines, middle.h, middle.k_index, True)
                    if self._validate_fx_bh(fx):
                        self.fx_lists.append(fx)
                    fx_klines = []
                elif fx_status == FxStatus.VERIFY_BOTTOM:
                    last_fx = self.get_before_last_fx()[1]
                    if last_fx is not None and last_fx.type == FxStatus.BOTTOM and last_fx.k.date == middle.date:
                        self.fx_lists.pop()
                    fx = FX(FxStatus.VERIFY_BOTTOM, middle, fx_klines, middle.l, middle.k_index, True)
                    if self._validate_fx_bh(fx):
                        self.fx_lists.append(fx)
                    fx_klines = []
                elif fx_status == FxStatus.FAILURE_TOP or fx_status == FxStatus.FAILURE_BOTTOM:
                    if len(self.fx_lists) > 0:
                        self.fx_lists.pop()
            else:
                fx_klines.append(df.loc[index])
        return self.fx_lists
                
    def find_gd_high_low(self, k: CLKline):
        date_str = k.date.strftime('%Y-%m-%d %H:%M:%S')
        high = k.h
        low = k.low
        index_no = k.k_index
        if self.status == FenXingProcessStatus.NEXT_MIDDLE:
            before_last_fx, last_fx = self.get_before_last_fx()
            if last_fx is not None and last_fx.type == FxStatus.TOP:
                if high > last_fx.val:
                    ret_k = self.middle
                    self.left = self.next_left
                    self.middle = k
                    self.status = FenXingProcessStatus.RIGHT
                    return FxStatus.FAILURE_TOP, ret_k
                elif low < self.next_left.l:
                    ret_k = self.middle
                    self.left = self.next_left
                    self.middle = k
                    self.status = FenXingProcessStatus.RIGHT
                    return FxStatus.VERIFY_TOP, ret_k
                else:
                    self.left = self.free
                    self.middle = self.next_left
                    self.right = k
                    self.status = FenXingProcessStatus.FREE
                    return FxStatus.BOTTOM, self.middle
            elif last_fx is not None and last_fx.type == FxStatus.BOTTOM:
                if low < last_fx.val:
                    ret_k = self.middle
                    self.left = self.next_left
                    self.middle = k
                    self.status = FenXingProcessStatus.RIGHT
                    return FxStatus.FAILURE_BOTTOM, ret_k
                elif high > self.next_left.h:
                    ret_k = self.middle
                    self.left = self.next_left
                    self.middle = k
                    self.status = FenXingProcessStatus.RIGHT
                    return FxStatus.VERIFY_BOTTOM, ret_k
                else:
                    self.left = self.free
                    self.middle = self.next_left
                    self.right = k
                    self.status = FenXingProcessStatus.FREE
                    return FxStatus.TOP, self.middle
            else:
                ret_k = self.middle
                self.left = self.free
                self.middle = self.next_left
                self.right = k
                self.status = FenXingProcessStatus.NEXT_LEFT
                
        elif self.status == FenXingProcessStatus.NEXT_LEFT:
            before_last_fx, last_fx = self.get_before_last_fx()
            if last_fx is not None and last_fx.type == FxStatus.TOP:
                if high > last_fx.val:
                    ret_k = self.middle
                    self.left = self.free
                    self.middle = k
                    self.status = FenXingProcessStatus.RIGHT
                    return FxStatus.FAILURE_TOP, ret_k
                elif low < self.free.l:
                    self.next_left = k
                    self.status = FenXingProcessStatus.NEXT_MIDDLE
            elif last_fx is not None and last_fx.type == FxStatus.BOTTOM:
                if low < last_fx.val:
                    ret_k = self.middle
                    self.left = self.free
                    self.middle = k
                    self.status = FenXingProcessStatus.RIGHT
                    return FxStatus.FAILURE_BOTTOM, ret_k
                elif high > self.free.h:
                    self.next_left = k
                    self.status = FenXingProcessStatus.NEXT_MIDDLE

        elif self.status == FenXingProcessStatus.FREE:
            before_last_fx, last_fx = self.get_before_last_fx()
            if last_fx is not None and last_fx.type == FxStatus.TOP and high > last_fx.val:
                ret_k = self.middle
                self.left = self.right
                self.middle = k
                self.status = FenXingProcessStatus.RIGHT
                return FxStatus.FAILURE_TOP, self.right
            elif last_fx is not None and last_fx.type == FxStatus.BOTTOM and low < last_fx.val:
                ret_k = self.middle
                self.left = self.right
                self.middle = k
                self.status = FenXingProcessStatus.RIGHT
                return FxStatus.FAILURE_BOTTOM, self.right
            elif before_last_fx and before_last_fx.type == FxStatus.BOTTOM and low < before_last_fx.val:
                ret_k = self.middle
                self.left = self.right
                self.middle = k
                self.status = FenXingProcessStatus.RIGHT
                return FxStatus.TOP, ret_k
            elif before_last_fx and before_last_fx.type == FxStatus.TOP and high > before_last_fx.val:
                ret_k = self.middle
                self.left = self.right
                self.middle = k
                self.status = FenXingProcessStatus.RIGHT
                return FxStatus.BOTTOM, ret_k
            else:
                self.free = k
                self.status = FenXingProcessStatus.NEXT_LEFT

        elif self.status == FenXingProcessStatus.RIGHT:
            if self.middle.h > self.left.h:
                if high > self.middle.h:
                    self.left = self.middle
                    self.middle = k
                else:
                    self.right = k
                    before_last_fx, last_fx = self.get_before_last_fx()
                    if last_fx is None:
                        self.status = FenXingProcessStatus.FREE
                        return FxStatus.TOP, self.middle
                    elif last_fx.type == FxStatus.VERIFY_BOTTOM and low < last_fx.val:
                        ret_k = self.middle
                        self.left = self.middle
                        self.middle = k
                        self.status = FenXingProcessStatus.RIGHT
                        return FxStatus.TOP, ret_k
                    elif last_fx.type == FxStatus.BOTTOM and low < last_fx.val:
                        ret_k = self.middle
                        self.left = self.middle
                        self.middle = self.right
                        self.status = FenXingProcessStatus.RIGHT
                        return FxStatus.TOP, ret_k
                    else:
                        self.status = FenXingProcessStatus.FREE
                        return FxStatus.TOP, self.middle

            elif self.middle.l < self.left.l:
                if low < self.middle.l:
                    self.left = self.middle
                    self.middle = k
                else:
                    self.right = k
                    before_last_fx, last_fx = self.get_before_last_fx()
                    if last_fx is None:
                        self.status = FenXingProcessStatus.FREE
                        return FxStatus.BOTTOM, self.middle
                    elif last_fx.type == FxStatus.VERIFY_TOP and high > last_fx.val:
                        ret_k = self.middle
                        self.left = self.middle
                        self.middle = k
                        self.status = FenXingProcessStatus.RIGHT
                        return FxStatus.BOTTOM, ret_k
                    elif last_fx.type == FxStatus.TOP and high > last_fx.val:
                        ret_k = self.middle
                        self.left = self.middle
                        self.middle = self.right
                        self.status = FenXingProcessStatus.RIGHT
                        return FxStatus.BOTTOM, ret_k
                    else:
                        self.status = FenXingProcessStatus.FREE
                        return FxStatus.BOTTOM, self.middle
                
        elif self.status == FenXingProcessStatus.MIDDLE:
            self.middle = k
            self.status = FenXingProcessStatus.RIGHT

        elif self.status == FenXingProcessStatus.LEFT:
            self.left = k
            self.status = FenXingProcessStatus.MIDDLE
        return None, None
    
    def get_before_last_fx(self):
        if len(self.fx_lists) >= 2:
            return self.fx_lists[-2], self.fx_lists[-1]
        elif len(self.fx_lists) == 1:
            return None, self.fx_lists[-1]
        else:
            return None, None

    
if __name__ == '__main__':
    src_klines = get_src_klines('SZ.002430', '1m', None )
    cl_klines = get_cl_lines(src_klines)
    fx_proc = FX_PROCESS()
    fx_list = fx_proc.find_fenxing(cl_klines)
    for fx in fx_list:
        print(fx.type, fx.k.date, fx.val, fx.index)
