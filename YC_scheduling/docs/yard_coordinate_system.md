# Yard Coordinate System

## 목적

컨테이너 작업 위치와 크레인 외부 대기 위치를 분리한다. 야드의 실제 bay 수만
입력하면 작업 범위와 양쪽 대기 위치가 자동으로 결정된다.

## 좌표 정의

`layout.bays = N`일 때 좌표는 다음과 같다.

```text
해측 외부 대기      실제 컨테이너 작업 bay       육측 외부 대기
       0                  1 ... N                    N+1
```

`StaticLayout`은 다음 값을 제공한다.

```text
first_work_bay       = 1
last_work_bay        = N
seaside_parking_bay  = 0
landside_parking_bay = N + 1
working_bays         = range(1, N + 1)
```

예를 들어 `layout.bays = 10`이면 작업 bay는 1~10이고 외부 대기 위치는
0과 11이다. `layout.bays = 20`이면 작업 bay는 1~20이고 대기 위치는 0과
21이다.

## 크레인 이동 규칙

해측 크레인이 0에 있으면 육측 크레인은 1~N을 사용할 수 있다. 육측
크레인이 N+1에 있으면 해측 크레인은 1~N을 사용할 수 있다. 두 크레인이
동시에 내부에 있을 때에는 모든 시각에 다음 제약을 만족해야 한다.

```text
seaside_position + minimum_crane_separation_bays
    <= landside_position
```

크레인은 서로 통과하거나 순서를 바꿀 수 없다. 외부 대기 위치도 실제 rail
좌표이므로 대기 위치까지의 gantry 이동시간을 makespan에 포함한다.

## 작업·적치·인계 위치

- 일반 stack은 1~N에만 존재한다.
- transfer slot과 handover bay도 1~N에만 존재한다.
- 0과 N+1에는 stack이나 transfer slot을 만들 수 없다.
- edge-to-edge 비교 작업은 실제 서비스 bay인 1과 N 사이에서 수행한다.
- 외부 대기 위치 0과 N+1은 크레인이 작업공간을 양보할 때 사용한다.

이 구분으로 NO_SHARING도 한 크레인이 1에서 N까지 직접 운반할 수 있다.
다른 크레인은 반대편 외부 위치에서 대기한다. HANDSHAKE_AREA와 ANY_BAY는
같은 직접 운반을 후보로 유지하면서 허용된 내부 bay에서 인계하는 후보를
추가한다.

## 안전거리 범위

현재 기본 배치는 최소 안전거리 1 bay에 맞춘 외부 대기점 0과 N+1을
사용한다. 최소 안전거리를 1보다 크게 설정하면 한 크레인이 대기해도 다른
크레인이 반대쪽 끝 작업 bay까지 접근할 수 없을 수 있다. 더 큰 안전거리를
사용하는 실험에서는 향후 외부 rail buffer 길이를 별도 입력으로 확장해야
한다.
