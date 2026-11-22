# Guia de Resultados Experimentais para o Artigo

Este documento consolida todos os resultados experimentais gerados pelo projeto **Análise Comparativa do Escalonamento Pré-Execução de Processos em Tempo Real utilizando SMT/Z3**, explica o significado científico de cada experimento e apresenta sugestões prontas de **estrutura textual e comandos LaTeX (padrão IEEEtran)** para a seção **VII. Resultados e Discussão** do artigo.

> **Reprodutibilidade:** todos os dados brutos (`.json`), tabelas (`.csv` e `.tex`) e figuras (`.png` em 300 DPI e `.pdf` vetorial para LaTeX) presentes nesta pasta foram gerados de forma determinística pelo script [`scripts/gerar_resultados_artigo.py`](../scripts/gerar_resultados_artigo.py) no ambiente **Python 3.10.19**, **Z3 5.4.1**, **Linux x86\_64**.

---

## Mapa dos Artefatos Gerados

| Bloco do Artigo | Tabela (`.csv` / `.tex`) | Figura (`.png` / `.pdf`) | Dados Brutos (`.json`) |
|---|---|---|---|
| **A. Validação de Fidelidade e Conformidade (OE2–OE4)** | `tabelas/tabela1_validacao_cruzada.*` | — | `dados_brutos/validacao_cruzada.json` |
| **B. Escalas na Aplicação de Temperatura (Qualitativo)** | — | `figuras/fig1_gantt_temperatura.*` | `dados_brutos/benchmark_referencia.json` |
| **C. Desempenho nas Instâncias de Referência (OE5)** | `tabelas/tabela2_desempenho_referencia.*` | `figuras/fig2_desempenho_referencia.*` | `dados_brutos/benchmark_referencia.json` |
| **D. Escalabilidade por Unidades Discretas (`U`) (OE5)** | `tabelas/tabela3_escalabilidade_unidades.*` | `figuras/fig3_escalabilidade_unidades.*` | `dados_brutos/escalabilidade_unidades.json` |
| **E. Escalabilidade por Segmentos (`N`) e Conflitos (OE5)** | `tabelas/tabela4_escalabilidade_segmentos.*` | `figuras/fig4_escalabilidade_segmentos.*` | `dados_brutos/escalabilidade_segmentos_conflitos.json` |
| **F. Viabilidade vs. Otimização de `Lmax` (OE5)** | `tabelas/tabela5_viabilidade_vs_otimizacao.*` | — | `dados_brutos/viabilidade_vs_otimizacao.json` |
| **G. Calibração, Execução Real e Diagnósticos (OE4)** | `tabelas/tabela6_execucao_real_e_calibracao.*` | `figuras/fig5_execucao_temporizada.*` | `dados_brutos/calibracao.json`, `execucao_*.json`, `diagnostico_falhas.json` |

---

## 1. Validação Cruzada de Fidelidade e Conformidade

**Arquivos:** `tabelas/tabela1_validacao_cruzada.csv`, `tabelas/tabela1_validacao_cruzada.tex`, `dados_brutos/validacao_cruzada.json`

### Resumo dos Números Obtidos

| Caso / Lote | Seg. / Unid. | Oráculo | Xu & Parnas | SMT/Z3 | `Lmax` (Xu / Z3) | Concordância |
|---|---:|---|---|---|---|---:|
| `temperature_case_v1` | 9 / 19 | — | Viável | Viável | `-1 / -1` | 100% |
| `xu_parnas_example_1 (G1)` | 4 / 80 | — | Viável | Viável | `0 / 0` | 100% |
| `xu_parnas_example_2 (G2)` | 3 / 100 | — | Viável | Viável | `0 / 0` | 100% |
| `preempcao_sem_EX` | 2 / 3 | Viável | Viável | Viável | `0 / 0` | 100% |
| `exclusao_dir_A_EX_B` | 2 / 3 | Inviável | Inviável | Inviável | `1 / --` | 100% |
| `exclusao_dir_B_EX_A` | 2 / 3 | Viável | Viável | Viável | `0 / 0` | 100% |
| `inviavel_ciclo_PC` | 2 / 4 | Inviável | Inviável | Inviável | `-- / --` | 100% |
| `inviavel_sobrecarga` | 2 / 7 | Inviável | Inviável | Inviável | `2 / --` | 100% |
| **Lote aleatório viabilidade (`N=100`)** | 2–4 / 2–12 | **48V / 52I** | **100 / 100** | **100 / 100** | — | **100,0%** |
| **Lote aleatório `min Lmax` (`N=30`)** | 2–4 / 2–12 | **Ótimo** | **30 / 30** | **30 / 30** | **Exato** | **100,0%** |

