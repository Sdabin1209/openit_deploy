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

## 7-1. 추론 서버를 다른 곳에 두는 법 (D72)

추론 서버(model-serving)는 컨테이너이고 어디에 두든(같은 컴포즈, 다른 GPU 서버) 기능 차이가 없어야 한다. 호출하는 survey-service는 주소(`SURVEY_INFERENCE_URL`)와 토큰만 알고, 서버는 release-gate 주소·토큰·프로파일을 환경 변수로만 받는다. **이 절의 구성은 파일과 스크립트를 만든 단계이며, 이 PC에서는 Docker 데몬이 꺼져 있어 컨테이너로 실행해 확인하지 못했다(미확인).** 확인된 것은 `bash -n`, 인자 검사, doctor 점검의 가짜 서버 시험, YAML 문법뿐이다. 실제 GPU 이미지는 이 단위에서 빌드·내려받지 않았다.

**(a) 추론 서버를 둘 호스트에서** (`compose.inference.yaml` 파일 하나와 이미지, 토큰 env 파일만 있으면 된다. deploy의 잠금 파일·네트워크·서비스 이름에 의존하지 않는다. 문진 스키마는 이미지에 내장되어 있어 스키마 마운트나 survey-service 이미지가 필요 없다)

| 변수 | 필수 | 뜻 |
| --- | --- | --- |
| `INFERENCE_IMAGE` | 필수 | model-serving 이미지 전체 참조(digest 고정). GPU 변형 이미지도 여기에 둔다 |
| `RELEASE_URL` | 필수 | release-gate 주소. 이 호스트에서 닿아야 한다 |
| `INFERENCE_ENV_FILE` | 필수 | 토큰 env 파일의 경로(값이 아니다): `MODEL_RUNTIME_TOKENS=<호출자>=<토큰>`, `MODEL_RUNTIME_RELEASE_TOKEN=<게이트 읽기 토큰>` (프로파일 등 모델 설정도 여기) |
| `INFERENCE_BACKEND` | 선택 | 기본 `fake`. GPU 변형은 model-runtime이 정한 값 |
| `INFERENCE_BIND` / `INFERENCE_PORT` | 선택 | 호스트 바인드(기본 0.0.0.0) / 포트(기본 8080, 빈 값이면 Docker 배정 -> `docker port`로 읽는다) |

```
INFERENCE_IMAGE=<레지스트리>/openit/model-serving@sha256:... \
RELEASE_URL=http://<release-gate 주소>:<포트> \
INFERENCE_ENV_FILE=/안전한/경로/inference.env \
docker compose -p deploy-inference -f compose.inference.yaml up -d --wait
```

- 데몬 없이 병합만 보려면 세 변수를 주고 `docker compose -f compose.inference.yaml config`(이 PC에서는 docker가 없어 실행해 보지 못했다).
- GPU 예약과 HF 캐시 볼륨은 파일 안에 주석 처리된 예시가 있다(GPU 이미지의 캐시 폴더 쓰기 권한은 확인 안 함).
- 배포용 model-serving 이미지는 `build-images.sh`가 문진 스키마(survey-service의 `survey-schema-v1.0.0` 태그 시점 `schema/`)를 `--build-context schema=`로 내장해 만든다. **이미지를 다시 만들고 게시해 `locks/images.lock`의 model-serving digest를 갱신해야 한다**(이 변경 전 digest의 이미지는 스키마가 없다).
- 토큰 값을 파일·인자로 저장소에 넣지 않는다.

**(b) 본 구성(호출자) 쪽에서**

```
export INFERENCE_TOKEN=<서버의 MODEL_RUNTIME_TOKENS 에 등록한 이 호출자 토큰>   # 또는 INFERENCE_TOKEN_FILE=<EXTERNAL_INFERENCE_TOKEN=... 한 줄이 든 파일 경로>
bash scripts/doctor.sh --up --inference http://<서버>:8080        # 닿는지, 토큰이 통과하는지
bash scripts/up.sh deploy --external-inference http://<서버>:8080   # 이 구성의 model-serving 은 프로필로 꺼진다
bash scripts/demo.sh up --external-inference http://<서버>:8080     # 데모도 같은 옵션
```

토큰 값은 인자로 받지 않고 출력하지 않는다(`INFERENCE_TOKEN`이면 `secrets/external-inference.env`로 600 권한 파일을 만든다).

**양방향 도달성.** 호출자 -> 서버(위 doctor가 확인)와 서버 -> release-gate가 모두 열려야 한다. 후자는 서버 호스트에서 `RELEASE_URL`이 닿는지 직접 확인한다(doctor가 대신 확인하지 못한다). 상시 구성에서 release-gate는 호스트 포트를 열지 않으므로, 다른 호스트의 서버가 읽게 하려면 게이트를 노출하는 방법(운영 결정: 사설 네트워크·TLS·접근 제한)을 정해야 한다. 이 결정은 아직 없다(미정). 시험은 임시로 게이트를 0.0.0.0의 빈 포트에 한 번 더 노출한다.

