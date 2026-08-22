# Reference Solver Phase 5: Timing Repair and Branch Nodes

## 목적

Phase 4의 구조화된 `CraneConflict`를 실제 탐색 분기로 바꿀 수 있도록 다음 두
자료구조를 구현한다.

```text
TimingConstraint  충돌을 피하기 위해 한 operation을 상대 operation 뒤로 미루는 조건
BranchNode        지금까지 선택된 timing 조건과 그 조건을 반영한 일정을 보관하는 노드
```

이 단계는 Branch-and-Bound의 **노드 생성 기반**이다. 아직 node queue 전체 탐색,
incumbent 기반 가지치기, 종료 인증은 구현하지 않는다.

## TimingConstraint

주요 필드는 다음과 같다.

```text
operation_index             지연시킬 operation
delayed_crane_id            해당 operation의 crane
earliest_start              절대 최소 시작시각
opposing_operation_index    먼저 끝나야 하는 상대 operation
conflict_time               분기를 만든 충돌시각
reason                      CRANE_CONFLICT_REPAIR
```

`earliest_start`만 저장하면 상대 operation이 나중에 다시 지연될 때 선후관계가
깨질 수 있다. 따라서 `opposing_operation_index → operation_index` 관계도 precedence
graph에 추가한다. 상대 operation이 밀리면 지연된 operation과 같은 crane의 후속
operation도 함께 밀린다.

동일한 `(operation_index, opposing_operation_index)` 조건이 반복되면 가장 강한
`earliest_start`만 유지한다. 정규화된 constraint signature는 향후 중복 노드 제거에
사용한다.

## Timing Repair

`repair_schedule_timing()`은 다음 순서로 일정을 다시 계산한다.

1. crane별 기존 operation 순서를 precedence로 고정한다.
2. job별 pickup, move, drop 순서를 precedence로 고정한다.
3. TimingConstraint의 상대 operation 선행관계를 추가한다.
4. 위상정렬 순서로 가능한 가장 이른 시작시각을 계산한다.
5. 공통 Validator와 구조화된 충돌 탐지기를 다시 실행한다.

operation tuple의 순서는 바꾸지 않으므로 구조화된 충돌정보의 operation index는
repair 전후에 안정적으로 유지된다. 제약을 추가해 cycle이 생기면 해당 branch는
`INFEASIBLE`로 처리한다.

## BranchNode와 최초 충돌 분기

`branch_on_first_conflict()`는 두 크레인이 모두 operation을 수행 중인 최초 충돌에
대해 최대 두 자식을 만든다.

```text
N0.S  충돌 중인 해측 operation을 육측 operation 뒤로 지연
N0.L  충돌 중인 육측 operation을 해측 operation 뒤로 지연
```

각 자식은 누적 TimingConstraint, repaired schedule, 공통 validation 결과, 다음 최초
충돌과 constraint signature를 저장한다. 가능한 상태는 `FEASIBLE`, `CONFLICTED`,
`INFEASIBLE` 등이다.

한쪽 크레인이 operation 없이 정지해 있는 동안 생긴 충돌은 현재 분기 대상이
아니다. 이를 해결하려면 정지 상태를 나타내는 wait/occupancy operation 또는 별도
공간 분기 규칙이 필요하다.

## lower_bound의 현재 의미

노드의 `lower_bound`는 고정된 route와 crane/job operation 순서, 그리고 현재까지의
TimingConstraint 아래에서 만든 earliest-start 완화 일정의 final-drop 완료시각이다.
충돌 제약 일부를 아직 반영하지 않은 값이므로 해당 노드 후손에 대한 시간 하한으로
사용할 준비가 된 값이다.

단, root에 외부에서 임의의 불필요한 대기가 포함된 schedule을 전달하면 이 성질이
자동 인증되지는 않는다. 현재 concurrency generator 또는 timing repair가 만든
earliest-start schedule을 root로 사용하는 것을 전제로 한다. 또한 전체 route/order를
포괄하는 전역 lower bound나 전역 최적성 인증은 아직 아니다.

## 다음 구현 단계

1. OPEN node priority queue와 deterministic node 선택 규칙
2. constraint signature 기반 중복 노드 제거
3. feasible incumbent UB 갱신
4. node LB가 incumbent 이상일 때 가지치기
5. node/time limit과 탐색 종료 사유 기록
6. 모든 route-mode 후보와 결합한 정책별 exact certificate
