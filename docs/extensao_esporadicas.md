# Extensão para Tarefas Esporádicas — Guia de Execução, Resultados e Limites Científicos

**Branch:** `feature/sporadic-tasks`  
**Commit-base auditado:** `8b43480` (`main`)  
**Diagnóstico técnico prévio:** [`docs/diagnostico_esporadicas.md`](diagnostico_esporadicas.md)

---

## 1. Arquitetura Adotada (Zero Alterações nos Planejadores Originais)

Como verificado no diagnóstico da Fase A, tanto `plan_xu_parnas` quanto `plan_smt_z3` e `validate_schedule` já operam sobre conjuntos finitos arbitrários de processos/segmentos com liberações `r` e deadlines `d` inteiros arbitrários, sem qualquer premissa oculta de periodicidade.

Portanto, toda a extensão foi isolada em módulos dedicados:

```text
src/str_project/sporadic/
├── models.py          # SegmentTemplate, TaskSpec, CrossTaskRule, ScenarioSpec, Activation, AdaptedSporadicInstance
├── validation.py      # Validação independente de chegadas (r[k+1]-r[k] >= T), horizonte H, adaptador e escalas
├── generator.py       # Geração determinística (seed local) nos 5 modos: min_interval, jittered, bursty, explicit, mixed
├── adapter.py         # Conversão para o contrato SchedulingInstance + exportação JSON com input_hash SHA-256
├── experiments.py     # Execução pareada e alternada de Xu & Parnas e SMT/Z3 sobre a mesma instância congelada
├── reporting.py       # Exportação metrics.csv, summary.csv/json, gráficos (.png/.pdf) e RELATORIO_ESPORADICAS.md
└── cli.py             # CLI dedicada: python -m str_project.sporadic.cli
configs/sporadic/
├── demo_temperature_sporadic.json
├── demo_mixed_profiles.json
├── matrix_pilot.json
├── matrix_main.json
└── matrix_stress_boundary.json
tests/sporadic/
├── test_generator_and_adapter.py
└── test_integration_planners.py
results/sporadic/      # Isolado de resultados_artigo/ (periódico preservado intacto)
├── demos/
├── pilot/
├── main/
└── stress/
```

---

## 2. Como Reproduzir de Ponta a Ponta

### 2.1 Rodar toda a suíte de testes (esporádicos + regressão periódica)

```bash
.venv/bin/python -m pytest -v
```

### 2.2 Executar um cenário esporádico isolado (domínio real de temperatura)

```bash
# Gerar e congelar a instância esporádica adaptada
.venv/bin/python -m str_project.sporadic.cli generate \
  --config configs/sporadic/demo_temperature_sporadic.json \
  --out results/sporadic/demos/temperature/inst_check.json

# Executar Xu & Parnas e SMT/Z3 sobre a mesma instância e validar escalas
.venv/bin/python -m str_project.sporadic.cli run-scenario \
  --config configs/sporadic/demo_temperature_sporadic.json \
  --out results/sporadic/demos/temperature \
  --timeout-ms 10000

# Validar independentemente as escalas geradas
.venv/bin/python -m str_project.sporadic.cli validate \
  --instance results/sporadic/demos/temperature/instances/demo_temperature_sporadic__seed2026.json \
  --schedule results/sporadic/demos/temperature/schedules/demo_temperature_sporadic__seed2026__xu-parnas.json

.venv/bin/python -m str_project.sporadic.cli validate \
  --instance results/sporadic/demos/temperature/instances/demo_temperature_sporadic__seed2026.json \
  --schedule results/sporadic/demos/temperature/schedules/demo_temperature_sporadic__seed2026__smt-z3.json
```

### 2.3 Executar uma matriz experimental completa

```bash
# Matriz piloto (96 cenários)
.venv/bin/python -m str_project.sporadic.cli run-matrix \
  --config configs/sporadic/matrix_pilot.json \
  --out results/sporadic/pilot \
  --warmup 1

# Matriz principal (675 cenários: N in {3,5,8}, H in {50,100,200}, 3 padrões, 3 cargas, 5 seeds)
.venv/bin/python -m str_project.sporadic.cli run-matrix \
  --config configs/sporadic/matrix_main.json \
  --out results/sporadic/main \
  --warmup 2

# Bateria de fronteira crítica (36 cenários: transição SAT/UNSAT sob jitter e exclusões)
.venv/bin/python -m str_project.sporadic.cli run-matrix \
  --config configs/sporadic/matrix_stress_boundary.json \
  --out results/sporadic/stress \
  --warmup 1
```

---

## 3. Síntese dos Resultados Medidos (`results/sporadic/`)

