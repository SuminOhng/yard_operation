# 야드 크레인 스케줄러 사용 설명서

이 문서는 `static_version_3`의 세 가지 야드 크레인 스케줄러를 처음 보는 사람이
같은 입력 데이터로 무엇을 실행하고, 코드가 어떤 순서로 움직이며, 최종 산출물이
무엇인지 이해할 수 있도록 정리한 사용 설명서이다.

대상 정책은 다음 세 가지이다.

| 정책 | 의미 | 인계 허용 |
|---|---|---|
| `NO_SHARING` | 두 크레인이 컨테이너를 서로 넘기지 않고 직접 처리한다. | 없음 |
| `HANDSHAKE_AREA` | 직접 처리 또는 지정된 H bay 고정 버퍼에서 1회 인계한다. | 입력의 `handshake_bay` 고정 transfer slot |
| `ANY_BAY` | 직접 처리, H bay 인계, 작업 bay/row의 임시 stack-top 인계를 모두 후보로 둔다. | 고정 transfer slot + 자동 생성 virtual transfer slot |

세 정책은 모두 같은 입력 JSON, 같은 물리 시간 모델, 같은 크레인 안전거리 규칙,
같은 검증기를 사용한다. 정책별 차이는 “컨테이너를 어디서 넘길 수 있는가”뿐이다.

## 빠른 실행

작업 디렉터리는 `static_version_3`이다.

```powershell
cd C:\Users\sumin\OneDrive\Desktop\RiskLab\AGV_Truck_Study\static_version_3
```

세 정책을 한 번에 비교한다.

```powershell
python3.14 scripts/run_three_policy_comparison.py data/any_bay_handover_micro.json
```

요약 JSON과 정책별 schedule JSON까지 파일로 저장한다.

```powershell
python3.14 scripts/run_three_policy_comparison.py `
  data/any_bay_handover_micro.json `
  --output-dir results/any_bay_micro
```

정책 하나만 실행할 수도 있다.

```powershell
python3.14 scripts/run_no_sharing.py data/static_fair_micro.json
python3.14 scripts/run_handshake_area.py data/handshake_handover_micro.json
python3.14 scripts/run_any_bay.py data/any_bay_handover_micro.json
```

## 전체 흐름

세 정책 비교 실행은 다음 순서로 진행된다.

```text
입력 JSON 파일
  ↓
load_instance()
  ↓
parse_instance(): JSON을 StaticSchedulingInstance로 변환 : 입력 전체를 담은 객체. 
  ↓
validate_instance(): 입력 데이터 자체 검증
  ↓
validate_policy_lattice(): NO_SHARING ⊆ HANDSHAKE_AREA ⊆ ANY_BAY 관계 검증
  ↓
run_three_policy_comparison()
  ├─ build_no_sharing_schedule()
  ├─ build_handshake_area_schedule()
  └─ build_any_bay_schedule()
  ↓
validate_schedule(): 각 후보 schedule을 동일한 simulator로 replay 검증
  ↓
PolicyMetrics / ThreePolicyComparison 생성
  ↓
화면 JSON 출력 또는 output-dir에 파일 저장
```

중요한 점은 planner가 만든 일정이 곧바로 정답으로 채택되지 않는다는 것이다.
각 planner는 `CandidateSchedule`을 만들고, 공통 `validate_schedule()`이 그
일정을 처음부터 끝까지 다시 replay한다. 이 replay에서 물리 규칙, stack 상태,
transfer slot 상태, handover 횟수, crane 간 안전거리 등이 맞아야만 유효한
upper bound로 인정된다.

## 입력 JSON의 공통 데이터

모든 scheduler는 하나의 `StaticSchedulingInstance`를 입력으로 받는다. 
이 객체는 JSON 파일에서 만들어지며, 세 정책에 동일하게 전달된다.

최상위 JSON 필드는 다음과 같다.

