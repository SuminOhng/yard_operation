# Pipeline Handover and Spatial Replay

## 목적

기존 serial handover 후보는 작업마다 두 크레인을 동기화하고 외곽 bay로
복귀시켰다. 이 구조에서는 인계정책의 이점보다 불필요한 대기와 빈 이동이 더 크게
나타났다. 파이프라인 후보는 물리조건을 바꾸지 않고 다음 세 가지를 개선한다.

- donor가 다음 컨테이너를 준비하는 동안 receiver가 이전 컨테이너를 운반한다.
- 각 작업 후 외곽 parking bay로 복귀하지 않는다.
- 고정 buffer 또는 임시 stack 인계점에 drop된 컨테이너는 receiver의 고정 operation sequence에서
  pickup되고 최종 목적지까지 연속 처리된다.

## 일정 생성 구조

정책별 파일은 다음과 같다.

```text
planners/
├─ pipeline.py
│  ├─ 고정 buffer·임시 stack 인계점 capacity 선후관계
│  ├─ donor/receiver transfer bay 접근 선후관계
│  └─ bounded timing repair
├─ handshake_area/pipeline.py
│  └─ 지정 H bay의 파이프라인 seed
└─ any_bay/pipeline.py
   └─ 모든 물리적 transfer bay별 고정경계 파이프라인 seed
```

먼저 기존 물리 operation 생성함수로 상태가 올바른 serial seed를 만든다. 이
단계에서 pickup, drop, stack, reshuffle과 container 상태 변화가 결정된다. 파이프라인
builder는 외곽 복귀 operation을 추가하지 않는다.

`HANDSHAKE_AREA` 파이프라인은 같은 물리 seed 생성 로직으로 여러 작업순서도
평가한다. `original`은 입력 순서를 보존하고, `cross_first`는 H 인계가 필요한
작업을 먼저 배치하며, `balanced_interleave`는 해측 local 작업과 H 인계 작업을
교차 배치해 육측 크레인이 초반부터 원거리 수출 작업을 H bay로 가져오게 한다.

그다음 `repair_schedule_timing()`이 다음 선후관계만 남기고 operation을 가능한
왼쪽으로 이동한다.

1. 같은 크레인의 operation 순서
2. 같은 job의 donor, transfer, receiver 순서
3. 같은 transfer point의 capacity와 stack tier 순서
4. donor가 transfer bay에서 퇴거한 뒤 receiver가 진입하는 순서
5. 이전 receiver가 transfer bay에서 퇴거한 뒤 다음 donor가 진입하는 순서

따라서 선택된 transfer point는 한 번에 한 컨테이너만 사용하지만, transfer bay 밖의
donor 준비와 receiver 운반은 동시에 실행할 수 있다. donor의 퇴거 위치는 외곽
parking bay가 아니라 transfer bay에서 최소 안전거리만큼 떨어진 staging 위치다.

마지막으로 공통 Simulator와 Validator가 연속 crane separation, non-crossing,
operation duration, stack capacity, tier, blocker, transfer capacity와 모든 최종
drop을 검사한다. 이 검사를 통과한 일정만 Upper Bound 후보가 된다.

`FIXED_BUFFER`는 입력에 정의된 독립 buffer다. `STACK_BACKED`는 입력에 지정된
실제 stack 상단을 사용한다. `VIRTUAL_STACK`은 런타임에 생성되는 같은 물리방식의
논리적 인계점이다. 두 stack 방식 모두 drop부터 pickup까지 다음 빈 tier를 실제
점유하며 최대 tier와 최상단 pickup 규칙을 적용한다.

## 후보 평가

다음 함수는 scheduler가 비교한 후보를 숨기지 않고 반환한다.

```python
evaluate_handshake_area_candidates(instance)
evaluate_any_bay_candidates(instance)
```

각 `PlannerCandidateEvaluation`에는 label, schedule, ValidationResult, error가 들어
있다. 화면의 직접 운반, H handover, ANY_BAY handover 카드는 실제 선택된 검증
일정의 makespan, handover 수와 operation 수를 표시한다.

## 공간 리플레이

리플레이는 별도 물리 시뮬레이션을 만들지 않는다. 공통 Validator가 생성한
`OperationTrace`와 `StateDelta`를 JSON에 기록하고, HTML은 그 결과만 재생한다.

- 이동 operation 중 crane bay와 row는 시작·종료 위치 사이를 선형 보간한다.
- pickup, handover drop/pickup, final drop 완료시점에는 Simulator의 상태 delta를
  적용한다.
- stack, AGV, 실제 사용 transfer point와 crane 적재 상태를 시간 슬라이더 위치에 맞춰 표시한다.
- 수입은 초록 원, 수출은 주황 마름모로 표시하며 crane 적재 중에도 같은 표식을
  유지한다. 작업에 연결되지 않은 blocker는 회색 사각형으로 표시한다.
- 정책 탭을 바꾸면 해당 정책의 Best UB 일정으로 리플레이가 초기화된다.
- 재생, 일시정지, 처음으로 이동, 직접 시간 탐색과 0.5배~32배 속도를 지원한다.

Gantt Chart, 후보 makespan 카드와 공간 리플레이는 모두 같은
`StaticScheduleVisualization`에서 생성된다. 감사용
`visualization_data.json`의 schema version은 `2.2.0`이다. 각 handover operation은
`transfer_point_kind`를 기록하며, 고정 buffer는 보라색 사각형, ANY 임시 stack
인계점은 보라색 점선 마름모로 구분한다.

## 20작업 결과

`data/large_15out_5in_seed42.json`을 전체 정적 문제로 실행한 planner 결과는 다음과
같다.

| 정책 | 검증 makespan | handover | 사용 transfer bay |
|---|---:|---:|---|
| NO_SHARING | 396.75초 | 0 | 없음 |
| HANDSHAKE_AREA | 291.15초 | 9 | 10 |
| ANY_BAY | 284.35초 | 16 | 2, 3, 4, 5, 6, 7, 8, 9 |

Bound 시각화의 기존·신규 작업 분할에서 ANY_BAY의 Best UB는 284.35초다.
True ANY_BAY 후보는 모두 공통 Simulator로 검증되며, 해측 수출 방향이 반영된 이
입력에서는 여러 가상 stack 인계점을 사용해 H bay 10보다 빠른 Best UB가 된다.

## 현재 한계

파이프라인은 fixed job order와 후보별 fixed transfer boundary를 사용하는 feasibility
heuristic이다. 여러 job order와 작업별 transfer point 조합을 전역 탐색하지 않으며
최적해 인증을 제공하지 않는다. 동적 arrival과 재스케줄링도 이 정적 단계의 범위가
아니다.
