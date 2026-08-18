from opt import H2DesignOpt
import pandas as pd
import json
import matplotlib.pyplot as plt
import numpy as np
from pyomo.opt import TerminationCondition




def main():
    with open('data/parameters.json', 'r') as f:
        data = json.load(f)

    scenario    = "data/scenarios/weekly/"
    demand      = pd.read_csv(f"{scenario}/gas_representative.csv")
    pv          = pd.read_csv(f"{scenario}/pv_representative.csv")
    metadata    = pd.read_csv(f"{scenario}/scenario_metadata.csv")
    prob = {row['scenario']: row['probability'] for _, row in metadata.iterrows()}
    horizon = len(demand)

    opt = H2DesignOpt(data, demand, pv, prob, horizon)
    opt.build()
    
    results = opt.solve()

    if results.solver.termination_condition != TerminationCondition.optimal:
        raise RuntimeError(f"Optimization failed: {results.solver.termination_condition}")

    
    print("Operational results by scenario:")

    report = {"100%": {}} 

    report["100%"]["total_cost"] = opt.model.objective()
    report["100%"]["electrolyzer_capacity"] = opt.model.Λez.value
    report["100%"]["tank_capacity"] = opt.model.Λht.value
    report["100%"]["pv_capacity"] = opt.model.Λpv.value
    report["100%"]["bess_capacity"] = opt.model.Λbess.value
    report["100%"]["compressor_capacity"] = opt.model.Λcomp.value
    report["100%"]["ghg_emissions"] = opt.model.ghg.value/1000


    report["100%"]["h2_total"] = sum(opt.model.vez[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep * opt.h2.density
    report["100%"]["ng_total"] = sum(opt.model.vng[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
    report["100%"]["grid_in_total"] = sum(opt.model.pts_import[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
    report["100%"]["grid_out_total"] = sum(opt.model.pts_export[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
    report["100%"]["pv_total"] = sum(opt.model.ppv[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
    report["100%"]["bess_charging_total"] = sum(opt.model.pch[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
    report["100%"]["bess_discharging_total"] = sum(opt.model.pds[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep

    
    with open('results/optimization_results.json', 'w') as f:
        json.dump(report, f, indent=4)

    total_ghg = opt.model.ghg.value  # Convert to kgCO2eq/year

    for ghg_limit in range(99.9, 0, -0.1):  # Example GHG limits in kgCO2eq/year
        print(f"Running optimization with GHG limit: {ghg_limit}% of total GHG ({total_ghg * ghg_limit / 100:.2f} kgCO2eq/year)")
        opt.build(ghg=ghg_limit*total_ghg/100)  # Set GHG limit as a percentage of the total GHG
        

        
        report[f"{ghg_limit}%"]["total_cost"] = opt.model.objective()
        report[f"{ghg_limit}%"]["electrolyzer_capacity"] = opt.model.Λez.value
        report[f"{ghg_limit}%"]["tank_capacity"] = opt.model.Λht.value
        report[f"{ghg_limit}%"]["pv_capacity"] = opt.model.Λpv.value
        report[f"{ghg_limit}%"]["bess_capacity"] = opt.model.Λbess.value
        report[f"{ghg_limit}%"]["compressor_capacity"] = opt.model.Λcomp.value
        report[f"{ghg_limit}%"]["ghg_emissions"] = opt.model.ghg.value/1000
    
    
        report[f"{ghg_limit}%"]["h2_total"] = sum(opt.model.vez[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep * opt.h2.density
        report[f"{ghg_limit}%"]["ng_total"] = sum(opt.model.vng[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
        report[f"{ghg_limit}%"]["grid_in_total"] = sum(opt.model.pts_import[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
        report[f"{ghg_limit}%"]["grid_out_total"] = sum(opt.model.pts_export[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
        report[f"{ghg_limit}%"]["pv_total"] = sum(opt.model.ppv[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
        report[f"{ghg_limit}%"]["bess_charging_total"] = sum(opt.model.pch[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep
        report[f"{ghg_limit}%"]["bess_discharging_total"] = sum(opt.model.pds[t, s].value for t in opt.model.Ωt for s in opt.model.Ωs) * opt.general.timestep

        with open('results/optimization_results.json', 'w') as f:
            json.dump(report, f, indent=4)
                
       
      

       
    
    return


if __name__ == "__main__":
    main()
