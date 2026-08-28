# Large 20-Job Static Instance

## 목적

작은 4~6작업 benchmark보다 큰 입력에서 세 정책 planner, 공통 Validator, Bound
Calculator와 Gantt 시각화가 끝까지 실행되는지 확인한다. 배치는 재현 가능하도록
JSON에 고정했으며 stochastic benchmark를 의미하지 않는다.

## 야드

```text
work bays: 1..20
rows: 4
tiers: 4
seaside parking: 0
landside parking: 21
handshake bay: 10
configured fixed transfer bays: 6, 10, 14
ANY virtual transfer points: every other work Bay·Row
minimum crane separation: 1 bay
```

## 작업

- 수출 컨테이너 15개: 서로 다른 stack의 tier 1에서 시작하며 해측 bay 0으로 이동
- 수입 컨테이너 5개: 해측 bay 0의 AGV에서 시작하며 지정된 빈 stack tier 1에 적치
- 초기 blocker 없음
- 모든 release time과 AGV ready time은 0

수출 초기 bay는 `2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20`이다.
수입 목표 bay는 `4, 8, 12, 16, 19`이며 기존 수출 stack과 다른 row를 사용한다.

Bound 시각화에서는 다음 기술적 분할을 사용한다.

```text
existing: JOB_EXP_01..10, JOB_IMP_01..02
new:      JOB_EXP_11..15, JOB_IMP_03..05
decision time: 0
```

## 실행 결과

공통 Validator를 통과한 현재 리플레이 산출물 기준 결과는 다음과 같다.

| 정책 | validated makespan | handover | transfer bay |
|---|---:|---:|---|
| NO_SHARING | 396.75초 | 0 | 없음 |
| HANDSHAKE_AREA | 291.15초 | 9 | 10 |
| ANY_BAY | 284.35초 | 16 | 2, 3, 4, 5, 6, 7, 8, 9 |

파이프라인 후보는 donor의 다음 컨테이너 준비와 receiver의 이전 컨테이너 운반을
겹치고, 매 작업 후 외곽 복귀를 제거한다. HANDSHAKE_AREA는 입력 순서 외에도
교차 작업 우선과 local/cross 교차 배치 후보를 함께 평가하므로, 육측 크레인이
초반부터 원거리 수출 작업을 H bay 10으로 가져온다. True ANY_BAY는 모든 적격
Bay·Row의 임시 stack 인계 후보를 검증하며, 수정된 해측 수출 방향에서는 H bay
10보다 앞쪽의 가상 인계점을 선택해 HANDSHAKE보다 빠른 일정을 만든다.

위 existing/new 분할을 Bound Calculator에 적용한 화면 값은 다음과 같다.

| 정책 | Best validated UB | analytical LB | relative gap |
|---|---:|---:|---:|
| NO_SHARING | 396.75초 | 112.00초 | 71.77% |
| HANDSHAKE_AREA | 291.15초 | 112.00초 | 61.53% |
| ANY_BAY | 284.35초 | 112.00초 | 60.61% |

ANY_BAY 값이 HANDSHAKE_AREA보다 작은 것은 고정 H bay 대신 해측 쪽 여러
가상 stack 인계점을 쓸 수 있기 때문이다. 전역 최적해 비교는 아니다.

## 산출물

- 입력: `data/large_15out_5in_seed42.json`
- HTML: `results/large_20job_handshake_replay_v2/index.html`
- 감사 JSON: `results/large_20job_handshake_replay_v2/visualization_data.json`

HTML에는 후보 makespan 카드, 정책별 Gantt Chart와 크레인·컨테이너 공간 리플레이가
포함된다.
