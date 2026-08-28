# Static Bound Batch Runner

## 목적

Benchmark manifest에 정의된 모든 시나리오를 세 YC 협력정책으로 실행하고,
개별 감사 JSON과 전체 비교표를 한 번에 생성한다.

현재 manifest는 다음 계산을 만든다.

```text
5 scenarios × 3 policies = 15 bound calculations
```

## 실행

프로젝트 루트에서 다음 명령을 사용한다.

```powershell
python scripts/run_bound_batch.py `
  --manifest data/benchmarks/benchmark_manifest.json `
  --output-dir results/bound_batch
```

## 출력 구조

```text
results/bound_batch/
├─ batch_summary.json
├─ batch_summary.csv
├─ batch_summary.md
└─ artifacts/
   ├─ BALANCED_LOCAL_4/
   │  ├─ no_sharing.json
   │  ├─ handshake_area.json
   │  └─ any_bay.json
   └─ ...
```

개별 artifact는 단일 Bound Calculator CLI와 같은 상세 형식을 사용한다.
Summary는 다음 필드를 포함한다.

- scenario, feature, job 수와 기존·신규 작업 수
- policy와 기대 결과
- 실제 COMPLETE/UPPER_BOUND_ONLY/LOWER_BOUND_ONLY/FAILED 상태
- baseline, Strict Append UB, Full Replan UB, Best-known UB
- Combined LB와 absolute/relative gap
- best UB를 만든 방법
- handover, reshuffle, operation 수
- 사용 transfer slot
- 전체 계산 runtime
- 기대값 일치 여부와 오류

## 기대결과 판정

Manifest의 `expected_complete_policies`는 실제 상태가 `COMPLETE`일 때만
일치한다. `expected_infeasible_policies`는 유효 UB가 없고 LB만 있는
`LOWER_BOUND_ONLY`일 때 일치한다.

따라서 gate-to-gate NO_SHARING처럼 의도된 infeasible 사례는 batch 전체를
실패로 만들지 않는다. 반대로 COMPLETE로 선언한 정책이 planner 오류를 내면
`all_expectations_met=false`가 되고 CLI 종료코드는 1이다.

## 출력 폴더 규칙

출력 폴더는 존재하지 않거나 비어 있어야 한다. 이전 batch의 상세 artifact와
새 summary가 섞이는 것을 막기 위해 비어 있지 않은 폴더는 자동으로
덮어쓰지 않는다. 반복 실행은 `results/bound_batch_001`,
`results/bound_batch_002`처럼 새 경로를 사용한다.

## 종료코드

- `0`: 15개 실행 결과가 manifest 기대값과 모두 일치
- `1`: 파일은 생성했지만 실제 결과와 기대값이 하나 이상 불일치
- `2`: manifest, 입력 또는 실행 자체의 오류

## 저장 순서

상세 calculation artifact를 먼저 원자적으로 저장하고, 모든 계산이 기록된 뒤
summary JSON, CSV, Markdown을 마지막에 저장한다. Summary가 존재하면 그 실행의
상세 artifact 기록까지 완료됐다는 의미다.

## 주요 파일

- `src/yard_crane_v3/experiments/manifest.py`
- `src/yard_crane_v3/experiments/runner.py`
- `src/yard_crane_v3/experiments/serialization.py`
- `scripts/run_bound_batch.py`
- `tests/test_bound_batch_runner.py`
