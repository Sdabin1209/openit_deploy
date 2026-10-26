# 실행 안내 (서버에 띄워 화면을 눌러 보려는 사람용)

표기: **확인함** = 이 저장소의 스크립트·E2E로 실제 확인한 것. **문서 기준** = 영역의 설계 문서에서 읽은 설명이며 사람이 실제 화면을 눌러 확인한 것이 아니다. 시간은 측정한 것만 쓰고 나머지는 "측정 안 함"이라 쓴다.

## 1. 한눈에

| | 상시 구성 | 데모 | E2E |
| --- | --- | --- | --- |
| 목적 | 운영 형태 그대로 띄운다 | 사람이 화면을 눌러 본다 | 합격 시나리오 자동 검증 |
| 명령 | `up.sh deploy` (3절) | `demo.sh up` (4절) | `e2e.sh` / `e2e.sh --fast` |
| 프로젝트 | `deploy` | `deploy-demo` | 임시 이름, 끝나면 지움 |
| 활성 릴리스 | 없음 (503 `no_active_release`가 정상) | 있음 (시험용으로 만들어 활성화) | 단계 안에서 만들고 지움 |
| 가짜 모델 | 모델 백엔드는 지금 `fake`뿐 | 가짜 모델 + 시험용 승인자 + 위험 문구 스위치 | 가짜 모델 + 시험용 대역 |
| 데이터 지속 | 볼륨에 남는다 | `demo.sh down`이 `state/demo`와 함께 지운다 | 끝나면 모두 지운다(`--keep`이면 남김) |

## 2. 전제

[SETUP.md](SETUP.md)를 따라 설치하고 `bash scripts/doctor.sh`가 FAIL 없이 끝나야 한다(형제 폴더 배치, Docker 데몬, compose 포함). `up.sh`와 `demo.sh up`은 시작에서 doctor를 자동으로 돌린다.

## 3. 상시 구성 기동

먼저 알아 둘 것: **활성 릴리스가 없으면 survey-service `/readyz`가 503 `no_active_release`이고, 키오스크가 "직원을 불러 주세요"(직원 호출) 화면을 띄운다. 둘 다 정상이다.** 화면을 눌러 보려면 4절의 데모를 쓴다.

```
cd <루트>/deploy
bash scripts/registry.sh up        # 로컬 레지스트리 기동(주소를 state/registry.env 에 기록)
bash scripts/build-images.sh       # 8개 영역 이미지를 현재 HEAD 소스로 빌드
bash scripts/publish-images.sh     # 이미지를 레지스트리에 올리고 digest를 locks/images.lock 에 기록
bash scripts/gen-secrets.sh        # 토큰·계정 암호를 secrets/ 에 만든다(값은 출력 안 함)
bash scripts/up.sh deploy          # compose 기동, healthy 확인
```

| 명령 | 하는 일 | 걸리는 시간 |
| --- | --- | --- |
| registry.sh up | registry:2 컨테이너 기동 | 측정 안 함 |
| build-images.sh | 이미지 8개 빌드 | 측정 안 함 (첫 빌드는 의존 내려받기 때문에 더 걸린다) |
| publish-images.sh | push + digest 잠금 | 측정 안 함 |
| gen-secrets.sh | 비밀 파일 생성 | 측정 안 함 |
| up.sh | 기동·healthy 대기 | 측정 안 함 (E2E의 compose 기동·검사 구간은 약 67~68초: STATUS.md) |

- 레지스트리 기본 호스트 포트는 5000이다. 충돌하면 `REGISTRY_HOST_PORT= bash scripts/registry.sh up`처럼 빈 값을 주면 빈 포트를 고른다.
- gateway의 호스트 포트는 Docker가 배정한다. `bash scripts/status.sh`로 본다.
- 이미 만든 상태에서 다시 올릴 때는 이미지가 그대로면 빌드·게시를 건너뛰어도 된다. 소스를 바꿨다면 다시 빌드·게시한다.

## 4. 데모 (화면을 눌러 보기)

```
bash scripts/demo.sh up                          # 시험 구성 기동 + 시험용 릴리스 생성·활성화 + 접속 안내 출력
bash scripts/demo.sh up --stop-before-approval   # 승인 대기까지만. /admin/ 에서 직접 승인한 뒤 아래 activate
bash scripts/demo.sh activate                    # 승인된 릴리스를 활성화
bash scripts/demo.sh status                      # 컨테이너·주소·/readyz 요약
bash scripts/demo.sh down                        # deploy-demo 자원과 state/demo 제거
bash scripts/demo.sh reset                       # down 후 up
```