| 필드 | 역할 |
|---|---|
| `schema_version` | 입력 형식 버전. 현재 `"3.1.0"`이어야 한다. |
| `instance_id` | 문제 인스턴스 ID. 결과 파일에도 들어간다. |
| `layout` | 야드 block, bay/row/tier 수, handshake bay 위치. |
| `motion` | bay 이동, row 이동, tier별 hoist, pickup/drop 시간. |
| `physical_rules` | 크레인 최소 안전거리와 작업당 최대 handover 수. |
| `cranes` | 해측/육측 크레인 ID, side, 초기 위치. |
| `transfer_slots` | 입력에 명시된 고정 transfer buffer 목록. |
| `initial_state` | 초기 stack, container, crane, transfer slot 상태. |
| `jobs` | 처리할 컨테이너 작업 목록. |

### `layout`

예시:

```json
{
  "block_id": "B1",
  "bays": 6,
  "rows": 2,
  "tiers": 4,
  "handshake_bay": 3
}
```

`bays=6`이면 실제 작업 bay는 `1..6`이다. 해측 외부 대기 bay는 자동으로 `0`,
육측 외부 대기 bay는 자동으로 `7`이 된다. 크레인은 이 외부 대기 위치와 작업
bay를 포함한 rail 위에서 움직인다.

`handshake_bay`는 `HANDSHAKE_AREA`가 사용할 고정 인계 bay이다. 해당 bay에는
enabled transfer slot이 최소 하나 있어야 한다.

### `motion`

예시:

```json
{
  "gantry_seconds_per_bay": 1.0,
  "trolley_seconds_per_row": 1.0,
  "hoist_seconds_per_tier": 0.5,
  "pickup_seconds": 1.0,
  "drop_seconds": 1.0
}
```

`TimeModel`이 이 값을 사용해 operation 시간을 계산한다. bay 이동은 gantry 시간,
row 이동은 trolley 시간, stack tier가 있는 pickup/drop은 hoist 시간을 반영한다.

### `physical_rules`

예시:

```json
{
  "minimum_crane_separation_bays": 1.0,
  "maximum_handovers_per_job": 1
}
```

두 크레인은 같은 rail 위에서 움직이므로 서로 교차하거나 최소 안전거리보다 가까워질
수 없다. `maximum_handovers_per_job`은 한 작업이 컨테이너 인계를 몇 번까지 할 수
있는지 제한한다. 현재 정책들은 직접 운반 또는 1회 handover를 전제로 한다.

NO_SHARING: handover 자체 금지. 실제 최대 0.
HANDSHAKE_AREA: H bay에서 최대 1회.
ANY_BAY: 고정/가상 transfer point에서 최대 1회.


### `cranes`

예시:

```json
[
  {
    "id": "C_SEA",
    "side": "SEASIDE",
    "initial_position": {"bay": 0, "row": 1}
  },
  {
    "id": "C_LAND",
    "side": "LANDSIDE",
    "initial_position": {"bay": 7, "row": 1}
  }
]
```

정확히 두 대가 필요하다. 하나는 `SEASIDE`, 하나는 `LANDSIDE`여야 한다. 세 정책
모두 같은 두 크레인을 활성화한다.

### `transfer_slots`

예시:

```json
[
  {
    "id": "H_ROW_1",
    "position": {"bay": 3, "row": 1},
    "capacity": 1,
    "enabled": true
  }
]
```

입력에 쓰는 transfer slot은 고정 buffer로 취급된다. `HANDSHAKE_AREA`는 이 중
`layout.handshake_bay`에 있고 `enabled=true`인 slot만 쓴다.

`ANY_BAY`는 입력 고정 slot에 더해, 고정 slot이 없는 모든 작업 bay/row 좌표에
가상 transfer slot을 런타임에 자동 생성한다. ID 형식은 다음과 같다.

```text
VIRTUAL::<block_id>::BAY_<bay>::ROW_<row>
```

예: `VIRTUAL::B1::BAY_5::ROW_1`

