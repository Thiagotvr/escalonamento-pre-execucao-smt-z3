# Relatório Experimental — Extensão para Tarefas Esporádicas (`sporadic_pilot_v1`)

> **Nota de Escopo Científico:** estes resultados referem-se exclusivamente à **extensão para cenários finitos offline de tarefas esporádicas** (`0 < C_i <= D_i <= T_i`, horizonte fechado por deadline `d <= H`), totalmente separados dos resultados periódicos originais em `resultados_artigo/`. Uma resposta `SAT` para uma ou `N` sequências finitas **não** constitui prova universal de escalonabilidade para todas as sequências esporádicas admissíveis.

## 1. Resumo Geral

- **Total de cenários esporádicos avaliados:** 96 (após 1 cenário(s) de aquecimento)
- **Limite de tempo por consulta (`timeout_ms`):** 3000 ms
- **Revisão de código (`git`):** `c920bdd`
- **Ambiente:** Python `3.10.19`, Z3 `5.4.1`, `Linux-7.0.0-42-generic-x86_64-with-glibc2.39`
- **Concordância (nos 80 pares concluídos por ambos):** **80/80 (100.0%)**
- **Divergências detectadas (SAT vs. UNSAT):** `0`

| Métrica | Xu & Parnas | SMT/Z3 |
|---|---:|---:|
| `SAT` (viável) | 64 | 64 |
| `UNSAT` (inviável) | 32 | 16 |
| `TIMEOUT` (inconclusivo) | 0 | 16 |
| `UNKNOWN` | 0 | 0 |
| Escalas `SAT` aprovadas no verificador independente | 64/64 | 64/64 |
| Tempo de planejamento — Mediana (ms) | 1.462 | 22.335 |
| Tempo de planejamento — p95 (ms) | 6.441 | 3017.534 |
| Tempo de planejamento — Máximo (ms) | 9.571 | 3023.528 |
| Tempo de planejamento — IQR (ms) | 2.268 | 27.701 |
| Tempo médio de preparação (gerador + adaptador, ms) | 0.527 | 0.527 |
| Máximo de nós expandidos | 0 | N/A |

## 2. Resultados Agrupados por Configuração

