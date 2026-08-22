# Reference Solver Phase 2: Explicit Route Modes

## 구현 범위

Phase 1의 모든 작업순서 열거에 작업별 운반방식 선택을 추가했다.

```text
모든 job order
× job별 direct crane 또는 handover slot
× 공통 physical validation
```

Route Mode는 정책과 독립된 공통 자료구조다.

```text
DIRECT_SEASIDE
DIRECT_LANDSIDE
HANDOVER_AT_<transfer_slot_id>
```

정책은 허용되는 Route Mode 집합만 제한한다.

```text
NO_SHARING
  DIRECT_SEASIDE
  DIRECT_LANDSIDE

HANDSHAKE_AREA
  NO_SHARING의 모든 mode
  handshake bay에 있는 enabled slot handover

ANY_BAY
  HANDSHAKE_AREA의 모든 mode
  그 밖의 enabled slot handover
```

따라서 Route Mode 집합 자체가 다음 포함관계를 만족한다.

```text
NO_SHARING route space
  ⊆ HANDSHAKE_AREA route space
  ⊆ ANY_BAY route space
```

## 후보 실행

선택된 route는 보호된 serial phase에서 실행된다. 직접 운반 시 반대 크레인은
외부 대기 위치로 이동한다. Handover 시 선택된 transfer slot을 강제로 사용한다.
모든 후보는 기존 공통 Simulator와 Validator를 통과해야 한다.

실행 불가능한 조합도 탐색 후보에는 포함될 수 있다. 예를 들어 육측 크레인이
해측 외부 위치까지 직접 운반하려 하면 non-crossing 위반으로 탈락한다. 이 방식은
사전에 휴리스틱으로 가능한 조합만 남겨 최적 후보를 누락하지 않기 위한 것이다.

## 조합 수 제한

기존 정책 scheduler가 각 작업순서에서 만드는 후보도 유지하여, Route Mode
탐색을 추가한 뒤 결과가 기존 Reference Solver보다 나빠지지 않게 한다. 총 후보
수는 다음과 같다.

```text
n! × (1 + 2 × Π(job별 허용 Route Mode 수))
```

괄호 안의 `1`은 각 순서의 기존 policy planner 후보다. Route plan마다 보호된
직렬 후보와 left-shift 병렬 후보를 하나씩 평가하므로 Route Mode 곱에 2가
곱해진다. 최종 결과에는 `candidate_source`가 저장된다.

기본 `maximum_route_candidates`는 100,000이다. 예상 후보 수가 한도를 초과하면
부분 탐색 결과를 정확한 결과처럼 내보내지 않고 시작 전에 중단한다.

## 인증 범위

Phase 2 결과는 다음 범위에서 exact다.

```text
JOB_ORDER_ROUTES_POLICY_PLANNER_AND_LEFT_SHIFT
```

보호된 serial 후보 외에 crane별 순서와 job precedence를 유지하며 불필요한 대기를
제거한 left-shift 병렬 후보도 평가한다. 하지만 충돌을 피하기 위한 임의의 추가
대기와 모든 operation interleaving은 아직 탐색하지 않는다. 따라서 artifact는
계속 `globally_optimal=false`를 기록한다.

## 실행

```powershell
python scripts/run_reference_solver.py `
  --input data/static_fair_micro.json `
  --policy ALL `
  --search-space ROUTE_MODE `
  --maximum-jobs 8 `
  --maximum-route-candidates 100000 `
  --output results/reference_solver_002/static_fair_routes.json
```

Phase 1 방식만 실행하려면 `--search-space JOB_ORDER`를 사용한다.

## 다음 단계

1. 해측·육측 크레인의 작업 sequence를 각각 독립적으로 표현한다.
2. 서로 다른 작업의 동시운행 후보를 생성한다.
3. 현재 공통 continuous collision validator로 모든 후보를 심사한다.
4. workload·release-time lower bound를 Branch-and-Bound 가지치기에 연결한다.
5. 전체 후보가 종료된 작은 문제에 대해 global optimality 인증을 검토한다.
