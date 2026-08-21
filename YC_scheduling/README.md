# Static Version 3

`static_version_3`는 독립적인 정적 야드크레인 스케줄링 프로젝트다.
Python 표준 라이브러리만으로 입력 로딩, 공통 일정 생성, 물리 검증과 세 정책
실행 경계를 사용할 수 있다.

```powershell
python3.14 scripts/run_static_baseline.py data/static_fair_micro.json
python3.14 scripts/run_no_sharing.py data/static_fair_micro.json
python3.14 scripts/run_handshake_area.py data/static_fair_micro.json
python3.14 scripts/run_handshake_area.py data/handshake_handover_micro.json
python3.14 scripts/run_any_bay.py data/any_bay_handover_micro.json
python3.14 scripts/run_three_policy_comparison.py data/any_bay_handover_micro.json
python3.14 scripts/render_schedule.py --input data/true_any_bay_replay_demo.json --existing-jobs JOB_OUTBOUND --new-jobs JOB_INBOUND --decision-time 0 --output-dir results/visualization_true_any
python3.14 scripts/run_reference_solver.py --input data/benchmarks/02_handshake_cross_4jobs.json --policy ALL --output results/reference.json
python3.14 scripts/render_schedule.py --input data/static_fair_micro.json --existing-jobs JOB_IN_NEAR --new-jobs JOB_OUT_FAR --decision-time 0 --output-dir results/visualization_micro
python3.14 -m unittest discover -s tests -v
```

공통 직렬 기준해와 별도로 실제 2대 크레인을 사용하는 `NO_SHARING`, 지정 H
bay에서 한 번 인계할 수 있는 `HANDSHAKE_AREA`, 모든 물리적으로 사용 가능한
Bay·Row의 stack top을 임시 인계점으로 평가하는 `ANY_BAY` scheduler가 구현되어
있다. 정책별 코드는
`src/yard_crane_v3/planners`의 각 정책 폴더에 분리한다.

정책 외에 layout, 속도, handling time, release time, crane 안전거리, transfer 용량과
작업당 최대 인계 횟수는 모두 동일한 입력에서 읽는다.

## 현재 물리자료 구조

고정 야드 구조와 시점별 상태는 `src/yard_crane_v3/model` 아래에 분리되어 있다.

```text
model/
├─ geometry.py   Position, StackKey, Slot
├─ equipment.py  CraneSpec, MotionParameters
├─ yard.py       StaticLayout, StackSpec, TransferSlotSpec, YardSpec
├─ job.py        Job과 stacking 결과(final_slot)
├─ state.py      Stack·Container·Crane·TransferSlot·Yard 상태
└─ instance.py   전체 정적 문제와 자료구조 불변조건
```

입력에 나열하지 않은 빈 stack도 loader가 정규 야드 크기에 맞춰 자동 생성한다.
컨테이너 stack 위치는 bottom-to-top 배열의 순번과 `Slot.tier`가 일치해야 하며,
stack capacity와 stacking 결과의 목표 slot도 입력 단계에서 검증한다.

`layout.bays=N`이면 실제 작업 bay는 `1..N`, 해측·육측 외부 대기 위치는
각각 `0`, `N+1`로 자동 정의한다. 외부 위치에 한 크레인이 대기하면 반대
크레인은 non-crossing과 최소 안전거리 범위에서 작업 bay 전체를 사용할 수
있다. 자세한 좌표 규칙은 `docs/yard_coordinate_system.md`에 기록한다.

