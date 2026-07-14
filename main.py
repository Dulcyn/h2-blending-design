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
    scenarios = list(opt.model.Ωs)


    
    
   

    # Potência do eletrolisador
    for s in scenarios:
        fig, axes = plt.subplots(3, 1, figsize=(12,10))
        pez = {s: [opt.model.pez[t, s].value for t in time_steps]}  # Potência do eletrolisador (MW)
        sht = {s: [opt.model.sht[t, s].value for t in time_steps]}  # Armazenamento do tank (kg)
        vng = {s: [opt.model.vng[t, s].value for t in time_steps]}  # Consumo de gás natural (Sm3/h)
        axes[0].plot(time_steps, pez[s], marker='o', label=f'Cenário {s}')

        axes[0].set_xlabel('Tempo (h)')
        axes[0].set_ylabel('Potência (MW)')
        axes[0].set_title('Potência do Eletrolisador')
        axes[0].grid(True)
        axes[0].legend()

        axes[1].plot(time_steps, sht[s], marker='s', label=f'Cenário {s}')

        axes[1].set_xlabel('Tempo (h)')
        axes[1].set_ylabel('H₂ (kg)')
        axes[1].set_title('Armazenamento de Hidrogênio')
        axes[1].grid(True)
        axes[1].legend()


        axes[2].plot(time_steps, vng[s], marker='^', label=f'Cenário {s}')

        axes[2].set_xlabel('Tempo (h)')
        axes[2].set_ylabel('GN (Sm³/h)')
        axes[2].set_title('Consumo de Gás Natural')
        axes[2].grid(True)
        axes[2].legend()

        plt.tight_layout()
        plt.savefig(f'results/optimization_results_{s}.pdf')
        plt.close("all")
    
    

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

    print("Optimal design found:")
    print(f"Total cost (EUR): {opt.model.objective():.2f}")
    print(f"Electrolyzer capacity (MW): {opt.model.Λez.value:.2f}")
    print(f"Tank capacity (kg): {opt.model.Λht.value:.2f}")
    print(f"PV capacity (MW): {opt.model.Λpv.value:.2f}")
    print(f"BESS capacity (MWh): {opt.model.Λbess.value:.2f}")
    print("Operational results by scenario:")
    for s in opt.sets.Ωs:
        h2_mass = (
            sum(opt.model.vez[t, s].value for t in opt.model.Ωt)
            * opt.general.timestep
            * opt.h2.density)
    
        ng_volume = (sum(opt.model.vng[t, s].value for t in opt.model.Ωt) * opt.general.timestep)
        print(f"Scenario {s}")
        print(f"  Total H2 produced (kg): {h2_mass:.2f}")
        print(f"  Total NG consumed (Sm³): {ng_volume:.2f}")
    
         # Plotar gráficos de produção, consumo, armazenamento para análise dos resultados
    plot_results(opt)
    
    return


if __name__ == "__main__":
    main()
