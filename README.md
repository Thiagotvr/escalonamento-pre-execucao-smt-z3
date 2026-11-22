# Análise Comparativa do Escalonamento Pré-Execução de Processos em Tempo Real utilizando SMT/Z3

Implementação em Python e protocolo experimental do trabalho acadêmico **"Análise Comparativa do Escalonamento Pré-Execução de Processos em Tempo Real utilizando SMT/Z3"** (UFAM — Engenharia Elétrica).

O projeto compara duas abordagens para o problema de escalonamento pré-execução em processador único com tempos de liberação (`r`), demandas discretas (`C`), deadlines (`d`), relações de precedência (`PRECEDES`) e exclusões direcionais (`EXCLUDES`):

1. **Algoritmo clássico de Xu & Parnas (1990):** busca *branch-and-bound* fiel ao artigo original (consistência de relações `PC`/`EX`/`PM`, liberações ajustadas `r'`, construção de escala válida inicial orientada a deadline com desempate pelo maior `c` original, cálculo de `Z[i]`, conjuntos de expansão `G1`/`G2`, `GAP` e limites inferiores `LB1`/`LB2`).
2. **Formulação declarativa em SMT/Z3:** modelagem em aritmética linear inteira sem quantificadores (`QF_LIA`) com variáveis unitárias `x[i,k]`, `Distinct`, precedências e exclusões direcionais, com suporte a decisão de viabilidade (`z3.Solver`) e minimização de `Lmax` (`z3.Optimize`).

Ambas as abordagens compartilham o mesmo contrato de instâncias, um **verificador independente de escalas**, um **oráculo exaustivo** para auditoria em instâncias pequenas e um **executor cooperativo** que executa uma aplicação real de monitoramento de temperatura (leitura CSV, validação, média móvel, cálculo de indicadores estatísticos, classificação de alerta, comando virtual de ventilação, publicação de estado compartilhado e registro consistente em arquivo).

---

## Estrutura do Projeto

```text
src/str_project/
├── cli.py                  # Interface de linha de comando (plan, validate, calibrate, execute, compare, benchmark)
├── model.py                # Estruturas de instância, escala, validação e resultado de planejamento
├── instance_io.py          # Leitura/validação estrutural de instâncias JSON
├── schedule_io.py          # Persistência de escalas e escalas de referência (Seção 10)
├── validator.py            # Verificador independente das 9 regras de escalonamento
├── oracle.py               # Oráculo enumerativo exaustivo para instâncias pequenas
├── application.py          # Operações reais da aplicação de temperatura (A1–A8 e S)
├── executor.py             # Executor cooperativo comum (modos lógico e temporizado)
├── calibration.py          # Calibração empírica do quantum físico q
├── reporting.py            # Relatórios de execução e comparação sistemática (JSON + Markdown)
└── planners/
    ├── smt_z3.py           # Planejador SMT/Z3 (viabilidade e min_lmax)
    ├── xu_relations.py     # Fecho de PC, checagem de consistência (PC/EX/PM) e r'
    ├── xu_initial.py       # Escala válida inicial (Apêndice 1 de Xu & Parnas)
    ├── xu_bounds.py        # Segmento crítico, Z[i], G1/G2, GAP e lower bound
    └── xu_parnas.py        # Busca branch-and-bound completa de Xu & Parnas
instances/
├── temperature_case.json   # Instância principal (3 processos, 9 segmentos, 19 unidades)
├── xu_example_1.json       # Exemplo 1 do Apêndice 3 de Xu & Parnas (ramificação G1)
└── xu_example_2.json       # Exemplo 2 do Apêndice 3 de Xu & Parnas (ramificação G2 + preempção)
data/
├── temperatures.csv        # Conjunto determinístico temperature_fixture_v1 (120 amostras)
└── application_config.json # Parâmetros funcionais da aplicação de temperatura
tests/
├── test_model.py
├── test_application.py
├── test_executor.py
├── test_smt.py
├── test_xu_initial.py
├── test_xu_search.py
└── test_cli_and_reporting.py
```

---

