import pandas as pd
import numpy as np  
from typing import List, Dict, Any, NamedTuple
from chanlun.cl_interface import XD, XianDuanType
from chanlun.get_src_klines import get_src_klines
from chanlun.get_cl_klines import get_cl_lines
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process
from chanlun.get_xd import XD_Process
from chanlun.get_duokong_bi import Bi_DuoKong_Process
from chanlun.get_duokong_xd import XianDuan_DuoKong_Process

class Point(NamedTuple):
    date: str
    point_type: str
    price: float

class BuySellPoint:
    def __init__(self):
        self.points: List[Point] = []

    def add_point(self, date, point_type, price):
        self.points.append(Point(date, point_type, price))
        
    def __repr__(self):
        return f"BuySellPoint(total_points={len(self.points)})"


def compute_all_mmds(
    klines: pd.DataFrame, 
    bi_dk_high: List[Dict[str, Any]], 
    bi_dk_low: List[Dict[str, Any]], 
    xd_dk_high: List[Dict[str, Any]], 
    xd_dk_low: List[Dict[str, Any]],
    config=None
) -> BuySellPoint:
    
    if klines.empty:
        return BuySellPoint()

    df = klines.copy()
    if 'date' not in df.columns and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
        
    df['date'] = pd.to_datetime(df['date'])

    # 1. 映射轨道区间到 K 线轴
    def map_list_tunnel_to_klines(k_df, tunnel_list, name):
        if not tunnel_list:
            k_df[name] = np.nan
            return k_df
        
        tdf = pd.DataFrame(tunnel_list)
        tdf['start_date'] = pd.to_datetime(tdf['start_date'])
        tdf['stop_date'] = pd.to_datetime(tdf['stop_date'])
        
        k_df[name] = np.nan
        
        for _, row in tdf.iterrows():
            mask = (k_df['date'] >= row['start_date']) & (k_df['date'] <= row['stop_date'])
            k_df.loc[mask, name] = row['price']
            
        return k_df

    df = map_list_tunnel_to_klines(df, bi_dk_high, 'bi_high')
    df = map_list_tunnel_to_klines(df, bi_dk_low, 'bi_low')
    df = map_list_tunnel_to_klines(df, xd_dk_high, 'xd_high')
    df = map_list_tunnel_to_klines(df, xd_dk_low, 'xd_low')

    # 2. 计算当前行是否符合突破条件（返回布尔序列）
    bi_buy_cond  = df['h'] > df['bi_high']
    xd_buy_cond  = df['h'] > df['xd_high']
    bi_sell_cond = df['l'] < df['bi_low']
    xd_sell_cond = df['l'] < df['xd_low']

    # 3. 核心修改：通过配合 .shift() 寻找“第一次突破”的上升沿
    # 逻辑：当前行符合条件(True) 且 前一行不符合条件(False/NaN)，才算作第一次触发
    bi_buy_mask  = bi_buy_cond & (~bi_buy_cond.shift(1).fillna(False))
    xd_buy_mask  = xd_buy_cond & (~xd_buy_cond.shift(1).fillna(False))
    bi_sell_mask = bi_sell_cond & (~bi_sell_cond.shift(1).fillna(False))
    xd_sell_mask = xd_sell_cond & (~xd_sell_cond.shift(1).fillna(False))

    # 4. 收集结果
    result = BuySellPoint()
    
    for row in df[bi_buy_mask][['date', 'h']].to_dict(orient='records'):
        result.add_point(row['date'].strftime('%Y-%m-%d %H:%M:%S'), 'bi_buy', row['h'])
        
    for row in df[xd_buy_mask][['date', 'h']].to_dict(orient='records'):
        result.add_point(row['date'].strftime('%Y-%m-%d %H:%M:%S'), 'xd_buy', row['h'])
        
    for row in df[bi_sell_mask][['date', 'l']].to_dict(orient='records'):
        result.add_point(row['date'].strftime('%Y-%m-%d %H:%M:%S'), 'bi_sell', row['l'])
        
    for row in df[xd_sell_mask][['date', 'l']].to_dict(orient='records'):
        result.add_point(row['date'].strftime('%Y-%m-%d %H:%M:%S'), 'xd_sell', row['l'])

    return result

if __name__ == '__main__':
    src_klines = get_src_klines('SZ.300491', 'd', None)
    cl_klines = get_cl_lines(src_klines)
    fx_proc = FX_PROCESS()
    fxlist = fx_proc.find_fenxing(cl_klines)
    bi_process = BI_Process()
    bilist = bi_process.handle(fxlist)
    bi_process = BI_Process()
    xd_process = XD_Process()
    xdlist = xd_process.handle(bilist)
    bi_dk_process = Bi_DuoKong_Process()
    bi_dk_high, bi_dk_low = bi_dk_process._compute_dk_sequences(bilist, src_klines)
    xd_dk_process = XianDuan_DuoKong_Process()
    xd_dk_high, xd_dk_low = xd_dk_process._compute_dk_sequences(xdlist, src_klines)
    bs_list = compute_all_mmds(src_klines, bi_dk_high, bi_dk_low, xd_dk_high, xd_dk_low)
    for bs in bs_list.points:
        print(bs)