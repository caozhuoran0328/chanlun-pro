from chanlun.backtesting.base import *
from chanlun.get_bi import BiType
from chanlun.get_xd import XianDuanType

class MyStrategy(Strategy):
    def __init__():
        pass

    # 计算仓位
    def caculate_position():
        pass

    def open(self, code, market_data: MarketDatas, poss: Dict[str, POSITION]) -> List[Operation]:
        opts = []
        cd_30m = market_data.get_cl_data(code, '30m')
        xds = cd_30m.get_xds()
        # 查找是否符合类2买
        middle_xd = xds[-1]
        if middle_xd.type in [XianDuanType.DOWN, XianDuanType.VERIFY_DOWN]:
            left_xd = xds[-3]
            start_xd = xds[-4]
            if left_xd.low > start_xd.low and middle_xd.low > start_xd.low:
                cd_1m = market_data.get_cl_data(code, '1m')
                mmd_1m = cd_1m.get_mmds()
                for mmd in mmd_1m:
                    if "buy" in mmd_1m:
                        opts.append(
                            code = code,
                            opt="buy",
                            mmd=mmd,
                            loss_price = 

                        )
        return opts



    def close(self, code, mmd:str, pos: POSITION, market_data:MarketDatas) -> [Operation, None, List[Operation]]:
        pass
