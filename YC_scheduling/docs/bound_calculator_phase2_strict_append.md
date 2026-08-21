# Bound Calculator Phase 2: Strict Append Upper Bound

## 구현 목적

Phase 2는 기존 일정을 변경하지 않고 신규 작업을 그 뒤에 배치한 뒤,
전체 결합 일정이 공통 물리검증기를 통과할 때만 그 makespan을 Upper
Bound로 인정한다.

## 실행 흐름

1. `BoundCalculationRequest`를 기존 작업과 신규 작업으로 나눈다.
2. 선택한 협력정책의 실제 planner로 기존 작업만 스케줄링한다.
3. 기존 일정을 공통 simulator로 검증한다.
4. 기존 일정의 마지막 operation 종료시각과 `decision_time` 중 큰 값을
   신규 일정의 시작 경계로 선택한다.
5. 검증된 최종 야드·크레인 상태로 residual instance를 만든다.
6. 같은 협력정책과 같은 planner로 신규 작업을 residual instance에서
   스케줄링한다.
7. 기존 operations와 신규 operations를 이어 붙인다.
8. 결합 일정을 원본 전체 instance에서 다시 검증한다.
9. 이 마지막 검증을 통과한 makespan만 `strict_append_upper_bound`로 저장한다.

## Residual state 정규화

기존 inbound 작업이 완료되면 컨테이너는 최종 stack에 실제로 남아 있다.
Simulator의 작업 종료 표시는 `COMPLETED`이지만 다음 계획에서는 해당
컨테이너가 stack의 물리적 점유물 또는 blocker로 작동해야 한다. 따라서
residual instance에서는 stack에 남은 완료 컨테이너를 `IN_STACK`으로
정규화한다.

또한 두 crane의 위치는 기존 일정 최종 위치로 바뀌고, 두 crane의
`available_time`은 continuation time 이상으로 맞춰진다. 적재 중인 crane이나
컨테이너가 남은 transfer slot은 strict append 경계로 인정하지 않는다.

## 계산값의 의미

- `baseline_makespan`: 기존 작업들의 마지막 final drop 시각
- `baseline_operation_horizon`: 기존 일정의 모든 operation 중 마지막 종료시각
- `strict_append_upper_bound`: 결합 일정의 마지막 final drop 시각
- `makespan_extension`: `strict_append_upper_bound - baseline_makespan`
- `append_valid`: 기존·신규·결합 일정이 필요한 검증을 모두 통과했는지 여부
- `upper_bound_validated`: 전체 원본 instance 재검증까지 통과했는지 여부

`baseline_makespan`과 `baseline_operation_horizon`은 의도적으로 분리한다.
Final drop 뒤에 안전 이동 같은 operation이 존재할 수 있으므로 신규 작업은
makespan이 아니라 실제 operation horizon 이후에 시작해야 한다.

## 아직 계산하지 않는 값

Phase 2는 Strict Append Upper Bound만 계산한다. Full-replan Upper Bound,
Lower Bound, absolute/relative gap은 후속 단계에서 계산한다. 계산하지 않은
필드는 계속 `None`이며 lower-bound 인증 플래그도 `False`이다.

## 주요 파일

- `src/yard_crane_v3/bounds/residual.py`: 다음 계획용 물리상태 생성
- `src/yard_crane_v3/bounds/strict_append.py`: Phase 2 계산 실행 및 감사자료 보존
- `tests/test_bound_phase2_strict_append.py`: 정책별 성공, 시간경계, 상태정규화,
  실패 시 가짜 bound 방지 테스트

