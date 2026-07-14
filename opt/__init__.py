from pyomo.opt import SolverFactory
import pyomo.environ as pyo

from .general import General, Sets

from .electrolyzer import Electrolyzer
from .photovoltaic import Photovoltaic
from .hydrogen import Hydrogen
from .bess import Battery
from .water import Water
from .tank import Tank
from .grid import Grid
from .gas import Gas




class H2DesignOpt:
    def __init__(self, data, demand, pv, prob, horizon):
        self.general = General(data['general'])
        self.ez     = Electrolyzer(data['electrolyzer'])
        self.h2     = Hydrogen(data['hydrogen'])
        self.wt     = Water(data['water'])
        self.ts     = Grid(data['grid'])
        self.ht     = Tank(data['tank'])
        self.ng     = Gas(data['gas'])
        self.pv     = Photovoltaic(data['PV'])
        self.bess   = Battery(data['BESS'])

        self.sets   = Sets(horizon, prob)

        solver_data = data.get('solver', {})
        if isinstance(solver_data, str):
            self.solver_name = solver_data
            self.solver_options = {}
        else:
            self.solver_name = solver_data.get('name', 'gurobi')
            self.solver_options = solver_data.get('options', {})

        self.demand = demand
        self.pvgen = pv
        return
    
    def build(self):
        m = pyo.ConcreteModel()

        # Sets
        m.Ωt = pyo.Set(initialize=[t for t in self.sets.Ωt])
        m.Ωs = pyo.Set(initialize=[s for s in self.sets.Ωs])
        m.prob = pyo.Param(m.Ωs, initialize=self.sets.prob, mutable=True)
    
        
        Δt = self.general.timestep        

        ################## Decision making variables ##################
        m.Λez = pyo.Var(within=pyo.NonNegativeReals) #tamanho do eletrolisador (MW)
        m.Λht = pyo.Var(within=pyo.NonNegativeReals) #tamanho do tanque         (kg)
        m.Λpv = pyo.Var(within=pyo.NonNegativeReals) #tamanho do PV (MW)
        m.Λbess = pyo.Var(within=pyo.NonNegativeReals) #tamanho da bess (MWh)
        # m.Λts = pyo.Var(within=pyo.NonNegativeReals) #tamanho da grid (MW)
        # m.Λcompress = pyo.Var(within=pyo.NonNegativeReals) #tamanho do compressor (MW)


        ################## Operation Variables ##################
        # Power
        m.pts_export   = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)    #MW exported to the grid
        m.pts_import   = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)    #MW imported from the grid
        m.pez          = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)    #Mw
        m.ppv          = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)    #MW
        m.pbess        = pyo.Var(m.Ωt, m.Ωs, within=pyo.Reals)               #MW


        # Energy
        m.ebess  = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # BESS energy storage level


        # Volume
        m.vng       = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # Natural gas flow (Sm3/h)
        m.vh2       = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # H2 demand flow (Sm3/h)
        m.vez       = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # Electrolyzer H2 output (Sm3/h)
        m.vht_in    = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # Tank input flow (Sm3/h)
        m.vht_out   = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # Tank output flow (Sm3/h)

        m.vht   = pyo.Var(m.Ωt, m.Ωs, within=pyo.Reals)  # Net H2 flow into storage (Sm3/h)

        # Water
        m.vwater = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # Electrolysis water flow (m3/h)


        # storage
        m.sht   = pyo.Var(m.Ωt, m.Ωs, within=pyo.NonNegativeReals)  # Hydrogen stored in the tank (kg)

        ################## Objective Function ##################
        def objective_rule(m):
            capex = (
                1000 * self.ez.capex * m.Λez
                + self.ht.capex * m.Λht
                + 1000 * self.pv.capex * m.Λpv
                + 1000 * self.bess.capex * m.Λbess
            )
            variable_opex = Δt * sum(self.sets.prob[s] * (
                self.ts.cost * m.pts_import[t, s] + self.wt.cwater * m.vwater[t, s] + self.ng.cost * m.vng[t, s] for t in m.Ωt
            )   for s in m.Ωs)
            yearly_variable_opex = self.sets.year * variable_opex
            yearly_fixed_opex = 1000 * (
                self.pv.opex * m.Λpv + self.bess.opex * m.Λbess
            )
            yearly_opex = yearly_variable_opex + yearly_fixed_opex
            opex = sum(
                yearly_opex / (1 + self.general.r) ** y
                for y in range(1, self.general.lifetime + 1)
            )
            return capex + opex
        m.objective = pyo.Objective(rule=objective_rule, sense=pyo.minimize)


        ################## Power Constraints ##################
        # Power balance
        def power_balance_rule(m, t, s):
            return m.pts_import[t, s] + m.ppv[t, s] == m.pez[t, s] + m.pbess[t, s] + m.pts_export[t, s]
        m.power_balance = pyo.Constraint(m.Ωt, m.Ωs, rule=power_balance_rule)


        def pv_generation_rule(m, t):
            return m.ppv[t] <= m.Λpv * self.pv.eff * self.pvgen[t]
        m.pv_generation = pyo.Constraint(m.Ωt, rule=pv_generation_rule)

        def bess_charging_rule(m, t):
            return m.pbess[t] <= m.Λbess * self.bess.crate
        m.bess_charging = pyo.Constraint(m.Ωt, rule=bess_charging_rule)

        def bess_discharging_rule(m, t):
            return m.pbess[t] >= -m.Λbess * self.bess.crate
        m.bess_discharging = pyo.Constraint(m.Ωt, rule=bess_discharging_rule)

        ################## Energy Constraints ##################
        def bess_energy_rule(m, t):
            if t == 0:
                return m.ebess[t] == m.Λbess * self.bess.E0 + m.pbess[t] * Δt
            else:
                return m.ebess[t] == m.ebess[t-1] + m.pbess[t] * Δt
        m.bess_energy = pyo.Constraint(m.Ωt, rule=bess_energy_rule)

        def bess_energy_capacity_rule(m, t):
            return m.ebess[t] <= m.Λbess
        m.bess_energy_capacity = pyo.Constraint(m.Ωt, rule=bess_energy_capacity_rule)

        last_t = max(m.Ωt)
        m.bess_terminal = pyo.Constraint(expr=m.ebess[last_t] == m.Λbess * self.bess.E0)
        
        ################## Volume and mass Constraints #########
        # Gas energy demand
        def gas_energy_demand_rule(m, t):
            return self.h2.lhv * m.vh2[t] + self.ng.lhv * m.vng[t] == self.demand[t] * 1000
        m.gas_energy_demand = pyo.Constraint(m.Ωt, rule=gas_energy_demand_rule)

        # h2 blending constraint
        def h2_blending_rule(m, t):
            return m.vh2[t] == (self.general.αh2/100) * (m.vh2[t] + m.vng[t])
        m.h2_blending = pyo.Constraint(m.Ωt, rule=h2_blending_rule)

        def tank_storage_rule(m, t):
            net_stored_mass = Δt * self.h2.density * m.vht[t]
            if t == 0:
                return m.sht[t] == m.Λht * self.ht.V0 + net_stored_mass
            else:
                return m.sht[t] == m.sht[t-1] + net_stored_mass
        m.tank_storage = pyo.Constraint(m.Ωt, rule=tank_storage_rule)

        def tank_storage_linearization_rule(m, t):
            return m.vht[t] == m.vht_in[t] - m.vht_out[t]
        m.tank_storage_linearization = pyo.Constraint(m.Ωt, rule=tank_storage_linearization_rule)

        def ez_h2_production_rule(m, t):
            return m.vez[t] == self.ez.eff * m.pez[t] * 1000 / self.h2.lhv
        m.ez_h2_production = pyo.Constraint(m.Ωt, rule=ez_h2_production_rule)

        def volume_balance_rule(m, t):
            return m.vez[t] + m.vht_out[t] == m.vh2[t] + m.vht_in[t]
        m.volume_balance = pyo.Constraint(m.Ωt, rule=volume_balance_rule)

        def water_volume_rule(m, t):
            return m.vwater[t] == m.vez[t] * self.h2.density * self.ez.qwater / 1000
        m.water_volume = pyo.Constraint(m.Ωt, rule=water_volume_rule)

        def electrolyzer_capacity_rule(m, t):
            return m.pez[t] <= m.Λez
        m.electrolyzer_capacity = pyo.Constraint(m.Ωt, rule=electrolyzer_capacity_rule)

        def tank_capacity_rule(m, t):
            return m.sht[t] <= m.Λht
        m.tank_capacity = pyo.Constraint(m.Ωt, rule=tank_capacity_rule)

        m.tank_terminal = pyo.Constraint(expr=m.sht[last_t] == m.Λht * self.ht.V0)

        self.model = m

    def solve(self):
        opt = SolverFactory(self.solver_name)
        results = opt.solve(self.model, options=self.solver_options)
        return results
    
    



