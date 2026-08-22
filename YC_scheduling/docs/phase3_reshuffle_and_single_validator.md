# 공통 물리모델 3차 구현 보고

## 구현 목표

- blocker를 실제 reshuffle operation으로 이동
- crane 연속궤적 안전거리 검사를 simulator로 통합
- validator와 simulator의 중복 물리판정 제거
- operation별 상태 변경 증거 기록

## Operation 자료구조 확장

`ScheduledOperation`에 다음 필드를 추가했다.

```text
purpose
container_id
target_slot
```

`OperationPurpose`는 다음 세 값을 가진다.

```text
PRIMARY_JOB
HANDOVER
RESHUFFLE
```

Primary job은 `job_id`로 scheduled container를 찾는다. Reshuffle은 job에
포함되지 않은 blocker도 이동할 수 있도록 명시적인 `container_id`를 사용한다.
Reshuffle drop은 정확한 block/bay/row/tier를 가진 `target_slot`을 사용한다.

## Reshuffle 실행

다음 operation 조합이 같은 물리 엔진을 통과한다.

```text
RESHUFFLE PICKUP
 → RESHUFFLE MOVE_LOADED
 → RESHUFFLE FINAL_DROP
 → 원래 job PICKUP
```

Reshuffle pickup은 blocker가 stack top인지 확인하고, drop은 목적 stack capacity와
다음 빈 tier를 검사한다. 정상 종료 후 blocker 상태는 `IN_STACK`이며 새
`current_slot`을 가진다. Reshuffle drop은 job 완료나 makespan 완료작업으로
계산하지 않는다.

검증 예제에서는 bay 6 tier 2의 blocker를 bay 5 tier 1로 옮긴 뒤, bay 6
tier 1의 outbound container를 꺼내 최종 목적지까지 운반한다. 검증된 makespan은
20초다.

## 단일 물리검증 경로

기존 `validator.py`의 별도 시간·충돌·lifecycle 검사를 제거했다.

```text
validate_schedule()
 → replay_schedule() 한 번 실행
 → SimulationResult를 ValidationResult로 정리
```

따라서 실행 가능 여부, makespan, handover count와 violation의 원본은 모두
`simulation/engine.py`다.

## 연속 Crane Separation

두 crane의 모든 operation 시작·종료시각을 공통 breakpoint로 만들고, 각 구간의
선형 bay 궤적을 평가한다. landside bay와 seaside bay의 차이가 공통 최소
안전거리보다 작으면 `CRANE_SEPARATION`을 기록한다. 선형 구간의 최소 차이는
구간 끝점에서 발생하므로 모든 breakpoint 검사로 crossing과 safety violation을
검출한다.

## State Delta

각 accepted operation trace에는 다음 변경증거가 포함된다.

- crane 위치 전/후
- crane 적재 container 전/후
- container status 전/후
- container slot 전/후
- 변경된 stack의 전체 bottom-to-top 배열 전/후
- 변경된 transfer slot 배열 전/후

이를 통해 결과표, replay와 향후 schedule revision이 같은 상태변화를 사용할 수 있다.

## 테스트

- reshuffle 후 blocker 새 stack 점유
- blocker 제거 후 원래 outbound job 완료
- reshuffle 목적 tier 오류 거부
- stack/container state delta 검증
- 두 crane crossing을 simulator 내부에서 거부
- validator 결과와 SimulationResult의 직접 일치

전체 1~3차 테스트 20개가 통과한다.

## 현재 경계

- reshuffle operation은 실행·검증할 수 있지만 목적 stack을 자동 선택하지 않는다.
- 현재 serial baseline planner는 blocker가 있으면 reshuffle을 자동 생성하지 않는다.
- 두 crane 모두 정책상 active지만 baseline은 아직 seaside crane만 사용한다.
- partial candidate를 평가하는 planner 전용 prefix replay가 없다.

## 다음 구현계획: 두 Crane Active NO_SHARING Planner

1. `planners/` 패키지와 공통 planner 결과계약 정의
2. 전체 완료를 요구하지 않는 candidate prefix replay 또는 증분 상태 평가
3. 각 job에 대해 seaside/landside 직접운반 후보 생성
4. 컨테이너 위 blocker의 reshuffle 후보와 빈 목적 stack 선택
5. simulator를 통과하는 후보만 채택
6. 예상 completion time이 가장 작은 crane/job 후보를 선택
7. 한 container를 pickup한 crane이 final drop까지 담당하도록 강제
8. handover operation 생성 금지
9. 두 crane이 실제로 동시에 작업하는 fixture와 회귀테스트

NO_SHARING planner가 완성된 뒤 동일 candidate generator에 allowed handover bay만
추가해 HANDSHAKE_AREA와 ANY_BAY를 구현한다.