가상 transfer slot은 별도 설비가 아니라 일반 stack top에 잠시 내려놓는 인계
동작을 뜻한다. 따라서 stack capacity와 top-of-stack 규칙을 그대로 따른다.

### `initial_state`

초기 상태는 네 부분이다.

| 하위 필드 | 역할 |
|---|---|
| `current_time` | 일정 시작 시각. |
| `stacks` | 현재 stack별 컨테이너 배열. bottom-to-top 순서이다. |
| `containers` | 컨테이너별 상태, 현재 slot, 목표 slot. |
| `cranes` | 크레인별 현재 위치, 들고 있는 컨테이너, 사용 가능 시각. |
| `transfer_slots` | 고정 transfer slot별 현재 보유 컨테이너. |

입력에 비어 있는 stack을 모두 직접 적을 필요는 없다. loader가 layout에 맞춰 모든
bay/row stack을 만들고, JSON에 나열된 stack에만 컨테이너를 채운다.

컨테이너 상태는 stack 배열과 맞아야 한다. 예를 들어 `IN_STACK` 컨테이너는
`current_slot`이 있어야 하며, 그 slot의 tier와 stack 배열 위치가 일치해야 한다.
`ON_AGV` 컨테이너는 야드 안 holder가 없어야 한다.

### `jobs`

예시:

```json
{
  "id": "JOB_IN_NEAR",
  "container_id": "CONT_IN_NEAR",
  "direction": "INBOUND",
  "origin": {"bay": 0, "row": 1},
  "destination": {"bay": 2, "row": 1},
  "final_slot": {
    "block_id": "B1",
    "bay": 2,
    "row": 1,
    "tier": 1
  },
  "release_time": 0.0,
  "agv_ready_time": 0.0
}
```

`origin`과 `destination`은 크레인이 컨테이너를 집고 내려놓는 위치이다. 수입
작업은 보통 외부 bay에서 시작해 yard stack으로 들어오며, `final_slot`이 필요하다.
수출 작업은 stack에서 시작해 외부 bay로 나가며, 보통 `final_slot`은 `null`이다.

`release_time`과 `agv_ready_time` 중 늦은 값이 작업 ready time으로 쓰인다.

## 정책별 scheduler 동작

### `NO_SHARING`

파일 위치:

```text
src/yard_crane_v3/planners/no_sharing/scheduler.py
```

진입 함수:

```python
build_no_sharing_schedule(instance, CooperationPolicy.NO_SHARING)
```

동작 개요:

1. 각 job을 해측 local, 육측 local, cross-region으로 분류한다.
2. 해측 local job은 해측 크레인이 처리한다.
3. 육측 local job은 육측 크레인이 처리한다.
4. cross-region job은 한 크레인이 직접 처리하고, 다른 크레인은 외부 대기 위치로
   이동해 안전거리를 확보한다.
5. 컨테이너 위에 blocker가 있으면 허용된 안전 bay 안의 다른 stack으로 reshuffle한다.
6. handover operation은 절대 만들지 않는다.
7. 생성된 schedule을 `NO_SHARING` constraints로 검증한다.

결과적으로 `HANDOVER_DROP`, `HANDOVER_PICKUP` operation이 없어야 한다. 유효하면
handover count는 0이다.

### `HANDSHAKE_AREA`

파일 위치:

```text
src/yard_crane_v3/planners/handshake_area/scheduler.py
```

진입 함수:

```python
build_handshake_area_schedule(instance, CooperationPolicy.HANDSHAKE_AREA)
```

동작 개요:

1. 입력의 `handshake_bay`에 있는 enabled fixed transfer slot을 후보로 본다.
2. 직접 처리 가능한 job은 한 크레인이 origin부터 destination까지 운반한다.
3. 두 크레인 협력이 유리하거나 필요한 job은 H bay transfer slot에서 1회 인계한다.
4. donor crane이 컨테이너를 transfer slot에 내려놓는다.
5. receiver crane이 같은 transfer slot에서 컨테이너를 집어 최종 목적지로 운반한다.
6. 중간 중간 `_synchronize()`와 외부 대기 이동으로 두 크레인의 rail 안전거리를 맞춘다.
7. 생성된 schedule을 `HANDSHAKE_AREA` constraints로 검증한다.

