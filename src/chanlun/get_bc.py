# -*- coding: utf-8 -*-
"""
背驰计算模块

按照缠论108课标准，提供三类背驰判断：
    - 盘整背驰 (pz): 中枢内部，离开段力度小于进入段
    - 趋势背驰 (qs): 两个同向中枢形成趋势后，离开段力度衰减
    - 线背驰 (bi/xd): 相邻同向线段的力度比较

背驰判断基于 MACD 力度 (柱子面积) 比较，使用 cl_interface 中的
    query_macd_ld() 和 compare_ld_beichi() 辅助函数。
"""
from typing import List, Tuple, Union

from chanlun.cl_interface import (
    BI,
    ICL,
    LINE,
    XD,
    ZS,
    BiType,
    compare_ld_beichi,
    query_macd_ld,
)

from chanlun.get_zs import zss_is_qs


def _get_direction(line: Union[LINE, BI, XD]) -> str:
    """获取线的方向: 'up' 或 'down'"""
    t = line.type
    if isinstance(t, BiType):
        if t in (BiType.UP, BiType.VERIFY_UP):
            return "up"
        return "down"
    s = str(t).lower()
    if s in ("up", "shang"):
        return "up"
    return "down"


def beichi_pz(
    cd: ICL,
    zs: ZS,
    now_line: Union[LINE, BI, XD],
) -> Tuple[bool, Union[LINE, BI, XD, None]]:
    """
    判断中枢与指定线是否构成盘整背驰

    盘整背驰: 当前离开段与中枢进入段的 MACD 力度比较。
    如果离开段力度 < 进入段力度，则构成盘整背驰。

    比较对象:
        - zs.lines[-2]: 中枢中与 now_line 同方向的倒数第二段（进入段）
        - now_line: 当前离开段

    Args:
        cd: 缠论数据对象 (需要 get_idx() 提供 MACD 数据)
        zs: 中枢对象 (需包含 lines 列表)
        now_line: 当前需要比较的线 (离开段)

    Returns:
        (is_bc, compare_line)
        - is_bc: 是否构成盘整背驰
        - compare_line: 用于比较的线（zs.lines 中与 now_line 同方向的段）
    """
    if zs is None or now_line is None:
        return False, None

    if not hasattr(zs, "lines") or len(zs.lines) < 2:
        return False, None

    now_dir = _get_direction(now_line)

    # 在中枢 lines 中找与 now_line 同方向的前一段
    compare_line = None
    for ln in reversed(zs.lines):
        if ln is now_line:
            continue
        if _get_direction(ln) == now_dir:
            compare_line = ln
            break

    if compare_line is None:
        return False, None

    # 计算 MACD 力度
    try:
        one_ld = compare_line.get_ld(cd)
        two_ld = now_line.get_ld(cd)
    except Exception:
        return False, None

    # 比较力度
    is_bc = compare_ld_beichi(one_ld, two_ld, now_dir)
    return is_bc, compare_line


