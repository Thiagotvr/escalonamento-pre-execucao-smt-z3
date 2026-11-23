# Relatório Experimental — Extensão para Tarefas Esporádicas (`sporadic_main_v1`)

> **Nota de Escopo Científico:** estes resultados referem-se exclusivamente à **extensão para cenários finitos offline de tarefas esporádicas** (`0 < C_i <= D_i <= T_i`, horizonte fechado por deadline `d <= H`), totalmente separados dos resultados periódicos originais em `resultados_artigo/`. Uma resposta `SAT` para uma ou `N` sequências finitas **não** constitui prova universal de escalonabilidade para todas as sequências esporádicas admissíveis.

## 1. Resumo Geral

- **Total de cenários esporádicos avaliados:** 675 (após 2 cenário(s) de aquecimento)
- **Limite de tempo por consulta (`timeout_ms`):** 2000 ms
- **Revisão de código (`git`):** `c920bdd`
- **Ambiente:** Python `3.10.19`, Z3 `5.4.1`, `Linux-7.0.0-42-generic-x86_64-with-glibc2.39`
- **Concordância (nos 675 pares concluídos por ambos):** **675/675 (100.0%)**
- **Divergências detectadas (SAT vs. UNSAT):** `0`

| Métrica | Xu & Parnas | SMT/Z3 |
|---|---:|---:|
| `SAT` (viável) | 675 | 675 |
| `UNSAT` (inviável) | 0 | 0 |
| `TIMEOUT` (inconclusivo) | 0 | 0 |
| `UNKNOWN` | 0 | 0 |
| Escalas `SAT` aprovadas no verificador independente | 675/675 | 675/675 |
| Tempo de planejamento — Mediana (ms) | 2.883 | 24.101 |
| Tempo de planejamento — p95 (ms) | 17.832 | 93.028 |
| Tempo de planejamento — Máximo (ms) | 45.899 | 138.677 |
| Tempo de planejamento — IQR (ms) | 5.282 | 34.442 |
| Tempo médio de preparação (gerador + adaptador, ms) | 0.595 | 0.595 |
| Máximo de nós expandidos | 0 | N/A |

## 2. Resultados Agrupados por Configuração

