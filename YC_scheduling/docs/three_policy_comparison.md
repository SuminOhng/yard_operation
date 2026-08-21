# 실제 세 정책 비교기 브리핑

## 목적

하나의 `StaticSchedulingInstance`를 실제 NO_SHARING, HANDSHAKE_AREA, ANY_BAY
planner에 차례로 전달하고 같은 물리 시뮬레이터로 검증한다. 공통 직렬 기준해를
세 번 실행하는 기능과 달리 각 정책의 실제 scheduler 결과를 비교한다.

## 실행 흐름

```text
한 번 로드한 immutable instance
  ├─ build_no_sharing_schedule
  ├─ build_handshake_area_schedule
  └─ build_any_bay_schedule
          ↓
각 정책을 공통 validator로 재검증
          ↓
PolicyMetrics 세 개 생성
          ↓
포함관계와 전체 유효성 검사
```

정책별 실행은 독립적으로 감싼다. 한 planner가 오류를 내면 해당 정책은
`PLANNER_ERROR`로 기록하고, 나머지 정책 실행과 결과는 보존한다.

## 수집 지표

- 물리검증 통과 여부
- 실행 가능한 makespan Upper Bound
- planner 실행시간
- handover 횟수
- reshuffle 횟수
- operation 수
- 실제 사용 크레인
- 실제 사용 transfer slot
- 완료 작업 ID
- 위반 코드 또는 planner 오류

reshuffle 횟수는 `RESHUFFLE` 목적의 pickup 수로 계산한다. 따라서 pickup, 이동,
drop 세 operation을 컨테이너 한 번의 reshuffle로 센다.

## 포함관계 판정

세 일정이 모두 유효하고 Upper Bound가 존재할 때 다음을 검사한다.

```text
ANY_BAY UB <= HANDSHAKE_AREA UB <= NO_SHARING UB
```

세 결과 중 하나라도 실패하면 `nested_upper_bounds_hold`는 `null`이다. 모두
성공했지만 관계가 깨지면 `false`가 되어 구현 또는 후보 생성 문제를 바로 알 수
있다.

## 실행과 산출물

화면에 요약만 출력:

```powershell
python scripts/run_three_policy_comparison.py data/any_bay_handover_micro.json
```

요약과 전체 일정 저장:

```powershell
python scripts/run_three_policy_comparison.py `
  data/any_bay_handover_micro.json `
  --output-dir results/any_bay_micro
```

저장 파일은 다음 네 개다.

```text
comparison_summary.json
no_sharing_schedule.json
handshake_area_schedule.json
any_bay_schedule.json
```

정책 파일에는 요약 지표와 모든 operation의 시간, 위치, job, container,
transfer slot과 목적이 들어간다. 파일은 같은 디렉터리의 임시파일을 완성한 뒤
최종 이름으로 교체한다.

## 예제 결과

`any_bay_handover_micro.json`을 실행하면 다음 검증된 Upper Bound가 나온다.

| 정책 | UB | 인계 | 사용 위치 |
|---|---:|---:|---|
| NO_SHARING | 12.7 | 0 | 없음 |
| HANDSHAKE_AREA | 11.9 | 1 | H_ROW_1 |
| ANY_BAY | 10.9 | 1 | VIRTUAL::B1::BAY_1::ROW_1 |

`all_valid`와 `nested_upper_bounds_hold`는 모두 `true`다.

## 해석 한계

이 비교기는 동일 입력과 물리검증을 보장하지만 현재 planner가 최적화된 것은
아니다. 따라서 비교값은 세 정책의 검증된 heuristic Upper Bound이며 정책별 최적
makespan이나 Lower Bound가 아니다. 매우 짧은 단일 실행시간도 성능평가 자료로
사용하지 않고, 반복 실험과 충분한 규모의 입력을 추가한 뒤 비교해야 한다.