| `N` | `H` | Carga | Padrão | Jitter | Jobs (med.) | Unid. (med.) | `U_nom` | `U_efet` | Xu (SAT/UNSAT/TO) | Xu med. (ms) | Z3 (SAT/UNSAT/TO) | Z3 med. (ms) |
|---:|---:|---|---|---|---:|---:|---:|---:|---|---:|---|---:|
| 3 | 50 | alta | bursty | J0 | 12.0 | 40.0 | 0.96 | 0.80 | 0/2/0 | 1.42 | 0/2/0 | 22.04 |
| 3 | 50 | alta | bursty | J_half | 12.0 | 40.0 | 0.96 | 0.80 | 0/2/0 | 1.58 | 0/2/0 | 21.14 |
| 3 | 50 | alta | jittered | J_half | 11.5 | 38.0 | 0.96 | 0.76 | 0/2/0 | 1.30 | 0/2/0 | 20.86 |
| 3 | 50 | alta | min_interval | J0 | 14.0 | 46.0 | 0.96 | 0.92 | 0/2/0 | 1.71 | 0/2/0 | 25.31 |
| 3 | 50 | baixa | bursty | J0 | 7.0 | 14.0 | 0.37 | 0.28 | 2/0/0 | 0.45 | 2/0/0 | 9.58 |
| 3 | 50 | baixa | bursty | J_half | 7.0 | 14.0 | 0.37 | 0.28 | 2/0/0 | 0.40 | 2/0/0 | 9.48 |
| 3 | 50 | baixa | jittered | J_half | 7.0 | 14.0 | 0.37 | 0.28 | 2/0/0 | 0.43 | 2/0/0 | 10.10 |
| 3 | 50 | baixa | min_interval | J0 | 8.0 | 16.0 | 0.37 | 0.32 | 2/0/0 | 0.49 | 2/0/0 | 12.32 |
| 3 | 50 | media | bursty | J0 | 10.0 | 26.0 | 0.63 | 0.52 | 2/0/0 | 0.89 | 2/0/0 | 12.29 |
| 3 | 50 | media | bursty | J_half | 10.0 | 26.0 | 0.63 | 0.52 | 2/0/0 | 0.89 | 2/0/0 | 12.28 |
| 3 | 50 | media | jittered | J_half | 8.5 | 22.5 | 0.63 | 0.45 | 2/0/0 | 0.74 | 2/0/0 | 11.39 |
| 3 | 50 | media | min_interval | J0 | 11.0 | 29.0 | 0.63 | 0.58 | 2/0/0 | 1.08 | 2/0/0 | 13.83 |
| 3 | 100 | alta | bursty | J0 | 24.0 | 80.0 | 0.96 | 0.80 | 0/2/0 | 4.07 | 0/2/0 | 56.05 |
| 3 | 100 | alta | bursty | J_half | 24.0 | 80.0 | 0.96 | 0.80 | 0/2/0 | 3.90 | 0/2/0 | 56.60 |
| 3 | 100 | alta | jittered | J_half | 22.5 | 74.5 | 0.96 | 0.74 | 0/2/0 | 3.53 | 0/2/0 | 49.98 |
| 3 | 100 | alta | min_interval | J0 | 29.0 | 96.0 | 0.96 | 0.96 | 0/2/0 | 5.51 | 0/2/0 | 77.90 |
| 3 | 100 | baixa | bursty | J0 | 15.0 | 30.0 | 0.37 | 0.30 | 2/0/0 | 1.15 | 2/0/0 | 19.60 |
| 3 | 100 | baixa | bursty | J_half | 15.0 | 30.0 | 0.37 | 0.30 | 2/0/0 | 1.14 | 2/0/0 | 19.74 |
| 3 | 100 | baixa | jittered | J_half | 14.5 | 29.0 | 0.37 | 0.29 | 2/0/0 | 1.16 | 2/0/0 | 18.68 |
| 3 | 100 | baixa | min_interval | J0 | 18.0 | 36.0 | 0.37 | 0.36 | 2/0/0 | 1.55 | 2/0/0 | 25.94 |
| 3 | 100 | media | bursty | J0 | 19.0 | 50.0 | 0.63 | 0.50 | 2/0/0 | 2.13 | 2/0/0 | 28.12 |
| 3 | 100 | media | bursty | J_half | 19.0 | 50.0 | 0.63 | 0.50 | 2/0/0 | 2.11 | 2/0/0 | 26.02 |
| 3 | 100 | media | jittered | J_half | 19.0 | 49.5 | 0.63 | 0.49 | 2/0/0 | 2.27 | 2/0/0 | 25.96 |
| 3 | 100 | media | min_interval | J0 | 24.0 | 63.0 | 0.63 | 0.63 | 2/0/0 | 3.81 | 2/0/0 | 36.96 |
| 5 | 50 | alta | bursty | J0 | 10.0 | 34.0 | 0.95 | 0.68 | 0/2/0 | 1.45 | 0/0/2 | 3010.48 |
| 5 | 50 | alta | bursty | J_half | 10.0 | 34.0 | 0.95 | 0.68 | 0/2/0 | 1.45 | 0/0/2 | 3010.54 |
| 5 | 50 | alta | jittered | J_half | 10.0 | 34.0 | 0.95 | 0.68 | 0/2/0 | 1.28 | 0/0/2 | 3009.92 |
| 5 | 50 | alta | min_interval | J0 | 13.0 | 43.0 | 0.95 | 0.86 | 0/2/0 | 2.27 | 0/0/2 | 3017.46 |
| 5 | 50 | baixa | bursty | J0 | 9.0 | 18.0 | 0.37 | 0.36 | 2/0/0 | 0.92 | 2/0/0 | 11.81 |
| 5 | 50 | baixa | bursty | J_half | 9.0 | 18.0 | 0.37 | 0.36 | 2/0/0 | 0.92 | 2/0/0 | 11.88 |
| 5 | 50 | baixa | jittered | J_half | 6.0 | 12.0 | 0.37 | 0.24 | 2/0/0 | 0.54 | 2/0/0 | 8.62 |
| 5 | 50 | baixa | min_interval | J0 | 9.0 | 18.0 | 0.37 | 0.36 | 2/0/0 | 0.92 | 2/0/0 | 11.67 |
| 5 | 50 | media | bursty | J0 | 10.0 | 28.0 | 0.63 | 0.56 | 2/0/0 | 1.44 | 2/0/0 | 12.85 |
| 5 | 50 | media | bursty | J_half | 10.0 | 28.0 | 0.63 | 0.56 | 2/0/0 | 1.44 | 2/0/0 | 12.55 |
| 5 | 50 | media | jittered | J_half | 9.0 | 25.0 | 0.63 | 0.50 | 2/0/0 | 1.06 | 2/0/0 | 11.59 |
| 5 | 50 | media | min_interval | J0 | 10.0 | 28.0 | 0.63 | 0.56 | 2/0/0 | 1.43 | 2/0/0 | 12.71 |
| 5 | 100 | alta | bursty | J0 | 23.0 | 77.0 | 0.95 | 0.77 | 0/2/0 | 6.44 | 0/0/2 | 3017.71 |
| 5 | 100 | alta | bursty | J_half | 23.0 | 77.0 | 0.95 | 0.77 | 0/2/0 | 6.46 | 0/0/2 | 3017.91 |
| 5 | 100 | alta | jittered | J_half | 22.0 | 74.5 | 0.95 | 0.74 | 0/2/0 | 4.91 | 0/0/2 | 3016.16 |
| 5 | 100 | alta | min_interval | J0 | 28.0 | 94.0 | 0.95 | 0.94 | 0/2/0 | 9.43 | 0/0/2 | 3020.32 |
| 5 | 100 | baixa | bursty | J0 | 14.0 | 28.0 | 0.37 | 0.28 | 2/0/0 | 1.74 | 2/0/0 | 20.49 |
| 5 | 100 | baixa | bursty | J_half | 14.0 | 28.0 | 0.37 | 0.28 | 2/0/0 | 1.83 | 2/0/0 | 22.05 |
| 5 | 100 | baixa | jittered | J_half | 14.0 | 28.0 | 0.37 | 0.28 | 2/0/0 | 1.76 | 2/0/0 | 19.45 |
| 5 | 100 | baixa | min_interval | J0 | 17.0 | 34.0 | 0.37 | 0.34 | 2/0/0 | 2.20 | 2/0/0 | 24.16 |
| 5 | 100 | media | bursty | J0 | 18.0 | 50.0 | 0.63 | 0.50 | 2/0/0 | 3.36 | 2/0/0 | 28.36 |
| 5 | 100 | media | bursty | J_half | 18.0 | 50.0 | 0.63 | 0.50 | 2/0/0 | 3.44 | 2/0/0 | 30.29 |
| 5 | 100 | media | jittered | J_half | 17.0 | 47.0 | 0.63 | 0.47 | 2/0/0 | 3.17 | 2/0/0 | 29.79 |
| 5 | 100 | media | min_interval | J0 | 21.0 | 58.0 | 0.63 | 0.58 | 2/0/0 | 5.99 | 2/0/0 | 36.73 |

## 3. Limitações Científicas Declaradas

1. **Cenários finitos offline ≠ garantia universal:** `SAT` certifica apenas que a sequência concreta de liberações avaliada dentro do horizonte `H` admite escala válida; não prova escalonabilidade para todas as sequências esporádicas admissíveis.
2. **Contraexemplos `UNSAT`:** uma resposta `UNSAT` para uma sequência esporádica válida demonstra que aquela sequência específica não é escalonável sob as restrições modeladas (servindo de contraexemplo caso se deseje viabilidade universal).
3. **Operação online:** ambos os planejadores operam *offline* conhecendo as liberações do cenário de antemão, não sendo escalonadores *online* para chegadas imprevisíveis.
4. **Escopo de deadlines restritos:** esta bateria adota `0 < C_i <= D_i <= T_i` e política de horizonte `d <= H` (com registro explícito das ativações descartadas).
5. **Carga nominal vs. efetiva:** `U_nom = sum(C_i / T_i)` é apenas um indicador assintótico e não decide isoladamente a viabilidade na presença de segmentos, precedências, exclusões direcionais e horizonte finito.

## 4. Figuras Geradas

- `fig_esporadica_padroes.png`
- `fig_esporadica_unidades.png`
