from abc import ABCMeta, abstractmethod
from chanlun.cl_interface import ICL, Config, Kline, CLKline, FX, BI, XD, ZS, LINE
from typing import List, Union, Tuple
import datetime
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
from chanlun.get_src_klines import get_src_klines, convert_src_klines
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process
from chanlun.get_xd import XD_Process
from chanlun.get_zs import create_dn_zs as create_dn_zs_fn, zss_is_qs as zss_is_qs_fn, get_last_zs
from chanlun.get_bc import beichi_pz as beichi_pz_fn, beichi_qs as beichi_qs_fn, compute_all_bcs
from chanlun.get_mmd import compute_all_mmds
from chanlun.get_duokong_bi import Bi_DuoKong_Process
from chanlun.get_duokong_xd import XianDuan_DuoKong_Process

class CL(ICL):
    # 序列化版本号：当 CL 类结构变更导致 pickle 不兼容时，递增此版本号
    # 变更历史:
    #   1: 初始版本 (config 替代 cl_config, 新增 idx/bc/mmd 计算)
    PICKLE_VERSION: int = 1

    def __init__(self, code: str, frequency: str, config: Union[dict, None] = None, start_datetime: datetime.datetime = None):
        self.code = code
        self.frequency = frequency
        self.config = config if config is not None else {}
        self.start_datetime = start_datetime
        self.src_klines: List[Kline] = []
        self.cl_klines = []
        self.idx: dict = {}
        self.fxs: List[FX] = []
        self.bis: List[BI] = []
        self.xds: List[XD] = []
        self.zsds: List[XD] = []
        self.qsds: List[XD] = []
        self.bi_zss: List[ZS] = []
        self.xd_zss: List[ZS] = []
        self.zsd_zss: List[ZS] = []
        self.qsd_zss: List[ZS] = []
        self.dksd_xd_high: List[float] = []
        self.dksd_xd_low: List[float] = []
        self.dksd_bi_high: List[float] = []
        self.dksd_bi_low: List[float] = []
        self._pickle_version = CL.PICKLE_VERSION

    def __getstate__(self) -> dict:
        """确保 pickle 序列化时始终包含版本号"""
        state = self.__dict__.copy()
        state['_pickle_version'] = CL.PICKLE_VERSION
        return state

    def __setstate__(self, state):
        """
        兼容旧版本 pickle 对象：老代码将配置存储在 cl_config 中，新代码使用 config。
        从 pickle 反序列化时，如果 state 中有 cl_config 但没有 config，则自动迁移。
        """
        # 检查 pickle 版本号，版本不匹配时清除 state 中可能不兼容的数据字段
        stored_version = state.pop('_pickle_version', 0)

        self.__dict__.update(state)

        # 老版本 (version 0): cl_config → config 迁移
        # 仅当 config 不存在时才从 cl_config 迁移，避免覆盖已有的 config
        if stored_version < 1 and 'cl_config' in state:
            if 'config' not in self.__dict__:
                self.config = state['cl_config']
            # 清理旧属性避免重复序列化
            self.__dict__.pop('cl_config', None)

        # 确保 config 存在（兼容直接 unpickle 未触发 __setstate__ 的情况）
        if 'config' not in self.__dict__ and 'cl_config' in self.__dict__:
            self.config = self.__dict__['cl_config']
            del self.__dict__['cl_config']

        # 确保必需的基础属性存在（兼容从极旧版本加载）
        defaults = {
            'idx': {},
            'start_datetime': None,
            'fxs': [],
            'bis': [],
            'xds': [],
            'zsds': [],
            'qsds': [],
            'bi_zss': [],
            'xd_zss': [],
            'zsd_zss': [],
            'qsd_zss': [],
            'dksd_xd_high': [],
            'dksd_xd_low': [],
            'dksd_bi_high': [],
            'dksd_bi_low': []
        }
        for attr, default in defaults.items():
            if attr not in self.__dict__:
                self.__dict__[attr] = default

        self._pickle_version = CL.PICKLE_VERSION

    def process_klines(self, klines: pd.DataFrame):
        diag_ctx = f"[{self.code}/{self.frequency}]"
        logger.info(f"{diag_ctx} process_klines START: input rows={len(klines)}")

        # 兼容两种输入格式：原始交易所格式（有 'high' 列）或已转换格式（有 'h' 列）
        if 'high' in klines.columns:
            src_df = convert_src_klines(klines)
        else:
            src_df = klines
        logger.info(f"{diag_ctx} after convert: src_df rows={len(src_df)}")
        print(f"[CL-DIAG] {self.code} {self.frequency} convert={len(src_df)}")

        if len(self.src_klines) > 0:
            # 增量处理：只追加新的 K 线
            if isinstance(self.src_klines, pd.DataFrame):
                last_date = self.src_klines['date'].iloc[-1]
            else:
                last_date = self.src_klines[-1]['date']
            src_df = src_df[src_df['date'] > last_date]
            logger.info(f"{diag_ctx} incremental: new rows={len(src_df)}")
            if len(src_df) == 0:
                logger.info(f"{diag_ctx} process_klines SKIP: no new klines")
                return self
            self.src_klines = pd.concat([self.src_klines, src_df], ignore_index=True)
        else:
            self.src_klines = src_df

        logger.info(f"{diag_ctx} src_klines total: {len(self.src_klines)}")
        print(f"[CL-DIAG] {self.code} {self.frequency} src_klines={len(self.src_klines)}")
        self.cl_klines = get_cl_lines(self.src_klines, config=self.config)
        logger.info(f"{diag_ctx} after get_cl_lines: cl_klines={len(self.cl_klines)}")
        print(f"[CL-DIAG] {self.code} {self.frequency} cl_klines={len(self.cl_klines)}")

        fx_proc = FX_PROCESS(config=self.config)
        self.fxs = fx_proc.find_fenxing(self.cl_klines)
        logger.info(f"{diag_ctx} after find_fenxing: fxs={len(self.fxs)}")
        print(f"[CL-DIAG] {self.code} {self.frequency} fxs={len(self.fxs)}")

        bi_process = BI_Process(config=self.config)
        self.bis = bi_process.handle(self.fxs)
        logger.info(f"{diag_ctx} after BI_Process: bis={len(self.bis)}")
        print(f"[CL-DIAG] {self.code} {self.frequency} bis={len(self.bis)}")

        xd_process = XD_Process(config=self.config)
        self.xds = xd_process.handle(self.bis)
        logger.info(f"{diag_ctx} after XD_Process: xds={len(self.xds)}")
        print(f"[CL-DIAG] {self.code} {self.frequency} xds={len(self.xds)}")

        # 计算多空隧道
        bi_dk_proc = Bi_DuoKong_Process()
        self.dksd_bi_high, self.dksd_bi_low = bi_dk_proc._compute_dk_sequences(self.bis, self.src_klines)

        xd_dk_proc = XianDuan_DuoKong_Process()
        self.dksd_xd_high, self.dksd_xd_low = xd_dk_proc._compute_dk_sequences(self.xds, self.src_klines)

        compute_all_mmds(self.src_klines, self.dksd_bi_high, self.dksd_bi_low, self.dksd_xd_high, self.dksd_xd_low)


        return self

    def _calc_idx(self):
        """计算 MACD(12, 26, 9) 指标"""
        if len(self.src_klines) == 0:
            self.idx = {'macd': {'dif': [], 'dea': [], 'hist': []}}
            return
        closes = self.src_klines['c']
        ema_fast = closes.ewm(span=12, adjust=False).mean()
        ema_slow = closes.ewm(span=26, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = 2 * (dif - dea)
        self.idx = {
            'macd': {
                'dif': dif.tolist(),
                'dea': dea.tolist(),
                'hist': hist.tolist(),
            }
        }

    def get_code(self) -> str:
        return self.code

    def get_frequency(self) -> str:
        return self.frequency

    def get_config(self) -> dict:
        return self.config

    def get_src_klines(self) -> List[Kline]:
        return self.src_klines

    def get_cl_klines(self) -> List[CLKline]:
        return self.cl_klines

    def get_klines(self) -> List[Kline]:
        return self.src_klines

    def get_idx(self) -> dict:
        return self.idx

    def get_fxs(self) -> List[FX]:
        return self.fxs

    def get_fx(self) -> Union[FX, None]:
        if len(self.fxs) > 0:
            return self.fxs[-1]
        return None

    def get_bis(self) -> List[BI]:
        return self.bis

    def get_xds(self) -> List[XD]:
        return self.xds

    def get_zsds(self) -> List[XD]:
        return self.zsds

    def get_qsds(self) -> List[XD]:
        return self.qsds

    def get_bi_zss(self, zs_type: str = None) -> List[ZS]:
        return self.bi_zss

    def get_xd_zss(self, zs_type: str = None) -> List[ZS]:
        return self.xd_zss

    def get_zsd_zss(self) -> List[ZS]:
        return self.zsd_zss

    def get_qsd_zss(self) -> List[ZS]:
        return self.qsd_zss

    def get_last_bi_zs(self) -> Union[ZS, None]:
        if len(self.bi_zss) > 0:
            return self.bi_zss[-1]
        return None

    def get_last_xd_zs(self) -> Union[ZS, None]:
        if len(self.xd_zss) > 0:
            return self.xd_zss[-1]
        return None

    def create_dn_zs(self, zs_type: str, lines: List[LINE], max_line_num: int = 999,
                     zs_include_last_line: bool = True) -> List[ZS]:
        """
        创建段内中枢

        代理到 get_zs.create_dn_zs() 实现。

        @param zs_type: 中枢类型：bi/xd
        @param lines: 线的列表
        @param max_line_num: 中枢最大线段数量
        @param zs_include_last_line: 是否包含最后一笔
        """
        return create_dn_zs_fn(zs_type, lines, max_line_num, zs_include_last_line, config=self.config)

    def beichi_pz(self, zs: ZS, now_line: LINE) -> Tuple[bool, Union[LINE, None]]:
        """
        判断中枢与指定线是否构成盘整背驰

        代理到 get_bc.beichi_pz() 实现。

        @param zs: 中枢
        @param now_line: 需要对比的线
        """
        return beichi_pz_fn(self, zs, now_line)

    def beichi_qs(self, lines: List[LINE], zss: List[ZS], now_line: LINE) -> Tuple[bool, List[LINE]]:
        """
        判断指定线与之前的中枢是否形成趋势背驰

        代理到 get_bc.beichi_qs() 实现。

        @param lines: 线的列表
        @param zss: 中枢列表
        @param now_line: 最后一个线
        """
        return beichi_qs_fn(self, lines, zss, now_line, self.config)

    def zss_is_qs(self, one_zs: ZS, two_zs: ZS) -> Tuple[str, None]:
        """
        判断两个中枢是否形成趋势

        代理到 get_zs.zss_is_qs() 实现。
        返回 'up' 向上趋势, 'down' 向下趋势, None 没有趋势
        """
        return zss_is_qs_fn(one_zs, two_zs, self.config)

    def get_duokong_bi(self) -> tuple:
        """获取笔级别多空隧道序列数据"""
        return self.dksd_bi_high, self.dksd_bi_low

    def get_duokong_suidao_xd(self) -> tuple:
        """获取线段级别多空隧道序列数据"""
        return self.dksd_xd_high, self.dksd_xd_low
