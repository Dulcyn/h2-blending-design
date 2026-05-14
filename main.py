from opt import H2DesignOpt
import pandas as pd
import json


def main():
    with open('data/parameters.json', 'r') as f:
        data = json.load(f)

    demand = pd.read_csv("data/energy_demand_MW.csv")
    demand = demand.p3

    opt = H2DesignOpt(data, demand)
    opt.build()
    
    opt.solve()

    print("Optimal design found:")
    print(f"Total cost (USD): {opt.model.objective():.2f}")
    print(f"Electrolyzer capacity (kW): {opt.model.Λez.value:.2f}")
    print(f"Tank capacity (kg): {opt.model.Λht.value:.2f}")
    print(f"Total H2 produced (kg): {sum(opt.model.vh2[t].value for t in opt.model.Ωt):.2f}")
    print(f"Total NG consumed (kg): {sum(opt.model.vng[t].value for t in opt.model.Ωt):.2f}")


    return


if __name__ == "__main__":
    main()