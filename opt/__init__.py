from pyomo.opt import SolverFactory
import pyomo.environ as pyo

from .general import General

from .electrolyzer import Electrolyzer
from .hydrogen import Hydrogen
from .water import Water
from .tank import Tank
from .grid import Grid
from .gas import Gas



class H2DesignOpt:
    def __init__(self, data, demand):
        self.general = General(data['general'])

        self.ez = Electrolyzer(data['electrolyzer'])
        self.h2 = Hydrogen(data['hydrogen'])
        self.wt = Water(data['water'])
        self.ts = Grid(data['grid'])
        self.ht = Tank(data['tank'])
        self.ng = Gas(data['gas'])

        self.demand = demand

        return
    
    def build(self):
        m = pyo.ConcreteModel()

        # Sets
        m.Ωt = pyo.Set(initialize=[t for t in range(0, 24)])
        
        Δt = self.general.timestep        

        ################## Decision making variables ##################
        m.Λez = pyo.Var(within=pyo.NonNegativeReals)
        m.Λht = pyo.Var(within=pyo.NonNegativeReals)

        ################## Operation Variables ##################
        # Energy
        m.pts   = pyo.Var(m.Ωt, within=pyo.Reals)
        m.pez   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)


        # Volume
        m.vng       = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Natural gas volume
        m.vh2       = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Hydrogen for demand volume
        m.vez       = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Electrolyzer hydrogen output volume
        m.vht_in    = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Hydrogen tank storage input volume
        m.vht_out   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Hydrogen tank storage output volume

        m.vht   = pyo.Var(m.Ωt, within=pyo.Reals)  # Hydrogen for storage volume

        # mass
        m.mwt   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Water for electrolysis mass


        # storage
        m.sht   = pyo.Var(m.Ωt, within=pyo.NonNegativeReals)  # Hydrogen tank storage volume

        ################## Objective Function ##################
        def objective_rule(m):
            capex = self.ez.capex * m.Λez + self.ht.capex * m.Λht
            yearly_opex = Δt * sum(
                self.ts.cost * m.pts[t] + self.wt.cost * m.mwt[t] + self.ng.cost * m.vng[t] for t in m.Ωt
            )
            opex = sum(yearly_opex / (1 + self.general.r) ** y for y in range(0, self.general.lifetime))
            return capex + opex
        m.objective = pyo.Objective(rule=objective_rule, sense=pyo.minimize)


        ################## Constraints ##################
        # Power balance
        def power_balance_rule(m, t):
            return m.pts[t] == m.pez[t]
        m.power_balance = pyo.Constraint(m.Ωt, rule=power_balance_rule)

        # Gas energy demand
        def gas_energy_demand_rule(m, t):
            return self.h2.lhv * m.vh2[t] + self.ng.lhv * m.vng[t] == self.demand[t] * 1000
        m.gas_energy_demand = pyo.Constraint(m.Ωt, rule=gas_energy_demand_rule)

        # h2 blending constraint
        def h2_blending_rule(m, t):
            return m.vh2[t] == self.general.αh2 * (m.vh2[t] + m.vng[t])
        m.h2_blending = pyo.Constraint(m.Ωt, rule=h2_blending_rule)

        def tank_storage_rule(m, t):
            if t == 0:
                return m.sht[t] == m.Λht * self.ht.V0
            else:
                return m.sht[t] == m.sht[t-1] + Δt * m.vht[t]
        m.tank_storage = pyo.Constraint(m.Ωt, rule=tank_storage_rule)

        def tank_storage_linearization_rule(m, t):
            return m.vht[t] == m.vht_in[t] - m.vht_out[t]
        m.tank_storage_linearization = pyo.Constraint(m.Ωt, rule=tank_storage_linearization_rule)

        def ez_h2_production_rule(m, t):
            return m.vez[t] == Δt * self.ez.eff * m.pez[t]/self.h2.lhv
        m.ez_h2_production = pyo.Constraint(m.Ωt, rule=ez_h2_production_rule)

        def volume_balance_rule(m, t):
            return m.vez[t] == m.vh2[t] + m.vht[t]
        m.volume_balance = pyo.Constraint(m.Ωt, rule=volume_balance_rule)

        def water_mass_rule(m, t):
            return m.mwt[t] == m.vez[t] * self.h2.density * self.ez.qrate
        m.water_mass = pyo.Constraint(m.Ωt, rule=water_mass_rule)

        def electrolyzer_capacity_rule(m, t):
            return m.pez[t] <= m.Λez
        m.electrolyzer_capacity = pyo.Constraint(m.Ωt, rule=electrolyzer_capacity_rule)

        def tank_capacity_rule(m, t):
            return m.sht[t] <= m.Λht
        m.tank_capacity = pyo.Constraint(m.Ωt, rule=tank_capacity_rule)

        self.model = m

    def solve(self):
        opt = SolverFactory('gurobi')
        results = opt.solve(self.model)
        return results
    
    



