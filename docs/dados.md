# Decisões de dados

Registro das escolhas de tratamento que afetam os resultados, com a evidência de cada uma.

## Fontes

| Fonte | Uso | Acesso |
|---|---|---|
| BDGD (PRODIST Módulo 10), Energisa MT, snapshots de 31/12 de 2018 a 2025 | Trafos (kVA, alimentador, município, posição), GD de BT e MT, consumidores e energia | ArcGIS Hub da ANEEL, um `.gdb` de ~1 GB por ano |
| Relação de empreendimentos de geração distribuída (ANEEL) | Potência oficial de cada GD pelo código CEG | `dadosabertos.aneel.gov.br`, Parquet |
| Pedidos de conexão de MMGD, região Centro-Oeste (ANEEL) | Validação externa: pedidos com necessidade de obra | `dadosabertos.aneel.gov.br`, Parquet |

## Transformadores

* **Universo:** trafos MT/BT ativos (`UNTRMT`; `UNTRD` no modelo antigo M10). O diagnóstico e o backtest
  usam só os trafos com ao menos uma unidade consumidora de BT (~75% do total). Os demais são trafos sem
  consumidor cadastrado: iluminação, bombeamento rural, reserva etc.
* **Potência:** `POT_NOM` já vem em kVA nos snapshots usados (5, 10, 15, 30, 45, 75, 112,5...).
* **IDs instáveis:** o `COD_ID` dos trafos mudou entre os snapshots (só 0,05% dos códigos de 2022 existem em
  2025). O mesmo trafo é reconhecido pela posição: **vizinho mais próximo mútuo a até 20 m**. Entre 2022 e
  2025 isso liga 99,1% dos trafos; nos pares ligados, 91,5% mantêm o mesmo kVA e só 0,5% perdem GD, o que
  confirma que a ligação acerta o trafo.

## Geração distribuída

* **BT, modelo novo (2021-2025):** `UGBT_tab`, ligada ao trafo por `UNI_TR_MT`.
* **BT, modelo antigo (2018-2020):** a camada `UGBT_tab` da distribuidora vem **vazia**. As unidades com GD são
  reconstruídas pelas UCs de BT que têm código CEG de GD (`UCBT_tab.CEG` começando com `GD`), ligadas ao
  trafo por `UNI_TR_D`.
* **Potência:** sempre que o código CEG existe no registro de empreendimentos da ANEEL, vale a potência do
  registro (fonte oficial, mesma unidade em todos os anos). Sem registro, vale a potência da BDGD **se for
  compatível com microgeração (até 75 kW)**. Em 2025 há ~2.400 unidades de BT com potência acima disso (até
  43 MW numa única "microgeração") que não estão no registro; elas ficam de fora (`NaN`). Sem essa regra, a
  GD de BT de 2025 seria ~1,3 GW maior, um valor implausível.
* **Efeito colateral do registro:** ele traz a potência atual. Ampliações posteriores de uma mesma GD apareceriam
  em snapshots antigos. É raro em microgeração e não afeta a ligação temporal das unidades, que vem do snapshot.
* **MT:** `UGMT_tab`, só unidades com CEG de GD (PCHs e térmicas ficam de fora), com a mesma regra de potência e
  limite de 5 MW (minigeração). O snapshot de 2024 tem uma unidade cadastrada com 125 GW; a regra a descarta.

## Critério de saturação (premissa, `configs/premissas.yaml`)

* **Trafo:** GD de BT instalada ≥ 100% da potência nominal (kW ≥ kVA). A REN ANEEL 1.000/2021 permite à
  distribuidora exigir obras quando a conexão provoca inversão do fluxo de potência no posto de
  transformação; este é um indicador simples desse risco, não o critério de planejamento de nenhuma
  distribuidora. Também é reportado o nível de alerta de 80%.
* **Alimentador:** GD total (BT + MT) x 0,7 (simultaneidade da geração solar ao meio-dia) comparada à carga
  média do alimentador (consumo anual faturado de BT e MT / 8.760 h). Acima de 1, o meio-dia tende a exportar
  energia para a subestação. É um indicador de triagem: a carga ao meio-dia e a curva real de geração variam
  por alimentador.

## Corte temporal do backtest

* Origem dez/2022, horizonte de 3 anos (alvo: GD em dez/2025, no trafo ligado pela posição).
* Treino só com janelas (origem, horizonte) cujo alvo já era conhecido em dez/2022: (2019, 1-3), (2020, 1-2),
  (2021, 1). Cada origem usa o snapshot anterior para o crescimento recente, então 2018 não é origem.
* Features da origem: só o snapshot de dez/origem e o anterior. O alvo do treino é a fração do crescimento do
  sistema que caiu em cada trafo naquela janela, o que torna janelas de anos diferentes comparáveis.

## Alimentadores

* GD de MT só aparece na BDGD da distribuidora a partir de 2021 (no modelo M10, `UGMT_tab` só traz PCHs e
  térmicas). O crescimento de MT por alimentador usa 2022-2025, ligando os alimentadores pelo nome operacional
  (estável em 98,7% dos casos; o `COD_ID` muda).