이 정책은 H bay 외 transfer slot을 쓰면 검증에서 실패한다.

### `ANY_BAY`

파일 위치:

```text
src/yard_crane_v3/planners/any_bay/scheduler.py
```

진입 함수:

```python
build_any_bay_schedule(instance, CooperationPolicy.ANY_BAY)
```

동작 개요:

1. `constraints_for(instance, ANY_BAY)`에서 transfer slot을 얻는다.
2. 그중 `STACK_BACKED`와 `VIRTUAL_STACK`을 현재 planner의 인계 후보로 사용한다.
3. 작업별 transfer 후보를 골라 seed schedule을 만든다.
4. 후보별로 donor/receiver handover operation을 만든다.
5. 필요한 경우 `repair_pipeline_seed()`가 timing을 보정한다.
6. 모든 후보를 공통 validator로 검증한다.
7. 유효 후보 중 `(makespan, handover_count, operation_count, label)` 순으로 가장 좋은 schedule을 선택한다.

세 정책의 허용 공간은 중첩되지만 현재 planner의 휴리스틱 후보 집합은 독립적이다.
따라서 다음 관계는 비교기가 관찰하는 지표이며 보장 조건이 아니다.

```text
ANY_BAY upper bound <= HANDSHAKE_AREA upper bound <= NO_SHARING upper bound
```

관계가 깨져도 각 일정이 유효할 수 있다.

## 공통 schedule 형식

planner의 결과는 `CandidateSchedule`이다.

```python
CandidateSchedule(
    instance_id="...",
    policy=CooperationPolicy.ANY_BAY,
    operations=(ScheduledOperation(...), ...)
)
```

각 operation은 다음 정보를 가진다.

| 필드 | 의미 |
|---|---|
| `crane_id` | operation을 수행하는 크레인 ID. |
| `operation_type` | 이동, pickup, handover drop/pickup, final drop, wait 등. |
| `purpose` | 주 작업, handover, reshuffle 중 무엇인지. |
| `start_time`, `end_time` | operation 시작/종료 시각. |
| `start_position`, `end_position` | bay/row 위치. |
| `job_id` | 관련 job ID. 없을 수 있다. |
| `container_id` | 관련 container ID. 없을 수 있다. |
| `transfer_slot_id` | handover에 사용한 transfer slot ID. |
| `target_slot` | stack에 내려놓을 때의 target slot. |

operation type은 다음 값을 쓴다.

| 값 | 의미 |
|---|---|
| `MOVE_EMPTY` | 컨테이너 없이 이동. |
| `PICKUP` | 컨테이너를 집음. |
| `MOVE_LOADED` | 컨테이너를 들고 이동. |
| `HANDOVER_DROP` | donor가 transfer slot에 내려놓음. |
| `HANDOVER_PICKUP` | receiver가 transfer slot에서 집음. |
| `FINAL_DROP` | 최종 목적지 또는 reshuffle 목적지에 내려놓음. |
| `WAIT` | 대기. |

purpose는 다음 값을 쓴다.

| 값 | 의미 |
|---|---|
| `PRIMARY_JOB` | 원래 job 처리를 위한 operation. |
| `HANDOVER` | 두 크레인 사이 인계를 위한 operation. |
| `RESHUFFLE` | blocker 제거를 위한 임시 재배치 operation. |

## 검증기가 확인하는 것

`validate_schedule(instance, constraints, schedule)`은 schedule을 다시 replay한다.
검증기는 planner 내부 상태를 믿지 않고, 입력 초기 상태에서 operation을 순서대로
적용한다.

대표적으로 다음을 확인한다.