## Instalação e Ambiente

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
pip install --no-build-isolation --no-deps -e .
```

Para executar toda a suíte de testes automatizados:

```bash
python -m pytest -v
```

---

## Fluxo Experimental (CLI)

### 1. Planejamento (Xu & Parnas e SMT/Z3)

```bash
python -m str_project.cli plan --method xu-parnas --instance instances/temperature_case.json --out runs/xu/plan.json
python -m str_project.cli plan --method smt-z3    --instance instances/temperature_case.json --out runs/z3/plan.json
```

Para comparar minimização do maior *lateness* (`Lmax`), informe `--objective min_lmax` em ambos os métodos:

```bash
python -m str_project.cli plan --method xu-parnas --objective min_lmax --instance instances/xu_example_2.json --out runs/xu_ex2/plan.json --trace
python -m str_project.cli plan --method smt-z3    --objective min_lmax --instance instances/xu_example_2.json --out runs/z3_ex2/plan.json
```

### 2. Verificação Independente das Escalas

```bash
python -m str_project.cli validate --instance instances/temperature_case.json --schedule runs/xu/plan.json
python -m str_project.cli validate --instance instances/temperature_case.json --schedule runs/z3/plan.json
```

### 3. Calibração do Quantum Físico

```bash
python -m str_project.cli calibrate --instance instances/temperature_case.json --input data/temperatures.csv --out runs/calibration.json
```

### 4. Execução Real da Aplicação (Modo Lógico e Modo Temporizado)

```bash
python -m str_project.cli execute --instance instances/temperature_case.json --schedule runs/xu/plan.json --input data/temperatures.csv --mode logical --out runs/xu/logical
python -m str_project.cli execute --instance instances/temperature_case.json --schedule runs/z3/plan.json --input data/temperatures.csv --mode logical --out runs/z3/logical

python -m str_project.cli execute --instance instances/temperature_case.json --schedule runs/xu/plan.json --input data/temperatures.csv --mode timed --timing runs/calibration.json --out runs/xu/timed
python -m str_project.cli execute --instance instances/temperature_case.json --schedule runs/z3/plan.json --input data/temperatures.csv --mode timed --timing runs/calibration.json --out runs/z3/timed
```

### 5. Comparação e Benchmark Repetido

```bash
python -m str_project.cli compare --left runs/xu --right runs/z3 --out runs/comparison
python -m str_project.cli benchmark --instance instances/temperature_case.json --repetitions 10 --warmup 2 --out runs/benchmark_temp.json
```

---

## Notas Técnicas e Adaptações Documentadas

1. **Condição existencial em `compute_Z` (`xu_bounds.py`):** conforme Xu & Parnas (1990), Seção IV (p. 364), um segmento `k` com `e[k] == s[l]` para algum `l ∈ Z[i]` entra em `Z[i]` quando **existe** `l' ∈ Z[i]` tal que `r'[l'] < e[k]` (isto é, pelo menos um segmento em `Z[i]` já estava liberado antes do término de `k`, caracterizando atraso efetivo). Essa condição reproduz exatamente os conjuntos `Z`, `G1`, `G2` e os limites inferiores dos Exemplos 1 e 2 do artigo, além de apresentar 100% de concordância com o oráculo enumerativo e com o SMT/Z3 em testes aleatórios tanto em viabilidade quanto em `min_lmax`.
2. **Desempate estável em `build_valid_initial_schedule`:** após menor deadline `d[j]` e maior demanda original `c[j]` (não tempo restante), empates residuais são resolvidos lexicograficamente por `segment_id`.
3. **Detecção de leitura inconsistente entre `A7` e `S`:** `SharedState` emprega guarda de versão (`update_started_version` / `version`) que permite a `S` detectar imediatamente leituras parciais em escalas propositalmente inválidas, preservando ao mesmo tempo a semântica permitida de `P3` registrar `E0` (versão 0) ou o estado recém-publicado (versão 1).
4. **Caráter experimental da execução temporizada:** a execução em Python sobre sistema operacional de propósito geral avalia comportamento temporal observado (atrasos de despacho, duração real das unidades e excessos de slot) e não constitui certificação formal de tempo real rígido nem prova de WCET.

---

## Referências

- **[X1]** J. Xu and D. L. Parnas, *"Scheduling Processes with Release Times, Deadlines, Precedence, and Exclusion Relations"*, IEEE Transactions on Software Engineering, vol. 16, no. 3, pp. 360–369, 1990.
- **[Z1]** Z3 Theorem Prover — https://github.com/Z3Prover/z3