### O que este resultado prova
1. **Fidelidade bidirecional comprovada empiricamente:** a formulação SMT/Z3 e a implementação de Xu & Parnas concordaram em **100% dos 108 casos de viabilidade** e em **100% dos 30 casos de otimização exata de `Lmax`**, com **0 escalas inválidas** segundo o verificador independente.
2. **Semântica direcional de `EXCLUDES` preservada:** no caso de preempção obrigatória (`A(r=0,C=2,d=3)`, `B(r=1,C=1,d=2)`), adicionar apenas `A EXCLUDES B` torna a instância **inviável**, enquanto adicionar apenas `B EXCLUDES A` mantém a **viabilidade** (pois `A` inicia antes de `B`, satisfazendo vacuamente `s[B] < s[A] => f[B] <= s[A]`).
3. **Validação das ramificações clássicas:** os Exemplos 1 e 2 do Apêndice 3 de Xu & Parnas (1990) comprovam que tanto a ramificação `G1` (`PC(C,A)`) quanto a ramificação `G2` com relações auxiliares e preempção (`PC(B,A)` e `PM(C,A)`) funcionam fielmente.

### Como apresentar no artigo (subseção *A. Validação de Fidelidade e Conformidade*)
> *Sugestão de texto:* "Para assegurar que a formulação SMT/Z3 preserva integralmente as hipóteses do modelo de Xu e Parnas [1], ambas as abordagens foram auditadas por um verificador independente e confrontadas com um oráculo enumerativo exaustivo. Conforme sintetizado na Tabela~\ref{tab:validacao_cruzada}, obteve-se concordância de 100\% tanto nos casos estruturais de referência — incluindo exclusão direcional assimétrica, ciclos de precedência, sobrecarga e os Exemplos 1 e 2 de [1] — quanto em um lote aleatório de 100 instâncias (48 viáveis e 52 inviáveis) em modo de viabilidade e 30 instâncias em minimização exata de $L_{\max}$, sem ocorrência de escalas inválidas."

---

## 2. Comparação das Escalas na Aplicação de Temperatura

**Arquivos:** `figuras/fig1_gantt_temperatura.pdf` (para LaTeX), `figuras/fig1_gantt_temperatura.png`

### O que a Figura 1 mostra
- **Escala de Xu & Parnas (`Lmax = -1`):** `A1 [0–2)`, `A2 [2–3)`, `A3 [3–6)`, `A4 [6–10)`, **`S [10–12)`**, `A8 [12–15)`, `A5 [15–16)`, `A6 [16–17)`, **`A7 [17–19)`**.
  - `S` executa antes de `A7`, copiando de forma consistente o estado inicial **`E0` (versão 0)**; posteriormente `A7` publica a versão 1 sem interferir na gravação já realizada por `A8`.
- **Escala de SMT/Z3 (`Lmax = -1`):** `A1 [0–2)`, `A2 [2–3)`, `A3 [3–6)`, `A4 [6–10)`, `A5 [10–11)`, `A6 [11–12)`, **`A7 [12–14)`**, **`S [14–16)`**, `A8 [16–19)`.
  - `A7` conclui antes de `S`, permitindo que `P3` capture e grave de forma consistente a **versão 1** (bloco atual).

### Por que isso é importante para o artigo
Demonstra na prática um ponto conceitual elegante do Método Proposto: **existência de múltiplas escalas válidas com comportamentos funcionais distintos, porém igualmente consistentes**. Por não impor artificialmente `A7 → S`, o escalonador tem liberdade para ordenar `A7` e `S` sem intercalá-los (`A7 EXCLUDES S` e `S EXCLUDES A7`), preservando integridade em ambos os casos.

### Como inserir no LaTeX
```latex
\begin{figure*}[t]
    \centering
    \includegraphics[width=0.95\textwidth]{figuras/fig1_gantt_temperatura.pdf}
    \caption{Escalas vi\'aveis produzidas por Xu \& Parnas e SMT/Z3 para a aplica\c{c}\~ao de monitoramento de temperatura ($L_{\max} = -1$). Ambas respeitam as preced\^encias e a exclus\~ao m\'utua $A_7 \leftrightarrow S$, resultando no registro consistente da vers\~ao 0 ($E_0$) em Xu \& Parnas e da vers\~ao 1 em SMT/Z3.}
    \label{fig:gantt_temperatura}
\end{figure*}
```

---