| 검증 대상 | 설명 |
|---|---|
| 정책 제약 | 해당 정책에서 허용된 크레인과 transfer slot만 쓰는지 확인한다. |
| handover 횟수 | 작업별 최대 handover 수를 넘지 않는지 확인한다. |
| 컨테이너 소유자 | 컨테이너가 stack, crane, transfer slot 중 한 곳에만 있는지 확인한다. |
| stack 규칙 | capacity, tier, top-of-stack pickup/drop이 맞는지 확인한다. |
| transfer slot 규칙 | capacity와 pickup/drop 순서가 맞는지 확인한다. |
| crane 이동 | rail 위 위치인지, 시간 계산과 이동 경로가 맞는지 확인한다. |
| 크레인 안전거리 | 두 크레인이 교차하거나 최소 bay separation을 위반하지 않는지 확인한다. |
| 완료 작업 | 모든 job이 완료 상태가 되었는지 확인한다. |

검증에 실패하면 해당 schedule은 유효한 upper bound가 아니다. 세 정책 비교기에서는
한 정책이 실패해도 나머지 정책 실행 결과는 보존된다.

## 세 정책 비교기의 결과

`scripts/run_three_policy_comparison.py`는 화면에 summary JSON을 출력한다.

주요 필드는 다음과 같다.

| 필드 | 의미 |
|---|---|
| `instance_id` | 입력 인스턴스 ID. |
| `all_valid` | 세 정책 schedule이 모두 검증 통과했는지. |
| `nested_upper_bounds_hold` | `ANY_BAY <= HANDSHAKE_AREA <= NO_SHARING` 관계가 성립하는지. |
| `policies` | 정책별 metrics 묶음. |

정책별 metrics는 다음과 같다.

| 필드 | 의미 |
|---|---|
| `valid` | 검증 통과 여부. |
| `feasible_upper_bound` | 유효 schedule의 makespan. 실패하면 `null`. |
| `runtime_seconds` | planner 실행과 검증에 걸린 시간. |
| `handover_count` | schedule 내 handover 횟수. |
| `reshuffle_count` | blocker reshuffle 횟수. |
| `operation_count` | operation 개수. |
| `used_crane_ids` | 실제 operation에 등장한 crane ID 목록. |
| `used_transfer_slot_ids` | 실제 사용된 transfer slot ID 목록. |
| `completed_job_ids` | simulator가 완료로 인정한 job ID 목록. |
| `violation_codes` | 검증 실패 코드. planner 예외는 `PLANNER_ERROR`. |
| `policy` | 정책 이름. |
| `planner` | 사용된 planner 함수 이름. |
| `error` | planner 예외 메시지. 없으면 `null`. |

`--output-dir`을 주면 다음 파일이 저장된다.

```text
comparison_summary.json
no_sharing_schedule.json
handshake_area_schedule.json
any_bay_schedule.json
```

`comparison_summary.json`은 화면 출력과 같은 요약 정보이다.

각 `*_schedule.json`은 정책별 요약 정보에 더해 `operations` 배열을 가진다. 이
배열이 실제 Gantt chart나 replay visualization의 원천 데이터가 된다.

## 결과 해석 방법

`feasible_upper_bound`는 검증된 makespan이다. 값이 작을수록 해당 planner가 더
짧은 일정을 찾았다는 뜻이다.

단, 이것은 전역 최적해가 아니라 현재 휴리스틱 planner가 찾은 검증된 upper bound이다.
정책 feasible set이 더 넓어도 제한된 휴리스틱이 더 좋은 일정을 항상 찾는 것은
아니다.

`nested_upper_bounds_hold=false`이면 다음을 확인한다.

1. 독립적인 휴리스틱 후보 제한 때문에 상위 정책 일정이 더 길어졌는지 확인한다.
2. 후보 선택 기준이나 validation 정책 매핑이 잘못되었는지 확인한다.
3. 입력의 transfer slot 또는 handshake bay 정의가 의도와 맞는지 확인한다.

`all_valid=false`이면 먼저 정책별 `violation_codes`와 `error`를 확인한다.

## 예시 입력에서 결과 보기

명령:

