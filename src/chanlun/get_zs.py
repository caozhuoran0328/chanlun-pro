# -*- coding: utf-8 -*-
"""
中枢计算模块

提供线段内中枢（段内中枢）的识别与创建功能。
按照缠论108课标准：至少三段连续的、有重叠区间的笔/线段构成中枢。

核心算法:
- create_dn_zs: 滑动窗口识别重叠线段，生成中枢列表
- zss_is_qs: 判断两个中枢是否构成趋势（上涨/下跌）
"""
from typing import List, Tuple, Union

from chanlun.cl_interface import BI, LINE, XD, Config, ZS


def create_dn_zs(
    zs_type: str,
    lines: List[LINE],
    max_line_num: int = 999,
    zs_include_last_line: bool = True,
    config: dict = None,
) -> List[ZS]:
    """
    创建段内中枢

    算法说明:
        取连续至少三段线段。第1段与第3段方向相同，其重叠区间定义中枢范围：
            zg = min(high[0], high[2])
            zd = max(low[0], low[2])
        若 zg > zd 则形成有效中枢。
        此后每增加一段同方向线段，更新 zg/zd 并检查重叠是否延续。

    Args:
        zs_type: 中枢类型 'bi' 或 'xd'
        lines: 笔(BI)或线段(XD)列表
        max_line_num: 单个中枢最多包含的线段数
        zs_include_last_line: 最后一个中枢是否包含最后一笔
        config: 缠论配置字典 (Phase 4 config propagation)

    Returns:
        List[ZS]: 中枢对象列表
    """
    if config is None:
        config = {}
    if len(lines) < 3:
        return []

    zss: List[ZS] = []
    i = 0

    while i <= len(lines) - 3:
        # 取三段线
        l0, l1, l2 = lines[i], lines[i + 1], lines[i + 2]

        # 中枢区间由第1段和第3段（同方向）的高/低点确定
        zg = min(l0.high, l2.high)
        zd = max(l0.low, l2.low)

        if zg <= zd:
            # 无重叠，不构成中枢
            i += 1
            continue

        gg = max(l0.high, l1.high, l2.high)
        dd = min(l0.low, l1.low, l2.low)

        zs = ZS(
            zs_type=zs_type,
            start=l0.start,
            end=l2.end,
            zg=zg,
            zd=zd,
            gg=gg,
            dd=dd,
            index=len(zss),
            line_num=3,
        )
        zs.done = True
        zs.real = True
        zs.add_line(l0)
        zs.add_line(l1)
        zs.add_line(l2)

        # 尝试扩展中枢：后续每添加一段，检查重叠是否依然有效
        j = i + 3
        while j < len(lines) and zs.line_num < max_line_num:
            next_line = lines[j]

            # 扩展时，只更新同方向（进入段/离开段）线段对 zg/zd 的影响
            # 偶数偏移（0,2,4...）的线段为进入/离开方向
            rel_idx = j - i
            if rel_idx % 2 == 0:
                new_zg = min(zg, next_line.high)
                new_zd = max(zd, next_line.low)
            else:
                new_zg = zg
                new_zd = zd

            # 判断是否仍然重叠
            if new_zg > new_zd or (zs_include_last_line and j == len(lines) - 1):
                zs.add_line(next_line)
                zs.end = next_line.end
                zs.gg = max(zs.gg, next_line.high)
                zs.dd = min(zs.dd, next_line.low)
                zs.line_num += 1
                zg, zd = new_zg, new_zd
                j += 1
            else:
                break

        zss.append(zs)
        i = j  # 跳过已被当前中枢覆盖的线段

    # 结果数量限制
    if len(zss) > max_line_num:
        zss = zss[-max_line_num:]

    return zss


def zss_is_qs(
    one_zs: ZS,
    two_zs: ZS,
    config: Union[dict, None] = None,
) -> Tuple[Union[str, None], None]:
    """
    判断两个中枢是否形成趋势

    根据配置中的 ZS_WZGX_TYPE 比较两个中枢的位置关系:
        - ZS_WZGX_ZGD (默认): 一分型 gg < 二分型 dd → 向上趋势
                              一分型 dd > 二分型 gg → 向下趋势
        - ZS_WZGX_ZGGDD:      一分型 zg < 二分型 dd → 向上趋势
                              一分型 zd > 二分型 zg → 向下趋势
        - ZS_WZGX_GD (严格):  一分型 gg < 二分型 dd → 向上趋势
                              一分型 dd > 二分型 gg → 向下趋势

    Args:
        one_zs: 第一个中枢
        two_zs: 第二个中枢
        config: 配置字典，可选 ZS_WZGX_TYPE 字段

    Returns:
        ('up', None)     向上趋势
        ('down', None)   向下趋势
        (None, None)     无趋势关系
    """
    if one_zs is None or two_zs is None:
        return (None, None)

    compare_type = (
        config.get("ZS_WZGX_TYPE", Config.ZS_WZGX_ZGD.value)
        if config
        else Config.ZS_WZGX_ZGD.value
    )

    if compare_type == Config.ZS_WZGX_ZGD.value:
        # 默认：比较 gg vs dd
        if one_zs.gg < two_zs.dd:
            return ("up", None)
        if one_zs.dd > two_zs.gg:
            return ("down", None)
    elif compare_type == Config.ZS_WZGX_ZGGDD.value:
        # 较宽松：比较 zg vs dd / zd vs zg
        if one_zs.zg < two_zs.dd:
            return ("up", None)
        if one_zs.zd > two_zs.zg:
            return ("down", None)
    elif compare_type == Config.ZS_WZGX_GD.value:
        # 严格：比较 gg vs dd
        if one_zs.gg < two_zs.dd:
            return ("up", None)
        if one_zs.dd > two_zs.gg:
            return ("down", None)

    return (None, None)


def get_last_zs(zss: List[ZS], zs_type: str = None) -> Union[ZS, None]:
    """
    获取最后一个中枢

    Args:
        zss: 中枢列表
        zs_type: 可选，按类型过滤

    Returns:
        最后一个匹配的中枢，或 None
    """
    if not zss:
        return None
    if zs_type is not None:
        for zs in reversed(zss):
            if zs.zs_type == zs_type:
                return zs
        return None
    return zss[-1]


def get_last_zs_by_level(zss: List[ZS], level: int = 0) -> Union[ZS, None]:
    """
    按级别获取最后一个中枢

    Args:
        zss: 中枢列表
        level: 中枢级别 (0=本级别, 1=上一级别...)

    Returns:
        最后一个匹配级别的中枢，或 None
    """
    for zs in reversed(zss):
        if zs.level == level:
            return zs
    return None