## 3. Desempenho de Planejamento nas Instâncias de Referência

**Arquivos:** `tabelas/tabela2_desempenho_referencia.*`, `figuras/fig2_desempenho_referencia.*`, `dados_brutos/benchmark_referencia.json`

### Resumo dos Números Obtidos (15 repetições alternadas, 3 aquecimentos, modo `feasibility`)

| Instância | Seg. / Unid. | Xu & Parnas med. `[min–max]` | Nós (ger./exp.) | Z3 *build* | Z3 *check* | Z3 total med. `[min–max]` | Razão Z3 / Xu |
|---|---:|---:|---:|---:|---:|---:|---:|
| `temperature_case_v1` | 9 / 19 | **0,443 ms** `[0,398–0,899]` | 1 / 0 | 4,138 ms | 3,969 ms | **12,186 ms** `[9,755–14,404]` | **27,5×** |
| `xu_parnas_example_1` | 4 / 80 | **0,692 ms** `[0,633–1,465]` | 2 / 1 | 11,235 ms | 57,725 ms | **73,704 ms** `[64,842–95,766]` | **106,5×** |
| `xu_parnas_example_2` | 3 / 100 | **1,029 ms** `[0,918–2,282]` | 3 / 1 | 13,930 ms | 122,282 ms | **142,627 ms** `[136,216–148,193]` | **138,7×** |

### Interpretação científica
- Nas três instâncias clássicas, o algoritmo de **Xu & Parnas** permanece na faixa de **0,44 ms a 1,03 ms**, expandindo no máximo 1 nó da árvore *branch-and-bound*.
- No **SMT/Z3**, o tempo total sobe de **12,19 ms** (19 unidades) para **73,70 ms** (80 unidades) e **142,63 ms** (100 unidades) — um custo de **27× a 139× maior**.
- A decomposição de tempos revela a causa: além do custo fixo de inicialização do contexto/solucionador e da construção da fórmula (`build`: 4,1 ms → 13,9 ms), o tempo de consulta (`check`) cresce acentuadamente (3,97 ms → 122,28 ms) à medida que aumenta o número de variáveis unitárias dentro da restrição global `Distinct`.

---

## 4. Escalabilidade por Granularidade Discreta (`U`) vs. Conflitos entre Segmentos (`N`)

### 4.1 Escalabilidade por Demanda Discreta (`temperature_case_v1` escalado por `k`)
**Arquivos:** `tabelas/tabela3_escalabilidade_unidades.*`, `figuras/fig3_escalabilidade_unidades.*`

| Fator `k` | Unidades (`U`) | Xu & Parnas (med.) | Z3 *build* | Z3 *check* | Z3 total (med.) | Razão Z3 / Xu |
|---:|---:|---:|---:|---:|---:|---:|
| `1×` | 19 | 0,773 ms | 3,568 ms | 3,592 ms | 15,606 ms | 20,2× |
| `2×` | 38 | 0,522 ms | 6,881 ms | 12,794 ms | 27,308 ms | 52,3× |
| `3×` | 57 | 0,774 ms | 9,451 ms | 24,985 ms | 41,209 ms | 53,2× |
| `4×` | 76 | 1,186 ms | 12,900 ms | 43,236 ms | 65,733 ms | 55,4× |
| `6×` | 114 | 0,805 ms | 16,290 ms | 113,841 ms | 135,131 ms | 167,9× |
| `8×` | 152 | 1,130 ms | 21,394 ms | 8,185 ms | 36,145 ms | 32,0× |

**Ponto forte para discussão no artigo:**
1. Mantendo exatamente os mesmos **9 segmentos**, aumentar a granularidade temporal de `19` para `152` unidades mantém Xu & Parnas praticamente **constante** (`~0,5–1,2 ms`), porque a rotina avança por eventos de liberação/conclusão de segmentos.
2. Já no SMT/Z3, o tempo de **construção da fórmula cresce linearmente** com `U` (`3,57 → 21,39 ms`), enquanto o tempo de **busca apresenta forte variabilidade heurística** (cresce até `113,84 ms` em `6×` e cai para `8,19 ms` em `8×` conforme a ordem de decisão interna do CDCL/aritmética linear do Z3). Esse comportamento não-monotônico do tempo de resolução é um achado característico de solucionadores SMT e reforça a menor previsibilidade do custo de planejamento em comparação ao algoritmo clássico.

### 4.2 Escalabilidade por Número de Segmentos (`N`) com Alta Densidade de Exclusões (`~45%`)
**Arquivos:** `tabelas/tabela4_escalabilidade_segmentos.*`, `figuras/fig4_escalabilidade_segmentos.*`