```powershell
python3.14 scripts/run_three_policy_comparison.py `
  data/any_bay_handover_micro.json `
  --output-dir results/any_bay_micro
```

확인할 파일:

```text
results/any_bay_micro/comparison_summary.json
results/any_bay_micro/no_sharing_schedule.json
results/any_bay_micro/handshake_area_schedule.json
results/any_bay_micro/any_bay_schedule.json
```

읽는 순서:

1. `comparison_summary.json`에서 `all_valid`가 `true`인지 확인한다.
2. `nested_upper_bounds_hold`가 `true`인지 확인한다.
3. 각 정책의 `feasible_upper_bound`를 비교한다.
4. `used_transfer_slot_ids`로 어떤 인계점이 실제 쓰였는지 확인한다.
5. 더 자세히 보고 싶으면 각 `*_schedule.json`의 `operations` 배열을 시간순으로 읽는다.

## 입력을 새로 만들 때 체크리스트

- `schema_version`은 `"3.1.0"`이다.
- `layout.handshake_bay`는 `1..bays` 안에 있다.
- `transfer_slots`에는 `handshake_bay` 위치의 enabled slot이 하나 이상 있다.
- crane은 정확히 두 대이며 `SEASIDE`, `LANDSIDE`가 각각 하나씩 있다.
- crane initial state는 crane spec의 initial position과 같다.
- stack 배열은 bottom-to-top 순서이다.
- `IN_STACK` 컨테이너의 `current_slot.tier`는 stack 배열 순서와 일치한다.
- `ON_AGV` 컨테이너는 `current_slot`, `carried_by`, `transfer_slot_id`가 없다.
- 모든 job의 `container_id`는 `initial_state.containers`에 존재한다.
- 수입 job은 `final_slot`이 있고 `destination`과 같은 bay/row이다.
- 수출 job은 출발 stack에 컨테이너가 실제로 있어야 한다.
- stack capacity를 넘는 초기 상태나 final slot을 만들지 않는다.
- job ID와 container ID는 중복되지 않는다.

## 코드 위치 요약

| 파일 | 역할 |
|---|---|
| `scripts/run_three_policy_comparison.py` | 세 정책 비교 CLI 진입점. |
| `scripts/run_no_sharing.py` | `NO_SHARING` 단일 실행 CLI. |
| `scripts/run_handshake_area.py` | `HANDSHAKE_AREA` 단일 실행 CLI. |
| `scripts/run_any_bay.py` | `ANY_BAY` 단일 실행과 visualization 옵션 CLI. |
| `src/yard_crane_v3/loader.py` | JSON 입력을 `StaticSchedulingInstance`로 변환. |
| `src/yard_crane_v3/model/` | layout, crane, yard, state, job 자료구조와 입력 불변조건. |
| `src/yard_crane_v3/policy.py` | 정책별 허용 transfer slot과 포함관계 정의. |
| `src/yard_crane_v3/planners/no_sharing/scheduler.py` | 인계 없는 scheduler. |
| `src/yard_crane_v3/planners/handshake_area/scheduler.py` | H bay 인계 scheduler. |
| `src/yard_crane_v3/planners/any_bay/scheduler.py` | 고정/가상 인계점 후보 scheduler. |
| `src/yard_crane_v3/schedule.py` | schedule과 operation 자료구조. |
| `src/yard_crane_v3/validator.py` | simulator replay 기반 검증 진입점. |
| `src/yard_crane_v3/comparison/runner.py` | 세 정책 실행과 metrics 생성. |
| `src/yard_crane_v3/comparison/serialization.py` | summary와 schedule artifact JSON 저장. |

## 한 줄 요약

이 프로젝트의 세 scheduler는 같은 JSON 입력을 읽어 같은 물리 모델 위에서 각기 다른
handover 허용범위를 적용하고, 각자가 만든 `CandidateSchedule`을 공통 simulator로
검증한 뒤, 검증된 makespan upper bound와 operation-level JSON 산출물을 반환한다.
