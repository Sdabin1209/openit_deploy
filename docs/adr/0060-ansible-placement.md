# 0060. 여러 서버 배치: Ansible 인벤토리 + 플레이북, 서버에는 SSH·python3·Docker 만

- 상태: 채택 (U99 배치 줄, 2026-11-03)
- 날짜: 2026-11-03
- 번호: 0058, 0059 는 같은 날 다른 브랜치(TLS 등)가 쓸 수 있어 비워 두었다. 합칠 때 번호가 겹치면 이 파일의 번호를 옮긴다.

## 맥락

지금까지 배치는 서버 한 대의 Compose 하나(`scripts/up.sh`)였다. 영역은 배치와 무관해야 한다(어느 서버·지역에 놓여도 코드·이미지가 같다). 서비스를 여러 서버에 나눠 놓을 때, 서버 이름·주소·지역·서비스 묶음은 **배치 정의 한 곳**에만 있어야 하고, 서버나 지역이 바뀌어도 스크립트를 고치지 않아야 한다. 서버에는 새 OS 패키지를 요구하지 않는다(SSH, python3, Docker 만).

## 결정

- 표준 도구는 Ansible(`ansible-core`). 에이전트 없이 SSH 로 서버에 접속한다. 지휘 기계의 프로젝트 가상환경에 pip 로 설치하고 `requirements-deploy-tools.txt` 에 전이 의존까지 판을 고정한다(ansible-core 2.18.20, 2.18 은 장기 지원 줄기).
- 배치 정의 = Ansible YAML 인벤토리(`ansible/inventory.example.yml`). 서버마다 `ansible_host`(주소), `placement_region`, `placement_services`(compose 서비스 이름 목록). 공통 변수 `placement_scheme`(기본 https), `placement_ports`.
- `scripts/placement.py` 가 인벤토리를 스키마(`schemas/Placement.schema.json`)와 compose 의 서비스 목록으로 점검한다: 서비스 이름 일치, 한 서비스는 한 서버에만, 기반 요소(postgres, step-ca, keycloak, gateway) 배치, 배치해야 할 서비스의 누락, 다른 서버에서 불리는 서비스의 게시 포트 명시 여부. 점검은 서버에 닿기 전에 플레이북의 첫 플레이로 돈다.
- `ansible/site.yml` 은 서버마다 (a) 그 서버 몫의 설정·비밀 파일을 배포(비밀은 640, 그룹은 SECRETS_GID 규칙, ADR 0054; 다른 서버의 비밀은 보내지 않는다. DB 접속 비밀(db-*-dsn)은 postgres 가 다른 서버면 호스트를 그 서버 주소와 게시 포트로 바꿔 서버마다 새로 만들고, https 배치면 sslmode=verify-full 과 sslrootcert 를 붙인다) (b) 상대 서비스 주소를 계산한 compose override 를 놓고 (c) 서버를 넘나드는 단계(postgres, step-ca, keycloak, 저장소·서버 서비스, survey·model-serving, gateway)로 그 서버 몫만 `docker compose up -d --wait <서비스>` 한다. 다음 단계 전에 앞 단계에서 게시된 서비스가 `/readyz`(postgres 는 TCP)에 응답하는지 지휘 기계에서 `ansible.builtin.uri`(until/retries)로 기다린다. 지휘 기계의 첫 단계에서 서버별 환경을 `check_config_contracts` 로 검증하고 실패면 멈춘다. 같은 서버의 상대는 서비스 이름 그대로, 다른 서버의 상대는 `<scheme>://<그 서버 주소>:<게시 포트>` 로 바꾼다. 다른 서버에서 불리는 서비스는 그 서버에서 호스트 포트를 연다(서버 사이 호출은 게시 포트로만). 게시 포트는 인벤토리 `placement_ports` 에 명시하며 빠지면 점검이 거부한다(순서로 계산하지 않는다). 바인드 주소는 서버별 `placement_bind_address`(없으면 address 가 IP 일 때 그 값). 내부 전용 네트워크에만 붙은 서비스(postgres, model-registry 등)는 게시할 때 override 가 일반 네트워크 `placement-publish` 를 더한다. 게이트웨이만 사람·기기 입구라는 노출 규칙은 그대로이고, 서버 사이 게시 포트는 서비스 토큰 인증 + TLS 이며 인벤토리의 서버 사이 망에만 바인드한다.
- Docker 전용 Ansible 모듈(`community.docker`)은 쓰지 않고 `command`/`shell` 로 compose 를 부른다. compose 호출은 `scripts/lib.sh` 의 `dc` 를 그대로 쓴다(서버 한 대 배치와 같은 경로).
- 서버 한 대 배치는 override 가 비어(`services: {}`) 기존 `up.sh` 와 같은 compose 호출이 된다.

