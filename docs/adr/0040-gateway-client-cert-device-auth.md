# 0040. 키오스크 기기 인증은 게이트웨이(Caddy)의 클라이언트 인증서 검증, 기기 ID는 인증서 주체 CN

- 상태: 채택 (계약 2.3.0, 헤드 D113·ADR 0012의 deploy 쪽 실행)
- 날짜: 2026-10-29

## 맥락

기기 인증은 기기별 무작위 토큰(`Authorization: Bearer`)을 우리가 발급·보관·회전·폐기하고, 목록을 Caddy(`gateway-devices.caddy`)와 survey-service 두 곳에 복제했다(표준 점검 R07, 직접 만든 기기 자격). 계약 2.3.0(PUBLIC_API F절)은 기기 인증을 게이트웨이의 클라이언트 인증서 검증(mTLS)으로 바꾸고, 서비스에는 검증된 기기 ID를 헤더 `X-Openit-Device`로 넘긴다.

## 결정

- 게이트웨이 사이트에 `tls { issuer internal; import device_client_auth }`를 두고, 조각 `(device_client_auth)`는 설정 파일(`config/device-tls.caddy`, 켠 예시는 `device-tls.mtls.caddy.example`)이 정의한다. 켜면 `client_auth { mode verify_if_given; trusted_ca_cert_file /etc/caddy/device-ca.pem }`다: 신뢰 CA는 하나이고 파일 설정이다(비밀 아님, `DEVICE_CA_FILE`).
- 키오스크 경로(`/v1/sessions*`)에서 검증된 인증서의 주체 CN을 `X-Openit-Device`로 붙여 survey-service에 넘긴다. 클라이언트가 보낸 `X-Openit-Device`는 survey로 가는 모든 reverse_proxy에서 지운다(인증서 경로는 CN으로 덮어쓴다). CN이 `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`에 맞지 않으면 기기 인증이 안 된 것으로 본다(401 + `WWW-Authenticate: Bearer`).
- 2.x 호환: 인증서가 없으면 기기 토큰 경로(`@device_ok`)가 그대로 동작하고 survey의 기기 토큰 표(`SURVEY_KIOSK_DEVICE_TOKENS_FILE`)는 선택이다(survey는 헤더가 있으면 헤더를 쓴다). 3.0.0에서 토큰 경로를 없앤다.
- 인증서 발급·갱신·폐기는 조직 PKI/MDM 몫이다. 이 프로젝트는 시험·데모용 일회용 CA와 기기 인증서만 만든다(`scripts/device-pki.sh`, 운영 사용 금지 표시, 키는 `state/device-pki/` 권한 600, 리포에 넣지 않는다).

## 왜

- 표준: X.509 클라이언트 인증서 + TLS 상호 인증(RFC 8446 4.3.2 CertificateRequest, RFC 5280). Caddy `client_auth`는 이 표준 기능이다. 고정 단말(키오스크)의 기기 자격으로 토큰보다 표준에 맞고, 폐기는 CA(CRL/짧은 유효기간)가 맡는다(우리 목록 복제가 사라진다).
- CN을 기기 ID로 쓰는 이유: 계약이 정한 값이다(헤더 형식). Caddy에는 CN만 내는 플레이스홀더가 없어 주체 문자열(`{http.request.tls.client.subject}`, RFC 2253)을 내부 헤더 `X-Openit-Dn`에 항상 덮어쓰고(`dn=` 접두어로 값이 비어 지워지는 일이 없다) `header_regexp`의 이름 있는 캡처로 CN을 꺼낸다. 인증서 신뢰는 핸드셰이크의 `client_auth`가 이미 검증했다.
- `verify_if_given`인 이유: 같은 사이트가 직원 콘솔(계정 인증, 인증서 없음)도 서빙한다. 인증서를 낸 클라이언트는 신뢰 CA가 발급한 것이어야 하고(아니면 TLS 거부), 키오스크 경로는 CN이 있어야 통과한다.

## 검토한 대안과 버리는 이유

- 기기 토큰 유지: 직접 만든 발급·회전·복제 구조가 남는다(R07).
- 키오스크 경로에만 별도 포트·사이트(`require_and_verify`): 경로 하나를 위해 포트를 늘리고 TLS 설정을 중복한다. `verify_if_given` + 경로 매처가 단순하다. 단점은 모든 경로의 핸드셰이크가 선택적 인증서를 요청한다는 것이다(브라우저가 인증서 선택 창을 띄울 수 있다: 직원 PC에 클라이언트 인증서가 설치돼 있을 때). 이 영향은 측정하지 않았다.
- SAN(DNS/URI)에 기기 ID: 계약이 CN을 정했다.
- `map` 지시어로 정규식 캡처: 캡처 플레이스홀더 문법을 확신하지 못해 문서화가 확실한 `header_regexp` 캡처(`{re.<이름>.N}`)를 쓴다.

## 값의 출처

일회용 CA 유효 30일, 기기 인증서 7일(RSA 2048): 시험·데모용 시작값이고 표준·측정 근거 없음(운영 값은 조직 PKI 정책). 헤더 형식은 계약 PUBLIC_API F절.

## 결과와 한계

- 얻는 것: 기기 자격 발급·복제 코드가 운영 경로에서 사라진다(토큰 경로는 3.0.0까지 호환용으로만 남는다).
- 감수: 서비스는 헤더를 믿는다(게이트웨이 뒤 내부망, ADR 0005). 게이트웨이를 우회해 survey에 직접 닿는 경로는 네트워크 분리(compose `serving`)가 막는다.
- **검증 상태**: 이 변경을 쓴 시점에 Docker가 꺼져 Caddy를 띄우는 시험(`scripts/test-device-mtls.sh` 동적 부분: Caddyfile 검증, 인증서 통과/거부, CN 전달, 위조 헤더 덮어쓰기)을 실행하지 못했다. 정적 시험 9건(일회용 CA 스크립트, 설정 조각, Caddyfile 구조)만 통과했다. `tls { ... import ... }`, `request_header` 플레이스홀더, `header_regexp` 캡처 문법은 **Caddy로 검증되지 않았다**: Docker가 돌 때 `bash scripts/test-device-mtls.sh`를 먼저 돌려야 한다.

## 되돌리는 조건

조직이 클라이언트 인증서를 발급·배포할 수 없다고 판단하면(MDM 없음) 기기 토큰 경로를 3.0.0 이후에도 유지하는 새 ADR을 쓴다.
