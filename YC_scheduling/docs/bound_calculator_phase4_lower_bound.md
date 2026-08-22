# Bound Calculator Phase 4: Certified Lower Bound and Gap

## 구현 목적

Phase 4는 검증된 Upper Bound와 비교할 수 있는 보수적인 Lower Bound를
계산한다. Lower Bound는 예상 makespan이 아니라, 어떤 실행 가능한 일정도
이보다 빨리 끝날 수 없다는 낙관적 기준이다.

## 기존 아이디어의 명확한 해석

“기존 스케줄의 최적해 안에서 신규 작업이 유휴시간에 처리된다”는 아이디어는
기존 작업의 **최적값 또는 인증된 lower bound**가 있을 때 유효하다. 현재
planner가 만든 기존 일정의 makespan은 실행 가능한 Upper Bound이지 자동으로
Lower Bound가 되지 않는다.

따라서 입력의 `certified_existing_lower_bound`만 인증된 외부값으로 사용한다.
이 값이 없으면 기존 작업에도 안전한 analytical relaxation을 적용한다.

## 구현된 Lower Bound

### Existing-jobs LB

다음 값의 최댓값이다.

- 기존 작업들의 mandatory workload를 active crane 수로 나눈 값
- 기존 작업별 낙관적 earliest completion의 최댓값
- 사용자가 제공한 `certified_existing_lower_bound`가 있으면 그 값

### New-jobs earliest-completion LB

신규 작업별로 다음을 계산하고 최댓값을 사용한다.

```text
availability = max(job ready time, decision_time)
earliest completion = availability + minimum pickup + minimum drop
```

Travel, interference, blocker, reshuffle를 일부러 무시한다. 컨테이너가 미리
이동될 가능성까지 허용하는 낙관적 완화이므로 안전한 Lower Bound가 된다.

### Workload LB

각 작업에 반드시 필요한 최소 crane work를 다음처럼 계산한다.

```text
minimum pickup + direct loaded travel + minimum final drop
```

그 합계를 active crane 수로 나눈다. Empty travel, safety waiting, handover,
stacking interference와 reshuffle는 무시하므로 실제 일정시간을 과대평가하지
않는 완화값이다.

### Combined LB

```text
combined_lower_bound = max(
    existing_jobs_lower_bound,
    new_jobs_earliest_completion,
    workload_lower_bound,
)
```

독립적으로 유효한 Lower Bound들의 최댓값도 유효하며, 각각보다 강한 bound다.

## Gap 정의

```text
absolute_gap = best_known_upper_bound - combined_lower_bound

relative_gap = absolute_gap / best_known_upper_bound
```

Relative gap은 0에서 1 사이의 비율이며 화면에서 필요하면 100을 곱해 백분율로
표시할 수 있다.

## 안전장치

- Lower Bound와 Upper Bound는 같은 request에서 나온 결과만 결합한다.
- Combined LB가 검증된 UB보다 크면 모순으로 판정한다.
- 모순이면 `lower_bound_certified=False`로 바꾸고 gap을 `None`으로 둔다.
- Planner의 baseline makespan은 인증 근거 없이 LB로 사용하지 않는다.
- 작업별 구성값과 bound provenance를 결과에 보존한다.

## 공용 실행 함수

```python
calculation = calculate_bounds(request)
result = calculation.result
```

`calculation.upper_bounds`에는 Strict Append와 Full Replan 증거가,
`calculation.lower_bound`에는 작업별 Lower Bound 구성값이 들어 있다.

## 주요 파일

- `src/yard_crane_v3/bounds/lower_bound.py`
- `src/yard_crane_v3/bounds/bound_calculator.py`
- `tests/test_bound_phase4_lower_bound.py`

