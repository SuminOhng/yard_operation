# Reference Solver Phase 3: Crane Sequences and Concurrency

## 목적

명시적 Route Mode의 보호된 직렬 일정을 그대로 최종 후보로만 사용하지 않고,
해측·육측 크레인의 operation sequence를 분리하여 독립 작업을 겹쳐 실행한다.

## CraneSequence

각 크레인에 대해 다음 정보를 추출한다.

```text
crane_id
operation_indices
job_ids
```

병렬화 과정에서도 다음 순서는 바꾸지 않는다.

- 같은 크레인의 operation 순서
- 같은 job의 pickup, loaded move, handover, final drop 순서
- job release time과 AGV ready time

각 operation은 이 precedence가 허용하는 가장 이른 시각으로 이동한다. 이를
left shift라고 한다.

## 공통 Validator

Left shift는 시간 후보만 만든다. 유효성은 기존 공통 Simulator와 Validator가
결정한다.

```text
left-shift candidate
        ↓
continuous non-crossing
minimum crane separation
stack capacity / tier / blocker
handover precedence / transfer capacity
release time / final completion
        ↓
PASS인 후보만 Upper Bound
```

Left shift 후 충돌이 발생하면 해당 병렬 후보만 탈락한다. 원래의 유효한 serial
후보와 현재 policy planner 후보는 그대로 보존된다.

## 후보공간

작업이 `n`개일 때 평가 후보 수는 다음과 같다.

```text
n! × (1 + 2 × Π(job별 Route Mode 수))
```

- `1`: 현재 policy planner 후보
- 첫 번째 Route 후보: 보호된 serial 실행
- 두 번째 Route 후보: precedence-preserving left shift 실행

## 현재 인증 범위

```text
JOB_ORDER_ROUTES_POLICY_PLANNER_AND_LEFT_SHIFT
```

현재 방식은 각 고정 operation sequence에 대해 가장 이른 시작 후보 하나를 만든다.
충돌 회피를 위해 일부 operation을 의도적으로 기다리게 하는 모든 wait 조합이나
모든 operation interleaving을 완전탐색하지는 않는다. 따라서 아직 global optimum
인증은 하지 않는다.

## 다음 단계

구조화된 연속 충돌 탐지기는 Phase 4에 구현됐다. 다음에는 탐지된 operation에
TimingConstraint를 적용하고 해측 지연·육측 지연 BranchNode를 생성한다.