| Bateria | Cenários | Pares concluídos (concordância) | Divergências | Xu & Parnas (SAT/UNSAT/TO) | Xu med. (p95) ms | SMT/Z3 (SAT/UNSAT/TO) | Z3 med. (p95) ms |
|---|---:|---:|---:|---|---:|---|---:|
| `demos/temperature` (`H=80`, templates reais `P1/P2/P3`) | 1 | 1/1 (100%) | 0 | 1 / 0 / 0 | 1,88 | 1 / 0 / 0 | 42,03 |
| `demos/mixed` (`H=60`, `min`+`jit`+`bst`) | 1 | 1/1 (100%) | 0 | 1 / 0 / 0 | 1,67 | 1 / 0 / 0 | 23,08 |
| `pilot` (`N∈{3,5}`, `H∈{50,100}`, `timeout=3s`) | 96 | 80/80 (100%) | 0 | 64 / 32 / 0 | 1,46 (6,44) | 64 / 16 / 16 | 22,34 (3017,5) |
| `main` (`N∈{3,5,8}`, `H∈{50,100,200}`, 5 seeds) | 675 | 675/675 (100%) | 0 | 675 / 0 / 0 | 2,88 (17,83) | 675 / 0 / 0 | 24,10 (93,03) |
| `stress` (`fronteira_critica`, `timeout=2s`) | 36 | 36/36 (100%) | 0 | 26 / 10 / 0 | 3,27 (9,89) | 26 / 10 / 0 | 53,56 (232,06) |

**Principais achados empíricos desta extensão:**
1. **100% de concordância e 0 escalas inválidas:** em todos os **793 pares** decididos por ambos os métodos nas 4 baterias (`demos`, `pilot`, `main`, `stress`), não houve uma única divergência entre `Xu & Parnas` e `SMT/Z3`, e todas as escalas `SAT` foram aprovadas pelo verificador independente.
2. **Efeito do padrão de ativação sobre o custo:** na matriz principal (`675` cenários), `min_interval` apresentou o maior tempo mediano para ambos os métodos (`4,63 ms` em Xu & Parnas; `30,73 ms` em SMT/Z3) por instanciar o maior número de ativações e unidades no horizonte `H`, enquanto `jittered` (`2,50 ms` / `20,74 ms`) e `bursty` (`3,03 ms` / `23,29 ms`) inseriram lacunas maiores.
3. **Provas `UNSAT` sob alta carga (`pilot`):** em `N=5` com alta carga e múltiplas ativações sobrepostas, o SMT/Z3 atingiu `16` timeouts (`3000 ms`) ao tentar provar `UNSAT` sobre restrições `Distinct` inteiras, enquanto `Xu & Parnas` concluiu `UNSAT` em `< 10 ms` via limites inferiores `LB1`/`LB2`.
4. **Anomalia de jitter sob exclusões (`stress`):** na bateria `fronteira_critica`, configurações que eram `SAT` sob `min_interval` (`N=3, H=50` e `N=5, H=100`, 3/3 `SAT`) apresentaram **contraexemplos `UNSAT` sob `jittered`** (`1 SAT / 2 UNSAT` e `2 SAT / 1 UNSAT`), porque deslocamentos positivos de chegada alinharam janelas de segmentos sujeitos a `EXCLUDES`. Isso comprova empiricamente que testar apenas o caso periódico (`min_interval`) não basta para certificar tarefas esporádicas com relações de exclusão.

---

## 4. Limitações Científicas Declaradas (O que NÃO afirmar)

- `SAT` para uma ou `N` sequências finitas **não prova** escalonabilidade universal para todas as sequências esporádicas admissíveis.
- `UNSAT` para uma sequência esporádica válida constitui **contraexemplo** para aquela especificação (caso o requisito seja viabilidade para todas as sequências admissíveis).
- A avaliação executada é **offline em horizonte finito `H`**, com classe inicial de deadlines restritos `0 < C_i <= D_i <= T_i` e política explícita `d <= H` (todas as ativações que ultrapassam `H` são registradas em `discarded_activations`).
- Os escalonadores avaliados conhecem as ativações do cenário de antemão e **não** constituem escalonadores *online* para chegadas desconhecidas em tempo de execução.
- Análises universais (quantificando sobre todas as sequências de liberações ou testes analíticos *demand bound function* para tarefas independentes) permanecem como extensão futura fora do escopo desta entrega.

---

## 5. Checklist de Entrega (Seção 13)

- [x] Diagnóstico do repositório e commit-base (`8b43480`) registrados em `docs/diagnostico_esporadicas.md`.
- [x] Dados e resultados periódicos anteriores (`resultados_artigo/`) preservados intactos (zero alterações).
- [x] Gerador esporádico determinístico com seed local e validação independente de `T` (5 modos).
- [x] Adaptador para processos e segmentos concretos do modelo original preservando precedências e `EXCLUDES` direcional.
- [x] Xu & Parnas e SMT/Z3 recebem exatamente a mesma instância imutável (`instance_hash` e `input_hash` verificados).
- [x] Verificador independente aprova 100% das escalas reportadas como `SAT`.
- [x] Todos os 36 testes de regressão periódica + 15 testes da extensão esporádica passam (`51 passed, 0 failed`).
- [x] Logs e CSVs distinguem explicitamente `SAT`, `UNSAT`, `UNKNOWN`, `TIMEOUT` e erros.
- [x] Todos os relatórios e figuras esporádicas salvos separadamente em `results/sporadic/`.
- [x] Limitações de horizonte finito e natureza offline declaradas em todos os relatórios e documentação.
