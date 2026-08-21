# Exhaustive Reference Solver Phase 1

## 구현 목적

작은 정적 문제에서 세 정책에 동일한 작업순서 탐색을 적용한다. 입력 작업이
`n`개이면 가능한 `n!` 순서를 빠짐없이 평가한다. 각 순서에서 정책 scheduler가
만든 일정은 반드시 공통 physical simulator와 validator를 통과해야 후보가 된다.

```text
모든 job permutation 생성
        ↓
동일 policy scheduler 실행
        ↓
공통 validator 검사
        ↓
valid 후보 중 makespan 최소 선택
```

기본 제한은 8개 작업이다. 8개는 40,320개 순서이므로 문제에 따라 실행시간이
길어질 수 있다. 제한을 넘으면 탐색을 일부만 실행하지 않고 시작 전에 명시적으로
거부한다.

## 인증 범위

1차 결과의 `optimal_within_scope=true`는 다음 범위에서만 정확하다.

```text
모든 작업순서
× 현재 deterministic policy planner가 그 순서에서 생성하는 후보
```

현재 결과는 twin-crane 문제 전체의 global optimum을 인증하지 않는다. 그래서
artifact에는 항상 다음이 함께 저장된다.

```json
{
  "optimal_within_scope": true,
  "globally_optimal": false,
  "optimality_scope": "JOB_ORDER_AND_CURRENT_PLANNER_CANDIDATES"
}
```

전역 인증을 위해서는 후속 단계에서 작업별 direct crane 선택, handover 사용 여부,
transfer slot, 크레인별 sequence와 동시 시작시각을 공통 탐색변수로 확대해야 한다.

## 정책 공정성

세 정책 모두 동일하게 모든 작업순서를 평가한다. HANDSHAKE_AREA는 현재
NO_SHARING direct 후보를 포함하고 ANY_BAY는 HANDSHAKE_AREA 후보를 포함한다.
따라서 구현된 reference candidate space에서는 다음 관계를 자동 검사한다.

```text
ANY_BAY reference UB
    <= HANDSHAKE_AREA reference UB
    <= NO_SHARING reference UB
```

## 실행

세 정책을 한 번에 실행한다.

```powershell
python scripts/run_reference_solver.py `
  --input data/benchmarks/02_handshake_cross_4jobs.json `
  --policy ALL `
  --maximum-jobs 8 `
  --output results/reference_solver_001/edge_to_edge.json
```

한 정책만 실행하려면 `--policy NO_SHARING`, `HANDSHAKE_AREA`, `ANY_BAY` 중
하나를 지정한다.

## 후속 구현 상태

작업별 route mode, direct 운반 crane과 handover slot의 명시적 열거는 Phase 2에
구현됐다. 다음 미구현 범위는 두 크레인의 독립 sequence, 동시운행 시작시각과
Branch-and-Bound다.
