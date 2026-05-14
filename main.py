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


    return


if __name__ == "__main__":
    main()