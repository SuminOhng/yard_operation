# Bound Calculator CLI and JSON Artifact

## 목적

Python 코드를 직접 수정하지 않고 입력 파일, 정책, 기존·신규 작업 구분과
decision time을 명령행에서 지정하여 완전한 UB/LB 계산 결과를 저장한다.

## 실행 예시

프로젝트 루트에서 다음처럼 실행한다.

```powershell
python scripts/run_bound_calculator.py `
  --input data/static_fair_micro.json `
  --policy NO_SHARING `
  --existing-jobs JOB_IN_NEAR `
  --new-jobs JOB_OUT_FAR `
  --decision-time 0 `
  --output results/micro_no_sharing_bound.json
```

인증된 기존 작업 Lower Bound가 있을 때만 다음 인자를 추가한다.

```powershell
--certified-existing-lower-bound 4.5
```

인증 근거가 없는 기존 heuristic makespan을 이 인자에 입력하면 안 된다.

## 인자

- `--input`: 정적 야드 instance JSON
- `--policy`: `NO_SHARING`, `HANDSHAKE_AREA`, `ANY_BAY` 중 하나
- `--existing-jobs`: 한 개 이상의 기존 작업 ID
- `--new-jobs`: 한 개 이상의 신규 작업 ID
- `--decision-time`: 신규 작업이 알려진 시각, 기본값 0
- `--certified-existing-lower-bound`: 선택적인 외부 인증 LB
- `--output`: 생성할 단일 JSON artifact 경로

모든 instance 작업은 기존 또는 신규 집합 중 정확히 하나에 포함되어야 한다.

## 콘솔 출력과 종료코드

콘솔에는 결과 전체가 아니라 빠르게 확인할 수 있는 다음 요약만 출력한다.

- Strict Append UB
- Full Replan UB
- Best-known UB
- Combined LB
- Absolute/relative gap
- 결과 파일 경로

종료코드의 의미는 다음과 같다.

- `0`: UB와 LB가 모두 유효한 COMPLETE 결과
- `1`: 계산 artifact는 만들었지만 UB 또는 LB 인증이 불완전함
- `2`: 입력, 인자 또는 요청 계약 오류로 계산을 시작하지 못함

## JSON artifact 구조

최상위 구조는 다음과 같다.

```text
schema_version
status
source_input
request
result
strict_append
full_replan
lower_bound
```

`result`에는 최종 UB, LB와 gap이 들어 있다. `strict_append`와
`full_replan`에는 각 operation, 일정 metrics, validation 결과와 final state가
들어 있다. `lower_bound`에는 작업별 availability, mandatory workload와
earliest completion이 들어 있다.

현재 artifact schema version은 `1.0.0`이다.

## 저장 안전성

JSON은 같은 디렉터리의 임시 파일에 먼저 완전히 기록한 뒤 최종 경로로
교체한다. 중간에 프로세스가 중단되어 반쪽짜리 최종 JSON이 남는 위험을
줄인다. JSON 표준에 없는 `NaN`과 `Infinity`는 저장하지 않는다.

## 구현 파일

- `scripts/run_bound_calculator.py`
- `src/yard_crane_v3/bounds/serialization.py`
- `tests/test_bound_serialization_cli.py`