| Segmentos (`N`) | Viáveis / Inviáveis | Concordância | Xu med. (máx.) ms | Máx. nós exp. | Z3 med. (máx.) ms | Timeouts (Xu/Z3) |
|---:|---|---:|---:|---:|---:|---:|
| 4 | 4V / 2I | 6 / 6 | 0,255 (0,318) | 0 | 13,200 (15,709) | 0 / 0 |
| 6 | 3V / 3I | 6 / 6 | 0,405 (0,590) | 0 | 12,445 (13,110) | 0 / 0 |
| 8 | 3V / 3I | 6 / 6 | 0,435 (0,545) | 0 | 13,513 (20,643) | 0 / 0 |
| 10 | 3V / 3I | 6 / 6 | 0,692 (2,065) | 1 | 18,375 (22,094) | 0 / 0 |
| 12 | 3V / 3I | 6 / 6 | 1,490 (10,679) | 3 | 20,901 (327,173) | 0 / 0 |

**Ponto forte para discussão no artigo:**
- Mesmo na região de transição de fase (~50% viáveis, ~50% inviáveis) com alta densidade de exclusões direcionais (`~45%`), houve **100% de concordância** (30/30) e **0 timeouts** no limite de 5 s.
- Os limites inferiores (`LB1`/`LB2` com `GAP`) de Xu & Parnas podaram agressivamente a árvore (máximo de 3 nós expandidos em `N=12`, pico de `10,68 ms`), enquanto o SMT/Z3 apresentou cauda longa em instâncias combinatoriamente difíceis (pico de **`327,17 ms`** em `N=12`).

---

## 5. Decisão de Viabilidade (`feasibility`) vs. Otimização (`min_lmax`)

**Arquivos:** `tabelas/tabela5_viabilidade_vs_otimizacao.*`, `dados_brutos/viabilidade_vs_otimizacao.json`

| Instância | Unid. (`U`) | Xu viab. (ms) | Xu `min_lmax` (ms) | Z3 viab. (ms) | Z3 `min_lmax` (ms) | `Lmax*` (Xu / Z3) |
|---|---:|---:|---:|---:|---:|---:|
| `temperature_case_v1` | 19 | 0,450 | 0,598 | 12,576 | 36,254 | `-1 / -1` |
| `xu_parnas_example_1` | 80 | 0,690 | 0,703 | 76,975 | 27,202 | `0 / 0` |
| `xu_parnas_example_2` | 100 | 1,141 | 1,015 | 147,141 | **3341,221** | `0 / 0` |
| `inviavel_exclusao_apertada` | 10 | 0,191 | 0,178 | 7,467 | 9,662 | `3 / 3` |

### O que destacar no artigo
- Os dois métodos obtiveram exatamente o **mesmo valor ótimo global `Lmax*`** nas quatro instâncias (inclusive na instância inviável, onde `Lmax* = +3`).
- Em **Xu & Parnas**, o custo entre viabilidade e otimização é praticamente idêntico porque o algoritmo já calcula limites inferiores para `Lmax` nativamente.
- No **SMT/Z3**, migrar de `z3.Solver` (viabilidade) para `z3.Optimize` (OMT) introduz um salto expressivo no pior caso: em `xu_parnas_example_2` (100 unidades com preempção), o tempo passou de **147,14 ms** para **3,34 segundos** (~22,7× mais lento que a própria consulta de viabilidade e >3000× mais lento que Xu & Parnas). Isso confirma a recomendação metodológica de **nunca misturar medições de viabilidade com otimização completa**.

---

## 6. Execução Real da Aplicação, Calibração Física e Diagnósticos de Falha

**Arquivos:** `tabelas/tabela6_execucao_real_e_calibracao.*`, `figuras/fig5_execucao_temporizada.*`, `dados_brutos/calibracao.json`, `dados_brutos/diagnostico_falhas.json`

### Resumo dos Números Obtidos
- **Calibração empírica (30 repetições + 5 aquecimentos, 570 medições unitárias reais):**
  - Duração unitária observada: mediana `0,019 ms`, p95 `0,082 ms`, p99 `0,207 ms`, máximo **`0,472 ms`** (em `A8:1`, formatação e abertura de arquivo).
  - Latência de despacho (*probe*): mediana `0,001 ms`, p95 `0,004 ms`, máximo `1,406 ms` (pico esporádico de escalonador do SO).
  - Quantum físico calibrado adotado para ambos os métodos: **`q = 3,400 ms`** (fator de segurança 4× + margem documentada).
