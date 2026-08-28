# 22개 블록 시나리오 사용 가이드

이 패키지는 22개 야드 블록에 대해 생성한 크레인 작업 시나리오입니다.
각 블록은 `20 bays × 10 rows × 6 tiers`이며, 수출 작업 15개와 수입 작업
5개를 포함합니다.

## 가장 먼저 알아야 할 내용

시뮬레이션에는 항상 아래 두 파일을 한 쌍으로 사용합니다.

```text
instances/block_01.json
+
scenarios/block_01/handshake_area_scenario.json
```

첫 번째 파일은 야드의 초기 상태이고, 두 번째 파일은 크레인이 수행할 작업
순서입니다. 시나리오 파일만 사용하면 초기 컨테이너 위치, 야드 크기, 크레인
초기 위치를 알 수 없습니다.

세 정책은 서로 독립된 실험입니다. 한 번 실행할 때 아래 파일 중 하나만
선택해야 합니다.

- `no_sharing_scenario.json`
- `handshake_area_scenario.json`
- `any_bay_scenario.json`

서로 다른 정책의 action을 섞으면 안 됩니다.

각 정책은 다른 정책이 만든 schedule을 fallback 후보로 가져오지 않고 자체
planner로 독립 실행됩니다. 따라서 더 넓은 인계 위치를 허용하는 정책이라도
heuristic 탐색 결과의 makespan이 항상 더 짧다고 보장되지는 않습니다. 이는
scenario 오류가 아니라 세 방법을 독립적으로 실행한 결과입니다.

## 폴더 구성

```text
blocks_22_stack_h_team_package/
├─ README_FIRST_KO.md
├─ instances/
│  ├─ manifest.json
│  ├─ block_01.json
│  └─ ... block_22.json
├─ scenarios/
│  ├─ batch_summary.json
│  └─ block_01/
│     ├─ comparison_summary.json
│     ├─ no_sharing_scenario.json
│     ├─ handshake_area_scenario.json
│     ├─ any_bay_scenario.json
│     └─ *_schedule.json
└─ replays/
   ├─ index.html
   └─ block_01/index.html
```

### `instances`

시뮬레이션 시작 상태입니다. 다음 정보가 들어 있습니다.

- 야드 크기와 H area 위치
- 초기 컨테이너와 stack 배치
- 크레인 초기 위치
- 크레인 이동 및 handling 시간
- transfer slot 위치와 용량
- 수출 15개, 수입 5개 작업

Bay 10의 H area는 별도 빈 buffer가 아닙니다. `H_B10_R1`부터
`H_B10_R10`까지는 각 물리 stack의 상단을 인계점으로 사용하며 instance에는
다음과 같이 표시됩니다.

```json
{
  "id": "H_B10_R5",
  "position": {"bay": 10, "row": 5},
  "capacity": 1,
  "enabled": true,
  "kind": "STACK_BACKED"
}
```

해당 stack에 기존 컨테이너가 있어도 괜찮습니다. `HANDOVER_DROP`은 현재 높이의
바로 다음 tier에 놓고, `HANDOVER_PICKUP`은 그 컨테이너가 stack 최상단일 때만
가져갑니다. 최대 tier 6을 넘길 수 없으며, 가득 찬 H stack에는 놓을 수 없습니다.

### `scenarios`

정책별 크레인 실행 명령입니다. 팀원 시뮬레이터가 주로 읽어야 하는 파일입니다.

### `replays`

사람이 결과를 눈으로 확인하기 위한 HTML입니다. 시뮬레이터 입력 파일이
아닙니다. `replays/index.html`을 열면 22개 리플레이를 선택할 수 있습니다.

각 replay의 세 정책은 같은 블록의 `*_scenario.json`을 만든 schedule을 그대로
표시합니다. 기존 작업과 신규 작업으로 나누거나 별도 bound 계산으로 다른
schedule을 선택하지 않습니다. 따라서 정책별 action 순서, 크레인, 좌표와
예상시간이 scenario와 replay에서 일치합니다.

## 정책 선택

