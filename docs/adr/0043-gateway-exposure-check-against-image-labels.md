# 0043. 게이트웨이 노출은 영역 이미지의 노출 선언과 대조한다 (Caddyfile을 생성하지 않는다)

- 상태: 채택
- 날짜: 2026-10-30

## 맥락

`config/Caddyfile`은 영역 API의 경로·메서드·역할·상류 토큰 이름·시간 제한을 직접 적는다(구조 규칙 1 위반, OPEN_GAPS U47). 계약 v2.6.0은 영역이 이미지 라벨 `io.openit.exposure`(계약 `Exposure`)로 자기 노출 표를 선언하게 했고, 이미지 8곳이 이미 낸다(model-serving은 model-runtime의 build-image.sh가 main에 없어 아직 없다). 포트와 실행 사용자는 이미지 OCI 설정(`Config.ExposedPorts`, `Config.User`)에서 읽는다.

## 결정

Caddyfile을 라벨에서 **생성하지 않고**, 라벨과 **대조**해 어긋나면 실패하는 점검으로 바꾼다(`scripts/check-exposure.sh` → `scripts/check_exposure.py`, e2e.sh 자체 점검). 대조 항목: 서비스별로 경로, 메서드, 인증 종류, 역할, 상류 토큰 이름, 사용자 헤더, 연결·응답헤더·읽기 시간 제한, streaming. 거부(`denied`) 경로는 Caddyfile이 그 서비스 상류로 보내지 않아야 한다. 라벨에 없는 노출을 Caddyfile이 내도 어긋남이다. 상류 포트는 이미지 ExposedPorts에 있어야 하고 `Config.User`는 root가 아니어야 한다.

판정 규칙: Caddy의 `handle`은 소스 순서로 처음 맞는 하나만 실행하므로, 라벨의 (경로, 메서드)마다 Caddyfile에서 **처음 맞는 핸들러**를 찾아 비교한다. Caddyfile에 method 매처가 없으면 모든 메서드를 덮는데, 라벨이 메서드를 비워 둔 경로("비우면 모든 메서드")와만 같다고 본다.

알려진 어긋남은 `config/exposure-known-diffs.json`에 이유와 함께 적는다. 이 목록의 줄이 더는 어긋나지 않으면 "낡은 예외"로 실패한다(목록이 썩지 않게).

## 왜

- 생성하려면 Exposure가 Caddyfile의 나머지를 표현해야 한다: CSRF 방어, 클라이언트 인증서(mTLS) 기기 인증과 `X-Openit-Device` 주입, 계정 인증 조각과 역할 매처의 생성 파일, SSE 버퍼링, 상태 코드 변환(`/readyz`), 보안 헤더, 에러 핸들러. 현재 Exposure(v2.7.0)에는 이것을 담는 칸이 없다. 이 내용을 계약에 올리는 일은 헤드 몫이고, 그 전에 생성기를 만들면 생성기가 영역 선언과 deploy 지식을 섞어 두 번째 정본이 된다.
- 대조는 지금 가진 선언만으로 구조 규칙 1이 막으려는 사고(영역이 경로를 바꿨는데 게이트웨이가 모름, 거부한 경로가 열림, 역할이 다름)를 잡는다. 생성으로 가는 길도 막지 않는다: 대조가 있으면 나중에 생성 결과가 같은지 같은 점검으로 본다.
- 점검기는 `caddy adapt`로 JSON을 얻지 않고 작은 구문 분석기로 Caddyfile을 읽는다. `{file./run/secrets/…}`가 변환 때 파일을 읽고 계정·기기 조각(`secrets/`에서 생성)이 있어야 하기 때문이다. 대신 구문 분석기가 Caddyfile의 일부만 안다(블록, 스니펫과 `import 이름 인자`, `@이름` 매처, handle/handle_path, reverse_proxy, respond). 모르는 지시어는 무시하므로 **의미가 바뀌는 새 문법을 쓰면 점검이 놓칠 수 있다**. 그 한계는 변형 시험(`test_check_exposure.py`)이 흔한 어긋남 열 가지를 잡는 것으로만 확인했다.
- 역할 이름은 `gateway-lib.sh`가 매처를 만드는 규칙(`@role_<release- 뗀 이름>`)을 그대로 따른다.

## 검토한 대안

- Caddyfile 생성: 위 이유로 지금은 버린다.
- `caddy adapt` + JSON 분석: 구문 분석기를 안 쓰는 대신 위 이유(파일 치환, 생성 조각)로 버린다.
- E2E 요청으로만 확인(실제 호출): 거부 경로 열림은 잡지만 역할·상류 토큰·시간 제한은 잡지 못한다. E2E는 그대로 두고 이 점검을 더한다.

## 결과

얻는 것: 라벨과 Caddyfile이 어긋나면 E2E 자체 점검에서 실패한다. 실제 라벨 8개에 돌려 2건이 알려진 어긋남으로 나왔다(admin-console `/admin/*`의 역할 범위, survey-service `/healthz`; 이유는 목록 파일). 감수하는 것: 구문 분석기가 Caddyfile 문법 일부만 안다. model-serving은 라벨이 없어 대조하지 못한다(게이트웨이가 프록시하지 않아 "참고"로만 알린다). 측정한 것은 없다.

## 되돌리는 조건

Exposure가 위 게이트웨이 기능을 표현하게 되면(계약 변경) Caddyfile 생성으로 옮기고 이 ADR을 대체한다.
