# Reference Solver Phase 4: Structured Crane Conflicts

## 목적

기존 Validator의 `CRANE_SEPARATION` 문자열을 Branch-and-Bound가 사용할 수 있는
구조화된 자료로 확장한다. 충돌 판정은 별도 근사식이 아니라 공통 simulation
계층의 단일 탐지기를 사용한다.

## CraneConflict

```text
onset_time
witness_time
interval_start / interval_end
seaside_crane_id / landside_crane_id
seaside_operation_index / landside_operation_index
seaside_bay / landside_bay
actual_separation
required_separation
violation_amount
```

`onset_time`은 안전거리 위반이 시작되는 연속시간이다. `witness_time`은 해당
선형 구간에서 위반량이 가장 큰 검증시각이다. 한 크레인이 정지해 있으면 그
크레인의 operation index는 `None`일 수 있다.

## 연속시간 계산

각 크레인의 gantry 위치는 operation 구간에서 선형으로 변한다. 두 크레인의
거리도 각 event interval 안에서는 선형이므로 시작점과 끝점, 안전거리와의
교차시각을 계산하면 최초 위반시각을 정확히 구할 수 있다.

예제:

```text
C_SEA: bay 0 → 4, t=0..4
C_LAND: bay 7 → 3, t=0..4
required separation = 1

separation(t) = 7 - 2t
7 - 2t = 1
onset_time = 3
```

`t=4`의 실제 separation은 -1이고 위반량은 2다.

## Simulator 단일 기준

공통 Simulator의 연속 안전거리 검사도 `first_crane_conflict()`를 호출한다.
따라서 다음 두 결과의 충돌시각이 항상 같다.

```text
구조화된 CraneConflict.onset_time
CRANE_SEPARATION SimulationViolation.time
```

Public 함수:

```python
detect_crane_conflicts(instance, schedule)
first_crane_conflict(instance, schedule)
```

## 다음 단계

1. `TimingConstraint(operation_index, earliest_start, reason)` 구현
2. 기존 crane/job precedence와 TimingConstraint를 함께 적용해 재스케줄링
3. 최초 CraneConflict에서 해측 지연·육측 지연 Node 생성
4. 동일 constraint 집합 중복 제거
5. Node LB와 incumbent UB를 이용한 가지치기
