# HANDSHAKE_AREA 구현 브리핑

## 구현 목표

`HANDSHAKE_AREA`는 두 크레인이 직접운반을 선택할 수 있으면서, 필요한 작업은
지정된 H bay에서 한 번 인계할 수 있는 정적 scheduler다. 야드 상태와 물리검사는
다른 정책과 완전히 같은 공통 계층을 사용한다.

## 후보 구성

공개 함수 `build_handshake_area_schedule()`은 세 후보군을 만든다.

1. `DIRECT_FALLBACK`: 현재 `NO_SHARING` 일정의 정책 표지만 바꾼 후보
2. `DESIGNATED_H`: 지역 작업은 직접 처리하고 교차 작업은 H에서 인계하는 후보
3. `PIPELINE_H`: 같은 H 인계를 사용하되 두 크레인의 독립 작업을 겹치는 후보

`PIPELINE_H`는 split strategy와 H row 선택 heuristic 조합을 여러 개 평가한다.

두 후보 모두 공통 시뮬레이터를 통과해야 한다. 유효 후보 중 makespan이 가장
작은 것을 선택하고, makespan이 같으면 인계 횟수와 operation 수가 작은 후보를
선택한다. 그러므로 불필요한 인계를 강요하지 않는다.

## 작업 분류와 실행

- 해측 지역 안에서 끝나는 작업: 해측 크레인이 직접운반
- 육측 지역 안에서 끝나는 작업: 육측 크레인이 직접운반
- 두 보호지역을 연결하는 작업: origin 쪽 크레인이 donor, destination 쪽 크레인이
  receiver가 되어 H에서 한 번 인계

교차 작업의 operation 순서는 다음과 같다.

```text
donor empty move
→ primary pickup
→ loaded move to H
→ HANDOVER_DROP
→ donor safe retreat
→ receiver move to H
→ HANDOVER_PICKUP
→ loaded move to final destination
→ FINAL_DROP
```

donor가 H에서 물러난 뒤 receiver가 H로 진입하므로 두 크레인은 동시에 H를
점유하지 않는다. `DESIGNATED_H`는 각 작업 후 외곽으로 복귀하는 보수적 비교
후보다. 실제 선택 대상인 `PIPELINE_H`는 외곽 복귀를 넣지 않는다. donor는 H에서
안전거리만큼만 퇴거하고 다음 컨테이너를 준비하며, receiver는 이전 컨테이너를
최종 목적지로 운반하는 동안 다음 donor 작업과 겹쳐 실행된다.

## H row 선택

H bay에 활성 transfer slot이 여러 개 있으면 다음 기준으로 하나를 선택한다.

1. `origin → H row → destination` loaded travel 합이 최소
2. origin과 destination row에서의 trolley 편차 합이 최소
3. row 번호와 transfer slot ID 순

파이프라인 후보는 transfer slot의 drop 이후 pickup 선후관계와 slot capacity를
명시적 timing constraint로 유지한다. receiver는 자신의 operation sequence에서
transfer slot에 대기 중인 컨테이너를 순서대로 pickup한다. 실제 용량과 상태 변화는
공통 시뮬레이터가 다시 검사한다.

## 기존 물리모델과 결합한 부분

- 최종 적치 위치 `final_slot` 고정
- stack capacity와 next-tier 검사
- 출고 대상 위 blocker 자동 reshuffle
- release time과 AGV ready time 반영
- 실제 gantry, trolley, hoist, pickup, drop 시간 사용
- continuous crane separation과 non-crossing 검사
- H transfer slot의 enabled, bay, row, capacity 검사
- 작업당 최대 handover 수 검사

## 현재 알고리즘의 성격

이번 구현은 실행 가능한 Upper Bound를 만드는 파이프라인 heuristic이다. 작업
순서는 입력 순서로 고정하지만, seed 일정에서 크레인별 순서와 job 선후관계만
남기고 불필요한 전역 동기화를 제거한다. transfer bay의 donor/receiver 접근은
한 번에 한 대만 허용한다. 반환 makespan은 최적해 보장이 없다.

`evaluate_handshake_area_candidates()`를 사용하면 세 후보의 유효성, makespan,
handover 수와 오류를 따로 확인할 수 있다. 파이프라인 timing repair와 리플레이는
`docs/pipeline_handover_and_replay.md`에 설명한다.

실제 인계 동작은 다음 명령으로 확인한다.

```powershell
python scripts/run_handshake_area.py data/handshake_handover_micro.json
```