**위치 독립 시험.** `bash scripts/test-inference-location.sh` : 추론 서버(CPU/fake)를 별도 컴포즈 프로젝트(`deploy-e2e-loc-inf`)로 띄우고, 본 구성이 `--external-inference`로 그 서버를 불러 E2E 단계 1~5를 통과하는지 본다(서버 중단·복구는 건너뛴다: Docker 배정 포트가 재시작 뒤 바뀔 수 있다). 호스트 포트는 모두 Docker가 배정하고, 먼저 127.0.0.1 게시로 시도하며 컨테이너가 닿지 못할 때만 시험 동안 0.0.0.0으로 올린다. 자원은 `deploy-e2e-loc*` 접두사이며 끝나면 지운다(`--keep`, `--clean`). 이 PC에서는 실행하지 못했다(미확인). 서버에서 한 번 돌려 확인해야 한다.

## 7-2. GPU로 실제 LLM 쓰기 준비 (D72/D73)

이 절은 **준비 단계**(이미지 빌드, compose override, 점검)다. 릴리스에 연결해 데모에서 실제 LLM으로 문진하는 것(`demo.sh --llm`)은 다음 단위이며 아직 없다. 이 PC에서는 Docker가 꺼져 있어 아래 명령을 **실행해 확인하지 못했다**(미확인). 서버(GPU)에서 확인해야 한다.

| 항목 | 값 | 상태 |
| --- | --- | --- |
| GPU 이미지(`model-serving-gpu`) 용량 | 약 13GB | model-runtime의 안내값. 서버에서 측정 전 |
| HF 캐시 볼륨(`deploy-llm-hf-cache`) 용량 | 약 3GB (기반 모델 Qwen/Qwen2.5-1.5B-Instruct) | 측정 전 |
| **합계** | **약 16GB** = 이미지 13GB(데몬에 한 벌) + 캐시 3GB. 데모는 이미지를 레지스트리에 올리지 않으므로 **이중 보관이 없다** | 서버에서 측정 전 |
| 첫 기동 시간(모델 내려받기+적재) | 모름 | 측정 전. 헬스체크 start_period를 900초로 넉넉히 잡았다(잠정) |
| 프로파일 | `/app/profiles/gpu-12g.json`(12GB급, 기본), `rtx4090-24g.json`(24GB) | 이미지 안. `DEMO_LLM_PROFILE`로 고른다 |

순서:

```
bash scripts/doctor.sh --up --llm               # GPU 컨테이너 접근, 프로파일 대 GPU 메모리, 도커 디스크, huggingface.co 도달
bash scripts/build-images.sh --gpu              # GPU 변형만 빌드(model-runtime v0.5.2, 문진 스키마 내장). 빌드 전 docker system df 와 약 13GB 안내.
                                                #   비대화형이면 --yes-large 를 명시해야 진행한다
bash scripts/publish-images.sh model-serving-gpu   # 레지스트리에 올리고 잠금에 MODEL_SERVING_GPU_DIGEST 기록
```

- 기본 빌드(`build-images.sh`, 옵션 없음)에는 GPU 이미지가 들어가지 않는다. 기존 8개 서비스 흐름은 그대로다. 옵션 없이 `publish-images.sh`를 부르면 `build/images.env`에 GPU 이미지가 있을 때 그것도 올라가므로(약 13GB) 이름을 지정하는 편이 안전하다.
- `compose.llm.yaml`: model-serving을 GPU 이미지·`MODEL_RUNTIME_BACKEND=vllm`·`MODEL_RUNTIME_PROFILE`로 바꾸고, GPU 장치 1개 예약(`deploy.resources.reservations.devices`), 프로젝트 밖 이름 있는 볼륨(`external`, 기본 `deploy-llm-hf-cache`, `HF_CACHE_VOLUME`; 직접 쓸 때는 먼저 `docker volume create deploy-llm-hf-cache`)을 `HF_HOME`으로 붙인다. 쓰는 법(릴리스 연결 전의 수동 확인용): `docker compose -p <프로젝트> -f compose.yaml -f compose.llm.yaml -f compose.llm.digest.yaml --env-file locks/images.lock --env-file state/registry.env up -d`. 기본 `compose.yaml`은 바뀌지 않았다. **이미지 선택은 파일로 나눴다**: 운영/CI는 `-f compose.llm.digest.yaml`(게시된 digest), 데모는 `-f compose.llm.local.yaml`(`MODEL_SERVING_GPU_IMAGE`=로컬 태그, `pull_policy: never`). 중첩 기본값 한 파일(`${A:-${B:?}}`)은 일부 compose 버전이 안쪽 필수 변수를 미리 평가해 로컬 태그를 줘도 실패했다(서버 시험의 오류로 추정, 이 PC의 compose 5.0.2는 정상).
- **조합 규칙.** `compose.llm.yaml`은 `compose.external-inference.yaml`과 함께 쓰지 않는다(그쪽은 이 구성의 model-serving을 끈다). 다른 GPU 서버에 두려면 그 서버에서 `compose.inference.yaml`에 `INFERENCE_IMAGE=<GPU 이미지>`, `INFERENCE_BACKEND=vllm`과 프로파일을 준다. `compose.test.yaml`(가짜 백엔드)과 같이 쓰면 `-f` 순서에서 `compose.llm.yaml`이 뒤에 와야 한다.
- **인터넷.** 첫 기동은 huggingface.co에서 모델을 받는다. 오프라인이면 `hf-cache` 볼륨을 미리 채우고 `HF_HUB_OFFLINE=1`을 준다(이 볼륨 채우는 절차는 정리하지 않았다).
- 읽기 전용 루트에서 vLLM이 쓸 캐시 위치가 더 필요한지는 GPU 서버에서 확인 전이다(`XDG_CACHE_HOME`을 볼륨 안으로 두었다).

