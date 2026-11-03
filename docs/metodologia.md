# Metodologia

Este documento descreve o que é calculado, como e com que premissas. As decisões de tratamento dos dados
(IDs instáveis, GD reconstruída no modelo antigo da BDGD, limpeza de potência) estão em [`dados.md`](dados.md)
e não são repetidas aqui.

## 1. Perguntas

1. **Diagnóstico:** quantos transformadores MT/BT da Energisa MT já têm mais GD de baixa tensão do que potência
   nominal, e como isso evoluiu de 2018 a 2025?
2. **Previsão:** quais trafos vão saturar nos próximos anos, e em que ano?
3. **Decisão:** se a distribuidora reforçasse preventivamente uma lista de trafos, quanto do dinheiro cairia em
   trafos que de fato precisavam? Como essa lista se compara às regras simples que um planejador usaria?
4. **Alimentadores:** em quantos alimentadores a GD instalada já supera a carga média ao meio-dia?

## 2. Dados e período

| Dado | Período | Granularidade | Uso |
|---|---|---|---|
| BDGD (PRODIST Módulo 10), Energisa MT | snapshots de 31/12 de 2018 a 2025 | trafo, UC, GD, alimentador | painel de trafos e alvo do backtest |
| Registro de empreendimentos de GD (ANEEL) | situação atual | unidade de GD (código CEG) | potência oficial de cada GD |
| Pedidos de conexão de MMGD, Centro-Oeste (ANEEL) | 2022-2023 | pedido | tentativa de validação externa |

Universo do diagnóstico e do backtest: trafos com ao menos uma UC de BT (cerca de 75% dos trafos).

## 3. Pipeline

| Passo | Script | Funções principais | Saída |
|---|---|---|---|
| Download do registro de GD e dos pedidos | `scripts/01_baixar_aneel.py` | `gdhc.aneel` | `data/raw/` |
| Leitura dos 8 snapshots, GD por trafo | `scripts/02_build_bdgd.py` | `gdhc.bdgd` | `data/interim/trafos_<ano>.parquet`, `alimentadores_<ano>.parquet` |
| Diagnóstico, backtest, projeção | `scripts/03_analise.py` | `gdhc.painel`, `gdhc.modelo`, `gdhc.rede` | `reports/*.csv`, `reports/resultados.json`, `data/processed/` |
| Validações externas | `scripts/04_validacao.py` | `gdhc.painel.ligar` | `reports/validacao_*.csv` |
| Figuras | `scripts/05_figuras.py` | | `reports/figures/` |
| Indicadores de decisão | `scripts/06_resumo_decisao.py` | | `reports/resumo_decisao.csv/json` |

## 4. Definições e fórmulas

**Penetração do trafo** no snapshot *t*:

    p = GD_BT_kW / kVA_nominal

**Saturado:** `p ≥ L`, com `L = 1,0` (`limite_trafo`). **Alerta:** `p ≥ 0,8` (`limite_trafo_alerta`). É um indicador
de risco de inversão de fluxo no posto de transformação, não o critério de planejamento de uma distribuidora
(ver `rede.saturado`).

**Custo de reforço** (`rede.custo_reforco`): o trafo saturado é trocado pelo menor tamanho padrão
estritamente acima de `GD_kW / L`. O custo é

    custo = kVA_novo × R$ 300/kVA + R$ 8.000 por troca

Se nenhum tamanho padrão comporta a GD, usa o kVA exato. Trafo não saturado tem custo zero.

**Ligação de trafos entre snapshots** (`painel.ligar`): vizinho mais próximo mútuo a até 20 m, porque o código do
trafo muda entre os anos. Entre 2022 e 2025, liga 99,1% dos trafos.

**Alvo do modelo** (`modelo.treino`): para uma janela (origem *o*, horizonte *h*), a fração do crescimento do
sistema que caiu em cada trafo:

    share_i = max(GD_i(o+h) − GD_i(o), 0) / Σ_j max(GD_j(o+h) − GD_j(o), 0)

Prever a fração, e não os kW, separa duas perguntas diferentes: **para onde** vai o crescimento (o que a rede e o
histórico local explicam) e **quanto** cresce o sistema (que depende de juros, preço de módulos e regulação). Um
modelo de árvore não extrapola níveis nunca vistos, então o total fica de fora do modelo.

**Modelo de alocação** (`modelo.ajustar`): LightGBM com objetivo Tweedie (muitos zeros e cauda longa), média de
3 sementes. Features, todas da origem ou do ano anterior (`painel._features`):

* porte e folga: kVA, GD instalada, penetração, folga em kW, kVA por UC, folga por UC sem GD;
* consumidores: nº de UCs, consumo anual, consumo por UC, fração residencial, urbano/rural;
* histórico local: fração do crescimento do último ano que caiu no trafo, nº de GD novas no último ano, trafo
  novo;
* vizinhança de 500 m: GD instalada, UCs e fração do crescimento do último ano;
* município e alimentador: GD por UC, fração de UCs com GD, fração do crescimento do último ano, crescimento
  relativo;
* posição (lat/lon) e horizonte.

**Total de GD nova** (`modelo.total_ritmo_ultimo_ano`): `GD adicionada no último ano × h`, uma regra simples e
explícita conhecida na origem.

**kW previsto por trafo:** `total × share_previsto_i / Σ share_previsto`.

**Ano de saturação** (`rede.ano_saturacao`): crescimento linear a partir da taxa anual prevista,
`primeiro t ≥ 0 com GD + taxa × t ≥ L × kVA`, limitado a 2035.

