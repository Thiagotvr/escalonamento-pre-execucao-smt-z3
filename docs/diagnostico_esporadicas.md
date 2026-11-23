# Diagnóstico de Compatibilidade do Repositório — Extensão para Tarefas Esporádicas

**Projeto:** Análise Comparativa do Escalonamento Pré-Execução de Processos em Tempo Real utilizando SMT/Z3  
**Branch de trabalho:** `feature/sporadic-tasks`  
**Commit-base auditado:** `8b434808fb2f9a1d2bf8ac902afe47691a4acff9` (`main`)  
**Ambiente verificado:** Python `3.10.19` | Z3 `5.4.1` | Plataforma `Linux-7.0.0-42-generic-x86_64-with-glibc2.39`  
**Suíte de regressão basal:** `36 passed, 0 failed` (`pytest -v`, tempo `1.91s`)

---

## 1. Mapa de Auditoria dos Componentes Existentes

| Componente | Caminho real | Entrada | Saída | Reutilizável? | Adaptação necessária | Risco |
|---|---|---|---|---|---|---|
| Modelo de instância e escala | `src/str_project/model.py` | `ProcessSpec`, `SegmentSpec(id, release, execution_units, deadline)`, `precedence`, `exclusion` | `SchedulingInstance`, `Schedule`, `PlanningResult`, `ValidationReport`, `instance_hash()` | **Sim (100%)** | Nenhuma — já aceita liberações e deadlines inteiros arbitrários por segmento, sem qualquer premissa de periodicidade. | Nulo |
| I/O de instâncias e escalas | `src/str_project/instance_io.py`, `schedule_io.py` | JSON schema v1 / `SchedulingInstance` / `Schedule` | `SchedulingInstance`, `Schedule`, arquivos JSON | **Sim (100%)** | Nenhuma — já deriva precedências internas dos processos e preserva exclusões direcionais sem simetrização automática. | Nulo |
| Planejador Xu & Parnas | `src/str_project/planners/xu_parnas.py`, `xu_initial.py`, `xu_bounds.py`, `xu_relations.py` | `(SchedulingInstance, PlanningLimits, objective)` | `PlanningResult` (`feasible`/`infeasible`/`timeout`/`unknown`, nós, `Lmax`, `lower_bound`, tempos em ns) | **Sim (100%)** | Nenhuma — busca *branch-and-bound* completa (fecho de `PC`, inconsistência `PC`/`EX`/`PM`, `r'`, `Z[i]`, `G1`/`G2`, `GAP`, `LB1`/`LB2`) sem qualquer cálculo de `offset + k*T` ou hiperperíodo. | Nulo |
| Planejador SMT/Z3 | `src/str_project/planners/smt_z3.py` | `(SchedulingInstance, PlanningLimits, objective)` | `PlanningResult` (`feasible`/`infeasible`/`timeout`/`unknown`, `z3_statistics`, tempos separados em ns) | **Sim (100%)** | Nenhuma — usa variáveis unitárias `x[i,k]`, `Distinct`, `s[i] >= r[i]`, `f[i] <= d[i]`, `PC` e `Implies(s[i] < s[j], f[i] <= s[j])` para qualquer conjunto finito de segmentos. | Nulo |
| Verificador independente | `src/str_project/validator.py` | `(SchedulingInstance, Schedule, require_deadlines)` | `ValidationReport` (`valid`, `feasible`, `errors`, `logical_lmax`, `segment_bounds`) | **Sim (100%)** | Nenhuma — verifica todas as 9 regras diretamente sobre a escala sem depender de Z3 ou Xu & Parnas. | Nulo |
| Oráculo exaustivo | `src/str_project/oracle.py` | `(SchedulingInstance, objective)` | `OracleResult` (`feasible`, `optimal_lmax`, `schedule`) | **Sim (100%)** | Nenhuma — pode ser usado em testes unitários/integração para auditar cenários esporádicos minúsculos. | Nulo |
| Aplicação de temperatura e Executor | `src/str_project/application.py`, `executor.py`, `calibration.py` | `ApplicationConfig`, CSV, `Schedule`, `TimingConfig` | `ExecutionReport`, registros em disco | **Opcional** | Templates reais de segmentos (`P1: A1=2, A2=1, A3=3`; `P2: A4=4, A5=1, A6=1, A7=2`; `P3: S=2, A8=3`) reutilizados conceitualmente no adaptador esporádico; executor físico não precisa ser alterado nesta fase focada em planejamento. | Nulo |
| Resultados periódicos anteriores | `resultados_artigo/` | Artefatos já consolidados no commit `7b5f737` | Tabelas `.csv`/`.tex`, figuras `.png`/`.pdf`, dados brutos | **Preservar intacto** | **Proibido modificar ou sobrescrever.** Todos os resultados esporádicos irão para `results/sporadic/`. | Nulo |

---

