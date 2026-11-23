# Relatório Experimental — Extensão para Tarefas Esporádicas (`sporadic_stress_boundary_v1`)

> **Nota de Escopo Científico:** estes resultados referem-se exclusivamente à **extensão para cenários finitos offline de tarefas esporádicas** (`0 < C_i <= D_i <= T_i`, horizonte fechado por deadline `d <= H`), totalmente separados dos resultados periódicos originais em `resultados_artigo/`. Uma resposta `SAT` para uma ou `N` sequências finitas **não** constitui prova universal de escalonabilidade para todas as sequências esporádicas admissíveis.

## 1. Resumo Geral

- **Total de cenários esporádicos avaliados:** 36 (após 1 cenário(s) de aquecimento)
- **Limite de tempo por consulta (`timeout_ms`):** 2000 ms
- **Revisão de código (`git`):** `c920bdd`
- **Ambiente:** Python `3.10.19`, Z3 `5.4.1`, `Linux-7.0.0-42-generic-x86_64-with-glibc2.39`
- **Concordância (nos 36 pares concluídos por ambos):** **36/36 (100.0%)**
- **Divergências detectadas (SAT vs. UNSAT):** `0`

| Métrica | Xu & Parnas | SMT/Z3 |
|---|---:|---:|
| `SAT` (viável) | 26 | 26 |
| `UNSAT` (inviável) | 10 | 10 |
| `TIMEOUT` (inconclusivo) | 0 | 0 |
| `UNKNOWN` | 0 | 0 |
| Escalas `SAT` aprovadas no verificador independente | 26/26 | 26/26 |
| Tempo de planejamento — Mediana (ms) | 3.269 | 53.559 |
| Tempo de planejamento — p95 (ms) | 9.890 | 232.061 |
| Tempo de planejamento — Máximo (ms) | 10.226 | 247.858 |
| Tempo de planejamento — IQR (ms) | 3.715 | 65.029 |
| Tempo médio de preparação (gerador + adaptador, ms) | 0.653 | 0.653 |
| Máximo de nós expandidos | 1 | N/A |

## 2. Resultados Agrupados por Configuração

| `N` | `H` | Carga | Padrão | Jitter | Jobs (med.) | Unid. (med.) | `U_nom` | `U_efet` | Xu (SAT/UNSAT/TO) | Xu med. (ms) | Z3 (SAT/UNSAT/TO) | Z3 med. (ms) |
|---:|---:|---|---|---|---:|---:|---:|---:|---|---:|---|---:|
| 3 | 50 | fronteira_critica | bursty | J_half | 12.0 | 40.0 | 0.97 | 0.80 | 3/0/0 | 1.25 | 3/0/0 | 24.33 |
| 3 | 50 | fronteira_critica | jittered | J_half | 11.7 | 39.0 | 0.97 | 0.78 | 1/2/0 | 1.16 | 1/2/0 | 23.54 |
| 3 | 50 | fronteira_critica | min_interval | J0 | 14.0 | 47.0 | 0.97 | 0.94 | 3/0/0 | 1.59 | 3/0/0 | 30.32 |
| 3 | 100 | fronteira_critica | bursty | J_half | 23.0 | 77.0 | 0.97 | 0.77 | 0/3/0 | 3.50 | 0/3/0 | 54.41 |
| 3 | 100 | fronteira_critica | jittered | J_half | 22.7 | 76.0 | 0.97 | 0.76 | 2/1/0 | 3.70 | 2/1/0 | 53.86 |
| 3 | 100 | fronteira_critica | min_interval | J0 | 29.0 | 97.0 | 0.97 | 0.97 | 0/3/0 | 6.10 | 0/3/0 | 87.56 |
| 5 | 50 | fronteira_critica | bursty | J_half | 10.0 | 34.0 | 0.98 | 0.68 | 3/0/0 | 1.73 | 3/0/0 | 22.73 |
| 5 | 50 | fronteira_critica | jittered | J_half | 11.3 | 38.3 | 0.98 | 0.77 | 3/0/0 | 2.19 | 3/0/0 | 32.73 |
| 5 | 50 | fronteira_critica | min_interval | J0 | 14.0 | 48.0 | 0.98 | 0.96 | 3/0/0 | 2.90 | 3/0/0 | 91.06 |
| 5 | 100 | fronteira_critica | bursty | J_half | 24.0 | 82.0 | 0.98 | 0.82 | 3/0/0 | 7.09 | 3/0/0 | 146.19 |
| 5 | 100 | fronteira_critica | jittered | J_half | 22.3 | 76.0 | 0.98 | 0.76 | 2/1/0 | 4.86 | 2/1/0 | 65.33 |
| 5 | 100 | fronteira_critica | min_interval | J0 | 29.0 | 99.0 | 0.98 | 0.99 | 3/0/0 | 10.04 | 3/0/0 | 234.83 |

## 3. Limitações Científicas Declaradas

1. **Cenários finitos offline ≠ garantia universal:** `SAT` certifica apenas que a sequência concreta de liberações avaliada dentro do horizonte `H` admite escala válida; não prova escalonabilidade para todas as sequências esporádicas admissíveis.
2. **Contraexemplos `UNSAT`:** uma resposta `UNSAT` para uma sequência esporádica válida demonstra que aquela sequência específica não é escalonável sob as restrições modeladas (servindo de contraexemplo caso se deseje viabilidade universal).
3. **Operação online:** ambos os planejadores operam *offline* conhecendo as liberações do cenário de antemão, não sendo escalonadores *online* para chegadas imprevisíveis.
4. **Escopo de deadlines restritos:** esta bateria adota `0 < C_i <= D_i <= T_i` e política de horizonte `d <= H` (com registro explícito das ativações descartadas).
5. **Carga nominal vs. efetiva:** `U_nom = sum(C_i / T_i)` é apenas um indicador assintótico e não decide isoladamente a viabilidade na presença de segmentos, precedências, exclusões direcionais e horizonte finito.

## 4. Figuras Geradas

- `fig_esporadica_padroes.png`
- `fig_esporadica_unidades.png`