**Critério de alimentador** (`rede.alimentadores`):

    razão = (GD_BT + GD_MT) × FS / carga_média,   carga_média = consumo anual (BT + MT) / 8.760 h

com `FS = 0,7` (simultaneidade da geração solar ao meio-dia). Razão ≥ 1 indica exportação provável para a
subestação ao meio-dia.

## 5. Desenho de validação

**Backtest point-in-time.** Origem dez/2022, horizonte de 3 anos (alvo: dez/2025).

* O treino usa só janelas cujo resultado já era conhecido em dez/2022: (2019, h = 1 a 3), (2020, h = 1 e 2) e
  (2021, h = 1). 2018 não é origem porque cada origem precisa do snapshot anterior para o crescimento recente.
* As features de cada janela usam só o snapshot da origem e o anterior.
* O teste é feito nos 197 mil trafos com consumidores que **não** estavam saturados em 2022. "Saturou" significa
  que a GD de 2025 atingiu o kVA que o trafo tinha em 2022, mesmo que ele tenha sido trocado depois.

**Baselines.** Todos distribuem o mesmo total entre os trafos:

| Regra | Distribui o total proporcionalmente a | Quem usaria |
|---|---|---|
| Maior penetração hoje | GD já instalada no trafo | a regra intuitiva: "onde já tem muita GD, vai ter mais" |
| Proporcional ao último ano | GD adicionada no último ano | "o ritmo recente continua" |
| Proporcional aos consumidores | nº de UCs do trafo | "cada consumidor tem a mesma chance de instalar" |
| Persistência | nada (GD não cresce) | referência mínima |

**Métricas.**

* *Average precision* do ranking de quem satura: média da precisão em cada ponto da lista onde aparece um acerto.
  Uma lista aleatória teria average precision igual à taxa de saturação (13.241 / 197.077 ≈ 0,07).
* Acertos entre os *k* primeiros da lista (k = 1.000, 2.000, 5.000): quantos dos trafos priorizados saturaram.
* Erro absoluto médio do kW adicionado por trafo.
* R$ da lista: para os *k* primeiros, o custo de reforço dos que saturaram (com a GD de 2025) e o custo mínimo de
  troca dos que não saturaram (antecipado sem necessidade). A razão entre o primeiro e a soma dos dois é a
  "fração do R$ bem gasto" (`reports/resumo_decisao.csv`).
* Calibração da alocação por decil (`reports/calibracao_alocacao.csv`).

O backtest é avaliado duas vezes: com o **total observado** (isola a habilidade de alocação) e com o **total da
regra do último ano** (o que se saberia de fato em 2022).

**Validação externa.** Trafos saturados em 2022 foram trocados por um maior até 2025, em proporção maior que os
demais? A troca é identificada ligando os trafos de 2022 e 2025 pela posição e comparando o kVA.

## 6. Premissas

| Premissa | Valor | Fonte / justificativa | Efeito se mudar |
|---|---|---|---|
| Limite de saturação do trafo | GD ≥ 100% do kVA | indicador de risco de inversão de fluxo (a REN ANEEL 1.000/2021 permite exigir obra nesse caso) | muda quantos trafos são contados; a ordem da lista muda pouco |
| Nível de alerta | 80% do kVA | escolha do projeto | só o indicador de alerta |
| Fator de simultaneidade solar | 0,7 | premissa de triagem | **alto**: 19% (0,3) a 82% (0,9) dos alimentadores acima (`reports/sensibilidade_alimentadores.csv`) |
| Custo do trafo | R$ 300/kVA + R$ 8.000 por troca | ilustrativo | escala os R$; não muda acertos nem a comparação entre regras |
| Tamanhos padrão | 15 a 1.000 kVA | catálogo típico | custo de cada troca |
| Total de GD futura | ritmo do último ano | regra simples | no backtest subestimou 30%; muda o nº de trafos por ano, pouco a ordem |
| Horizonte de previsão | 3 anos | janelas observáveis no período | |

## 7. Como interpretar os resultados

* **Diagnóstico (nº de trafos saturados):** conta quantos trafos passaram do indicador. Não diz que cada um tem
  problema de tensão hoje; diz onde a chance é maior. A taxa de troca 3,6 vezes maior nos saturados indica que o
  indicador captura algo que a própria distribuidora trata.
* **Acertos entre os 1.000 primeiros:** é a métrica de decisão. Se o orçamento comporta 1.000 reforços
  preventivos, ela diz quantos teriam sido necessários. 802 de 1.000 significa que, a cada 5 trafos reforçados
  com a lista do modelo, 4 de fato saturaram até 2025.
* **Average precision:** resume a qualidade da lista inteira. O modelo (0,37) fica cerca de 5 vezes acima de uma
  lista aleatória (0,07) e à frente da melhor regra simples (0,33).
* **R$ bem gasto:** depende do custo ilustrativo, mas a comparação entre regras não, porque todas usam o mesmo
  custo. Leia como "que parte do orçamento antecipado iria para o lugar certo".
* **Projeção 2026-2030:** usa o ritmo de 2025 e custos ilustrativos. Serve como ordem de grandeza para o
  orçamento plurianual. O número de trafos por ano é mais incerto que a ordem da lista.
* **Alimentadores:** é triagem. O número exato depende do fator de simultaneidade; a conclusão robusta é que a GD
  total já supera a carga média em boa parte da rede.