| 정책 | 파일 | 컨테이너 인계 방식 |
|---|---|---|
| No Sharing | `no_sharing_scenario.json` | 크레인 간 인계 없음 |
| Handshake Area | `handshake_area_scenario.json` | Bay 10 실제 stack 상단에서만 인계 |
| Any Bay | `any_bay_scenario.json` | 허용 가능한 일반 bay에서도 인계 가능 |

처음 연동할 때는 `handshake_area_scenario.json` 사용을 권장합니다. H area와
transfer slot이 명확하여 실행 상태를 확인하기 쉽습니다.

## Scenario JSON 구조

```text
scenario
├─ schema_version
├─ instance_id
├─ policy
├─ time_semantics
├─ execution_model
├─ cranes
├─ actions
├─ dependencies
└─ resource_locks
```

### `cranes`

각 크레인이 실행할 action ID를 순서대로 나열합니다.

```json
{
  "C_SEA": ["op_0000", "op_0001", "op_0002"],
  "C_LAND": ["op_0008", "op_0009", "op_0010"]
}
```

### `actions`

크레인이 실제로 수행할 동작입니다.

| `action_type` | 의미 |
|---|---|
| `MOVE_EMPTY` | 컨테이너 없이 이동 |
| `PICKUP` | 컨테이너 집기 |
| `MOVE_LOADED` | 컨테이너를 든 채 이동 |
| `HANDOVER_DROP` | H/transfer stack의 다음 빈 tier에 컨테이너 놓기 |
| `HANDOVER_PICKUP` | 최상단 인계 컨테이너 가져가기 |
| `FINAL_DROP` | 최종 위치에 컨테이너 놓기 |

각 action에는 크레인, 컨테이너, 출발 위치, 도착 위치가 들어 있습니다.

```json
{
  "action_id": "op_0001",
  "crane_id": "C_SEA",
  "action_type": "PICKUP",
  "purpose": "RESHUFFLE",
  "container_id": "B01_BLOCKER_OUT_03_2",
  "from": {"bay": 9, "row": 6},
  "to": {"bay": 9, "row": 6},
  "estimated_start_time": 28.8,
  "estimated_end_time": 46.4
}
```

`purpose`는 동작의 목적입니다.

- `PRIMARY_JOB`: 수출 또는 수입 본 작업
- `RESHUFFLE`: 목표 컨테이너 위 blocker 재배치
- `HANDOVER`: 두 크레인 사이의 컨테이너 인계

### `dependencies`

action을 시작하기 전에 완료되어야 할 조건입니다.

| dependency | 의미 |
|---|---|
| `CRANE_SEQUENCE` | 같은 크레인의 이전 action 완료 |
| `JOB_SEQUENCE` | 같은 작업의 이전 단계 완료 |
| `TRANSFER_SLOT_HAS_CONTAINER` | H slot에 컨테이너가 놓인 뒤 pickup |
| `HANDOVER_BAY_CLEAR` | 상대 크레인이 H bay에서 나온 뒤 진입 |
| `TRANSFER_SLOT_CAPACITY` | 이전 컨테이너가 빠진 뒤 slot 재사용 |

예를 들어 아래 dependency는 `op_0011` 완료 후 `op_0014`를 실행하라는 뜻입니다.

```json
{
  "before": "op_0011",
  "after": "op_0014",
  "type": "TRANSFER_SLOT_HAS_CONTAINER",
  "resource_id": "H_B10_R5"
}
```

### `resource_locks`

동시에 두 크레인이 점유하면 안 되는 자원입니다.

```json
{
  "action_id": "op_0011",
  "resource_id": "transfer_slot:H_B10_R5",
  "mode": "EXCLUSIVE",
  "reason": "TRANSFER_SLOT_ACCESS"
}
```

주요 자원은 다음과 같습니다.

- `bay:10`: H area 접근 구간
- `transfer_slot:H_B10_R5`: 특정 transfer slot

## 시뮬레이터 실행 순서

1. `instances/block_XX.json`을 읽어 초기 야드 상태를 만듭니다.
2. 실행할 정책의 `*_scenario.json` 하나를 읽습니다.
3. 각 크레인에서 아직 실행하지 않은 첫 action을 찾습니다.
4. 해당 action의 dependency가 모두 완료되었는지 확인합니다.
5. 필요한 resource lock이 비어 있는지 확인합니다.
6. 실제 크레인 위치와 이동경로가 안전한지 확인합니다.
7. 안전하면 action을 실행하고, 아니면 해당 크레인을 대기시킵니다.
8. action 완료 후 완료 상태를 기록하고 lock을 해제합니다.

