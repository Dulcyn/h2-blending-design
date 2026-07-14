from opt import H2DesignOpt
import pandas as pd
import json
import matplotlib.pyplot as plt
from pyomo.opt import TerminationCondition


def plot_results(opt):
    """
    #Plota gráficos dos resultados da otimização:
     #Potência do eletrolisador ao longo do tempo
     #Armazenamento de H2 no tank ao longo do tempo
     Consumo de gás natural ao longo do tempo
    """
    # Extrair valores das variáveis do modelo
    time_steps = list(opt.model.Ωt)
    
    pez = [opt.model.pez[t].value for t in time_steps]  # Potência do eletrolisador (MW)
    sht = [opt.model.sht[t].value for t in time_steps]  # Armazenamento do tank (kg)
    vng = [opt.model.vng[t].value for t in time_steps]  # Consumo de gás natural (Sm3/h)
    vez = [opt.model.vez[t].value for t in time_steps]  # Produção do eletrolisador (Sm3/h)
    vh2 = [opt.model.vh2[t].value for t in time_steps]  # H2 para demanda (Sm3/h)
    
    # Cria figura com 3 subplots
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    
    # Plot 1: Potência do Eletrolisador
    axes[0].plot(time_steps, pez, marker='o', linewidth=2, markersize=6, color='yellow')
    axes[0].set_xlabel('Tempo (horas)')
    axes[0].set_ylabel('Potência (MW)')
    axes[0].set_title('Potência do Eletrolisador ao Longo do Tempo')
    axes[0].grid(True, alpha=0.3)
    axes[0].set_xticks(time_steps)
    
    # Plot 2: Armazenamento de H2
    axes[1].plot(time_steps, sht, marker='s', linewidth=2, markersize=6, color='green')
    axes[1].set_xlabel('Tempo (horas)')
    axes[1].set_ylabel('Armazenamento (kg)')
    axes[1].set_title('Armazenamento de H2 no Tank ao Longo do Tempo')
    axes[1].grid(True, alpha=0.3)
    axes[1].set_xticks(time_steps)
    
    # Plot 3: Consumo de Gás Natural
    axes[2].plot(time_steps, vng, marker='^', linewidth=2, markersize=6, color='gray')
    axes[2].set_xlabel('Tempo (horas)')
    axes[2].set_ylabel('Consumo (Sm3/h)')
    axes[2].set_title('Consumo de Gás Natural ao Longo do Tempo')
    axes[2].grid(True, alpha=0.3)
    axes[2].set_xticks(time_steps)
    
    plt.tight_layout()
    plt.show()


def main():
    with open('data/parameters.json', 'r') as f:
        data = json.load(f)

    demand = pd.read_csv("data/gas/energy_demand_MW.csv")
    demand = demand.p3

    pv = pd.read_csv("data/pv/pv_generation.csv")
    pv = pv.p3

    opt = H2DesignOpt(data, demand, pv)
    opt.build()
    
    results = opt.solve()

    if results.solver.termination_condition != TerminationCondition.optimal:
        raise RuntimeError(f"Optimization failed: {results.solver.termination_condition}")

    print("Optimal design found:")
    print(f"Total cost (EUR): {opt.model.objective():.2f}")
    print(f"Electrolyzer capacity (MW): {opt.model.Λez.value:.2f}")
    print(f"Tank capacity (kg): {opt.model.Λht.value:.2f}")
    print(f"PV capacity (MW): {opt.model.Λpv.value:.2f}")
    print(f"BESS capacity (MWh): {opt.model.Λbess.value:.2f}")
    h2_mass = (
        sum(opt.model.vez[t].value for t in opt.model.Ωt)
        * opt.general.timestep
        * opt.h2.density
    )
    ng_volume = sum(opt.model.vng[t].value for t in opt.model.Ωt) * opt.general.timestep
    print(f"Total H2 produced (kg): {h2_mass:.2f}")
    print(f"Total NG consumed (Sm3): {ng_volume:.2f}")

    # Plotar gráficos de produção, consumo, armazenamento para análise dos resultados
    plot_results(opt)
    
    return


if __name__ == "__main__":
    main()
