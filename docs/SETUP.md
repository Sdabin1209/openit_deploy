# 설치 가이드 (이 문서 하나로 따라 한다)

원칙: 처음부터 누구나 어떤 환경에서든 따라 할 수 있어야 한다. 의존은 **가상환경(.venv)과 컨테이너**로 만들고, 그것으로 못 만드는 것(git, python3, Docker 자체)은 아래에 어떻게 구성하는지 적었다. 경로는 어디에도 고정되어 있지 않다(루트 폴더 이름과 위치는 자유). 막히면 먼저 `bash scripts/doctor.sh`를 돌려 무엇이 없는지 본다.

## 0. 필요한 것 한눈에

| 필요 | 이유 | 만드는 법 |
| --- | --- | --- |
| git | 워크스페이스 리포 clone, 이미지 빌드가 태그 시점 소스를 꺼낸다 | A절(리눅스), WSL은 배포판에 설치 |
| python3 (3.10+)와 venv 모듈 | E2E·스크립트가 `.venv` 가상환경을 만든다 | A절 |
| Docker (데몬 + compose + buildx 플러그인) | 모든 서비스·이미지 | A절(리눅스) 또는 B절(WSL2) |
| 형제 리포 11~13개 | 이미지는 각 영역 리포의 소스로 빌드한다 | C절 |
| 인터넷(빌드할 때만) | 베이스 이미지, pip, npm | 이미 만든 이미지로 `--reuse-build`만 할 때는 불필요 |
| curl | 점검·스모크(선택) | 패키지 관리자 |

## A. 일반 리눅스 서버 (Ubuntu/Debian 예시)

