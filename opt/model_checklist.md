# Checklist do Modelo Físico

Este checklist cobre tarefas de modelagem física e operacional. Arquivos legados de entrada e a metodologia de clustering estão fora do escopo.

## Corrigido

- [x] Corrigir as unidades da água para eletrólise. `vwater` está em m3/h, `qwater` em L/kgH2 e `cwater` em EUR/m3.
- [x] Manter `PV.eff = 0.95` como eficiência do inversor.
- [x] Definir a mistura de hidrogênio em base volumétrica. A conversão atual de 15% para 0,15 está consistente.

## Está errado e precisa ser corrigido

- [ ] Aplicar a eficiência da BESS. O parâmetro `BESS.eff` existe, mas não é usado na equação do estado de carga. Usar potências não negativas separadas para carga e descarga: `e[t] = e[t-1] + eta_c*p_ch[t]*dt - p_dis[t]*dt/eta_d`.
- [ ] Impedir ou penalizar explicitamente carga e descarga simultâneas da BESS. Caso seja necessária exclusividade estrita, adicionar uma variável de modo de operação; caso contrário, documentar por que perdas e custos são suficientes para evitar essa operação.
- [ ] Impedir entrada e saída simultâneas no tanque de hidrogênio. A formulação atual permite que ambas sejam positivas na mesma hora.
- [ ] Adicionar limites para as vazões de entrada e saída do tanque. A capacidade de armazenamento, sozinha, não limita as taxas de enchimento e retirada.
- [ ] Incluir o consumo elétrico da compressão de hidrogênio e, se necessário, a capacidade do compressor. Atualmente, a produção do eletrolisador é enviada diretamente ao armazenamento sem demanda de compressão.

## Necessário para as semanas representativas

- [ ] Substituir o conjunto fixo de 24 horas por um horizonte definido pelo tamanho dos dados de entrada, permitindo executar o mesmo modelo com semanas representativas de 168 horas.
- [ ] Ler cada cenário conjunto de gás e PV sem combinar dados provenientes de períodos diferentes.
- [ ] Ponderar os custos operacionais e resultados pela probabilidade conjunta de cada semana representativa.
- [ ] Definir a condição de contorno dos armazenamentos em cada semana representativa. A condição cíclica atual fixa o estado final no estado inicial de 50%.
- [ ] Decidir se as semanas representativas serão independentes ou interligadas:
  - **Semanas independentes:** cada semana começa e termina no mesmo nível de armazenamento. Isso impede transferência líquida de H2 entre semanas e representa apenas armazenamento intrassemanal. É uma simplificação adequada quando o tanque serve somente para compensar variações de horas ou poucos dias.
  - **Semanas interligadas:** o estado final de uma semana influencia o estado inicial da próxima. Isso permite armazenar H2 em períodos favoráveis e utilizá-lo semanas ou meses depois, sendo necessário para representar armazenamento sazonal.
  - O clustering remove a sequência cronológica direta. Para interligar as semanas, será necessário usar a sequência original de rótulos dos clusters ou uma matriz de transição entre semanas representativas.
- [ ] Validar os balanços de energia, gás, hidrogênio, água e armazenamento para todos os cenários e horas.

## Necessário para o modelo estocástico

- [ ] Adicionar um conjunto de cenários e suas probabilidades.
- [ ] Manter as capacidades de projeto como variáveis de primeiro estágio compartilhadas por todos os cenários.
- [ ] Tornar as variáveis operacionais horárias dependentes do cenário.
- [ ] Formular o custo operacional esperado como a soma dos custos dos cenários ponderados por suas probabilidades.
- [ ] Adicionar restrições de não antecipatividade somente se as decisões operacionais fizerem parte de uma árvore de cenários. Elas não são necessárias para recurso independente em semanas representativas.

## Alterações planejadas na formulação

- [ ] Alterar a igualdade da mistura volumétrica de hidrogênio para uma restrição de limite superior quando a formulação multiobjetivo for introduzida. Assim, o modelo poderá escolher a fração de H2 entre zero e o limite permitido ao avaliar o compromisso entre custo e emissões.
- [ ] Usar as emissões de carbono como segundo objetivo. Considerar, no mínimo, as emissões do gás natural e da eletricidade importada: `emissions = sum(dt*(ef_grid[t]*p_import[t] + ef_ng*vng[t]))`.
- [ ] Definir as unidades e fontes de `ef_grid` e `ef_ng`, o tratamento da exportação de eletricidade e se serão consideradas apenas emissões operacionais ou também emissões incorporadas nos equipamentos.
- [ ] Escolher o método multiobjetivo. Dar preferência ao método epsilon-constraint para gerar a fronteira de Pareto entre custo total e emissões sem depender de uma soma ponderada sensível à escala dos objetivos.

## Hipóteses a confirmar antes dos estudos finais

- [ ] Carga mínima, consumo em espera, limites de rampa, partida e degradação do eletrolisador.
- [ ] Perdas, faixa de pressão e capacidade útil do tanque de hidrogênio.
- [ ] Limites de importação e exportação da conexão com a rede e necessidade de impedir importação e exportação simultâneas.
- [ ] Potência nominal do inversor e tratamento do clipping de PV além da eficiência fixa de 0,95.
- [ ] Limites de qualidade do gás além da fração volumétrica de hidrogênio, caso sejam necessários para a aplicação.
