# 정책별 planner 구조와 구현 현황

세 협력정책은 `src/yard_crane_v3/planners` 아래에서 서로 분리한다. 정책에만
필요한 함수는 해당 정책 폴더의 `scheduler.py`에 둔다. 물리 자료구조, 시간 계산,
일정 형식과 최종 시뮬레이션 검증은 기존 공통 계층을 사용한다.

```text
planners/
├─ common/
│  ├─ contract.py         Planner 계약, 후보 평가 결과와 생성 실패 예외
│  └─ serial_baseline.py  검증용 단일 크레인 기준해
├─ pipeline.py            transfer 접근순서와 고정경로 timing repair
├─ no_sharing/
│  └─ scheduler.py        인계 없는 실제 2대 크레인 scheduler
├─ handshake_area/
│  ├─ scheduler.py        직접운반 또는 지정 H bay 1회 인계
│  └─ pipeline.py         지정 H 파이프라인 후보
└─ any_bay/
   ├─ scheduler.py        모든 고정·가상 transfer point 평가
   └─ pipeline.py         모든 적격 Bay별 파이프라인 후보
```

## 이번에 완성한 NO_SHARING 실행 논리

`build_no_sharing_schedule()`은 작업을 해측 지역, 육측 지역, 교차 지역으로
분류한다. 두 지역 작업은 안전거리를 확보한 서로 다른 구역에서 동시에 처리한다.
교차 지역 작업은 상대 크레인을 바깥 대기 위치로 이동시킨 후 한 크레인이
출발지부터 목적지까지 직접 처리한다. 어떤 경우에도 컨테이너 인계 동작은 만들지
않는다.

출고 컨테이너 위에 blocker가 있으면 해당 정책의 안전 작업구역 안에서 다음
조건을 만족하는 stack을 찾는다.

- 원래 stack이 아닐 것
- stacking 결과로 예약된 최종 stack이 아닐 것
- 용량이 남아 있을 것
- 작업 크레인의 안전구역 안에 있을 것

후보 중 이동시간, 현재 높이, bay와 row 순으로 가장 앞선 위치를 택하고,
`RESHUFFLE` pickup, loaded move, final drop 세 동작을 일정에 넣는다. 생성된 전체
일정은 공통 물리 시뮬레이터를 통과해야만 반환한다.

## 아직 최적화하지 않은 부분

HANDSHAKE_AREA와 ANY_BAY는 serial 후보 외에 두 크레인의 독립 operation을
left-shift하는 파이프라인 후보를 포함한다. 모든 후보는 같은 Validator를 통과한
경우에만 upper bound로 채택된다. 전체 작업 배정과 순서를 동시에 최적화하지
않으므로 최적해를 보장하지 않는다.

## 다음 구현 순서

1. 작은 문제용 공통 탐색기를 추가해 정책별 최적 makespan과 lower bound를 구한다.
2. 큰 문제에서는 같은 시간제한과 seed로 세 정책 휴리스틱을 비교한다.