상세 구현현황과 다음 단계는 `docs/phase1_physical_model.md`에 기록한다.
이벤트 기반 상태 전이는 `src/yard_crane_v3/simulation`에 있으며,
구현 내용은 `docs/phase2_state_transition_simulator.md`에 기록한다.
reshuffle, 연속 충돌검사와 state delta는
`docs/phase3_reshuffle_and_single_validator.md`에 기록한다.
정책별 planner 구조와 구현 범위는 `docs/policy_planner_structure.md`에 기록한다.
HANDSHAKE_AREA의 후보 생성과 안전운행은
`docs/handshake_area_implementation.md`에 기록한다.
ANY_BAY의 런타임 임시 인계점과 정책 포함관계는
`docs/any_bay_implementation.md`에 기록한다.
세 실제 policy planner의 동일 입력 비교와 JSON 산출물은
`docs/three_policy_comparison.md`에 기록한다.
처음 읽는 사람을 위한 전체 입력·실행·산출물 사용 설명서는
`docs/scheduler_user_manual.md`에 기록한다.
Bound Calculator의 기존·신규 작업 요청 계약과 부분문제 생성은
`docs/bound_calculator_phase1_contract.md`에 기록한다.
Strict Append Upper Bound와 residual state 생성은
`docs/bound_calculator_phase2_strict_append.md`에 기록한다.
Full Replan Upper Bound와 best-known UB 선택은
`docs/bound_calculator_phase3_full_replan.md`에 기록한다.
Certified Lower Bound와 UB-LB gap 계산은
`docs/bound_calculator_phase4_lower_bound.md`에 기록한다.
Bound Calculator 명령행 실행과 JSON artifact 형식은
`docs/bound_calculator_cli.md`에 기록한다.
4~6작업 정적 Bound benchmark 5종의 정의는
`data/benchmarks/README.md`와 `data/benchmarks/benchmark_manifest.json`에
기록한다.
5개 시나리오 × 3개 정책 batch 실행과 JSON·CSV·Markdown 출력은
`docs/bound_batch_runner.md`에 기록한다.
작은 문제의 모든 작업순서를 열거하는 공통 Reference Solver와 정확한 인증
범위는 `docs/reference_solver_phase1.md`에 기록한다.
작업별 직접 운반 크레인과 handover slot까지 명시적으로 열거하는 Route Mode
탐색은 `docs/reference_solver_phase2_route_modes.md`에 기록한다.
크레인별 operation sequence를 보존하면서 불필요한 대기를 제거하는 병렬 후보
생성은 `docs/reference_solver_phase3_concurrency.md`에 기록한다.
Branch-and-Bound 입력으로 사용할 구조화된 연속 충돌정보는
`docs/reference_solver_phase4_structured_conflicts.md`에 기록한다.
충돌에서 TimingConstraint를 만들고 해측·육측 지연 BranchNode를 생성하는 과정은
`docs/reference_solver_phase5_timing_repair.md`에 기록한다.
세 정책의 Best UB 일정, 분석적 LB와 gap을 동일 시간축 Gantt Chart로 표시하는
방법은 `docs/schedule_visualization_phase1.md`에 기록한다.
donor/receiver 파이프라인, transfer 접근 제약과 크레인·컨테이너 공간 리플레이는
`docs/pipeline_handover_and_replay.md`에 기록한다.
수출 15개·수입 5개의 고정 대형 입력과 실행 결과는
`docs/large_20job_instance.md`에 기록한다.

20작업 파이프라인 리플레이 실행 예시는 다음과 같다.

```powershell
python3.14 scripts/render_schedule.py `
  --input data/large_15out_5in_seed42.json `
  --existing-jobs JOB_EXP_01 JOB_EXP_02 JOB_EXP_03 JOB_EXP_04 JOB_EXP_05 JOB_EXP_06 JOB_EXP_07 JOB_EXP_08 JOB_EXP_09 JOB_EXP_10 JOB_IMP_01 JOB_IMP_02 `
  --new-jobs JOB_EXP_11 JOB_EXP_12 JOB_EXP_13 JOB_EXP_14 JOB_EXP_15 JOB_IMP_03 JOB_IMP_04 JOB_IMP_05 `
  --decision-time 0 `
  --output-dir results/visualization_large_pipeline
```

Batch 실행 예시:

```powershell
python3.14 scripts/run_bound_batch.py `
  --manifest data/benchmarks/benchmark_manifest.json `
  --output-dir results/bound_batch
```

Bound Calculator 실행 예시:

```powershell
python3.14 scripts/run_bound_calculator.py `
  --input data/static_fair_micro.json `
  --policy NO_SHARING `
  --existing-jobs JOB_IN_NEAR `
  --new-jobs JOB_OUT_FAR `
  --decision-time 0 `
  --output results/micro_no_sharing_bound.json
```

## 고정된 정책 정의

세 정책 모두 같은 두 크레인을 활성화하고, 한 크레인이 컨테이너를 출발지부터
최종 목적지까지 직접 운반하는 선택을 허용한다. 정책별 차이는 인계 위치뿐이다.

| 정책 | 활성 크레인 | 직접 운반 | 허용 인계 위치 |
|---|---:|---:|---|
| `NO_SHARING` | 두 대 | 허용 | 없음 |
| `HANDSHAKE_AREA` | 두 대 | 허용 | 입력에 정의된 지정 H bay 고정 buffer |
| `ANY_BAY` | 두 대 | 허용 | H 고정 buffer + 사용 가능한 모든 Bay·Row의 임시 stack top |

따라서 코드가 보장해야 하는 허용해 관계는 다음과 같다.

```text
NO_SHARING ⊆ HANDSHAKE_AREA ⊆ ANY_BAY
```

“두 대 활성”은 어느 한 크레인을 구조적으로 유휴 상태로 고정하지 않는다는 뜻이다.
실제 작업 배분은 입력과 목적함수에 따라 planner가 결정한다.

`ANY_BAY`의 가상 인계점은 입력 JSON에 고정 시설로 추가하지 않는다. 실행 시
`VIRTUAL::<block>::BAY_<bay>::ROW_<row>` ID로 자동 생성하며, 실제 일정이 선택한
점만 점유되고 리플레이에 표시된다. 임시 drop은 일반 stack의 한 tier를 사용하므로
stack capacity, top-of-stack, 동시 점유와 두 크레인의 안전거리를 공통 Simulator가
그대로 검증한다.