def beichi_qs(
    cd: ICL,
    lines: List[Union[LINE, BI, XD]],
    zss: List[ZS],
    now_line: Union[LINE, BI, XD],
    config: Union[dict, None] = None,
) -> Tuple[bool, List[Union[LINE, BI, XD]]]:
    """
    判断是否构成趋势背驰

    趋势背驰: 当两个同向中枢形成趋势后，离开第二个中枢的线段力度
    衰减，即构成趋势背驰。

    判断流程:
        1. 取最后两个中枢
        2. 检查两个中枢是否构成趋势 (zss_is_qs)
        3. 若构成趋势，检查 now_line 与第二个中枢的进入段是否存在背驰

    Args:
        cd: 缠论数据对象
        lines: 同级别线列表
        zss: 中枢列表
        now_line: 当前线 (离开段)
        config: 配置字典

    Returns:
        (is_bc, compare_lines)
        - is_bc: 是否趋势背驰
        - compare_lines: 用于比较的相关线列表
    """
    if len(zss) < 2 or now_line is None:
        return False, []

    one_zs, two_zs = zss[-2], zss[-1]

    # 判断两个中枢是否形成趋势
    qs_dir, _ = zss_is_qs(one_zs, two_zs, config)
    if qs_dir is None:
        return False, []

    # 检查趋势方向是否与当前线方向匹配
    now_dir = _get_direction(now_line)
    if (qs_dir == "up" and now_dir != "up") or (qs_dir == "down" and now_dir != "down"):
        return False, []

    # 在第二个中枢中检查盘整背驰
    bc, _ = beichi_pz(cd, two_zs, now_line)

    # 收集用于比较的线
    compare_lines: List[Union[LINE, BI, XD]] = []
    if hasattr(two_zs, "lines"):
        for ln in two_zs.lines:
            if ln is not None and _get_direction(ln) == now_dir:
                compare_lines.append(ln)

    return bc, compare_lines


def compute_line_bc(
    cd: ICL,
    line: Union[BI, XD],
    lines: List[Union[BI, XD]],
    idx: int,
) -> Tuple[bool, Union[LINE, BI, XD, None]]:
    """
    判断相邻同向线段是否构成笔/线段背驰

    比较当前线与前一个同方向的线，检查力度是否衰减。

    Args:
        cd: 缠论数据对象
        line: 当前线
        lines: 同级别线列表
        idx: 当前 line 在 lines 中的位置

    Returns:
        (is_bc, compare_line)
    """
    if idx < 2:
        return False, None

    now_dir = _get_direction(line)

    # 找前一个同方向的线
    compare_line = None
    for j in range(idx - 1, -1, -1):
        prev = lines[j]
        if _get_direction(prev) == now_dir:
            compare_line = prev
            break

    if compare_line is None:
        return False, None

    # 比较 MACD 力度
    try:
        one_ld = compare_line.get_ld(cd)
        two_ld = line.get_ld(cd)
    except Exception:
        return False, None

    is_bc = compare_ld_beichi(one_ld, two_ld, now_dir)
    return is_bc, compare_line


def compute_all_bcs(
    cd: ICL,
    lines: List[Union[BI, XD]],
    zss: List[ZS],
    zs_type: str,
    config: Union[dict, None] = None,
) -> None:
    """
    为所有线批量计算背驰

    对每条线依次计算:
        1. 盘整背驰 (pz): 比较该线与所在中枢的进入段
        2. 趋势背驰 (qs): 若存在趋势中枢，比较离开段力度
        3. 线背驰 (bi/xd): 与前一同方向线比较

    Args:
        cd: 缠论数据对象
        lines: 线列表
        zss: 中枢列表
        zs_type: 中枢类型标记 ('bi' 或 'xd')
        config: 配置字典
    """
    if len(lines) < 2:
        return

    for i, line in enumerate(lines):
        if i < 1:
            continue

        # 1. 线背驰 — 与前一同向线比较
        line_bc, line_cmp = compute_line_bc(cd, line, lines, i)
        if line_bc and line_cmp is not None:
            bc_type = "bi" if isinstance(line, BI) else "xd"
            line.add_bc(bc_type, None, line_cmp, [], True, zs_type)

        # 2. 盘整背驰 — 与所在中枢的进入段比较
        if zss:
            pz_bc, pz_cmp = beichi_pz(cd, zss[-1] if zss else None, line)
            if pz_bc and pz_cmp is not None:
                line.add_bc("pz", zss[-1], pz_cmp, [], True, zs_type)

        # 3. 趋势背驰 — 两个中枢形成趋势
        if len(zss) >= 2:
            qs_bc, qs_lines = beichi_qs(cd, lines, zss, line, config)
            if qs_bc:
                line.add_bc("qs", zss[-1], None, qs_lines, True, zs_type)