| `N` | `H` | Carga | Padrão | Jitter | Jobs (med.) | Unid. (med.) | `U_nom` | `U_efet` | Xu (SAT/UNSAT/TO) | Xu med. (ms) | Z3 (SAT/UNSAT/TO) | Z3 med. (ms) |
|---:|---:|---|---|---|---:|---:|---:|---:|---|---:|---|---:|
| 3 | 50 | alta | bursty | J_full | 10.0 | 30.0 | 0.85 | 0.60 | 5/0/0 | 0.92 | 5/0/0 | 14.23 |
| 3 | 50 | alta | bursty | J_half | 12.0 | 36.0 | 0.85 | 0.72 | 5/0/0 | 1.37 | 5/0/0 | 19.53 |
| 3 | 50 | alta | jittered | J_full | 9.6 | 28.8 | 0.85 | 0.58 | 5/0/0 | 0.92 | 5/0/0 | 15.02 |
| 3 | 50 | alta | jittered | J_half | 10.8 | 32.4 | 0.85 | 0.65 | 5/0/0 | 1.15 | 5/0/0 | 17.19 |
| 3 | 50 | alta | min_interval | J0 | 13.0 | 39.0 | 0.85 | 0.78 | 5/0/0 | 1.29 | 5/0/0 | 20.29 |
| 3 | 50 | baixa | bursty | J_full | 6.0 | 12.0 | 0.37 | 0.24 | 5/0/0 | 0.35 | 5/0/0 | 12.29 |
| 3 | 50 | baixa | bursty | J_half | 7.0 | 14.0 | 0.37 | 0.28 | 5/0/0 | 0.42 | 5/0/0 | 10.38 |
| 3 | 50 | baixa | jittered | J_full | 6.0 | 12.0 | 0.37 | 0.24 | 5/0/0 | 0.37 | 5/0/0 | 9.74 |
| 3 | 50 | baixa | jittered | J_half | 7.0 | 14.0 | 0.37 | 0.28 | 5/0/0 | 0.46 | 5/0/0 | 10.32 |
| 3 | 50 | baixa | min_interval | J0 | 8.0 | 16.0 | 0.37 | 0.32 | 5/0/0 | 0.48 | 5/0/0 | 11.19 |
| 3 | 50 | media | bursty | J_full | 7.0 | 18.0 | 0.58 | 0.36 | 5/0/0 | 0.58 | 5/0/0 | 11.86 |
| 3 | 50 | media | bursty | J_half | 9.0 | 24.0 | 0.58 | 0.48 | 5/0/0 | 0.82 | 5/0/0 | 14.22 |
| 3 | 50 | media | jittered | J_full | 7.0 | 18.2 | 0.58 | 0.36 | 5/0/0 | 0.55 | 5/0/0 | 12.10 |
| 3 | 50 | media | jittered | J_half | 8.6 | 22.8 | 0.58 | 0.46 | 5/0/0 | 0.75 | 5/0/0 | 14.41 |
| 3 | 50 | media | min_interval | J0 | 10.0 | 26.0 | 0.58 | 0.52 | 5/0/0 | 0.97 | 5/0/0 | 15.84 |
| 3 | 100 | alta | bursty | J_full | 19.0 | 57.0 | 0.85 | 0.57 | 5/0/0 | 2.34 | 5/0/0 | 30.59 |
| 3 | 100 | alta | bursty | J_half | 22.0 | 66.0 | 0.85 | 0.66 | 5/0/0 | 3.06 | 5/0/0 | 40.21 |
| 3 | 100 | alta | jittered | J_full | 19.2 | 57.6 | 0.85 | 0.58 | 5/0/0 | 2.52 | 5/0/0 | 33.21 |
| 3 | 100 | alta | jittered | J_half | 22.4 | 67.2 | 0.85 | 0.67 | 5/0/0 | 3.44 | 5/0/0 | 48.62 |
| 3 | 100 | alta | min_interval | J0 | 28.0 | 84.0 | 0.85 | 0.84 | 5/0/0 | 4.80 | 5/0/0 | 59.56 |
| 3 | 100 | baixa | bursty | J_full | 13.0 | 26.0 | 0.37 | 0.26 | 5/0/0 | 0.90 | 5/0/0 | 16.94 |
| 3 | 100 | baixa | bursty | J_half | 15.0 | 30.0 | 0.37 | 0.30 | 5/0/0 | 1.10 | 5/0/0 | 19.87 |
| 3 | 100 | baixa | jittered | J_full | 12.8 | 25.6 | 0.37 | 0.26 | 5/0/0 | 0.91 | 5/0/0 | 16.63 |
| 3 | 100 | baixa | jittered | J_half | 14.4 | 28.8 | 0.37 | 0.29 | 5/0/0 | 1.09 | 5/0/0 | 18.82 |
| 3 | 100 | baixa | min_interval | J0 | 18.0 | 36.0 | 0.37 | 0.36 | 5/0/0 | 1.49 | 5/0/0 | 25.74 |
| 3 | 100 | media | bursty | J_full | 15.0 | 39.0 | 0.58 | 0.39 | 5/0/0 | 1.49 | 5/0/0 | 19.14 |
| 3 | 100 | media | bursty | J_half | 17.0 | 45.0 | 0.58 | 0.45 | 5/0/0 | 1.85 | 5/0/0 | 23.90 |
| 3 | 100 | media | jittered | J_full | 14.4 | 37.6 | 0.58 | 0.38 | 5/0/0 | 1.40 | 5/0/0 | 19.13 |
| 3 | 100 | media | jittered | J_half | 17.8 | 47.0 | 0.58 | 0.47 | 5/0/0 | 1.99 | 5/0/0 | 25.44 |
| 3 | 100 | media | min_interval | J0 | 21.0 | 55.0 | 0.58 | 0.55 | 5/0/0 | 2.75 | 5/0/0 | 30.75 |
| 3 | 200 | alta | bursty | J_full | 38.0 | 114.0 | 0.85 | 0.57 | 5/0/0 | 7.68 | 5/0/0 | 97.18 |
| 3 | 200 | alta | bursty | J_half | 46.0 | 138.0 | 0.85 | 0.69 | 5/0/0 | 11.50 | 5/0/0 | 33.67 |
| 3 | 200 | alta | jittered | J_full | 37.4 | 112.2 | 0.85 | 0.56 | 5/0/0 | 7.15 | 5/0/0 | 91.90 |
| 3 | 200 | alta | jittered | J_half | 44.6 | 133.8 | 0.85 | 0.67 | 5/0/0 | 11.85 | 5/0/0 | 35.01 |
| 3 | 200 | alta | min_interval | J0 | 56.0 | 168.0 | 0.85 | 0.84 | 5/0/0 | 17.47 | 5/0/0 | 40.24 |
| 3 | 200 | baixa | bursty | J_full | 25.0 | 50.0 | 0.37 | 0.25 | 5/0/0 | 2.48 | 5/0/0 | 38.78 |
| 3 | 200 | baixa | bursty | J_half | 30.0 | 60.0 | 0.37 | 0.30 | 5/0/0 | 3.50 | 5/0/0 | 53.57 |
| 3 | 200 | baixa | jittered | J_full | 24.8 | 49.6 | 0.37 | 0.25 | 5/0/0 | 2.56 | 5/0/0 | 37.74 |
| 3 | 200 | baixa | jittered | J_half | 29.6 | 59.2 | 0.37 | 0.30 | 5/0/0 | 3.45 | 5/0/0 | 54.75 |
| 3 | 200 | baixa | min_interval | J0 | 36.0 | 72.0 | 0.37 | 0.36 | 5/0/0 | 4.71 | 5/0/0 | 79.79 |
| 3 | 200 | media | bursty | J_full | 30.0 | 79.0 | 0.58 | 0.40 | 5/0/0 | 4.43 | 5/0/0 | 52.01 |
| 3 | 200 | media | bursty | J_half | 36.0 | 95.0 | 0.58 | 0.47 | 5/0/0 | 6.04 | 5/0/0 | 71.06 |
| 3 | 200 | media | jittered | J_full | 29.2 | 76.4 | 0.58 | 0.38 | 5/0/0 | 3.89 | 5/0/0 | 46.97 |
| 3 | 200 | media | jittered | J_half | 34.6 | 91.0 | 0.58 | 0.46 | 5/0/0 | 5.84 | 5/0/0 | 65.60 |
| 3 | 200 | media | min_interval | J0 | 43.0 | 113.0 | 0.58 | 0.56 | 5/0/0 | 9.87 | 5/0/0 | 101.00 |
| 5 | 50 | alta | bursty | J_full | 10.0 | 30.0 | 0.83 | 0.60 | 5/0/0 | 1.48 | 5/0/0 | 14.20 |
| 5 | 50 | alta | bursty | J_half | 10.0 | 30.0 | 0.83 | 0.60 | 5/0/0 | 1.46 | 5/0/0 | 14.08 |
| 5 | 50 | alta | jittered | J_full | 9.4 | 28.2 | 0.83 | 0.56 | 5/0/0 | 1.21 | 5/0/0 | 14.35 |
| 5 | 50 | alta | jittered | J_half | 10.0 | 30.0 | 0.83 | 0.60 | 5/0/0 | 1.42 | 5/0/0 | 15.46 |
| 5 | 50 | alta | min_interval | J0 | 12.0 | 36.0 | 0.83 | 0.72 | 5/0/0 | 1.96 | 5/0/0 | 19.14 |
| 5 | 50 | baixa | bursty | J_full | 9.0 | 18.0 | 0.37 | 0.36 | 5/0/0 | 0.91 | 5/0/0 | 11.79 |
| 5 | 50 | baixa | bursty | J_half | 9.0 | 18.0 | 0.37 | 0.36 | 5/0/0 | 0.92 | 5/0/0 | 11.59 |
| 5 | 50 | baixa | jittered | J_full | 5.8 | 11.6 | 0.37 | 0.23 | 5/0/0 | 0.52 | 5/0/0 | 8.45 |
| 5 | 50 | baixa | jittered | J_half | 6.2 | 12.4 | 0.37 | 0.25 | 5/0/0 | 0.53 | 5/0/0 | 8.59 |
| 5 | 50 | baixa | min_interval | J0 | 9.0 | 18.0 | 0.37 | 0.36 | 5/0/0 | 0.99 | 5/0/0 | 12.34 |
| 5 | 50 | media | bursty | J_full | 10.0 | 28.0 | 0.59 | 0.56 | 5/0/0 | 1.42 | 5/0/0 | 12.60 |
| 5 | 50 | media | bursty | J_half | 10.0 | 28.0 | 0.59 | 0.56 | 5/0/0 | 1.42 | 5/0/0 | 12.71 |
| 5 | 50 | media | jittered | J_full | 6.4 | 17.4 | 0.59 | 0.35 | 5/0/0 | 0.72 | 5/0/0 | 8.87 |
| 5 | 50 | media | jittered | J_half | 7.4 | 20.2 | 0.59 | 0.40 | 5/0/0 | 0.83 | 5/0/0 | 9.88 |
| 5 | 50 | media | min_interval | J0 | 10.0 | 28.0 | 0.59 | 0.56 | 5/0/0 | 1.43 | 5/0/0 | 12.84 |
| 5 | 100 | alta | bursty | J_full | 20.0 | 60.0 | 0.83 | 0.60 | 5/0/0 | 4.26 | 5/0/0 | 34.75 |
| 5 | 100 | alta | bursty | J_half | 22.0 | 66.0 | 0.83 | 0.66 | 5/0/0 | 4.83 | 5/0/0 | 40.43 |
| 5 | 100 | alta | jittered | J_full | 18.6 | 55.8 | 0.83 | 0.56 | 5/0/0 | 3.29 | 5/0/0 | 31.61 |
| 5 | 100 | alta | jittered | J_half | 21.6 | 64.8 | 0.83 | 0.65 | 5/0/0 | 3.93 | 5/0/0 | 38.34 |
| 5 | 100 | alta | min_interval | J0 | 27.0 | 81.0 | 0.83 | 0.81 | 5/0/0 | 7.85 | 5/0/0 | 57.51 |
| 5 | 100 | baixa | bursty | J_full | 12.0 | 24.0 | 0.37 | 0.24 | 5/0/0 | 1.35 | 5/0/0 | 15.13 |
| 5 | 100 | baixa | bursty | J_half | 14.0 | 28.0 | 0.37 | 0.28 | 5/0/0 | 1.70 | 5/0/0 | 19.03 |
| 5 | 100 | baixa | jittered | J_full | 12.8 | 25.6 | 0.37 | 0.26 | 5/0/0 | 1.44 | 5/0/0 | 16.67 |
| 5 | 100 | baixa | jittered | J_half | 14.6 | 29.2 | 0.37 | 0.29 | 5/0/0 | 1.95 | 5/0/0 | 18.93 |
| 5 | 100 | baixa | min_interval | J0 | 17.0 | 34.0 | 0.37 | 0.34 | 5/0/0 | 2.30 | 5/0/0 | 24.79 |
| 5 | 100 | media | bursty | J_full | 16.0 | 44.0 | 0.59 | 0.44 | 5/0/0 | 3.04 | 5/0/0 | 23.97 |
| 5 | 100 | media | bursty | J_half | 16.0 | 44.0 | 0.59 | 0.44 | 5/0/0 | 3.08 | 5/0/0 | 23.16 |
| 5 | 100 | media | jittered | J_full | 14.2 | 39.4 | 0.59 | 0.39 | 5/0/0 | 1.86 | 5/0/0 | 18.35 |
| 5 | 100 | media | jittered | J_half | 16.0 | 44.0 | 0.59 | 0.44 | 5/0/0 | 2.52 | 5/0/0 | 21.10 |
| 5 | 100 | media | min_interval | J0 | 21.0 | 58.0 | 0.59 | 0.58 | 5/0/0 | 4.63 | 5/0/0 | 31.63 |
| 5 | 200 | alta | bursty | J_full | 37.0 | 111.0 | 0.83 | 0.56 | 5/0/0 | 12.71 | 5/0/0 | 92.76 |
| 5 | 200 | alta | bursty | J_half | 44.0 | 132.0 | 0.83 | 0.66 | 5/0/0 | 17.75 | 5/0/0 | 32.66 |
| 5 | 200 | alta | jittered | J_full | 36.6 | 109.8 | 0.83 | 0.55 | 5/0/0 | 9.27 | 5/0/0 | 90.69 |
| 5 | 200 | alta | jittered | J_half | 43.4 | 130.2 | 0.83 | 0.65 | 5/0/0 | 13.33 | 5/0/0 | 35.66 |
| 5 | 200 | alta | min_interval | J0 | 52.0 | 156.0 | 0.83 | 0.78 | 5/0/0 | 28.44 | 5/0/0 | 44.04 |
| 5 | 200 | baixa | bursty | J_full | 26.0 | 52.0 | 0.37 | 0.26 | 5/0/0 | 4.36 | 5/0/0 | 46.47 |
| 5 | 200 | baixa | bursty | J_half | 29.0 | 58.0 | 0.37 | 0.29 | 5/0/0 | 5.19 | 5/0/0 | 54.26 |
| 5 | 200 | baixa | jittered | J_full | 25.2 | 50.4 | 0.37 | 0.25 | 5/0/0 | 3.93 | 5/0/0 | 41.46 |
| 5 | 200 | baixa | jittered | J_half | 29.6 | 59.2 | 0.37 | 0.30 | 5/0/0 | 4.94 | 5/0/0 | 57.97 |
| 5 | 200 | baixa | min_interval | J0 | 36.0 | 72.0 | 0.37 | 0.36 | 5/0/0 | 7.81 | 5/0/0 | 80.32 |
| 5 | 200 | media | bursty | J_full | 31.0 | 86.0 | 0.59 | 0.43 | 5/0/0 | 7.98 | 5/0/0 | 59.47 |
| 5 | 200 | media | bursty | J_half | 34.0 | 94.0 | 0.59 | 0.47 | 5/0/0 | 10.60 | 5/0/0 | 69.81 |
| 5 | 200 | media | jittered | J_full | 28.0 | 77.4 | 0.59 | 0.39 | 5/0/0 | 5.12 | 5/0/0 | 54.89 |
| 5 | 200 | media | jittered | J_half | 33.2 | 91.8 | 0.59 | 0.46 | 5/0/0 | 7.37 | 5/0/0 | 64.62 |
| 5 | 200 | media | min_interval | J0 | 42.0 | 116.0 | 0.59 | 0.58 | 5/0/0 | 15.01 | 5/0/0 | 100.96 |
| 8 | 50 | alta | bursty | J_full | 11.0 | 33.0 | 0.83 | 0.66 | 5/0/0 | 2.13 | 5/0/0 | 14.81 |
| 8 | 50 | alta | bursty | J_half | 11.0 | 33.0 | 0.83 | 0.66 | 5/0/0 | 2.14 | 5/0/0 | 14.82 |
| 8 | 50 | alta | jittered | J_full | 8.4 | 25.2 | 0.83 | 0.50 | 5/0/0 | 1.30 | 5/0/0 | 11.33 |
| 8 | 50 | alta | jittered | J_half | 8.4 | 25.2 | 0.83 | 0.50 | 5/0/0 | 1.29 | 5/0/0 | 10.78 |
| 8 | 50 | alta | min_interval | J0 | 11.0 | 33.0 | 0.83 | 0.66 | 5/0/0 | 2.14 | 5/0/0 | 15.26 |
| 8 | 50 | baixa | bursty | J_full | 8.0 | 16.0 | 0.37 | 0.32 | 5/0/0 | 1.21 | 5/0/0 | 11.42 |
| 8 | 50 | baixa | bursty | J_half | 8.0 | 16.0 | 0.37 | 0.32 | 5/0/0 | 1.22 | 5/0/0 | 11.10 |
| 8 | 50 | baixa | jittered | J_full | 8.0 | 16.0 | 0.37 | 0.32 | 5/0/0 | 1.20 | 5/0/0 | 11.11 |
| 8 | 50 | baixa | jittered | J_half | 8.0 | 16.0 | 0.37 | 0.32 | 5/0/0 | 1.14 | 5/0/0 | 10.07 |
| 8 | 50 | baixa | min_interval | J0 | 8.0 | 16.0 | 0.37 | 0.32 | 5/0/0 | 1.16 | 5/0/0 | 10.25 |
| 8 | 50 | media | bursty | J_full | 8.0 | 22.0 | 0.59 | 0.44 | 5/0/0 | 1.28 | 5/0/0 | 10.11 |
| 8 | 50 | media | bursty | J_half | 8.0 | 22.0 | 0.59 | 0.44 | 5/0/0 | 1.28 | 5/0/0 | 10.06 |
| 8 | 50 | media | jittered | J_full | 8.0 | 22.0 | 0.59 | 0.44 | 5/0/0 | 1.30 | 5/0/0 | 10.29 |
| 8 | 50 | media | jittered | J_half | 8.0 | 22.0 | 0.59 | 0.44 | 5/0/0 | 1.32 | 5/0/0 | 10.69 |
| 8 | 50 | media | min_interval | J0 | 8.0 | 22.0 | 0.59 | 0.44 | 5/0/0 | 1.32 | 5/0/0 | 10.84 |
| 8 | 100 | alta | bursty | J_full | 16.0 | 48.0 | 0.83 | 0.48 | 5/0/0 | 5.08 | 5/0/0 | 24.98 |
| 8 | 100 | alta | bursty | J_half | 22.0 | 66.0 | 0.83 | 0.66 | 5/0/0 | 8.50 | 5/0/0 | 41.68 |
| 8 | 100 | alta | jittered | J_full | 17.6 | 52.8 | 0.83 | 0.53 | 5/0/0 | 4.25 | 5/0/0 | 26.83 |
| 8 | 100 | alta | jittered | J_half | 21.0 | 63.0 | 0.83 | 0.63 | 5/0/0 | 7.29 | 5/0/0 | 36.85 |
| 8 | 100 | alta | min_interval | J0 | 24.0 | 72.0 | 0.83 | 0.72 | 5/0/0 | 11.65 | 5/0/0 | 50.68 |
| 8 | 100 | baixa | bursty | J_full | 16.0 | 32.0 | 0.37 | 0.32 | 5/0/0 | 3.91 | 5/0/0 | 20.96 |
| 8 | 100 | baixa | bursty | J_half | 16.0 | 32.0 | 0.37 | 0.32 | 5/0/0 | 3.90 | 5/0/0 | 21.45 |
| 8 | 100 | baixa | jittered | J_full | 12.4 | 24.8 | 0.37 | 0.25 | 5/0/0 | 2.38 | 5/0/0 | 16.26 |
| 8 | 100 | baixa | jittered | J_half | 15.0 | 30.0 | 0.37 | 0.30 | 5/0/0 | 2.91 | 5/0/0 | 19.64 |
| 8 | 100 | baixa | min_interval | J0 | 16.0 | 32.0 | 0.37 | 0.32 | 5/0/0 | 3.91 | 5/0/0 | 21.07 |
| 8 | 100 | media | bursty | J_full | 16.0 | 44.0 | 0.59 | 0.44 | 5/0/0 | 5.32 | 5/0/0 | 25.77 |
| 8 | 100 | media | bursty | J_half | 16.0 | 44.0 | 0.59 | 0.44 | 5/0/0 | 5.00 | 5/0/0 | 22.29 |
| 8 | 100 | media | jittered | J_full | 14.4 | 39.0 | 0.59 | 0.39 | 5/0/0 | 2.85 | 5/0/0 | 18.09 |
| 8 | 100 | media | jittered | J_half | 16.4 | 44.8 | 0.59 | 0.45 | 5/0/0 | 3.85 | 5/0/0 | 21.94 |
| 8 | 100 | media | min_interval | J0 | 18.0 | 48.0 | 0.59 | 0.48 | 5/0/0 | 5.92 | 5/0/0 | 24.50 |
| 8 | 200 | alta | bursty | J_full | 35.0 | 105.0 | 0.83 | 0.53 | 5/0/0 | 18.15 | 5/0/0 | 86.77 |
| 8 | 200 | alta | bursty | J_half | 43.0 | 129.0 | 0.83 | 0.65 | 5/0/0 | 28.93 | 5/0/0 | 33.61 |
| 8 | 200 | alta | jittered | J_full | 37.0 | 111.0 | 0.83 | 0.56 | 5/0/0 | 15.13 | 5/0/0 | 90.69 |
| 8 | 200 | alta | jittered | J_half | 42.4 | 127.2 | 0.83 | 0.64 | 5/0/0 | 22.71 | 5/0/0 | 116.69 |
| 8 | 200 | alta | min_interval | J0 | 51.0 | 153.0 | 0.83 | 0.77 | 5/0/0 | 45.35 | 5/0/0 | 42.50 |
| 8 | 200 | baixa | bursty | J_full | 27.0 | 54.0 | 0.37 | 0.27 | 5/0/0 | 8.80 | 5/0/0 | 51.22 |
| 8 | 200 | baixa | bursty | J_half | 30.0 | 60.0 | 0.37 | 0.30 | 5/0/0 | 10.29 | 5/0/0 | 59.78 |
| 8 | 200 | baixa | jittered | J_full | 25.2 | 50.4 | 0.37 | 0.25 | 5/0/0 | 6.46 | 5/0/0 | 44.10 |
| 8 | 200 | baixa | jittered | J_half | 29.4 | 58.8 | 0.37 | 0.29 | 5/0/0 | 7.37 | 5/0/0 | 50.30 |
| 8 | 200 | baixa | min_interval | J0 | 35.0 | 70.0 | 0.37 | 0.35 | 5/0/0 | 13.02 | 5/0/0 | 86.93 |
| 8 | 200 | media | bursty | J_full | 32.0 | 88.0 | 0.59 | 0.44 | 5/0/0 | 15.34 | 5/0/0 | 62.16 |
| 8 | 200 | media | bursty | J_half | 34.0 | 92.0 | 0.59 | 0.46 | 5/0/0 | 16.80 | 5/0/0 | 68.82 |
| 8 | 200 | media | jittered | J_full | 28.2 | 76.6 | 0.59 | 0.38 | 5/0/0 | 7.68 | 5/0/0 | 48.56 |
| 8 | 200 | media | jittered | J_half | 33.8 | 91.8 | 0.59 | 0.46 | 5/0/0 | 12.26 | 5/0/0 | 65.78 |
| 8 | 200 | media | min_interval | J0 | 42.0 | 114.0 | 0.59 | 0.57 | 5/0/0 | 25.16 | 5/0/0 | 96.80 |

## 3. Limitações Científicas Declaradas

1. **Cenários finitos offline ≠ garantia universal:** `SAT` certifica apenas que a sequência concreta de liberações avaliada dentro do horizonte `H` admite escala válida; não prova escalonabilidade para todas as sequências esporádicas admissíveis.
2. **Contraexemplos `UNSAT`:** uma resposta `UNSAT` para uma sequência esporádica válida demonstra que aquela sequência específica não é escalonável sob as restrições modeladas (servindo de contraexemplo caso se deseje viabilidade universal).
3. **Operação online:** ambos os planejadores operam *offline* conhecendo as liberações do cenário de antemão, não sendo escalonadores *online* para chegadas imprevisíveis.
4. **Escopo de deadlines restritos:** esta bateria adota `0 < C_i <= D_i <= T_i` e política de horizonte `d <= H` (com registro explícito das ativações descartadas).
5. **Carga nominal vs. efetiva:** `U_nom = sum(C_i / T_i)` é apenas um indicador assintótico e não decide isoladamente a viabilidade na presença de segmentos, precedências, exclusões direcionais e horizonte finito.

## 4. Figuras Geradas

- `fig_esporadica_padroes.png`
- `fig_esporadica_unidades.png`