- **Execução temporizada das duas escalas sob o mesmo `q = 3,400 ms`:**

| Métrica | Xu & Parnas (Temporizado) | SMT/Z3 (Temporizado) |
|---|---:|---:|
| Status da execução | `ok` | `ok` |
| Unidades executadas | 19 / 19 | 19 / 19 |
| Tempo total *wall* | 63,230 ms | 63,693 ms |
| Tempo total de CPU | 20,658 ms | 20,240 ms |
| Maior duração real de unidade | 0,691 ms | 0,429 ms |
| Maior atraso de despacho | 0,019 ms | 0,018 ms |
| Maior excesso de slot | **0,000 ms** | **0,000 ms** |
| Todos os *deadlines* físicos atendidos | **Sim** | **Sim** |
| Erro numérico máx. vs. referência sequencial | **`0,00e+00`** | **`0,00e+00`** |
| Versão final do estado compartilhado (`A7`) | `1` | `1` |
| Versão registrada por `P3` (`A8`) | **`0` (`E0`)** | **`1` (bloco atual)** |

- **Indicadores funcionais calculados sobre `temperatures.csv` (idênticos à referência sequencial):**
  - `count = 120`, `min = 24,0 °C`, `max = 35,7 °C`, `mean = 29,754 °C`, `variance = 11,951`, alerta `alerta_ativo`, ventilação `ligado`.
- **Verificação de diagnósticos deliberados de falha (`dados_brutos/diagnostico_falhas.json`):**
  1. **Atraso deliberado em `A2` (`12 ms > q = 3,4 ms`):** o executor interrompeu imediatamente e classificou como `runtime_budget_violation` (excesso medido de `8,796 ms` no tick `t=2`).
  2. **Escala propositalmente inválida intercalando `A7` e `S`:** rejeitada antes da execução pelo verificador (`Exclusion violated for (A7 EXCLUDES S)`), e quando forçada em modo de teste (`allow_invalid_schedule=True`), capturada em tempo de execução por `S` com `StateConsistencyError` (`v1=0, u1=1, v2=1, u2=1`).

---

## 7. Roteiro Pronto para Escrever a Seção VII (*Resultados e Discussão*) no Artigo

Para encaixar perfeitamente no formato IEEE duas colunas do artigo de vocês, sugere-se esta sequência exata:

1. **VII-A. Ambiente Experimental e Validação de Fidelidade:**
   - Citar especificações (Python 3.10.19, Z3 5.4.1, Linux x86\_64, protocolo alternado com aquecimento) e inserir `\input{tabelas/tabela1_validacao_cruzada.tex}`.
2. **VII-B. Análise das Escalas na Aplicação de Monitoramento de Temperatura:**
   - Inserir `figuras/fig1_gantt_temperatura.pdf` e explicar a equivalência de viabilidade (`Lmax = -1`) com versões distintas e igualmente consistentes registradas por `P3` (`v0` vs. `v1`).
3. **VII-C. Desempenho Computacional e Escalabilidade:**
   - Inserir `\input{tabelas/tabela2_desempenho_referencia.tex}`, `figuras/fig2_desempenho_referencia.pdf`, `figuras/fig3_escalabilidade_unidades.pdf` (ou Tabela 3), `figuras/fig4_escalabilidade_segmentos.pdf` (ou Tabela 4) e `\input{tabelas/tabela5_viabilidade_vs_otimizacao.tex}`.
   - Discutir o **trade-off central do artigo**:
     - **SMT/Z3** vence em **clareza declarativa, rapidez de prototipagem e facilidade de extensão** para novas restrições (como extensões futuras para tarefas esporádicas — OE6), mantendo 100% de fidelidade;
     - **Xu & Parnas** vence amplamente em **desempenho e escalabilidade** (de ~20× a >100× mais rápido em viabilidade, e >3000× na otimização de `xu_parnas_example_2`), sobretudo quando as demandas discretas `C_i` são grandes, pois raciocina no nível de segmentos enquanto a codificação unitária em SMT/Z3 cresce com o total de unidades `U`.
4. **VII-D. Calibração e Execução Real Observada:**
   - Inserir `\input{tabelas/tabela6_execucao_real_e_calibracao.tex}` e `figuras/fig5_execucao_temporizada.pdf`, reportando o cumprimento dos *deadlines* físicos, erro numérico nulo (`0,00e+00`), detecção dos cenários de falha deliberada e a ressalva metodológica de que a execução em Python/SO de propósito geral é experimental e não substitui certificação de tempo real rígido nem prova formal de WCET.