## 왜

- Ansible 은 에이전트 없이 SSH 와 서버의 python3 만 요구하고(Ansible 문서의 요구 사항), 모듈이 멱등을 기본으로 한다. 요구 조건 "서버에 SSH·python3·Docker 만"과 "다시 돌려도 바뀐 것만"에 그대로 맞는다.
- `community.docker` 모듈은 서버의 Python 에 docker SDK 를 요구한다. 서버에 파이썬 라이브러리를 요구하지 않으려고 쓰지 않는다. 대신 compose 가 이미 멱등(`up -d`는 바뀐 것만 다시 만든다)이다.
- 배치 계산(주소, 게시 포트, depends_on 정리)을 Jinja 가 아니라 파이썬 한 파일에 둔 이유: YAML 구조를 다루고 스키마 검증이 필요하며, 단독으로 시험할 수 있다(`scripts/test-split-placement.sh`).
- 영역은 배치를 모른다: 영역 코드·이미지·compose 의 서비스 정의는 그대로이고, 서버별 override 와 배치 정의만 다르다. 이 도구가 아는 것은 서비스 이름, compose 의 환경·비밀 이름뿐이다(구조 규칙 4).

## 검토한 대안과 버리는 이유

- 직접 만든 도구(셸 + ssh + scp): 멱등·변경 감지·병렬·인벤토리 형식을 다시 만들어야 하고 유지 부담이 크다. 표준이 있다.
- `docker context`/`DOCKER_HOST=ssh://` 로 지휘 기계에서 원격 데몬을 직접 부르기: 비밀 파일 마운트가 호스트 경로 기준이라 원격 호스트에 파일이 먼저 있어야 한다(파일 배포 문제가 남는다). 서버별 파일 배포와 순서 제어를 못 푼다. 배포 뒤 기동 단계에서는 쓸 수 있으나 단독으로 충분하지 않다.
- 쿠버네티스/Swarm: 서버 한두 대 규모에 비해 운영 부담이 크고, 서버에 요구하는 것이 SSH·Docker 이상이다. 이 프로젝트의 서버 수에 대해 필요성을 측정하지 않았다. 규모가 커지면 다시 본다.
- Terraform/Puppet/Chef: 서버 프로비저닝 또는 에이전트가 필요하다. 요구는 이미 있는 서버에 배치하는 것이다.

## 결과

- 얻는 것: 서버·지역 변경은 인벤토리만 고친다. 한 서버 배치와 다서버 배치가 같은 compose 와 같은 경로를 쓴다. 잘못된 배치는 서버에 닿기 전에 거부된다.
- 감수하는 것: (1) 서버 사이 호출의 TLS(https)와 postgres 의 verify-full 연결은 TLS 작업이 합쳐진 뒤에야 확인할 수 있다. 지금 시험은 http 로 돌고 `SPLIT_SCHEME=https` 변수만 열어 두었다(미확인). sslrootcert 가 가리키는 postgres CA 파일의 마운트는 TLS 작업의 몫이다. (2) 분리 시험은 대역 서비스(또는 `SPLIT_IMAGE` 로 준 실제 이미지의 파이썬에 대역 스크립트를 얹은 것)로 배치만 본다. 실제 영역 서비스의 분리 기동은 합친 뒤 주 담당이 실제 이미지·https 로 돈다. (3) 서버 사이 주소의 포트는 컨테이너 안 8080(postgres 는 5432)으로 가정한다. (4) 지휘 기계의 계약 점검은 compose 가 해석되려면 잠금 파일에 모든 이미지 digest 가 있어야 한다.
- 측정하지 않은 값: 게시 포트에는 기본값이 없다(인벤토리 명시). 기동 단계의 /readyz 대기 한도(30회 x 2초)는 측정하지 않은 시작값이다. 단계 순서는 `scripts/placement.py` 의 STAGES 한 곳이다.

## 되돌리는 조건

서버가 수십 대로 늘거나 자동 확장이 필요해지면 오케스트레이터를 새 ADR 로 검토한다. 인벤토리 형식(`Placement` 스키마)은 그때도 배치 정의의 입력으로 남을 수 있다.
