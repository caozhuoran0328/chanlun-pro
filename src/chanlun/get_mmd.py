# -*- coding: utf-8 -*-
"""
买卖点计算模块

按照缠论108课标准，计算三类买卖点：
    - 1buy / 1sell (第一类买卖点): 趋势背驰后的转折点
    - 2buy / 2sell (第二类买卖点): 对第一类买卖点的回抽确认
    - 3buy / 3sell (第三类买卖点): 对中枢的突破回抽确认

MMD 计算依赖中枢(ZS)和背驰(BC)信息，需在 ZS 和 BC 计算之后执行。
"""
from typing import List, Union

from chanlun.cl_interface import (
    BI,
    ICL,
    LINE,
    XD,
    ZS,
    BiType,
)


def _is_down(line: Union[BI, XD, LINE]) -> bool:
    """判断线是否为下降方向"""
    t = line.type
    if isinstance(t, BiType):
        return t in (BiType.DOWN, BiType.VERIFY_DOWN)
    return str(t).lower() in ("down", "下", "xia", "下降笔", "下降线段")


def _is_up(line: Union[BI, XD, LINE]) -> bool:
    """判断线是否为上升方向"""
    t = line.type
    if isinstance(t, BiType):
        return t in (BiType.UP, BiType.VERIFY_UP)
    return str(t).lower() in ("up", "上", "shang", "上升笔", "上升线段")


def _get_prev_same_dir(line: Union[BI, XD], lines: List[Union[BI, XD]], idx: int):
    """获取前一个同方向的线"""
    for i in range(idx - 1, -1, -1):
        prev = lines[i]
        if _is_up(line) and _is_up(prev):
            return prev, i
        if _is_down(line) and _is_down(prev):
            return prev, i
    return None, -1


def _get_prev_reverse_dir(line: Union[BI, XD], lines: List[Union[BI, XD]], idx: int):
    """获取前一个反方向的线 (if current is down, find previous up)"""
    for i in range(idx - 1, -1, -1):
        prev = lines[i]
        if _is_up(line) and _is_down(prev):
            return prev, i
        if _is_down(line) and _is_up(prev):
            return prev, i
    return None, -1


def _line_has_mmd(line: Union[BI, XD], mmd_name: str, zs_type: str = None) -> bool:
    """检查 line 是否已包含指定买卖点"""
    return mmd_name in line.line_mmds(zs_type)


def compute_mmd(
    cd: ICL,
    line: Union[BI, XD],
    lines: List[Union[BI, XD]],
    zss: List[ZS],
    idx: int,
    zs_type: str = None,
) -> None:
    """
    为单条线计算买卖点

    在已有 ZS 和 BC 信息的基础上，检查当前 line 是否构成买卖点。

    Args:
        cd: 缠论数据对象 (ICL 实例，提供 get_idx() 等方法)
        line: 当前需要检查的线 (BI 或 XD)
        lines: 所有同级别线的列表
        zss: 当前级别所有中枢的列表
        idx: 当前 line 在 lines 中的位置索引
        zs_type: 中枢类型标记字符串
    """
    if zs_type is None:
        zs_type = ""

    if idx < 2 or len(zss) == 0:
        return

    # 找到在当前 line 之前形成的中枢
    prev_zss = [zs for zs in zss if hasattr(zs, "lines") and len(zs.lines) > 0]

    # ---- 第一类买点 (1buy) ----
    if _is_down(line) and prev_zss:
        _check_1buy(line, lines, prev_zss, idx, zs_type, cd)

    # ---- 第二类买点 (2buy) ----
    if _is_down(line) and prev_zss:
        _check_2buy(line, lines, prev_zss, idx, zs_type)

    # ---- 第三类买点 (3buy) ----
    if _is_down(line) and prev_zss:
        _check_3buy(line, lines, prev_zss, idx, zs_type)

    # ---- 第一类卖点 (1sell) ----
    if _is_up(line) and prev_zss:
        _check_1sell(line, lines, prev_zss, idx, zs_type, cd)

    # ---- 第二类卖点 (2sell) ----
    if _is_up(line) and prev_zss:
        _check_2sell(line, lines, prev_zss, idx, zs_type)

    # ---- 第三类卖点 (3sell) ----
    if _is_up(line) and prev_zss:
        _check_3sell(line, lines, prev_zss, idx, zs_type)


