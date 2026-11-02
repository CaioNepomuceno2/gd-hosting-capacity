# Geração distribuída × capacidade da rede

[![CI](https://github.com/CaioNepomuceno2/gd-hosting-capacity/actions/workflows/ci.yml/badge.svg)](https://github.com/CaioNepomuceno2/gd-hosting-capacity/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

**Quais transformadores vão saturar com a energia solar dos telhados, e quando?**

Em Mato Grosso, a geração distribuída (GD) de baixa tensão passou de **18 MW em 2018 para 1,97 GW em 2025**
(214 mil unidades). Este projeto mede, com o cadastro público da rede (BDGD/ANEEL), quantos transformadores da
**Energisa Mato Grosso** já têm mais GD do que potência nominal, prevê quais serão os próximos e estima o custo
de reforço, usando apenas dados abertos.

## Resultados em uma tela

| | |
|---|---|
| Trafos com GD ≥ potência nominal, dez/2025 | **11.592** (5,7% dos trafos com consumidores), contra 2.307 em 2022 |
| Trafos com GD ≥ 80% da potência, dez/2025 | 9,5% |
| Lista de 1.000 trafos para reforço montada em dez/2022: quantos de fato saturaram até 2025? | **802 com o modelo**, 657 com a melhor regra simples, 362 priorizando a maior penetração atual |
| Trafos saturados em 2022 que a distribuidora trocou por um maior até 2025 | **30,5%**, contra 8,5% dos demais |
| Projeção 2026-2030 (ritmo de 2025, custos ilustrativos) | +19,8 mil trafos saturados, ~R$ 750 mi em reforços |

![evolução](reports/figures/01_evolucao.png)

## 1. Diagnóstico: a saturação quintuplicou em três anos

Critério: **GD instalada na baixa tensão ≥ potência nominal do trafo** (kW ≥ kVA), um indicador simples de risco
de inversão de fluxo no posto de transformação (ver [premissas](configs/premissas.yaml)).

| Ano | Unidades de GD na BT | GD na BT | Trafos saturados | % dos trafos com consumidores |
|---|---|---|---|---|
| 2019 | 7,6 mil | 106 MW | 191 | 0,1% |
| 2021 | 42,1 mil | 495 MW | 1.588 | 0,9% |
| 2022 | 66,3 mil | 673 MW | 2.307 | 1,2% |
| 2023 | 103,0 mil | 1.027 MW | 4.359 | 2,3% |
| 2024 | 160,1 mil | 1.516 MW | 7.673 | 3,9% |
| 2025 | 214,2 mil | 1.974 MW | 11.592 | 5,7% |

* **O problema está nos trafos de 45 kVA para cima:** 16,4% dos trafos de 45 a 75 kVA e 15,2% dos acima de 75 kVA
  já estão saturados, contra 3,0% dos de até 10 kVA (em geral rurais, com um ou dois consumidores).
* **Concentração urbana:** Cuiabá (1.531 trafos saturados), Rondonópolis (683), Várzea Grande (656; 16,4% dos
  trafos da cidade), Sinop (632) e Sorriso (396).

![mapa](reports/figures/03_mapa_trafos.png)

## 2. Backtest: quem ia saturar entre 2023 e 2025?

Em dez/2022, com o que se sabia naquela data, o modelo ordena os trafos pela chance de saturar nos três anos
seguintes. O resultado é comparado com o cadastro de dez/2025. O treino só usa janelas cujo resultado já era
conhecido em 2022: (2019→2020/2021/2022), (2020→2021/2022) e (2021→2022).

O modelo (LightGBM) prevê **para onde vai o crescimento**: a fração da GD nova do sistema que cai em cada trafo.
Ele usa o porte do trafo, os consumidores e a folga por consumidor, a GD já instalada, o crescimento recente
no trafo, na vizinhança de 500 m, no alimentador e no município. As regras de comparação distribuem o mesmo
total de outras formas.

![backtest](reports/figures/02_backtest.png)

| Origem dez/2022, alvo dez/2025 (197 mil trafos não saturados; 13.241 saturaram) | Modelo | Proporcional aos consumidores | Maior penetração hoje | Proporcional ao último ano |
|---|---|---|---|---|
| Average precision (ranking de quem satura) | **0,37** | 0,33 | 0,21 | 0,20 |
| Acertos entre os 1.000 primeiros da lista | **802** | 657 | 362 | 153 |
| Acertos entre os 5.000 primeiros | **3.116** | 2.950 | 1.695 | 1.576 |
| Erro absoluto médio do kW adicionado por trafo | **4,8 kW** | 5,0 kW | 7,0 kW | 7,8 kW |

**Em reais** (custos ilustrativos): se em dez/2022 a distribuidora reforçasse preventivamente os 1.000 primeiros
trafos de cada lista, com o modelo **R$ 37 mi** iriam para trafos que de fato saturaram e R$ 7 mi seriam
antecipados sem necessidade. Priorizando a maior penetração atual, que é a regra intuitiva, seriam R$ 18 mi bem
gastos e R$ 19 mi sem necessidade ([`reports/backtest_reforco_rs.csv`](reports/backtest_reforco_rs.csv)).

A regra "proporcional aos consumidores" é um baseline forte: sozinha, ela já captura a maior parte do sinal
(trafo pequeno com muitos consumidores satura primeiro). O modelo fica à frente principalmente no topo da
lista, que é onde o orçamento de reforço é gasto. A alocação é bem calibrada por decil
([`reports/calibracao_alocacao.csv`](reports/calibracao_alocacao.csv)).

**O total é a parte difícil.** A regra simples "o ritmo do último ano se mantém" previa 818 MW de GD nova na BT
entre 2023 e 2025; entraram 1.161 MW (-30%). Com esse total, o modelo marca menos trafos como saturados
(precisão de 67%, recall de 18%), mas a ordem da lista praticamente não muda (average precision de 0,36).

## 3. Validação externa: a distribuidora trocou os trafos saturados

Se o critério captura um problema real, os trafos saturados deveriam receber obra. Ligando o cadastro de 2022 ao
de 2025 pela posição de cada trafo: **30,5% dos 2.239 trafos saturados em 2022 foram trocados por um maior até
2025, contra 8,5% dos não saturados** (3,6 vezes mais).

![validação](reports/figures/05_validacao.png)

## 4. Projeção: o que vem até 2030

Modelo treinado com todas as janelas até 2025. O total de GD nova segue o ritmo de 2025 (546 MW/ano na BT),
que no backtest se mostrou conservador. Cada trafo é reforçado no ano em que cruza o limite.

| Ano | Trafos que passam a saturar | Reforço (R$ mi, ilustrativo) | Saturados acumulados |
|---|---|---|---|
| 2026 | 3.903 | 161 | 15.495 |
| 2027 | 4.592 | 188 | 20.087 |
| 2028 | 4.076 | 163 | 24.163 |
| 2029 | 3.666 | 130 | 27.829 |
| 2030 | 3.565 | 107 | 31.394 |

![projeção](reports/figures/04_projecao.png)

A lista por trafo (com ano previsto de saturação) fica em `data/processed/trafos_previsao.parquet`. A lista por
alimentador está em [`reports/alimentadores_previsao.csv`](reports/alimentadores_previsao.csv).

**Alimentadores.** A rede da distribuidora tem 2,97 GW de GD (BT + MT) para uma carga média de
1,29 GW. Por isso o critério de alimentador (GD x 0,7 ≥ carga média, ou seja, exportação provável ao meio-dia)
já é atingido por **74% dos 638 alimentadores com carga cadastrada**; outros 45 cruzam em 2026 e 27 em 2027. O
número depende muito do fator de simultaneidade (58% com 0,5; 19% com 0,3;
[`reports/sensibilidade_alimentadores.csv`](reports/sensibilidade_alimentadores.csv)), mas a conclusão se
mantém: no nível do alimentador, a capacidade de hospedagem já foi ultrapassada em boa parte da rede. Daqui
para frente, o problema a priorizar é local, trafo a trafo.

> **Premissas.** Limite de saturação, fator de simultaneidade, tamanhos padrão de trafo e custos estão em
> [`configs/premissas.yaml`](configs/premissas.yaml) e são **ilustrativos**. Os valores em R$ servem para
> comparar estratégias, não como orçamento.

## Decisões de dados que fazem diferença

Os detalhes estão em [`docs/dados.md`](docs/dados.md). Os principais:

* **IDs de trafo instáveis.** Só 0,05% dos códigos de trafo de 2022 existem em 2025. O mesmo trafo é
  reconhecido pela posição (vizinho mais próximo mútuo a até 20 m), o que liga 99,1% dos trafos.
* **GD sumida no modelo antigo da BDGD.** De 2018 a 2020 a camada de GD de baixa tensão vem vazia. As
  unidades foram reconstruídas pelos consumidores com código CEG de GD.
* **Potências impossíveis.** O cadastro de 2025 tem ~2.400 "microgerações" de BT acima de 75 kW (até 43 MW), que
  somariam 1,3 GW. A potência vem do registro oficial de empreendimentos da ANEEL pelo código CEG; sem
  registro, só valem até 75 kW. O mesmo vale para uma GD de MT cadastrada com 125 GW em 2024.

## Estrutura

```
src/gdhc/
  bdgd.py        leitura da BDGD (modelos M10 e V10/V11), GD por trafo, limpeza de potência
  aneel.py       downloads do CKAN da ANEEL
  painel.py      ligação de trafos entre snapshots pela posição, features point-in-time
  modelo.py      alocação do crescimento (LightGBM), baselines e métricas
  rede.py        critério de saturação, custo de reforço, ano de saturação, alimentadores
scripts/         01_baixar_aneel, 02_build_bdgd, 03_analise, 04_validacao, 05_figuras
configs/         recorte (distribuidora, snapshots) e premissas de engenharia e custo
docs/dados.md    decisões de dados
```

## Reproduzir

```bash
pip install -e ".[dev]"
python scripts/01_baixar_aneel.py   # registro de GD e pedidos de conexão (~160 MB)
python scripts/02_build_bdgd.py     # 8 snapshots da BDGD (~1 GB cada, processados e apagados um a um)
python scripts/03_analise.py        # diagnóstico, backtest e projeção (~25 min com 2 núcleos)
python scripts/04_validacao.py      # validações externas (troca de trafos, pedidos de conexão)
python scripts/05_figuras.py
pytest
```

Para outra distribuidora, basta trocar a UF, a sigla e os IDs dos snapshots da BDGD em `configs/emt.yaml`.

## Limitações

* **O critério é um indicador, não um estudo de fluxo de potência.** GD ≥ kVA não garante inversão de fluxo
  (depende da carga ao meio-dia), e um trafo pode ter problema de tensão antes disso. O sinal de que ele captura
  algo real é a taxa de troca 3,6 vezes maior nos trafos saturados.
* **Pedidos de conexão não validaram o critério.** Nos pedidos de MMGD de BT de 2022-2023 (ANEEL), a fração com
  "necessidade de obra" por município é *menor* onde há mais trafos saturados (Spearman -0,27, 108
  municípios). Ela acompanha a ruralidade (Spearman -0,55 com a fração de trafos urbanos): nesses dados,
  obra parece significar extensão de rede, e o pedido não identifica o trafo.
* **O total de GD futura é incerto** (políticas, juros, preço dos módulos). A projeção usa o ritmo de 2025; no
  backtest, a mesma regra subestimou o crescimento em 30%.
* **Registro de GD com potência atual:** ampliações posteriores de uma mesma GD aparecem nos snapshots antigos.
* **GD de MT antes de 2021** não está na BDGD da distribuidora, então o histórico por alimentador começa em 2021.
* **Custos ilustrativos:** troca de trafo a R$ 300/kVA + R$ 8 mil por troca. Não incluem reforço de rede
  secundária nem de alimentador.

---
Autor: **Caio Nepomuceno**. Dados públicos da ANEEL. Projeto independente, sem vínculo com a Energisa ou com a ANEEL.
