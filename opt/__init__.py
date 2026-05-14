from pyomo.opt import SolverFactory
import pyomo.environ as pyo



from .electrolyzer import Electrolyzer
from .tank import Tank
from .grid import Grid

class H2DesignOpt:
    def __init__(self, data):
        self.ez = Electrolyzer(data['electrolyzer'])
        # self.ts = Grid(data['grid'])
        # self.ht = Tank(data['tank'])
        # self.

        return
    
    def build(self):
        m = pyo.ConcreteModel()
        m.Ωt = pyo.Set(initialize=[t for t in range(0, 24)])

        m.