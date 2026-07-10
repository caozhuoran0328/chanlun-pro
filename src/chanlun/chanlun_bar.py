from enum import Enum
from chanlun.cl_interface import Kline

class DIRECTION(Enum):
    UP = '上'
    DOWN = '下'

class Chanlun_Bar_Status(Enum):
    pass

class Chanlun_Bar_Process:
    def __init__(self):
        self.last_bar = None
        self.Direction = DIRECTION.UP

    def get_cl_bar(self, bar: Kline):
        if not self.last_bar:
            self.last_bar = bar
            return None
        
        if bar.h >= self.last_bar.h and bar.l <= self.last_bar.l:
            # 后包含
            temp_bar = self.last_bar
            self.last_bar = bar
            if self.Direction == DIRECTION.UP:
                self.last_bar.l = temp_bar.l
            else:
                self.last_bar.h = temp_bar.h
            return None
                
        if self.last_bar.h >= bar.h and self.last_bar.l <= bar.l:
            # 前包含
            if self.Direction == DIRECTION.UP:
                self.last_bar.l = bar.l
            else:
                self.last_bar.h = bar.h
            return None
        
        # 不包含
        ret_bar = self.last_bar
        if bar.h > self.last_bar.h:
            self.Direction = DIRECTION.UP
        else:
            self.Direction = DIRECTION.DOWN
        self.last_bar = bar
        return ret_bar
        


    

