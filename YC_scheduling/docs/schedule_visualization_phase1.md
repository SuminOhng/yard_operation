# Static Schedule Visualization Phase 1 and 2

## 목적

세 정책의 Bound Calculator 결과에서 실제 Best UB를 만든 검증 일정을 선택하고,
동일 시간축 Gantt Chart와 공간 리플레이로 비교한다. 직접 운반, H handover,
ANY_BAY handover의 makespan도 한 화면에서 표시한다. HTML 화면과 감사용 JSON은
같은 immutable view model에서 생성한다.

## 데이터 흐름

```text
StaticSchedulingInstance
  + existing/new job partition
  + decision time
        |
        v
three BoundCalculation objects
        |
        v
Best validated UB source schedule selection
  + route candidate evaluation
  + Simulator OperationTrace/StateDelta
        |
        v
StaticScheduleVisualization
        |
        +-- visualization_data.json
        +-- index.html
```

Strict Append와 Full Replan 값 중 `best_known_upper_bound`와 일치하는 일정만
표시한다. 선택 일정의 Validator makespan과 Best UB가 다르면 adapter가 결과
생성을 거부한다. 따라서 화면의 작업 막대와 UB 숫자가 서로 다른 일정을
나타내는 상황을 허용하지 않는다.

## 화면 구성

- NO_SHARING, HANDSHAKE_AREA, ANY_BAY 정책 탭
- Best UB, 분석적 LB, relative gap
- 선택된 UB 방법: STRICT_APPEND 또는 FULL_REPLAN
- handover와 reshuffle 횟수
- 두 크레인 동시작업 시간과 평균 transfer 대기시간
- 두 크레인의 operation Gantt Chart
- decision time, LB, UB 수직선
- 작업 선택 시 job, container, 위치와 시작·종료시각
- 공통 물리 Validator 통과 여부
- 직접 운반, H handover, ANY_BAY handover 후보 makespan 카드
- 시간 슬라이더 기반 crane bay·row 이동 리플레이
- 컨테이너의 stack, AGV, crane, transfer slot 상태 변화
- 재생, 일시정지, 초기화와 0.5배~32배 속도

세 정책은 `shared_time_horizon`을 사용한다. 정책을 변경해도 x축 크기가 바뀌지
않으므로 operation 길이와 makespan을 직접 비교할 수 있다.

## 실행

```powershell
python scripts/render_schedule.py `
  --input data/benchmarks/02_handshake_cross_4jobs.json `
  --existing-jobs JOB_CROSS_OUT_1 JOB_GATE_SEA_TO_LAND_1 `
  --new-jobs JOB_CROSS_OUT_2 JOB_GATE_SEA_TO_LAND_2 `
  --decision-time 8 `
  --title "Handshake Cross 4 Jobs" `
  --output-dir results/visualization_001
```

출력 폴더는 존재하지 않거나 비어 있어야 한다.

```text
results/visualization_001/
├─ index.html
└─ visualization_data.json
```

`index.html`은 외부 JavaScript 라이브러리나 API 호출 없이 실행되는 독립 파일이다.
브라우저에서 파일을 직접 열 수 있다.

## 화면용 자료구조

```text
StaticScheduleVisualization
├─ 공통 instance/layout/job partition
├─ shared_time_horizon
├─ 초기 crane/container 상태와 transfer slot
├─ RouteCandidateVisualization × 3
└─ PolicyScheduleVisualization × 3
   ├─ UB/LB/gap와 인증 상태
   ├─ UB source method
   └─ VisualizationOperation[]
      ├─ operation index와 crane
      ├─ operation type와 purpose
      ├─ start/end time
      ├─ start/end bay·row
      ├─ job/container/transfer slot
      └─ Simulator가 인증한 operation 완료 후 상태
```

## 리플레이 자료 원칙

크레인 위치는 같은 `VisualizationOperation`의 시작·종료 위치를 시간에 따라
보간한다. 컨테이너 상태는 공통 Simulator의 operation trace와 state delta만
사용한다. HTML에서 pickup, transfer, stacking 물리규칙을 다시 판단하지 않는다.
따라서 Gantt, 리플레이와 감사 JSON의 일정 출처가 같다. 컨테이너의 작업 방향과
실제 사용된 인계점 종류(`FIXED_BUFFER` 또는 `VIRTUAL_STACK`)도 감사 JSON에
기록한다. JSON schema version은 `2.2.0`이다. 리플레이는 후보 전체가 아니라
검증 일정에서 실제 사용된 인계점만 표시한다.

## 주요 파일

- `src/yard_crane_v3/visualization/model.py`
- `src/yard_crane_v3/visualization/adapter.py`
- `src/yard_crane_v3/visualization/serialization.py`
- `src/yard_crane_v3/visualization/renderer.py`
- `scripts/render_schedule.py`
- `tests/test_schedule_visualization.py`