- 처음에는 이미지 빌드가 들어가 오래 걸릴 수 있다(측정 안 함). E2E 단계 1~8 구간은 약 45초(STATUS.md).
- **출력 읽는 법.** 끝에 "데모 접속 안내" 블록이 나온다: 주소(Docker가 배정한 포트), 화면별 경로(`/` 키오스크, `/staff/` 직원 콘솔, `/admin/` 승인·검토), 계정 이름, 암호 파일 위치, 위험 문구. 암호 값은 출력하지 않는다.
- **계정.** 직원 콘솔 `staff`, 승인자 `trainer-e2e`(역할 release-approver), 검토자 `reviewer-e2e`(역할 reviewer). 암호는 각각 `state/demo/secrets/tokens/staff-console-password`, `admin-console-password`, `reviewer-console-password` 파일에 있다(`cat`으로 연다).
- **위험 문구.** 키오스크에서 `TEST-RISK`를 말하거나 입력하면 시험용 가짜 모델이 위험으로 판정해 정지한다. 시험 구성에만 있는 문구이며 운영 구성에는 없다.
- 이 데이터는 **시험용 대체**다(가짜 모델, 시험용 어댑터·평가 보고서, 시험용 승인자 스크립트). 실제 모델·실제 승인이 아니다.

## 5. 화면별로 써 보는 법

아래 동작은 모두 **문서 기준**(kiosk-frontend, admin-console 설계 문서)이다. 게이트웨이를 거친 API 경로는 E2E로 확인했지만(확인함), **실제 브라우저에서 화면을 눌러 본 확인은 없다**(BLOCKED).

**키오스크 `/`** (인증 없음)
1. 시작 버튼 -> 안내 문장 -> 듣기. 음성(STT)을 쓸 수 없으면 입력창이 나온다. 문진 한 턴: 말하거나 입력하고 응답을 읽는다.
2. 위험 정지: `TEST-RISK`를 입력한다 -> 직원 알림이 만들어지고, 알림이 전달되면(`DELIVERED`) "직원이 오고 있습니다"(대기) 화면이 된다. 대기 중 키오스크는 2초 간격으로 상태를 확인한다. 직원이 재개하면 `resume_text`와 함께 듣기로 돌아간다.
3. 알림 전달에 실패하면(`DELIVERY_FAILED`) "직원을 직접 불러 주세요" 화면이 최우선으로 뜬다.

**직원 콘솔 `/staff/`** (계정 `staff`)
- 알림 목록과 실시간 알림(SSE). 위험 정지가 나면 목록에 열린 알림이 뜬다.
- `DELIVERED`/`DELIVERY_FAILED`는 알림이 직원 쪽에 전달되었는지에 따라 갈린다. 직원 콘솔을 열어 SSE로 연결해 둔 상태에서 위험 정지를 내면 `DELIVERED`로 나오는 것을 E2E에서 확인했다(확인함). 연결이 없을 때 정확히 어떤 값이 되는지는 설계 문서 기준이며 데모에서 직접 확인하지 않았다.
- 알림마다 재개(RESUME) 또는 종료(END)를 고른다. 확인 후 전송이며, 같은 알림에는 같은 `turn_id`가 쓰인다. E2E에서 두 경로 모두 API로 확인함.

**승인 화면 `/admin/`** (계정 `trainer-e2e`)
1. 목록: 승인 대기(`AWAITING_APPROVAL`) 제출. (`up --stop-before-approval`로 띄우면 문항 세트 v1·v2 제출이 모두 대기한다.)
2. 보고서: 제출 정보와 자동 검사 결과 아래에 **SAFETY 지표를 먼저**, 그다음 나머지 그룹을 본다. "나빠짐"은 참고 표시일 뿐이다.
3. 결정: 승인 또는 반려(반려는 사유 필수). 확인창에서 보고서 해시 앞부분·결정·사유를 다시 보고 확정한다. 승인자 ID는 게이트웨이가 인증한 계정이 자동으로 기록된다.
- 화면은 합격/불합격을 판단하지 않는다. **합격 판정은 사람**이다. 다른 역할 계정은 403, 인증이 없으면 401(확인함).
- `--stop-before-approval`로 띄웠다면 승인 뒤 `demo.sh activate`.

**실패 사례 검토 화면 `/admin/` 의 검토 메뉴** (계정 `reviewer-e2e`)
- 시험 사례가 1건(PENDING) 있다. 사례를 열어 실패 유형·출처·비식별 trace를 보고 CONFIRMED 또는 반려로 검토한다. CONFIRMED는 종류(`expected_kind`: PARSER 또는 GENERATOR)를 고르고 고쳐 쓴 입력(`reviewed_input`)과 선택 정답을 JSON으로 쓴다.
- 검토자 계정만 쓸 수 있다(승인자 계정은 403, 확인함).

## 6. 원격 서버의 화면을 내 PC 브라우저로 열기

기본 바인드는 127.0.0.1이라 서버 밖에서 바로 열리지 않는다. SSH 터널을 쓴다.

```
bash scripts/status.sh                         # (서버에서) gateway 주소의 포트를 확인
ssh -L <포트>:127.0.0.1:<포트> <사용자>@<서버>   # (내 PC에서) 그 다음 브라우저로 http://127.0.0.1:<포트>
```

