from chanlun.cl_interface import Kline
from chanlun.get_fx import FX_PROCESS
from chanlun.get_bi import BI_Process
from chanlun.get_xd import XD_Process
from chanlun.chanlun_bar import Chanlun_Bar_Process
from chanlun.get_duokong_bi import Bi_DuoKong_Process
from chanlun.get_duokong_xd import XianDuan_DuoKong_Process


def bar_process(bar: Kline, bi_dk_proc:Bi_DuoKong_Process, xd_dk_proc:XianDuan_DuoKong_Process):
    cl_bar = cl_process.get_cl_bar(bar)
    if cl_bar:
        fx_process = FX_PROCESS()
        fx = fx_process.find_fenxing(cl_bar)
        if fx:
            bi_process = BI_Process()
            bi = bi_process.find_bi(fx)
            if bi:
                bi_dk_proc.find_duokong_status(bi)
                xd = xd_process.find_xd(bi)
                if xd:
                    xd_duokong_process = XianDuan_DuoKong_Process()
                    xd_duokong_process.find_duokong_status(xd)
                else:
                    # 线段多空隧道处理
                    pass
            else:
                # 笔的多空隧道处理
                pass

