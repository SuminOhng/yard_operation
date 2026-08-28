# Bound Calculator 1단계: 요청 계약과 작업 분리

## 범위

1단계는 Upper Bound와 Lower Bound를 계산하지 않는다. 전체 작업 중 어떤 작업이
기존 계획에 속하고 어떤 작업이 새로 공개됐는지를 오류 없이 고정하고, 이후
Strict Append가 사용할 두 부분문제를 만든다.

```text
전체 StaticSchedulingInstance
  ├─ existing_instance: 기존 작업만 포함
  └─ new_instance: 신규 작업만 포함
```

## 파일 구조

```text
bounds/
├─ request.py   계산 요청과 입력 불변조건
├─ result.py    이후 단계가 채울 안정적인 결과 형태
├─ scenario.py  기존·신규 작업 부분문제 생성
└─ __init__.py  공개 API
```

## BoundCalculationRequest

요청에는 다음 정보가 들어간다.

- 전체 `StaticSchedulingInstance`
- YC 협력정책
- 기존 작업 ID
- 신규 작업 ID
- 계산 결정시각
- 선택적인 기존 작업 인증 Lower Bound

```python
request = BoundCalculationRequest(
    instance=instance,
    policy=CooperationPolicy.HANDSHAKE_AREA,
    existing_job_ids=("JOB_IN_NEAR",),
    new_job_ids=("JOB_OUT_FAR",),
    decision_time=0.0,
)
```

다음 불변조건을 생성 시점에 검사한다.

- 기존 작업과 신규 작업이 각각 한 개 이상 존재
- 각 목록 내부 ID가 중복되지 않음
- 기존·신규 작업이 서로 겹치지 않음
- 모든 ID가 실제 instance에 존재
- instance의 모든 작업이 둘 중 하나로 분류됨
- 결정시각이 유한하며 initial state보다 이르지 않음
- 입력된 인증 LB가 유한하며 initial state보다 이르지 않음

## BoundScenario

`derive_bound_scenario()`는 요청에서 두 instance를 만든다.

```python
scenario = derive_bound_scenario(request)

scenario.existing_instance
scenario.new_instance
```

부분문제는 `jobs`만 선택한다. 다음 물리 객체는 원본과 같은 immutable 객체를
공유한다.

- YardSpec과 모든 stack
- MotionParameters
- PhysicalRules
- 두 CraneSpec
- 초기 YardState와 container 상태
- transfer slot

신규 부분문제에도 기존 컨테이너 상태가 남고, 기존 부분문제에도 신규 컨테이너
상태가 남는다. 이는 작업만 분리하되 같은 실제 야드를 나타내기 위한 의도적인
설계다. 해당 부분문제에서 실행할 `jobs`만 달라진다.

작업 ID를 어떤 순서로 요청하더라도 결과 작업은 원본 instance 순서를 유지한다.
따라서 결과 재현성과 후속 planner 입력순서가 안정적이다.

## BoundCalculationResult

1단계에서는 `BoundCalculationResult.pending(request)`로 계산 전 결과를 만든다.
instance, 정책, 작업 구분과 결정시각만 채우고 다음 값은 비워 둔다.

- baseline makespan과 operation horizon
- Strict Append UB
- Full Replan UB와 Best Known UB
- 세 Lower Bound 구성요소와 결합 LB
- 절대·상대 Gap
- makespan 증가량
- 검증·인증 상태

계산되지 않은 값을 0으로 기록하지 않고 `None`으로 둔다. 0은 실제 계산값일 수
있으므로 미계산 상태와 구분해야 한다.

## 2단계 연결

2단계에서는 다음 순서로 이 계약을 사용한다.

```text
scenario.existing_instance
→ 정책 planner
→ 공통 simulator의 final_state
→ 신규 작업용 residual instance
→ scenario.new_instance의 작업 스케줄링
→ 기존 operation과 신규 operation 결합
→ 원본 전체 instance에서 최종 물리검증
```

기존 작업과 신규 작업의 분류 규칙은 2단계에서 다시 만들지 않고 반드시 이
요청과 scenario를 사용한다.

