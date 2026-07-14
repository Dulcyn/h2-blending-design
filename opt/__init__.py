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

        self.demand = {
            s: demand[s].tolist()
            for s in self.sets.Ωs
        }
        self.pvgen = {
            s: pv[s].tolist()
            for s in self.sets.Ωs
        }

        solver_data = data.get('solver', {})
        if isinstance(solver_data, str):
            self.solver_name = solver_data
            self.solver_options = {}
        else:
            self.solver_name = solver_data.get('name', 'gurobi')
            self.solver_options = solver_data.get('options', {})

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
            variable_opex = Δt * sum(
                self.sets.prob[s] * sum(
                    self.ts.cost * m.pts_import[t, s]
                    + self.wt.cwater * m.vwater[t, s]
                    + self.ng.cost * m.vng[t, s]
                    for t in m.Ωt
                )
                for s in m.Ωs
            )
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


        def pv_generation_rule(m, t, s):
            return m.ppv[t, s] <= m.Λpv * self.pv.eff * self.pvgen[s][t]
        m.pv_generation = pyo.Constraint(m.Ωt, m.Ωs, rule=pv_generation_rule)

        def bess_charging_rule(m, t, s):
            return m.pbess[t, s] <= m.Λbess * self.bess.crate
        m.bess_charging = pyo.Constraint(m.Ωt, m.Ωs, rule=bess_charging_rule)

        def bess_discharging_rule(m, t, s):
            return m.pbess[t, s] >= -m.Λbess * self.bess.crate
        m.bess_discharging = pyo.Constraint(m.Ωt, m.Ωs, rule=bess_discharging_rule)

        ################## Energy Constraints ##################
        def bess_energy_rule(m, t, s):
            if t == 0:
                return m.ebess[t, s] == m.Λbess * self.bess.E0 + m.pbess[t, s] * Δt
            else:
                return m.ebess[t,s] == m.ebess[t-1,s] + m.pbess[t,s] * Δt
        m.bess_energy = pyo.Constraint(m.Ωt, m.Ωs, rule=bess_energy_rule)

        def bess_energy_capacity_rule(m, t, s):
            return m.ebess[t, s] <= m.Λbess
        m.bess_energy_capacity = pyo.Constraint(m.Ωt, m.Ωs, rule=bess_energy_capacity_rule)

        #last_t = max(m.Ωt)
        #m.bess_terminal = pyo.Constraint(expr=m.ebess[last_t] == m.Λbess * self.bess.E0)

        last_t = max(m.Ωt)
        def bess_terminal_rule(m, s):
            return m.ebess[last_t, s] == m.Λbess * self.bess.E0

        m.bess_terminal = pyo.Constraint(m.Ωs, rule=bess_terminal_rule)


        ################## Volume and mass Constraints #########
        # Gas energy demand
        def gas_energy_demand_rule(m, t, s):
            return self.h2.lhv * m.vh2[t, s] + self.ng.lhv * m.vng[t, s] == self.demand[s][t] * 1000
        m.gas_energy_demand = pyo.Constraint(m.Ωt, m.Ωs, rule=gas_energy_demand_rule)

        # h2 blending constraint
        def h2_blending_rule(m, t, s):
            return m.vh2[t, s] == (self.general.αh2/100) * (m.vh2[t, s] + m.vng[t, s])
        m.h2_blending = pyo.Constraint(m.Ωt, m.Ωs, rule=h2_blending_rule)

        def tank_storage_rule(m, t, s):
            net_stored_mass = Δt * self.h2.density * m.vht[t, s]
            if t == 0:
                return m.sht[t, s] == m.Λht * self.ht.V0 + net_stored_mass
            else:
                return m.sht[t, s] == m.sht[t-1, s] + net_stored_mass
        m.tank_storage = pyo.Constraint(m.Ωt, m.Ωs, rule=tank_storage_rule)

        def tank_storage_linearization_rule(m, t, s):
            return m.vht[t, s] == m.vht_in[t, s] - m.vht_out[t, s]
        m.tank_storage_linearization = pyo.Constraint(m.Ωt, m.Ωs, rule=tank_storage_linearization_rule)

        def ez_h2_production_rule(m, t, s):
            return m.vez[t, s] == self.ez.eff * m.pez[t, s] * 1000 / self.h2.lhv
        m.ez_h2_production = pyo.Constraint(m.Ωt, m.Ωs, rule=ez_h2_production_rule)

        def volume_balance_rule(m, t, s):
            return m.vez[t, s] + m.vht_out[t, s] == m.vh2[t, s] + m.vht_in[t, s]
        m.volume_balance = pyo.Constraint(m.Ωt, m.Ωs, rule=volume_balance_rule)

        def water_volume_rule(m, t, s):
            return m.vwater[t, s] == m.vez[t, s] * self.h2.density * self.ez.qwater / 1000
        m.water_volume = pyo.Constraint(m.Ωt, m.Ωs, rule=water_volume_rule)

        def electrolyzer_capacity_rule(m, t, s):
            return m.pez[t, s] <= m.Λez
        m.electrolyzer_capacity = pyo.Constraint(m.Ωt, m.Ωs, rule=electrolyzer_capacity_rule)

        def tank_capacity_rule(m, t, s):
            return m.sht[t, s] <= m.Λht
        m.tank_capacity = pyo.Constraint(m.Ωt, m.Ωs, rule=tank_capacity_rule)

        def tank_terminal_rule(m, s):
            return m.sht[last_t, s] == m.Λht * self.ht.V0

        m.tank_terminal = pyo.Constraint(m.Ωs, rule=tank_terminal_rule)

        self.model = m

    def solve(self):
        opt = SolverFactory(self.solver_name)
        results = opt.solve(self.model, options=self.solver_options)
        return results
    
    