def _check_1buy(line, lines, prev_zss, idx, zs_type, cd):
    """
    第一类买点: 下跌趋势末端，背驰后形成的最低点。

    条件:
        1. 当前为下降笔
        2. 当前低点低于所有之前中枢的下沿(dd)之上方... 
           （即价格在趋势下跌中创新低）
        3. 存在背驰（由 BC 模块计算的结果判断）
    """
    # 检查当前 line 是否有背驰标记
    bcs = line.line_bcs(zs_type)
    has_bc = any(bc in bcs for bc in ("pz", "qs", "bi", "xd"))

    # 检查是否在趋势末端创新低
    if not has_bc:
        return

    # 价格至少低于最近一个中枢的下沿
    last_zs = prev_zss[-1]
    if line.low >= last_zs.dd:
        return

    # 前面的同方向线存在向上的（之前是下跌趋势末端）
    prev_same, _ = _get_prev_same_dir(line, lines, idx)
    if prev_same is None:
        return

    line.add_mmd("1buy", last_zs, zs_type, msg="第一类买点: 下跌趋势背驰后创新低")


def _check_2buy(line, lines, prev_zss, idx, zs_type):
    """
    第二类买点: 1buy 后的回抽确认低点，不跌破 1buy 低点。

    条件:
        1. 当前为下降笔
        2. 前一个同方向笔有 1buy
        3. 当前低点未跌破 1buy 低点
    """
    prev_same, _ = _get_prev_same_dir(line, lines, idx)
    if prev_same is None:
        return

    if not _line_has_mmd(prev_same, "1buy", zs_type):
        return

    if line.low < prev_same.low:
        return

    last_zs = prev_zss[-1]
    line.add_mmd("2buy", last_zs, zs_type, msg="第二类买点: 回抽不破一买低点")


def _check_3buy(line, lines, prev_zss, idx, zs_type):
    """
    第三类买点: 向上突破中枢后，回抽不跌破中枢上沿(zg)。

    条件:
        1. 当前为下降笔
        2. 前一个上升笔的高点突破了最近中枢的上沿(zg)
        3. 当前下降笔的低点高于中枢上沿(zg)
    """
    if idx < 1:
        return

    prev_rev, _ = _get_prev_reverse_dir(line, lines, idx)
    if prev_rev is None:
        return

    last_zs = prev_zss[-1]
    if not hasattr(last_zs, "zg"):
        return

    # 前一个反向笔（上升）需要突破中枢上沿
    if prev_rev.high <= last_zs.zg:
        return

    # 当前下降笔的低点需在中枢上沿之上
    if line.low <= last_zs.zg:
        return

    line.add_mmd("3buy", last_zs, zs_type, msg="第三类买点: 突破中枢后回抽不破 zg")


def _check_1sell(line, lines, prev_zss, idx, zs_type, cd):
    """
    第一类卖点: 上涨趋势末端，背驰后形成的最高点。
    """
    bcs = line.line_bcs(zs_type)
    has_bc = any(bc in bcs for bc in ("pz", "qs", "bi", "xd"))

    if not has_bc:
        return

    last_zs = prev_zss[-1]
    if line.high <= last_zs.gg:
        return

    prev_same, _ = _get_prev_same_dir(line, lines, idx)
    if prev_same is None:
        return

    line.add_mmd("1sell", last_zs, zs_type, msg="第一类卖点: 上涨趋势背驰后创新高")


def _check_2sell(line, lines, prev_zss, idx, zs_type):
    """
    第二类卖点: 1sell 后的回抽确认高点，不突破 1sell 高点。
    """
    prev_same, _ = _get_prev_same_dir(line, lines, idx)
    if prev_same is None:
        return

    if not _line_has_mmd(prev_same, "1sell", zs_type):
        return

    if line.high > prev_same.high:
        return

    last_zs = prev_zss[-1]
    line.add_mmd("2sell", last_zs, zs_type, msg="第二类卖点: 反弹不破一卖高点")


def _check_3sell(line, lines, prev_zss, idx, zs_type):
    """
    第三类卖点: 向下突破中枢后，反弹不突破中枢下沿(zd)。
    """
    if idx < 1:
        return

    prev_rev, _ = _get_prev_reverse_dir(line, lines, idx)
    if prev_rev is None:
        return

    last_zs = prev_zss[-1]
    if not hasattr(last_zs, "zd"):
        return

    if prev_rev.low >= last_zs.zd:
        return

    if line.high >= last_zs.zd:
        return

    line.add_mmd("3sell", last_zs, zs_type, msg="第三类卖点: 跌破中枢后反弹不破 zd")


def compute_all_mmds(
    cd: ICL,
    lines: List[Union[BI, XD]],
    zss: List[ZS],
    zs_type: str = None,
    config: dict = None,
) -> None:
    """
    为所有线批量计算买卖点

    Args:
        cd: 缠论数据对象
        lines: 线列表 (BI 或 XD)
        zss: 中枢列表
        zs_type: 中枢类型
        config: 缠论配置字典 (Phase 4 config propagation)
    """
    if config is None:
        config = {}
    if len(lines) < 3 or len(zss) == 0:
        return

    for i, line in enumerate(lines):
        if i < 2:
            continue
        compute_mmd(cd, line, lines, zss, i, zs_type)
