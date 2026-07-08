from enum import Enum
from chanlun.cl_interface import FX, BI, FxStatus, BiType
from chanlun.get_src_klines import get_src_klines
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS, FxStatus
 
class BI_Process:
    def __init__(self, config: dict = None):
        self.bilist = []
        self.start_fx = None
        self.no = 0
        self.config = config if config is not None else {}

    def _has_gap(self, fx1: FX, fx2: FX) -> bool:
        """检查两个分型之间是否存在缺口"""
        if fx1.type in (FxStatus.TOP, FxStatus.VERIFY_TOP):
            # 顶分型 -> 底分型：顶的低点高于底的高点 = 向下缺口
            return fx1.val > fx2.k.l and fx2.val < fx1.k.h
        else:
            # 底分型 -> 顶分型：底的高点低于顶的低点 = 向上缺口
            return fx1.val < fx2.k.h and fx2.val > fx1.k.l
        return False

    def _check_min_kline_count(self, fx1: FX, fx2: FX, min_count: int = 5) -> bool:
        """检查两个分型之间的K线数量是否满足最小要求"""
        k_cnt = fx2.k.k_index - fx1.k.k_index
        return k_cnt >= min_count

    def _check_amplitude(self, fx1: FX, fx2: FX, min_amp: float = 0.001) -> bool:
        """检查笔的振幅是否满足最小要求"""
        if fx1.val == 0:
            return False
        amp = abs(fx2.val - fx1.val) / fx1.val
        return amp >= min_amp

    def _is_valid_bi(self, fx1: FX, fx2: FX) -> bool:
        """验证两个分型是否构成有效笔"""
        # 最小K线数检查 (新旧笔规则：至少5根K线)
        min_k = self.config.get('BI_MIN_KLINE_COUNT', 5)
        if not self._check_min_kline_count(fx1, fx2, min_k):
            return False
        # 振幅检查
        min_amp = self.config.get('BI_MIN_AMPLITUDE', 0.001)
        if not self._check_amplitude(fx1, fx2, min_amp):
            return False
        return True

    def find_bi(self, fx: FX) -> BI:
        ret_bi = None
        date_str = fx.k.date.strftime('%Y-%m-%d %H:%M:%S')
        if self.start_fx is None:
            self.start_fx = fx
            return None

        if self.start_fx.type in [FxStatus.TOP, FxStatus.VERIFY_TOP]:
            if fx.type in [FxStatus.BOTTOM, FxStatus.VERIFY_BOTTOM]:
                # 当至少一个分型是 VERIFY 时，笔类型为 VERIFY
                has_verify = (self.start_fx.type == FxStatus.VERIFY_TOP or
                              fx.type == FxStatus.VERIFY_BOTTOM)
                bi_type = BiType.VERIFY_DOWN if has_verify else BiType.DOWN
                ret_bi = BI(self.start_fx, fx, bi_type, self.no)
                self.start_fx = fx
                self.no += 1

        elif self.start_fx.type in [FxStatus.VERIFY_BOTTOM, FxStatus.BOTTOM]:
            if fx.type in [FxStatus.VERIFY_TOP, FxStatus.TOP]:
                has_verify = (self.start_fx.type == FxStatus.VERIFY_BOTTOM or
                              fx.type == FxStatus.VERIFY_TOP)
                bi_type = BiType.VERIFY_UP if has_verify else BiType.UP
                ret_bi = BI(self.start_fx, fx, bi_type, self.no)
                self.start_fx = fx
                self.no += 1

        return ret_bi

    def _update_last_bi(self, fx: FX):
        # 修复：使用 end 而非 stop_fx
        ret_bi = None
        if len(self.bilist) == 0:
            return ret_bi

        last_bi = self.bilist[-1]
        end_fx = last_bi.end  # 修复：stop_fx → end
        if fx.type == FxStatus.TOP and fx.val > end_fx.val:
            ret_bi = BI(last_bi.start, fx, BiType.UP, last_bi.index)
            self.bilist.pop()
            self.bilist.append(ret_bi)
            self.start_fx = fx
        elif fx.type == FxStatus.BOTTOM and fx.val < end_fx.val:
            ret_bi = BI(last_bi.start, fx, BiType.DOWN, last_bi.index)
            self.bilist.pop()
            self.bilist.append(ret_bi)
            self.start_fx = fx
        elif fx.type == FxStatus.VERIFY_TOP and fx.val > end_fx.val:
            ret_bi = BI(last_bi.start, fx, BiType.VERIFY_UP, last_bi.index)
            self.bilist.pop()
            self.bilist.append(ret_bi)
            self.start_fx = fx
        elif fx.type == FxStatus.VERIFY_BOTTOM and fx.val < end_fx.val:
            ret_bi = BI(last_bi.start, fx, BiType.VERIFY_DOWN, last_bi.index)
            self.bilist.pop()
            self.bilist.append(ret_bi)
            self.start_fx = fx
        return ret_bi

    def handle(self, fxlist: list[FX]):
        bilist = []
        if len(fxlist) == 0:
            return bilist
        self.start_fx = fxlist[0]  # 初始化 self.start_fx
        for fx in fxlist[1:]:
            bi = self.find_bi(fx)
            if bi is not None:
                bilist.append(bi)
        return bilist

if __name__ == '__main__':
    src_klines = get_src_klines('SZ.300491', 'd', '2026-01-09 11:30:00')
    cl_klines = get_cl_lines(src_klines)
    fx_proc = FX_PROCESS()
    fxlist = fx_proc.find_fenxing(cl_klines)
    bi_process = BI_Process()
    bilist = bi_process.handle(fxlist)
    for bi in bilist:
        print(bi)
