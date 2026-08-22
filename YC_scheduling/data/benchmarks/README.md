# Static Bound Benchmark Set

이 폴더는 동일 공통 물리모델에서 YC 협력정책과 Bound Calculator를 검증하기
위한 수작업 benchmark 5종을 포함한다. 모든 입력은 독립적인 native instance
JSON이며 `benchmark_manifest.json`이 기존·신규 작업 구분과 decision time을
정의한다.

## 01 Balanced Local

- 작업 4개, inbound 2개와 outbound 2개
- 해측 크레인 local 작업 2개와 육측 크레인 local 작업 2개
- 인계가 없어도 충분한 기준 사례
- 세 정책 모두 complete여야 하고 handover는 0이어야 한다

## 02 Edge-to-Edge Cross

- 작업 4개, 실제 서비스 bay 1과 8 사이의 양방향 운송
- 해측 외부 대기점은 0, 육측 외부 대기점은 9
- 한 크레인이 외부 대기점에 있으면 다른 크레인이 작업 bay 전체를 사용 가능
- NO_SHARING은 한 크레인이 끝까지 직접 운반하며 complete
- HANDSHAKE_AREA와 ANY_BAY는 직접 운반과 인계 운반을 모두 후보로 비교

외부 대기 위치와 컨테이너 서비스 위치를 분리하여 세 정책을 같은 feasible
조건에서 비교하는 사례다.

## 03 Any-Bay Advantage

- 작업 4개
- 횡단작업 1개와 짧은 해측 local 작업 3개
- 기존 횡단작업만 비교하면 지정 H bay 4보다 enabled bay 1 인계가 빠름
- ANY_BAY가 실제로 `ALT_B1_R1`을 선택하는지 검사

전체 append makespan에는 이후 local 작업과 크레인 최종위치도 영향을 주므로,
이 사례의 핵심 비교값은 existing baseline makespan과 선택 transfer slot이다.

## 04 Append Blocker

- 기존 inbound 작업 2개가 신규 outbound 컨테이너 위 tier 2에 적치됨
- 신규 작업을 append하면 blocker reshuffle이 반드시 발생
- residual state가 기존 적치 컨테이너를 실제 stack 점유로 보존하는지 검사

## 05 Mixed Reshuffle

- 작업 6개
- inbound/outbound, local/cross 작업 혼합
- 일정에 직접 포함되지 않은 blocker 컨테이너 1개 포함
- 세 정책의 reshuffle, strict append, full replan, UB/LB 통합 실행 검사

## Manifest 사용 규칙

각 항목에서 다음 조건을 만족해야 한다.

```text
existing_job_ids ∩ new_job_ids = empty
existing_job_ids ∪ new_job_ids = 모든 instance job
```

`expected_complete_policies`는 UB와 LB가 모두 인증되어야 하는 정책이고,
`expected_infeasible_policies`는 유효한 UB가 없어야 하는 정책이다.

이 폴더의 JSON은 benchmark 자체이므로 planner 결과에 맞춰 조용히 변경하지
않는다. 알고리즘 변경 후 기대 결과가 달라지면 물리적 이유와 변경 근거를
먼저 검토해야 한다.