### 7-2-1. 데모를 실제 LLM으로 (`demo.sh up --llm`)

```
bash scripts/demo.sh up --llm [--profile gpu-12g] [--yes-large]     # reset --llm 도 같은 옵션
bash scripts/demo.sh config --llm                                    # 컨테이너를 띄우지 않고 병합된 compose 설정만 검증(이미지 참조가 로컬 태그인지, GPU 이미지가 이미 있는지)
bash scripts/demo.sh status                                          # model-serving 의 /readyz 사유(적재 중인지)와 survey-service 의 inference 요약
```

`up --llm`이 하는 일(순서): (0) **병합 사전 검증**(빌드·게시 전에 `docker compose config`로 model-serving 이미지가 로컬 태그인지 확인, 실패하면 빌드·게시 없이 멈춤) (1) `doctor.sh --up --llm` (2) 기본 8개 이미지 빌드(없을 때) (3) `model-serving-gpu`가 없으면 `build-images.sh --gpu`(용량 안내, 비대화형이면 `--yes-large`) (4) `make-llm-package.sh`로 중립 LoRA 패키지 생성 (5) 임시 레지스트리에 기본 8개 이미지만 게시한다(**GPU 이미지는 게시하지 않는다**: model-serving은 방금 빌드한 로컬 이미지 `deploy-build/model-serving-gpu:<커밋>`를 태그로 직접 쓰고 `pull_policy: never`. digest 고정은 데모에서 하지 않는다. 운영/CI는 게시된 digest를 쓰는 기존 방식 그대로 -- `compose.llm.yaml`의 `MODEL_SERVING_GPU_IMAGE`/`MODEL_SERVING_GPU_PULL`로 고른다) (6) 기동 직전 병합 검증을 한 번 더 한 뒤 `compose.yaml` + `compose.test.yaml` + `compose.llm.yaml` + `compose.llm.local.yaml` + `test/compose.llm-demo.yaml`로 기동 (7) E2E 단계 1~3·데모 단계를 돌려 릴리스를 만들고 활성화 (8) 적재가 끝날 때까지 기다린다.