주의 한 줄: 이 PC에서 기본 SSH가 키 교환에서 멈추면 `-o KexAlgorithms=curve25519-sha256` 옵션을 붙인다.

HTTP·기본 인증이라 시험용이다. `DEMO_BIND=0.0.0.0`으로 열어 두는 것은 암호가 평문으로 흐르므로 권하지 않는다.

## 7. 수명주기

`bash scripts/status.sh`로 지금 상태(컨테이너, gateway 주소, `/readyz` 요약)를 본다. 내릴 때는 `scripts/down.sh [프로젝트=deploy] [옵션]`이다(`dc`는 셸 함수라 터미널에서 칠 수 없다). 프로젝트 이름은 `deploy`·`deploy-*`만 받는다.

| 명령 | 컨테이너 | 네트워크 | 데이터 볼륨 | 로컬 레지스트리 |
| --- | --- | --- | --- | --- |
| `down.sh deploy --stop` | 멈춤(남음) | 남음 | 남음 | 그대로 |
| `down.sh deploy` (= `--remove`) | 삭제 | 삭제 | 남음 | 그대로 |
| `down.sh deploy --purge` | 삭제 | 삭제 | **삭제(되돌릴 수 없음)**. 목록을 보이고 프로젝트 이름을 입력해야 진행 | 그대로 |
| 위에 `--registry` 추가 | | | | 내림. 이미지는 레지스트리 볼륨에 남음(`--purge`와 함께일 때만 볼륨 삭제, 따로 확인) |

비대화형 삭제는 `--purge --yes-purge-<프로젝트>`를 명시해야 한다. 끝나면 남은 자원을 출력한다.

다시 켜기: `--stop` 뒤에는 `docker compose -p deploy start`(또는 `scripts/up.sh deploy`). `--remove` 뒤에는 `scripts/up.sh deploy`(데이터 볼륨을 이어 쓴다). 데모는 `demo.sh down` 또는 `reset`.

디스크 정리: 먼저 `docker system df`로 크기를 확인한다. 지울지는 사용자가 판단한다. 대상은 `deploy-build/*` 이미지와 빌드 캐시, 데모·E2E가 남긴 `deploy-*` 자원 위주다. 예: `docker image ls 'deploy-build/*'`로 보고 필요 없으면 `docker rmi`, 빌드 캐시는 `docker builder prune`. 다른 이름의 자원은 건드리지 않는다.

## 8. 흔한 문제

| 증상 | 원인·조치 |
| --- | --- |
| `docker 실행 파일을 찾을 수 없다` / docker.exe 없음 | Docker가 설치되지 않았거나 PATH에 없다. WSL이면 Docker Desktop의 WSL 통합을 켠다. `bash scripts/doctor.sh`, [SETUP.md](SETUP.md) |
| `Docker 데몬에 닿지 않는다` | 데몬이 꺼졌거나 접근 권한(리눅스는 docker 그룹)·`DOCKER_HOST`/context가 틀렸다. doctor가 원인을 구분해 안내한다 |
| 빌드가 `docker-credential-desktop.exe: exec format error`로 실패 | WSL interop이 꺼진 상태에서 `credsStore`가 윈도 도우미를 가리킨다. 우회하지 않는다: doctor가 FAIL로 알리고 SETUP.md E절이 조치를 설명한다 |
| 형제 리포 또는 태그가 없다 | `head/setup.sh`로 받는다. 태그가 없으면 doctor가 어떤 리포의 어떤 태그인지 알린다([SETUP.md](SETUP.md) C절) |
| survey-service `/readyz` 503 `no_active_release`, 키오스크가 직원 호출 화면 | 상시 구성에서는 정상(활성 릴리스 없음). 눌러 보려면 데모 |
| 게이트웨이 401 | 인증 없이 직원·승인 경로를 부른 것. 계정과 `secrets/tokens/*-password` 파일의 암호로 로그인. 역할이 다르면 403 |
| 포트 충돌 | 컨테이너 호스트 포트는 Docker가 배정하므로 드물다. 레지스트리는 `REGISTRY_HOST_PORT=`(빈 값)으로 빈 포트를 고른다 |
| `state/registry.env`가 없다 | 레지스트리를 아직 안 띄웠다. `bash scripts/registry.sh up`을 먼저 |
| `이미 데모 상태가 있다` | `demo.sh down` 또는 `reset` |

## 9. 알려진 한계

- 실제 브라우저에서 화면을 눌러 본 확인이 없다(렌더링은 E2E에서 BLOCKED). 5절은 설계 문서 기준이다.
- 모델은 가짜 백엔드뿐이다(실제 GPU 모델은 미연결). 데모의 승인자·어댑터·평가 보고서는 시험용 대체다.
- 운영 로그인 방식과 HTTPS(도메인·인증서)는 미정이다. 지금은 HTTP + 기본 인증이다.
- 웹 푸시·음성 인식(STT) 수신 확인, 백업 설정(O16), 주기 잡 간격은 미정 또는 미확인이다.
- 이 문서의 시간은 측정한 것만 적었다.
