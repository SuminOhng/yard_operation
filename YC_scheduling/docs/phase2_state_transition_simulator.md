# 공통 물리모델 2차 구현 보고

## 구현 목표

1차에서 정의한 불변 `YardState`를 schedule operation에 따라 변경하고,
stack·container·crane·transfer slot의 물리적 불가능을 실행 중 거부한다.

## 폴더 구조

```text
src/yard_crane_v3/simulation/
├─ result.py          violation, operation trace, simulation result
├─ working_state.py   replay 동안만 사용하는 mutable 상태
├─ engine.py          START/END 이벤트 처리와 상태 전이
└─ __init__.py
```

외부에는 불변 `YardState`만 노출한다. `WorkingState`의 list/dict는 simulator
내부에서만 사용하고, 종료 후 다시 불변 `YardState` snapshot을 구성한다. 따라서 같은
초기 상태를 세 정책이 사용해도 한 실행이 다른 정책의 입력을 변경하지 않는다.

## 이벤트 실행 방식

모든 operation을 START와 END 이벤트로 나누고 다음 순서로 처리한다.

```text
시간 오름차순
동일 시각: END → START
```

같은 시각에 handover drop이 끝나고 상대 crane pickup이 시작되면 drop의 상태
변경이 먼저 반영된다. crane, container, final slot과 transfer capacity는
START에서 예약해 동시 operation의 중복 사용을 막는다.

## 구현된 상태 전이

### `PICKUP`

- release/AGV ready time, crane empty, container 실제 위치 검사
- IN_STACK이면 top container인지 검사
- blocker가 있으면 `BLOCKED_BY_CONTAINER`
- 종료 시 stack에서 제거하고 container를 `ON_CRANE`으로 변경

### 이동과 대기

- crane active/available 상태와 시작 위치 연속성
- 적재상태와 MOVE_EMPTY/MOVE_LOADED 일치
- 공통 이동시간
- 종료 시 crane 위치와 available time 변경

### `FINAL_DROP`

- crane 적재 container와 job destination
- stacking 결과의 final slot 불변
- stack capacity와 목표 tier가 다음 빈 tier인지 검사
- 종료 시 stack에 추가하고 container를 `COMPLETED`로 변경

### `HANDOVER_DROP/PICKUP`

- policy의 allowed handover bay
- 명시적인 `transfer_slot_id`
- 실제 활성 transfer slot과 위치
- drop/pickup 시간순서와 transfer capacity
- 종료 시 transfer와 crane 사이의 container holder 변경

## 검증 결과와 Upper Bound

`validator.validate_schedule()`은 일정 구조·충돌 검사와 simulator 결과를 합친다.
simulation violation이 있거나 모든 job이 완료되지 않으면 makespan을 반환하지
않는다. 모든 검사를 통과한 simulator makespan만 feasible upper bound가 된다.

`SimulationResult`는 initial/final YardState, completed job IDs, operation별 trace,
전체 violation과 검증된 makespan을 제공한다.

## 구현 테스트

- 정상 serial 일정의 stack 제거/추가와 crane 위치 변화
- blocker 아래 container pickup 거부
- 다음 빈 tier가 아닌 target drop 거부
- 정상 H handover 후 transfer slot 해제와 final stack 점유
- 가득 찬 transfer slot에 handover drop 거부
- 가득 찬 target stack에 final drop 거부

## 현재 경계

- blocker를 탐지하고 pickup을 거부하지만 reshuffle operation은 아직 없다.
- 연속궤적 충돌과 non-crossing은 기존 공통 validator가 담당한다.
- simulator와 validator에 일부 시간·operation 형상 검사가 중복돼 있다.
- planner는 아직 serial baseline이다.

## 다음 구현계획

아래 3차 계획은 version 0.4.0에서 구현되었다. 상세 결과는
`docs/phase3_reshuffle_and_single_validator.md`를 참조한다.

### 3차: reshuffle과 단일 물리검증 경로

1. schedule에 `RESHUFFLE` purpose 추가
2. blocker를 유효한 다른 stack으로 이동하는 상태 전이
3. reshuffle 목적 stack capacity와 stacking rule 검사
4. simulator에 continuous crane separation 검사를 이동
5. validator를 simulator 결과를 정리하는 얇은 facade로 축소
6. operation trace에 핵심 state delta 기록

### 4차: 두 크레인 active NO_SHARING planner

1. 각 job의 양쪽 crane 직접운반 후보 계산
2. non-crossing과 state transition을 통과하는 후보만 허용
3. completion time 기준 greedy/list scheduling baseline
4. 한 container의 crane 간 인계 금지

그 후 같은 planner 인터페이스에 HANDSHAKE_AREA와 ANY_BAY의 handover 후보만
추가하고, 작은 문제용 공통 exact model을 구현한다.
