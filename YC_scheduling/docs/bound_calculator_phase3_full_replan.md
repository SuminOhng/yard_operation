# Bound Calculator Phase 3: Full Replan Upper Bound

## 구현 목적

Phase 3는 기존 작업과 신규 작업을 하나의 문제로 다시 스케줄링하여
`full_replan_upper_bound`를 계산한다. Phase 2의 Strict Append와 독립적으로
물리검증하며, 검증된 두 값 중 작은 값을 `best_known_upper_bound`로 선택한다.

## Full Replan의 현재 정의

현재 정적 모델에는 `decision_time` 시점까지 실제로 실행된 작업 prefix가 없다.
따라서 Phase 3의 Full Replan은 다음과 같은 정적 비교 기준이다.

- 원본 초기 야드·크레인 상태에서 시작한다.
- 기존 작업과 신규 작업을 모두 planner에 제공한다.
- 기존 작업의 원래 release time은 유지한다.
- 신규 작업의 release time은 최소 `decision_time`으로 제한한다.
- 선택된 YC 협력정책과 공통 물리제약을 그대로 사용한다.

즉 신규 작업을 미리 처리하는 것은 허용하지 않지만, 이미 실행된 prefix를
고정하는 동적 suffix reoptimization은 아니다. 실제 실행 prefix를 가진
재스케줄링은 동적 단계에서 별도 구현해야 한다.

## 계산 흐름

1. 신규 작업 release time을 `max(original release, decision_time)`으로 만든다.
2. 기존·신규 작업 전체를 선택된 정책 planner로 스케줄링한다.
3. 공통 simulator와 validator로 전체 일정을 검증한다.
4. 검증된 makespan만 `full_replan_upper_bound`로 인정한다.
5. Strict Append UB와 Full Replan UB 중 작은 값을 선택한다.

```text
best_known_upper_bound = min(
    validated strict_append_upper_bound,
    validated full_replan_upper_bound,
)
```

휴리스틱에서는 Full Replan의 탐색공간이 더 넓더라도 Strict Append보다 나쁜
일정을 찾을 수 있다. 그래서 정책의 이론적 포함관계를 가정하여 값을
덮어쓰지 않고, 실제 검증된 두 값을 모두 보존한 뒤 최소값만 선택한다.

## 감사 구조

`UpperBoundCalculation`은 다음 자료를 함께 보존한다.

- 최종 병합 `BoundCalculationResult`
- Strict Append의 기존·신규·결합 일정과 검증 결과
- Full Replan instance, 일정, 검증 결과
- 각 bound가 만들어진 과정인 `bound_provenance`

계산이 실패하면 해당 방법의 Upper Bound는 `None`이며 오류가 별도 artifact에
남는다. 하나의 방법만 성공해도 그 검증값은 best-known UB로 사용할 수 있다.

## 아직 구현하지 않은 범위

- Lower Bound
- absolute gap과 relative gap
- 실행 중인 작업의 frozen prefix
- decision epoch의 실제 yard/crane snapshot
- suffix-only reoptimization

## 주요 파일

- `src/yard_crane_v3/bounds/full_replan.py`
- `src/yard_crane_v3/bounds/calculator.py`
- `tests/test_bound_phase3_full_replan.py`