## 2. Verificação Específica dos Critérios da Seção 2 do Guia

1. **Liberações arbitrárias vs. periodicidade oculta:** inspecionados `model.py`, `instance_io.py`, `xu_relations.py`, `xu_initial.py`, `xu_bounds.py`, `xu_parnas.py`, `smt_z3.py` e `validator.py`. Nenhum módulo pressupõe periodicidade, hiperperíodo, `T`, ou `offset + k*T`. Todas as liberações `r` e deadlines `d` são inteiros absolutos arbitrários por segmento.
2. **Processos multi-segmento e relações concretas:** `SchedulingInstance` modela processos com múltiplos segmentos (`ProcessSpec(id, segments)`) e aplica precedências (`PC`) e exclusões (`EX`) sobre identificadores concretos de segmentos.
3. **Semântica direcional de `EXCLUDES`:** confirmada em três camadas independentes — `validator.py` (regra 8: `s[i] < s[j] => f[i] <= s[j]`), `smt_z3.py` (`Implies(s[i] < s[j], f[i] <= s[j])`) e `xu_initial.py`/`xu_bounds.py` (sem simetrização automática em `instance_io.py`).
4. **Métricas e separação de tempos:** ambos os planejadores já reportam `preprocessing_ns`, `model_build_ns`, `search_ns`, `total_planning_ns`, `nodes_generated`, `nodes_expanded`, `lower_bound`, `logical_lmax` e `versions`.
5. **Fidelidade da implementação basal:** verificada por 36 testes automatizados passando integralmente, incluindo Exemplos 1 e 2 de Xu & Parnas (1990) e auditoria contra oráculo exaustivo em 100 instâncias aleatórias.

---

## 3. Decisão Arquitetural e Plano de Integração

Seguindo diretamente a regra da Seção 2 (*"Se ambos aceitam uma lista finita de processos com liberações e deadlines absolutos arbitrários, a extensão deve ocorrer fora dos planejadores"*):

- **Alterações nos planejadores, verificador e resultados periódicos anteriores:** **zero** (risco de regressão nulo).
- **Novo subpacote isolado:** `src/str_project/sporadic/` contendo:
  - `models.py` — especificações esporádicas (`SegmentTemplate`, `TaskSpec`, `CrossTaskRule`, `ScenarioSpec`, `Activation`, `GeneratedSequence`, `AdaptedSporadicInstance`).
  - `validation.py` — validação independente de especificação, de chegadas esporádicas (`r[k+1] - r[k] >= T`, `r >= offset`, `d = r + D`, horizonte) e de integridade do adaptador.
  - `generator.py` — geração determinística com `random.Random(seed)` local nos 5 modos (`min_interval`, `jittered`, `bursty`, `explicit`, `mixed`) e registro explícito das ativações descartadas pelo horizonte `H`.
  - `adapter.py` — conversão de ativações esporádicas para o contrato congelado `SchedulingInstance` (reutilizando templates reais de segmentos e regras explícitas de precedência/exclusão direcional), com exportação JSON e `input_hash` SHA-256.
  - `experiments.py` — execução pareada e alternada de `plan_xu_parnas` e `plan_smt_z3` sobre a mesma instância imutável, com validação independente de todas as escalas `SAT` (`feasible`) e classificação rigorosa de `SAT`, `UNSAT`, `UNKNOWN`, `timeout` e erros.
  - `reporting.py` — agregação de métricas (carga nominal e efetiva, contagens de jobs/segmentos/unidades, concordância, medianas, percentis p95/p99, dispersão, gráficos e relatório Markdown).
  - `cli.py` — interface de linha de comando dedicada (`python -m str_project.sporadic.cli`).
- **Configurações, testes e saídas totalmente isoladas:**
  - `configs/sporadic/` — cenários demonstrativos (incluindo o domínio real de temperatura esporádico), piloto e matriz experimental principal.
  - `tests/sporadic/` — testes unitários e de integração dedicados à extensão esporádica, executados em conjunto com toda a suíte de regressão original.
  - `results/sporadic/` — diretório exclusivo para instâncias congeladas, logs, métricas, gráficos e relatórios da extensão esporádica.

---

## 4. Escopo Científico e Limitações Declaradas desde o Início

- **Escopo desta entrega:** avaliação comparativa offline por **cenários finitos admissíveis** de ativações esporádicas dentro de um horizonte lógico `H > 0`, adotando inicialmente a classe de deadlines restritos `0 < C_i <= D_i <= T_i` (com política padrão de horizonte fechado por deadline `0 <= r < H` e `d <= H`, registrando todas as ativações descartadas).
- **Fora do escopo (extensão futura):** análise universal sobre **todas** as sequências esporádicas possíveis e escalonamento online com chegadas desconhecidas em tempo de execução. Uma resposta `feasible` (`SAT`) para uma ou `N` sequências finitas **não** constitui prova universal de escalonabilidade.
