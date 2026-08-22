# 공통 물리모델 1차 구현 보고

## 구현 목표

첫 단계의 목표는 정책별 planner를 만들기 전에 세 정책이 공유할 야드 구조와
초기 상태를 하나의 자료계약으로 고정하는 것이다. 이번 단계에서는 상태를
실제로 변경하는 simulator까지 구현하지 않는다.

## 폴더와 책임

```text
src/yard_crane_v3/
├─ model/
│  ├─ geometry.py
│  ├─ equipment.py
│  ├─ yard.py
│  ├─ job.py
│  ├─ state.py
│  └─ instance.py
├─ loader.py
├─ timing.py
├─ policy.py
├─ schedule.py
├─ planner.py
├─ validator.py
└─ runner.py
```

### `model/geometry.py`

- `Position`: 크레인이 이동하는 bay/row 좌표
- `StackKey`: block/bay/row로 stack 식별
- `Slot`: block/bay/row/tier로 컨테이너의 정확한 위치 식별

### `model/equipment.py`

- `CraneSpec`: 크레인 ID, 측면, 초기 위치
- `MotionParameters`: gantry, trolley, hoist, pickup, drop 시간

### `model/yard.py`

- `StaticLayout`: block ID와 bay/row/tier 크기
- `StackSpec`: stack 주소와 capacity
- `TransferSlotSpec`: 고정 buffer 또는 런타임 가상 stack 인계점의 위치와 capacity
- `YardSpec`: 모든 고정 야드 설비

정규 block의 모든 Bay·Row에는 하나의 `StackSpec`이 생성된다. 입력의
`TransferSlotSpec`은 기존 고정 buffer로 유지한다. ANY_BAY 실행 시에는 고정
buffer가 없는 모든 작업 Bay·Row에 `VIRTUAL_STACK` 인계점을 자동 생성한다.
가상 인계점은 별도 시설이 아니라 그 좌표의 일반 stack top을 일시적으로 사용한다.

### `model/job.py`

`Job`은 container ID, 출발·도착 좌표, release time, AGV ready time과
stacking module이 결정한 `final_slot`을 가진다. 스케줄러는 `final_slot`을
변경하지 않는다.

### `model/state.py`

- `StackState`: bottom-to-top 컨테이너 배열
- `ContainerState`: ON_AGV, IN_STACK, ON_CRANE, AT_TRANSFER_SLOT, COMPLETED
- `CraneState`: 위치, 적재 컨테이너, 사용 가능시각
- `TransferSlotState`: 인계공간 점유 컨테이너
- `YardState`: 위 상태를 묶은 한 시점의 불변 snapshot

### `model/instance.py`

`StaticSchedulingInstance`가 `YardSpec`, `YardState`, crane, job, motion,
physical rule을 하나로 묶는다. `validate_instance()`가 다음을 검사한다.

- layout과 정규 stack 집합 일치
- stack capacity
- stack bottom-to-top 순서와 container tier 일치
- container 중복 점유 금지
- stacking 결과와 container target slot 일치
- job endpoint와 inbound final slot 일치
- crane spec과 초기 crane state 일치
- transfer spec과 초기 transfer state 일치
- 활성 handshake bay에 실제 transfer slot 존재

## 입력과 상태 생성

`data/static_fair_micro.json`은 schema version `3.1.0`을 사용한다.

```text
JSON
 → loader.parse_instance()
 → 정규 YardSpec 생성
 → sparse initial stacks를 전체 StackState로 확장
 → ContainerState, CraneState, TransferSlotState 생성
 → StaticSchedulingInstance 생성
 → validate_instance()
```

예제는 6 bay × 2 row × 4 tier라서 총 12개 stack을 만든다. JSON에는
점유된 stack 하나만 적어도 나머지 11개 빈 stack이 자동 생성된다.

## 현재 실행 로직

```text
CLI
 → 공통 입력 로드 및 초기 물리상태 검증
 → 정책 포함관계 검증
 → serial baseline이 CandidateSchedule 생성
 → 공통 schedule validator 검사
 → 검증된 final drop 최대시각을 upper bound로 반환
```

baseline은 아직 해측 크레인이 job 입력순서대로 직접 처리한다. 다만 이번
변경부터 `Job.ready_time`과 초기/목표 tier에 따른 hoist 시간을 사용한다.
예제의 공통 baseline upper bound는 세 정책 모두 17초다. 이 값은 정책
우열이나 최적해가 아니다.

## 이번 단계의 경계

자료구조의 초기 일관성은 검사하지만 operation 실행에 따라 `YardState`를
변경하는 로직은 아직 없다. 따라서 현재 schedule validator는 다음을 아직
판정하지 않는다.

- pickup 시 top container인지
- blocker가 있어 reshuffle이 필요한지
- final drop 시 목표 tier가 실제로 비어 있는지
- operation 이후 stack/container/crane 상태 변화
- transfer slot의 시간별 점유 변화

이 항목들은 다음 단계의 simulator가 담당한다.

## 2차 구현계획: 상태 전이 Simulator

이 계획은 version 0.3.0에서 구현되었다. 상세 결과는
`docs/phase2_state_transition_simulator.md`를 참조한다.

1. `simulator.py`와 `SimulationResult` 추가
2. 초기 `YardState`로부터 실행용 상태 생성
3. `PICKUP` 상태 전이
   - ready time
   - container 실제 위치
   - top-of-stack 및 blocker 검사
   - crane empty 검사
4. `FINAL_DROP` 상태 전이
   - stacking target 불변
   - 아래 tier 연속성
   - stack capacity
5. `HANDOVER_DROP/PICKUP` 상태 전이
   - 정책 bay
   - 실제 transfer slot
   - 시간순서와 capacity
6. crane 위치·적재·available time 갱신
7. simulator가 낸 violation을 validator가 그대로 사용하도록 단일화

2차 완료기준은 full stack drop 거부, blocker pickup 거부, target tier 변경
거부, 올바른 pickup/drop 후 상태 snapshot 변화, transfer capacity 초과 거부다.

## 후속 단계

- 3차: simulator replay를 유일한 물리검증 경로로 확정
- 4차: 두 크레인 active NO_SHARING planner
- 5차: 같은 planner/model에 HANDSHAKE와 ANY_BAY 정책 옵션 연결
- 6차: 작은 문제용 공통 exact model, UB/LB/gap
- 이후: 동적 arrival와 공통 rescheduling 정책