1. 기본 도구: `sudo apt-get update && sudo apt-get install -y git python3 python3-venv curl`
2. Docker Engine: **공식 문서의 설치 절차**(https://docs.docker.com/engine/install/)를 따른다. 설치할 패키지: `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`.
3. 데몬 켜기: `sudo systemctl enable --now docker`
4. 권한: 현재 사용자를 docker 그룹에 넣고 **다시 로그인**한다: `sudo usermod -aG docker $USER`. (그렇지 않으면 `permission denied while trying to connect to the Docker daemon socket`)
5. 확인: `docker run --rm hello-world`, `docker compose version`, `docker buildx version`.

## B. WSL2 + Docker Desktop (윈도)

**전제: WSL 배포판 안에서 표준 `docker` 명령이 데몬에 닿는 상태**다. 스크립트는 `docker` CLI 하나와 설정된 데몬(`DOCKER_HOST`/context)만 쓴다. `docker.exe`로 갈아타거나 경로를 바꾸거나 설정을 우회하는 코드는 없다. 환경이 맞지 않으면 `bash scripts/doctor.sh`가 FAIL과 고치는 법을 보여 주고, 아래 절차로 환경을 맞춘다.

1. 윈도에 WSL2와 배포판(Ubuntu 등)을 설치하고, Docker Desktop(WSL2 백엔드)을 설치한다.
2. Docker Desktop > Settings > Resources > **WSL integration**에서 쓰는 배포판을 **켠다**. 그러면 배포판 안에서 `docker`가 동작하고 `/var/run/docker.sock`이 생긴다.
3. **순서**: 윈도를 켠 뒤 Docker Desktop을 먼저 시작하고 엔진이 "Running"이 된 다음 WSL 터미널을 연다. 연동 설정을 바꿨거나 이상하면 윈도에서 `wsl --shutdown` 한 뒤 다시 연다.
4. 배포판 안에서 A절 1번(git, python3, python3-venv, curl)을 한다. Docker Engine은 **설치하지 않는다**(Docker Desktop이 준다).
5. 확인: 배포판 안에서 `docker info`, `docker compose version`, `docker buildx version`이 된다. `bash scripts/doctor.sh`가 모두 OK.

**자격증명 도우미 설정 맞추기 (interop이 꺼진 배포판에서 필수).** `~/.docker/config.json`에 `"credsStore": "desktop.exe"`가 있으면 이미지 pull/build가 `error getting credentials … docker-credential-desktop.exe: exec format error`로 실패한다. interop이 꺼진 배포판(`/etc/wsl.conf`의 `[interop] enabled=false`)은 윈도 프로그램을 실행하지 못하기 때문이다. 이것은 환경 설정 문제라서 스크립트가 숨기지 않는다. doctor가 FAIL로 알려 주면 **사용자가 직접** 둘 중 하나를 한다.
- (권장) `~/.docker/config.json`에서 `"credsStore"` 항목을 지운다. 이 프로젝트의 이미지는 익명 pull로 받으므로 영향이 없다(저장된 레지스트리 로그인만 쓸 수 없게 된다). 백업해 두고 편집한다. doctor는 이 파일을 읽기만 하고 고치지 않으며 내용도 출력하지 않는다.
- 또는 interop을 켠다: `/etc/wsl.conf`에 `[interop]` / `enabled=true`를 쓰고 윈도에서 `wsl --shutdown` 후 다시 연다.

참고: Docker Desktop의 이미지 저장 디스크는 윈도 드라이브에 있다. WSL에서 `df`는 그 여유를 알려 주지 않는다(최소 20GB 여유 권장).

## C. 워크스페이스 구성 (형제 리포 clone)

유일한 전제는 **형제 폴더 배치**다: deploy의 상위 폴더에 리포들이 나란히 있고 폴더 이름이 `head/workspace.yaml`과 같다. 루트 폴더 이름은 자유다.

1. GitHub **읽기 접근**을 만든다(저장소는 비공개). 둘 중 하나를 고른다.
   - **읽기 전용 SSH 키**: 이 머신 전용 키(`ssh-keygen -t ed25519`)를 만들어 공개키를 GitHub에 읽기 전용으로 등록한다. 리포가 여러 개라 리포마다 deploy key를 만들기보다 읽기 권한만 가진 전용 계정/기계 사용자 하나에 등록하는 쪽이 간단하다. 개인 키는 `~/.ssh`에 두고 권한 600.
   - **읽기 전용 토큰**: fine-grained personal access token(Repository permissions: Contents = Read-only, 대상은 이 프로젝트 리포들)을 만들고 HTTPS로 clone한다: `git config --global url."https://github.com/".insteadOf "git@github.com:"`, `git config --global credential.helper store` 뒤 첫 clone 때 토큰을 입력(파일 `~/.git-credentials`, 권한 600).
   - **주의**: 키·토큰 값은 저장소, 채팅, 로그, 이슈에 **절대 넣지 않는다**. 이 프로젝트의 스크립트도 비밀 값을 출력하지 않는다.
2. head를 clone하고 나머지를 받는다:
   ```
   mkdir -p <루트> && cd <루트>
   git clone git@github.com:Sdabin1209/openit_head.git head
   bash head/setup.sh        # workspace.yaml 의 나머지 리포를 clone (있는 것은 건드리지 않음)
   ```
3. 확인: `ls <루트>`에 `deploy`, `boundary-contracts`, `survey-service` … 가 보이고, `bash deploy/scripts/doctor.sh`가 형제 리포와 태그를 확인한다.

## D. 첫 실행 순서

```
cd <루트>/deploy
bash scripts/doctor.sh        # 사전 점검. FAIL 이 있으면 해결 방법(한 줄)을 따른다
bash scripts/e2e.sh           # 처음이므로 --reuse-build 없이: 이미지 빌드 + 임시 레지스트리 + 전체 합격 시나리오 (인도 전 필수)
```
`e2e.sh`와 `up.sh`는 시작에서 doctor를 자동으로 돌리고 FAIL이면 멈춘다(건너뛰기 `DEPLOY_SKIP_DOCTOR=1`). `.venv`와 필요한 의존은 스크립트가 만든다.

- `--fast`: 단계 1~8과 compose 기동 검사만(약 2분). 개발 중 확인용이며 **전체 합격이 아니다**.
- `--reuse-build`: 이미 만든 로컬 이미지(`deploy-build/*`)를 쓰고 빌드를 건너뛴다. **소스(영역 리포)를 바꿨다면 쓰지 않는다**: 옛 이미지로 시험하게 된다. 빌드하지 않아 빠르고 인터넷도 필요 없다.
- `--keep`: 끝나도 시험 자원을 남긴다(디버깅). 평소에는 끝나면 컨테이너·네트워크·볼륨·임시 레지스트리·임시 폴더를 모두 지운다.

**결과 읽는 법.** 끝의 요약에 `PASS n / FAIL m`과 단계별 상태가 나온다. 종료 코드 0은 "실행한 검사가 모두 통과"다.
- `REAL`: 실제 서비스가 실제 인터페이스로 처리한 것.
- `TEST-SUB`: 시험 대역으로 대신한 것(예: 승인자를 스크립트가 시험용 토큰으로, 모델을 가짜 백엔드·시험용 어댑터로). 이름에 test가 들어간다.
- `BLOCKED`: 지금 구현이나 환경으로는 확인할 수 없는 것(예: 실제 브라우저 렌더링, 웹 푸시 수신). 실패가 아니지만 "전체 합격"도 아니다.
- 구간별 소요 시간 표가 같이 나온다.

주의: 이름이 비슷한 두 스크립트를 구분한다. `publish-images.sh`(복수)는 로컬에서 `build-images.sh`로 만든 이미지 전체를 레지스트리에 올리고(E2E가 쓴다), `publish-image.sh`(단수)는 영역 CI가 이미지 하나를 올릴 때 쓴다([ci.md](ci.md)).

### 사람이 화면을 직접 눌러 보기 (데모)

```
bash scripts/demo.sh up                         # 별도 프로젝트 deploy-demo 로 시험 구성을 띄우고 시험용 릴리스를 만들어 활성화, 접속 안내 출력
bash scripts/demo.sh up --stop-before-approval  # 승인 대기까지만 만든다: /admin/ 에서 직접 승인한 뒤
bash scripts/demo.sh activate                   #   승인된 릴리스를 활성화
bash scripts/demo.sh status | down | reset
```
상시 구성(`up.sh deploy`)은 활성 릴리스가 없어 survey-service가 `/readyz` 503(`no_active_release`)이고 키오스크가 직원 호출 화면을 띄운다. 그것이 정상이며, 화면을 눌러 보려면 데모를 쓴다. 데모의 데이터는 **시험용 대체**(가짜 모델, 시험용 승인자)다. 호스트 포트는 Docker가 배정하고 안내에 출력된다. 암호는 출력하지 않고 `state/demo/secrets/tokens/`의 파일에 있다. `down`은 데모 프로젝트(`deploy-demo`로 시작하는 자원)와 `state/demo`만 지운다.

실행 방법 전체(상시 구성, 데모, 화면별 사용, 원격 접속, 내리기, 흔한 문제)는 **[RUN.md](RUN.md)**.

운영 구성으로 띄우는 것(`up.sh`)과 롤백·백업·복구는 [runbook.md](runbook.md), 이미지 게시는 [ci.md](ci.md)를 본다.

## E. 증상별 표

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `docker: command not found` / `docker 실행 파일을 찾을 수 없다` | Docker 미설치 또는 WSL 연동 꺼짐 | A절(리눅스) 또는 B절(WSL: 연동 켜기). 다른 실행 파일을 쓰려면 `DOCKER=<경로>` |
| `Cannot connect to the Docker daemon` | 데몬이 꺼져 있다 | 리눅스: `sudo systemctl start docker`. WSL: Docker Desktop을 먼저 시작하고 연동을 켠 뒤 WSL을 다시 연다(`wsl --shutdown`) |
| `permission denied while trying to connect to the Docker daemon socket` | 사용자가 docker 그룹이 아니다 | `sudo usermod -aG docker $USER` 후 다시 로그인 |
| `error getting credentials … docker-credential-desktop.exe: exec format error` | interop이 꺼진 WSL에서 윈도 자격증명 도우미를 실행하려 함 | B절 "자격증명 도우미 설정 맞추기": `~/.docker/config.json`의 `credsStore` 항목을 직접 지우거나 interop을 켠다 (doctor가 이 증상을 미리 FAIL로 알려 준다) |
| `doctor`: `형제 리포가 없다` | 폴더 이름이 workspace.yaml과 다르거나 clone 안 함 | C절. 폴더 이름을 `head/workspace.yaml`의 path와 같게 |
| `doctor`: `태그가 없다: boundary-contracts v1.3.3` 등 | 리포가 태그 없이 clone됐거나 오래됨 | `git -C ../boundary-contracts fetch --tags`; 그래도 없으면 원격에 태그가 없는 것이니 head에 알린다 |
| `port is already allocated` / 포트 충돌 | 시험은 고정 포트를 쓰지 않는다(Docker 배정, 레지스트리는 빈 포트 선택). 운영 구성의 gateway(기본 8080)·레지스트리(기본 5000)가 다른 프로세스와 겹친 것 | `.env`의 `GATEWAY_PORT`, `REGISTRY_HOST_PORT`를 바꾼다 |
| `python3 -m venv` 실패(`ensurepip is not available`) | python3-venv 패키지 없음 | `sudo apt-get install -y python3-venv` |
| 빌드 중 pip/npm/pull 실패 | 인터넷 또는 프록시 | 인터넷 확인(프록시는 `HTTP(S)_PROXY`). 오프라인이면 이미 만든 이미지로 `--reuse-build`만 가능 |
