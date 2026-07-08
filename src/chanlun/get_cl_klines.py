import pandas as pd
from chanlun.cl_interface import Kline, CLKline
from enum import Enum
from datetime import datetime
from chanlun.get_src_klines import get_src_klines

class Direction(Enum):
    UP = 1
    DOWN = -1
    NONE = 0


def _has_containment(k1, k2) -> bool:
    """检查两根K线是否存在包含关系"""
    return ((k2['h'] >= k1['h'] and k2['l'] <= k1['l']) or
            (k1['h'] >= k2['h'] and k1['l'] <= k2['l']))


def _find_first_non_containment_direction(klines) -> Direction:
    """从首对无包含K线确定方向"""
    for i in range(len(klines) - 1):
        k1 = klines.iloc[i]
        k2 = klines.iloc[i + 1]
        if not _has_containment(k1, k2):
            return Direction.UP if k2['h'] > k1['h'] else Direction.DOWN
    return Direction.UP  # 全部包含，默认向上


def get_cl_lines(klines, config: dict = None, debug=False):
    """
    处理K线包含关系，生成缠论K线

    - 方向初始化：从首对无包含K线确定方向
    - 缺口检测：设置 CLKline._q = True
    - 设置 up_qs 属性
    - 修复末尾K线丢失

    Args:
        klines: K线 DataFrame
        config: 缠论配置字典 (Phase 4 config propagation)
        debug: 调试模式
    """
    if config is None:
        config = {}
    if len(klines) == 0:
        return pd.DataFrame()

    # 只有一根K线时直接返回
    if len(klines) == 1:
        k = klines.iloc[0]
        cl = CLKline(0, k['date'], k['h'], k['l'], k['o'], k['c'], k['a'], [], 0, 0)
        data = [vars(cl)]
        return pd.DataFrame(data)

    # 从首对无包含K线确定方向
    direction = _find_first_non_containment_direction(klines)
    if debug:
        print(f"[DEBUG] 初始方向: {direction}")

    # 取出第一根 K 线
    last_kline = klines.iloc[0].copy()
    # 初始化保留的 K 线列表
    ret_cl_klines = []
    cl_klines = []
    cl_num = 0

    # 遍历除第一根 K 线外的其他 K 线
    for i in range(1, len(klines)):
        current_kline = klines.iloc[i].copy()
        current_kline_high = current_kline['h']
        current_kline_low = current_kline['l']
        last_kline_high = last_kline['h']
        last_kline_low = last_kline['l']

        # 情况 1：当前 K 线包含上一个 K 线
        if current_kline_high >= last_kline_high and current_kline_low <= last_kline_low:
            if direction == Direction.UP:
                current_kline['l'] = last_kline_low
                current_kline['up_qs'] = 'up'
            elif direction == Direction.DOWN:
                current_kline['h'] = last_kline_high
                current_kline['up_qs'] = 'down'
            if len(cl_klines) == 0:
                cl_klines.append(last_kline)
            last_kline = current_kline
            cl_klines.append(current_kline)
        # 情况 2：上一个 K 线包含当前 K 线
        elif last_kline_high >= current_kline_high and last_kline_low <= current_kline_low:
            if direction == Direction.UP:
                last_kline['l'] = current_kline_low
                last_kline['up_qs'] = 'up'
            elif direction == Direction.DOWN:
                last_kline['h'] = current_kline_high
                last_kline['up_qs'] = 'down'
            if len(cl_klines) == 0:
                cl_klines.append(last_kline)
            cl_klines.append(current_kline)
        # 情况 3：不包含关系
        else:
            # 缺口检测：前后K线没有重叠即为缺口
            has_qk = (last_kline_high < current_kline_low or last_kline_low > current_kline_high)
            if debug and has_qk:
                date_str = last_kline['date'].strftime('%Y-%m-%d %H:%M:%S')
                print(f"[DEBUG] 缺口检测: {date_str} h={last_kline_high} l={last_kline_low} -> h={current_kline_high} l={current_kline_low}")

            cl = CLKline(
                cl_num,
                last_kline['date'],
                last_kline['h'], last_kline['l'],
                last_kline['o'], last_kline['c'],
                last_kline['a'],
                cl_klines, i,
                len(cl_klines),
                _q=has_qk
            )
            ret_cl_klines.append(cl)
            cl_klines = []
            last_kline = current_kline
            # 根据当前 K 线和上一个 K 线的高点关系更新方向
            if current_kline_high > last_kline_high:
                direction = Direction.UP
            else:
                direction = Direction.DOWN
            cl_num += 1

    # 始终添加最后一根 K 线（修复末尾K线丢失）
    last_qk = False
    cl = CLKline(
        cl_num,
        last_kline['date'],
        last_kline['h'], last_kline['l'],
        last_kline['o'], last_kline['c'],
        last_kline['a'],
        cl_klines, len(klines) - 1,
        len(cl_klines),
        _q=last_qk
    )
    ret_cl_klines.append(cl)

    data = [vars(cl) for cl in ret_cl_klines]
    df = pd.DataFrame(data)
    return df


def verify_bh(cl_klines, debug=False):
    """
    验证包含处理是否正确，检查是否存在包含关系
    debug=True 时输出所有验证结果
    """
    if 'date' not in cl_klines.columns:
        return True
    last_kline = cl_klines.iloc[0].copy()
    all_ok = True
    for i in range(1, len(cl_klines)):
        cur_kline = cl_klines.iloc[i].copy()
        if cur_kline['h'] >= last_kline['h'] and cur_kline['l'] <= last_kline['l']:
            if debug:
                print(f'[DEBUG] 包含错误(当前包含上一个): {cur_kline["date"]}')
            else:
                print(f'错误出现：{cur_kline["date"]}')
            all_ok = False
        elif last_kline['h'] >= cur_kline['h'] and last_kline['l'] <= cur_kline['l']:
            if debug:
                print(f'[DEBUG] 包含错误(上一个包含当前): {cur_kline["date"]}')
            else:
                print(f'错误出现：{cur_kline["date"]}')
            all_ok = False
        last_kline = cur_kline
    if debug and all_ok:
        print(f'[DEBUG] verify_bh: 全部通过 ({len(cl_klines)} 根K线)')
    return all_ok


if __name__ == "__main__":
    src_klines = get_src_klines("SH.601698", "d", "2024-09-08")
    ret_cl_klines = get_cl_lines(src_klines, debug=True)
    print(ret_cl_klines)
    verify_bh(ret_cl_klines, debug=True)
