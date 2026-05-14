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
        self.ng = Gas(data['gas'])

        return
    
    def build(self):
        m = pyo.ConcreteModel()

        # Sets
        m.Ωt = pyo.Set(initialize=[t for t in range(0, 24)])
        
        ################## Decision making variables ##################
        m.Λez = pyo.Var(within=pyo.NonNegativeReals)
        m.Λht = pyo.Var(within=pyo.NonNegativeReals)

        ################## Operation Variables ##################
        # Energy
        m.pgrid = pyo.Var(m.Ωt, within=pyo.Reals)
        m.pez   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)


        # Volume
        m.vng   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Natural gas volume
        m.vh2   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Hydrogen for demand volume
        m.vwt   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Water for electrolysis volume


        
        m.vht   = pyo.Var(m.Ωt, within=pyo.Reals)  # Hydrogen for storage volume

        # storage
        m.sht   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Hydrogen tank storage volume





