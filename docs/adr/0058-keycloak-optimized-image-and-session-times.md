# 0058. Keycloak optimized image(읽기 전용 루트)와 사람 세션 시간

## 상태
채택(wo-450 D10). 0057 의 "Keycloak 은 읽기 전용 루트 예외"와 "쿠키 12시간·5분 시작값"을 대체한다(0057 은 지우지 않는다).

## 맥락
기본 Keycloak 이미지는 시작할 때마다 Quarkus 가 /opt/keycloak/lib/quarkus 에 다시 빌드한 결과를 써서 읽기 전용 루트를 쓸 수 없었고, check-containers 에 예외 줄이 있었다. 쿠키 12h/5m 은 근거 없는 시작값이었다.

## 결정
1. `images/keycloak/Dockerfile`: 기반 이미지(locks/images.lock 의 KEYCLOAK_IMAGE, digest 고정)에서 `kc.sh build --db=postgres --health-enabled=true --http-relative-path=/auth` 를 미리 실행하고, 실행은 `start --optimized`. compose 는 `read_only: true` 이고 쓰는 곳은 tmpfs(/tmp, /opt/keycloak/data/tmp, /opt/keycloak/data/import)뿐이다. check-containers 의 예외를 지웠다.
2. kcadm 설정 파일은 읽기 전용 홈에 쓸 수 없어 `--config /tmp/kcadm.config` 로 tmpfs 에 둔다.
3. oauth2-proxy 쿠키: 절대 만료 8시간, 갱신 5분.

## 왜
- 1: Keycloak 공식 문서 "Configuring Keycloak > Running in a container > Building your optimized Keycloak image"가 권하는 방식이다. 빌드 옵션(db, health, http-relative-path)은 build 때와 실행 때 같아야 한다. `--cache` 는 런타임 옵션이라 build 에 넣으면 거부된다(시험에서 확인).
- 3 만료: OWASP Session Management Cheat Sheet 는 절대 시간제한을 업무 성격에 맞게(사무 앱은 업무일 4~8시간 예시) 두라고 한다. oauth2-proxy 기본 cookie-expire 는 168h 로 직원 화면에는 길다. 8시간은 하루 근무 길이다.
- 3 갱신: 역할 변경·계정 정지가 반영되는 지연의 상한이다. Keycloak 기본 액세스 토큰 수명(5분)과 같게 했다. 측정하지 않았다.
- 유휴 시간제한은 oauth2-proxy 에 없고 Keycloak SSO 세션 유휴 기본(30분)을 따른다. 바꾸지 않았다.

## 검토한 대안
- 예외 유지: 강화 규칙(읽기 전용 루트)을 한 서비스만 풀게 되어 버렸다.
- 쿠키 168h(기본): 퇴사·역할 회수 뒤에도 오래 남아 버렸다.
- 쿠키 4h: 하루 근무 중 재로그인을 강요한다. 측정·요구가 없어 8h.

## 결과
얻는 것: 모든 컨테이너가 읽기 전용 루트(예외 0). 감수: 이미지를 로컬에서 빌드하는 단계가 하나 더 생긴다(키클록 버전을 올릴 때 다시 빌드).

## 되돌리는 조건
사용자가 유휴 제한·재로그인 빈도 요구를 주면 값을 바꾼다. Keycloak 이 런타임 쓰기를 요구하는 기능을 쓰게 되면 tmpfs 를 늘린다.