간단한 형태는 다음과 같습니다.

```python
while unfinished_actions:
    for crane in cranes:
        action = next_action(crane)

        if not dependencies_completed(action):
            continue
        if not resource_locks_available(action):
            continue
        if not physical_path_is_safe(action):
            continue

        acquire_resource_locks(action)
        execute_with_velocity_and_acceleration(action)

        if action_completed(action):
            mark_completed(action)
            release_resource_locks(action)
```

## 시간값 사용 방법

Scenario JSON의 시간은 실행 명령이 아니라 참고값입니다.

```json
"time_semantics": "ESTIMATED_HINTS_ONLY"
```

팀원 시뮬레이터가 속도와 가속도로 실제 위치를 계산한다면
`estimated_start_time`에 맞추기 위해 action을 강제로 시작하면 안 됩니다.
dependency, resource lock, 실제 안전거리 순서로 시작 가능 여부를 판단해야 합니다.

## 연속운동 안전검사

시나리오는 작업 순서와 자원 충돌 방지 조건을 제공합니다. 실제 이동 중 크레인
충돌까지 자동으로 해결하지는 않습니다. 시뮬레이터는 매 simulation tick에서
다음 항목을 확인해야 합니다.

- 두 크레인의 최소 안전거리
- 크레인 non-crossing
- 현재 속도에서 정지할 때 필요한 제동거리
- 목적지까지의 예상 이동구간 중 상대 크레인과의 충돌 여부
- H area와 transfer slot 점유 상태

위험이 예상되면 action 순서를 바꾸지 말고 해당 크레인을 감속하거나 정지시킵니다.

## Handover 실행 예시

```text
C_SEA: 컨테이너 집기
  ↓
C_SEA: H area로 이동
  ↓
C_SEA: transfer slot에 놓기
  ↓
C_SEA: H area 밖으로 후퇴
  ↓ HANDOVER_BAY_CLEAR
C_LAND: H area 진입
  ↓ TRANSFER_SLOT_HAS_CONTAINER
C_LAND: 컨테이너 집기
  ↓
C_LAND: 최종 목적지로 이동
```

receiver 크레인은 컨테이너가 slot에 놓였다는 조건과 donor 크레인이 H area를
비웠다는 조건을 모두 확인해야 합니다.

H area에서는 추가로 다음 조건을 확인해야 합니다.

- drop 직전 stack 높이가 6보다 작은가?
- drop tier가 현재 stack 높이 + 1인가?
- pickup 대상이 현재 stack 최상단인가?
- 기존 컨테이너를 인계 컨테이너로 오인하지 않는가?

## 파일별 용도 정리

| 파일 | 용도 | 시뮬레이터 입력 여부 |
|---|---|---|
| `block_XX.json` | 초기 야드와 작업 정의 | 필수 |
| `*_scenario.json` | 실행 action과 dependency | 필수 |
| `*_schedule.json` | 계산 시간과 operation 감사자료 | 선택 |
| `comparison_summary.json` | 정책별 성능 비교 | 선택 |
| `replays/index.html` | 사람이 보는 리플레이 목록 | 사용하지 않음 |

## 연동 확인 체크리스트

- 인스턴스와 scenario의 `instance_id`가 같은가?
- 세 정책 중 하나만 선택했는가?
- 각 크레인이 `cranes`에 정의된 순서를 지키는가?
- dependency 완료 전에 action을 시작하지 않는가?
- resource lock을 action 완료 후 해제하는가?
- 시간값을 강제 시작시간으로 사용하지 않는가?
- 이동 중 최소 안전거리와 non-crossing을 매 tick 검사하는가?
- H stack의 최대 tier 6과 최상단 pickup 규칙을 지키는가?
- 모든 action 완료 후 20개 job이 완료 상태인가?

위 항목을 모두 만족하면 스케줄러가 만든 작업 순서를 팀원 시뮬레이터의
속도·가속도 기반 물리운동으로 안전하게 연결할 수 있습니다.
