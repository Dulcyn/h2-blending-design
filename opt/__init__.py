from pyomo.opt import SolverFactory
import pyomo.environ as pyo



from .electrolyzer import Electrolyzer
from .hydrogen import Hydrogen
from .water import Water
from .tank import Tank
from .grid import Grid
from .gas import Gas



class H2DesignOpt:
    def __init__(self, data):
        self.ez = Electrolyzer(data['electrolyzer'])
        self.h2 = Hydrogen(data['hydrogen'])
        self.wt = Water(data['water'])
        self.ts = Grid(data['grid'])
        self.ht = Tank(data['tank'])
        self.gt = Gas(data['gas'])

        return
    
    def build(self):
        m = pyo.ConcreteModel()
        m.Ωt = pyo.Set(initialize=[t for t in range(0, 24)])