- **모델은 학습하지 않은 Qwen/Qwen2.5-1.5B-Instruct + 시스템 프롬프트(prompt-2) + 효과 없는 LoRA(lora_B=0)이다. 시험용 대체다.** 작은 모델이라 응답이 거칠 수 있고, 출력 보호가 규칙 기반 대체 문장으로 바꾸기도 한다.
- **진단.** 릴리스 준비가 실패하면(`데모 릴리스 준비 실패`) `bash scripts/demo.sh diag`: release-gate의 모든 제출(status)과 각 GateDecision의 checks(kind, result, detail)·reject_codes, 활성 포인터, 후보 수집기 다시 실행(멱등) 결과, model-registry 패키지 요약, model-serving `/v1/info`(vllm 백엔드는 모델을 올리기 전에는 `serving_config_expectation`이 비어 있어 서빙 설정을 서버 값에서 맞출 수 없다: 그래서 패키지의 설정을 쓴다)를 읽기 전용으로 보여 준다. 자동 검사에서 반려되면 데모 실행도 60초를 기다리지 않고 같은 사유를 바로 출력한다.
- **재실행.** 이미 있는 이미지는 다시 빌드하지 않는다: 기본 8개는 `build/images.env`의 기록과 로컬 이미지가 모두 있으면 건너뛰고, GPU 이미지(13GB)는 기록과 이미지가 있으면 건너뛴다(8개를 다시 빌드해도 GPU 기록은 지우지 않는다). 강제: `--rebuild`(8개), `--rebuild-gpu`(GPU). 실패한 뒤에는 `demo.sh down`으로 상태(`state/demo`)를 지우고 다시 `up --llm`을 한다(로컬 이미지와 HF 캐시는 남는다).
- **중립 LoRA 패키지.** `scripts/make-llm-package.sh <프로파일> <폴더>`가 model-runtime 태그(v0.5.2)의 `git archive`에서 `make_neutral_package.py`와 `profiles/<이름>.json`을 꺼내 deploy의 `.venv`로 만든다. Docker 없이 실행되고 같은 입력이면 같은 바이트다(이 PC에서 실행해 `SUMMARY.json`과 결정성을 확인했다). 데모의 단계 3이 이 패키지를 model-registry에 게시한다. 서빙 설정은 fake의 `/v1/info` 기대값이 아니라 패키지의 vllm 설정이고, 서버가 적재할 때 같은 설정인지 스스로 검사한다. 평가 보고서는 이전처럼 **시험용 고정 지표**(TEST-SUB)다.
- **시험 위험 문구.** vllm 백엔드는 `MODEL_RUNTIME_FAKE_RISK_PHRASE`가 있으면 시작을 거부하므로 `test/compose.llm-demo.yaml`이 그 값을 비운다. 그래서 `TEST-RISK`는 이 모드에서 동작하지 않을 수 있다(위험 정지는 모델 출력에 달려 있다).
- **기다림.** 첫 기동은 모델 내려받기(약 3GB)와 적재로 오래 걸린다. `up`은 최대 20분(`DEMO_LLM_WAIT_MIN`) 30초마다 model-serving과 survey-service의 `/readyz`를 보여 준다. 시간이 지나도 **실패로 끝내지 않고** "아직 적재 중"이라 안내하고 끝낸다. `status`로 확인한다. **모델 캐시는 기본적으로 남는다**: `deploy-llm-hf-cache`는 프로젝트 밖 이름 있는 볼륨(없으면 `up --llm`이 만든다)이라 `demo.sh down/reset`, `down.sh --remove/--purge`가 지우지 않고, 다음 `up --llm`이 모델(약 3GB)을 다시 받지 않는다. 지우기: `bash scripts/demo.sh down --purge-cache` 또는 `bash scripts/down.sh --purge-hf-cache` (볼륨 이름을 직접 입력, 비대화형은 `--yes-purge-deploy-llm-hf-cache`). `status.sh`가 이 볼륨의 존재와 크기(`docker system df -v` 표를 읽음, 형식이 다르면 '알 수 없음')를 보여 준다. 로컬 GPU 이미지(`deploy-build/model-serving-gpu`)도 `down`이 지우지 않는다(`docker rmi`는 사용자가 판단).
- **미확인(서버에서 확인 필요).** 이 PC에서는 Docker가 꺼져 있어 이 흐름을 실행하지 못했다. 확인한 것은 `bash -n`, 인자 검사, `py_compile`, 중립 패키지 생성기 실행(`SUMMARY.json`)과 패키지 매니페스트의 `ModelPackageManifest` 스키마 통과다. 후보 수집·자동 검사(문항-모델 호환)가 vllm 설정에서 통과하는지, 서버의 실제 적재 시간, 위험 정지 동작은 확인하지 않았다.
- **조합 규칙.** `--llm`은 `--external-inference`와 함께 쓰지 않는다. 다른 GPU 서버에 두려면 7-1절을 따른다.

**용량과 정리.**
- 확인: `docker system df`(이미지·볼륨·빌드 캐시의 크기와 회수 가능량). Docker Engine(리눅스)은 보통 `/var/lib/docker`(`docker info --format '{{.DockerRootDir}}'`), Docker Desktop은 VM 디스크 안이라 이 셸의 `df`로 보이지 않는다(설정의 Resources > Disk image 위치).
- 지울지는 사용자가 판단한다. GPU 이미지: `docker image ls 'deploy-build/model-serving-gpu'`로 보고 필요 없으면 `docker rmi <이미지>`(레지스트리에 올렸다면 레지스트리 볼륨에도 있다: `scripts/down.sh <레지스트리 프로젝트> --registry --purge`는 레지스트리 볼륨까지 지운다). HF 캐시: `bash scripts/down.sh --purge-hf-cache`(또는 `demo.sh down --purge-cache`)로만 지워진다. **Docker Desktop(WSL2)은 이미지·볼륨을 지워도 호스트의 디스크 파일이 줄지 않을 수 있다**(디스크 이미지 축소는 Docker Desktop 설정에서 사용자가 판단). 빌드 캐시: `docker builder prune`.

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
