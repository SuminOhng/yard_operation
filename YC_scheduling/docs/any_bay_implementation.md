# True ANY_BAY 구현 브리핑

## 구현 목표

`ANY_BAY`는 직접운반과 지정 H 인계를 모두 포함하면서, 고정 buffer가 없는 모든
물리적 작업 Bay·Row의 일반 stack top도 한 번의 임시 인계점으로 사용할 수 있는
정적 scheduler다. 입력 JSON에 가상 slot을 열거하지 않으며 다음 ID를 런타임에
결정론적으로 생성한다.

```text
VIRTUAL::<block>::BAY_<bay>::ROW_<row>
```

입력에 이미 정의된 transfer slot은 호환성을 위해 `FIXED_BUFFER`로 유지된다.
`HANDSHAKE_AREA`는 H bay의 고정 buffer만 사용하고, `ANY_BAY`는 그 고정점들과
자동 생성된 `VIRTUAL_STACK` 점을 모두 후보로 사용한다.

## 임시 인계점의 물리 의미

가상점은 별도 고정 인계시설이 아니다. donor가 선택된 Bay·Row의 일반 stack
top에 컨테이너를 잠시 내려놓고 receiver가 다시 집는 동안만 존재하는 논리적
자원이다.

- capacity는 1이다.
- drop 시 그 stack의 다음 빈 tier를 사용한다.
- pickup 전까지 stack top, tier, 동시 예약과 점유 조건을 만족해야 한다.
- pickup이 끝나면 stack과 가상점 점유가 함께 해제된다.
- donor와 receiver는 서로 다른 크레인이어야 한다.
- 연속 궤적 non-crossing과 최소 안전거리는 공통 Simulator가 검사한다.

따라서 실제 stack이 가득 찼거나 blocker가 있거나 다른 operation과 같은 tier를
동시에 예약하면 후보가 거부된다. 화면에는 생성 가능한 모든 가상점이 아니라
최종 검증 일정이 실제 사용한 점만 보라색 점선 마름모로 표시된다.

## 후보 집합

`build_any_bay_schedule()`은 다음 후보를 공통 Simulator로 모두 검증한다.

1. `NESTED_HANDSHAKE`: HANDSHAKE_AREA의 최선 일정
2. `BEST_SLOT_PER_JOB`: 작업별 휴리스틱 비용이 가장 작은 고정·가상 인계점
3. `FIXED_SLOT`: 한 고정·가상 인계점을 전체 일정의 경계로 사용
4. `PIPELINE_BAY:<bay>`: 한 물리적 bay를 경계로 donor/receiver 작업을 겹침

가상점은 origin–destination 사이로 제한하지 않는다. Validator의 정책 가능영역은
yard 전체이며, 작업 출발지·목적지·두 크레인의 현재위치·stack tier handling 시간을
합친 비용으로 우선 후보를 정한다. makespan, handover 수, operation 수, 후보 label
순으로 최선의 유효 일정을 선택한다.

HANDSHAKE_AREA의 검증 일정을 후보에 그대로 포함하므로 휴리스틱 결과도 다음
관계를 유지한다.

```text
ANY_BAY makespan <= HANDSHAKE_AREA makespan <= NO_SHARING makespan
```

이는 정책 feasible set과 구현 후보가 포함된다는 뜻이지 ANY_BAY 전역 최적성을
인증한다는 뜻은 아니다.

## 수입·수출 방향

- bay가 증가하는 작업: 해측 크레인이 donor, 육측 크레인이 receiver
- bay가 감소하는 작업: 육측 크레인이 donor, 해측 크레인이 receiver

donor는 drop 뒤 안전거리만큼 퇴거하고 receiver가 진입한다. 고정 buffer는 기존
handling 시간을, 가상 stack은 실제 선택 tier의 hoist 시간을 사용한다.

## 실행 예제

```powershell
python3.14 scripts/run_any_bay.py data/any_bay_handover_micro.json
```

이 입력은 H bay 3과 고정 대안 bay 2만 명시하지만, True ANY_BAY는 입력에 없는
`VIRTUAL::B1::BAY_1::ROW_1`도 생성·검증해 선택할 수 있다.

2작업 리플레이용 `data/true_any_bay_replay_demo.json`에서는 검증된 Best UB가
NO_SHARING 13.40초, HANDSHAKE_AREA 13.40초, ANY_BAY 12.60초다. ANY_BAY는
Bay 1·Row 1의 가상 stack 인계점을 한 번 사용한다. 결과는
`results/visualization_007_true_any_bay_final/index.html`에 있다.

## 현재 범위

파이프라인 후보는 입력 작업순서를 유지하며 각 후보 경계를 독립적으로 평가한다.
전체 작업순서, 모든 작업별 인계점 조합과 직접/인계 조합을 전역 최적화하지 않는다.
온라인 신규 도착과 재스케줄링도 이 정적 단계의 범위가 아니다.

`evaluate_any_bay_candidates()`는 nested, serial-point, pipeline 후보와 검증 결과를
감사용으로 반환한다. 상세 timing repair와 화면 리플레이는
`docs/pipeline_handover_and_replay.md`에 설명한다.
