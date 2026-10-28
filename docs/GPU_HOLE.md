# GPU 서버가 열릴 때 할 일 (구멍 H1~H4)

GPU 서버가 필요한 부분은 "구멍"으로 두었다. 나머지(이미지, 구성 병합, 어댑터 검사·패키징, 비밀 점검, 가짜 모델 E2E)는 이 PC에서 끝나 있다. GPU 서버에서는 아래 순서대로 명령을 붙여 넣고 결과를 `head/docs/OPEN_GAPS.md`에 적으면 된다.

표시: **[PC]** 이 PC에서, **[서버]** GPU 서버에서, **[사용자]** 사용자가 직접(이 리포지토리의 세션은 학습 서버·GPU 서버에 접속하지 않는다).

확인한 것과 못 한 것(2026-10-27, 이 PC):
- 확인: `demo.sh config --llm --profile rtx4090-24g`(구성 병합), 가짜 어댑터 safetensors로 패키지 생성·거부(기반 모델 불일치, 순위 초과, 인자 누락), E2E(가짜 모델).
- **확인하지 못함(구멍)**: 24GB GPU에서 Qwen3-8B 적재, 진짜 어댑터 적재, 진짜 어댑터로 한 턴, 어댑터 교체, 부하. 프로파일 `rtx4090-24g.json`의 `engine` 값은 계산한 추정이다(프로파일 파일의 `status`가 `unverified`).

## 공통 준비

전제: GPU 서버에 Docker, NVIDIA 드라이버, NVIDIA Container Toolkit, huggingface.co 도달(모델 약 16GB를 받는다), 디스크 여유 약 60GB(GPU 이미지 약 13GB, 모델 캐시 약 16GB, 빌드 캐시). SSH 옵션은 이 환경에서 `-o KexAlgorithms=curve25519-sha256`이 필요할 수 있다(`../model-lab/docs/runbook.md`의 GPU 호스트 절).

### 서버 동기화 (git bundle)

서버에서 GitHub에 닿지 않아도 되도록 리포지토리를 bundle로 옮긴다. 비밀 값은 들어 있지 않다.

```bash
# [PC] 커밋된 내용과 태그만 담긴다(작업 중인 변경은 담기지 않는다: 먼저 커밋)
cd ~/sdabin/healthKiosk && mkdir -p /tmp/openit-bundles
for r in $(ls -d */ | tr -d /); do [ -d "$r/.git" ] && [ "$r" != head ] && git -C "$r" bundle create /tmp/openit-bundles/$r.bundle --all; done
scp -o KexAlgorithms=curve25519-sha256 -r /tmp/openit-bundles <서버>:~/openit-bundles      # [사용자] 서버 주소는 사용자가 안다
```
```bash
# [서버] 처음: clone, 이후: 이어받기 (deploy 와 영역 리포가 같은 폴더 아래 형제로 있어야 한다)
mkdir -p ~/openit && cd ~/openit
for b in ~/openit-bundles/*.bundle; do n=$(basename "$b" .bundle)
  if [ -d "$n/.git" ]; then git -C "$n" fetch "$b" 'refs/heads/main:refs/remotes/bundle/main' --tags && git -C "$n" merge --ff-only bundle/main
  else git clone "$b" "$n"; fi; done
git -C model-runtime tag | tail -3      # 기준 태그가 있어야 한다 (기준은 deploy/scripts/lib.sh 의 태그 표)
```

### 서버 점검

```bash
# [서버]
cd ~/openit/deploy
bash scripts/doctor.sh --up --llm      # GPU 컨테이너 접근, 프로파일 대 GPU 메모리, 도커 디스크, huggingface.co 도달
DEMO_LLM_PROFILE=/app/profiles/rtx4090-24g.json bash scripts/doctor.sh --up --llm   # 24GB 프로파일 기준으로 보려면
nvidia-smi                              # 24GB급인지 (메모리 합계)
```
FAIL이 있으면 안내된 해결을 먼저 한다(숨기거나 건너뛰지 않는다).

## H1. 24GB GPU에 Qwen3-8B 적재와 실측 (U02, U13)

전제: 공통 준비 끝. 어댑터는 아직 필요 없다(중립 LoRA로 적재만 본다).

```bash
# [서버] 중립 LoRA(학습하지 않은 시험용)로 24GB 프로파일 적재. 첫 실행은 GPU 이미지 빌드(약 13GB)와 모델 다운로드가 있다
cd ~/openit/deploy
bash scripts/demo.sh config --llm --profile rtx4090-24g          # 먼저 구성만 검증(컨테이너 없음)
bash scripts/demo.sh up --llm --profile rtx4090-24g --yes-large   # 최대 20분(DEMO_LLM_WAIT_MIN) 적재를 기다리며 상태를 찍는다
```
주의: 중립 패키지는 기반 모델의 `config.json`(차원)이 필요한데 `scripts/make-llm-package.sh`의 표에는 Qwen3-1.7B만 있다. Qwen3-8B로 `up --llm`을 중립 LoRA로 하면 "기록되지 않았다(미확인)"로 멈춘다. 이것은 일부러다(차원을 추정하지 않는다). 두 길 중 하나를 고른다.
1. 진짜 어댑터가 이미 있으면 H2로 바로 간다(어댑터는 차원이 필요 없다). **권장.**
2. 중립 LoRA로 적재만 보려면 `https://huggingface.co/Qwen/Qwen3-8B/resolve/<커밋>/config.json`의 리비전과 sha256을 확인해 `scripts/make-llm-package.sh`의 `case`에 추가한다(사용자 확인 후 deploy 변경).

합격 기준 (보이면 성공):
- model-serving `/readyz`가 200 (`demo.sh status` 또는 `up`의 대기 로그: "survey-service 준비됨").
- `nvidia-smi`에서 모델 프로세스 메모리가 24GB 안에 들고(여유 포함) OOM 로그가 없다.
- 컨테이너 로그에 "KV cache" 토큰 수가 찍힌다(프로파일 추정은 약 2.8만 토큰).

실패 시 모을 것 (값·발화 원문은 로그에 없다):
```bash
bash scripts/demo.sh diag > diag.txt 2>&1
docker compose -p deploy-demo logs --no-color --tail 200 model-serving > ms.log 2>&1
nvidia-smi > smi.txt; docker image ls 'deploy-build/*' > images.txt; df -h > df.txt
```

**시간 상한 재정을 위한 지연 측정(H1에 편입).** 적재가 끝나 `/readyz`가 200이 되면 같은 서버에서 extract와 respond 각각의 지연 분포를 잰다. model-runtime의 요청 상한(`MODEL_RUNTIME_REQUEST_DEADLINE_S` 기본 3.5초)과 서버·gateway 시간 불변식(키오스크 10초 > gateway > survey 턴 마감 6초 > survey의 읽기 timeout 4초 > 요청 상한)의 값은 실제 모델 지연으로 측정한 적이 없는 초기값이라 여기서 재정한다.
```bash
# [서버] 대표 발화 묶음을 수십~백 회(기본 입력 10개 x --repeat). extract 와 respond 가 각각 표로 나온다. 재시작 직후 첫 호출(콜드)은 따로 나온다
python3 scripts/probe-serving.py --demo --repeat 10 > probe-h1.txt
cat probe-h1.txt | sed -n '/== 지연 표/,$p'
```
표의 열: 호출 수, 성공(HTTP 200)과 성공률, respond의 `fallback` 수, 콜드 첫 호출 지연, 이후 호출의 p50/p95/max, `X-Openit-Attempts`가 2 이상인 재시도 호출의 호출 수와 p50/p95/max(재시도는 이후 호출과 겹쳐 세지 않고 따로 한 줄로 더 본다). 백분위는 최근접 순위이고 표본이 20 미만이면 p95는 max와 같다. 이 숫자를 OPEN_GAPS에 옮겨 적고(이 리포 문서에 숫자를 복사하지 않는다), 한 호출의 p95가 3.5초를 넘으면 요청 상한 초기값을 model-runtime 쪽에서 다시 정해야 한다(deploy가 정하지 않는다). `--endpoints extract`처럼 하나만 잴 수도 있다. 이 도구는 model-serving의 호출만 잰다(서비스·gateway를 거친 전체 턴이 아니다).

측정해서 OPEN_GAPS에 적을 것: **U02** 적재 성공 여부, 적재 시간(컨테이너 시작부터 `/readyz` 200까지), `nvidia-smi` 사용 메모리, KV 캐시 토큰 수. **U13**는 H2까지 끝나야 닫는다. 프로파일 값(`max_model_len`, `gpu_memory_utilization`, `max_num_seqs`)을 바꿔야 하면 deploy가 아니라 model-runtime 소유라 변경 요청으로 낸다.

## H2. 학습된 LoRA-A/B를 얹어 한 턴 통과, 어댑터 교체 (U07, U08, U10)

전제: H1이 통과(`rtx4090-24g`로 적재됨). **Qwen3-8B로 학습한** LoRA-A/B(각각 `adapter_model.safetensors` + `adapter_config.json`)와, 학습에 쓴 것과 같은 시스템 프롬프트 두 개(`../model-lab/prompts/lora_a.system.txt`, `lora_b.system.txt`).

```bash
# [사용자] 1) 학습 서버에서 어댑터를 가져온다 (읽기만 하는 복사. 경로는 학습 서버에서 확인)
rsync -a openit:<경로>/adapters/LORA_A/ ./attach/LORA_A/
rsync -a openit:<경로>/adapters/LORA_B/ ./attach/LORA_B/
cp ~/sdabin/healthKiosk/model-lab/prompts/lora_a.system.txt ~/sdabin/healthKiosk/model-lab/prompts/lora_b.system.txt ./attach/
# [사용자] 2) GPU 서버로 옮긴다
scp -o KexAlgorithms=curve25519-sha256 -r ./attach <서버>:~/attach
```
```bash
# [서버] 3) 어댑터를 얹어 데모를 띄운다. 기반 모델 불일치·순위 초과·파일 누락이면 이미지를 빌드하기 전에 거부한다
cd ~/openit/deploy
bash scripts/demo.sh config --llm --profile rtx4090-24g \
  --adapter-a ~/attach/LORA_A --adapter-b ~/attach/LORA_B --prompt-a ~/attach/lora_a.system.txt --prompt-b ~/attach/lora_b.system.txt   # 검사만
bash scripts/demo.sh up --llm --profile rtx4090-24g --yes-large \
  --adapter-a ~/attach/LORA_A --adapter-b ~/attach/LORA_B --prompt-a ~/attach/lora_a.system.txt --prompt-b ~/attach/lora_b.system.txt
```
`demo.sh`의 어댑터 지정 방식: 네 인자(`--adapter-a/-b`, `--prompt-a/-b`)를 모두 줘야 하고, 주면 `make-llm-package.sh`가 중립 LoRA 대신 `scripts/llm_attach_package.py`로 같은 구조의 패키지(`state/demo/llm-package/`)를 만든다. 거부 조건: `adapter_config.json`의 `base_model_name_or_path`가 프로파일 기반 모델과 다름, 순위 `r`이 프로파일 `max_lora_rank`(16) 초과, 필수 파일·LoRA 텐서 없음, 프롬프트가 비었거나 UTF-8이 아님. 이 길은 평가하지 않는다(보고서 지표는 시험용 고정값이라 화면의 점수를 믿지 않는다).

model-lab 쪽 명령도 있다: `python -m model_lab package-adapters ...`는 어댑터를 모델 패키지로 만들어 model-registry에 게시한다(절차는 `../model-lab/docs/runbook.md`의 "학습 서버 어댑터를 얹는 절차"). 다만 model-lab의 프로파일은 `gpu-dev-12g`뿐이라 `rtx4090-24g`(Qwen3-8B)로는 아직 쓸 수 없다. 이 데모 경로는 model-runtime의 프로파일을 쓰므로 막히지 않는다. model-lab에 24GB 프로파일이 필요하면 헤드가 변경 요청으로 낸다.

합격 기준 (한 턴 통과):
- `up`이 "survey-service 준비됨"으로 끝나고, 끝 부분의 "비밀 노출 점검"이 통과.
- `demo.sh diag`에서 제출 3건이 `REJECTED_AUTO` 없이 승인 대기 이상(CONTRACT_COMPAT 포함 checks가 PASS).
- 키오스크(안내된 주소)에서 한 턴: 형식 위반(`503 OUTPUT_INVALID`) 없이 다음 질문이나 확인 응답이 온다. 모델 출력은 로그에 원문이 없다.
- 가능하면 `/v1/info`의 `system_prompt_sha256`이 `--prompt-a/-b` 파일의 해시와 같다(어긋나면 학습 때 프롬프트와 다른 것).

어댑터 교체 시험 (U08): 같은 기반 모델의 두 번째 어댑터 세트(예: 다른 학습 run)로 바꿔 본다. 데모 전체를 지우지 않고 model-serving만 새 번들로 바꾸는 `swap-adapters`가 있다(D72).
```bash
# [서버] 떠 있는 --llm 데모에서. 같은 사전 검사로 기반 모델 불일치·순위 초과·파일 누락이면 아무것도 게시하지 않고 거부한다(활성 릴리스 그대로)
bash scripts/demo.sh swap-adapters \
  --adapter-a ~/attach2/LORA_A --adapter-b ~/attach2/LORA_B --prompt-a ~/attach/lora_a.system.txt --prompt-b ~/attach/lora_b.system.txt
```
`swap-adapters`는 새 패키지를 게시하고 자동 검사를 거쳐 시험용 승인자(스크립트, TEST-SUB)로 승인·활성화한 뒤, model-serving에서 새 release_id가 `LOADED`가 되는 것과 다른 서비스 컨테이너(survey-service, release-gate, model-registry, ops-feedback-ingest, question-authoring, gateway)의 ID·StartedAt이 전후로 같음을 출력한다(`docker inspect`의 두 필드만 읽는다). 합격: 그 출력 + 키오스크 한 턴이 다시 통과. 한계(확인하지 못한 것): 이 PC에서는 가짜 백엔드 데모로만 돌려 봤다(실제 vLLM에서 두 번째 LoRA를 적재하는 시간·메모리는 측정 전). 기존 어댑터가 GPU 메모리에 남아 있는지, 새 어댑터의 적재가 추론 중인 요청에 미치는 영향도 미확인. 같은 어댑터 쌍을 다시 주면 이미 활성이라 교체 없음으로 끝난다.

실패 시 모을 것: `bash scripts/demo.sh diag`, model-serving 로그 마지막 200줄, `nvidia-smi`, 거부 메시지 전문(`거부: ...`, 값은 없다). 기반 모델 불일치 거부는 정상 동작이다. 어댑터가 4B로 학습된 것이면 24GB 프로파일에는 얹을 수 없다.

측정해서 OPEN_GAPS에 적을 것: **U07** 실제 어댑터로 한 턴 통과 여부, 기동 시간, 시작·응답 지연. **U08** 교체 후 통과 여부(`swap-adapters` 출력의 LOADED·StartedAt 불변)와 위 한계. **U10** 이 길은 평가하지 않으므로 U10은 닫히지 않는다(평가는 model-lab 쪽, H3). **U13** H1+H2 결과로 갱신.

## H3. 학습 파이프라인 실제 실행 (G06)

이 리포지토리(deploy)의 몫이 아니다. 학습·평가·패키징·게시는 model-lab이 소유한다. 순서와 명령은 `../model-lab/docs/runbook.md`("GPU 호스트(gpu-dev) 실행", "학습 서버 어댑터를 얹는 절차")를 따른다. G06(학습 정본은 서버 코드, 비전문가용 실행)은 헤드 결정이 남아 있다. deploy 쪽 연결: 학습 결과의 어댑터는 H2의 `--adapter-a/-b`로 얹고, 게시까지 하려면 model-lab `package-adapters`(위 한계 참고)를 쓴다. 이 PC에서 확인하지 못한 것: 진짜 학습 실행 전부.

## H4. 문법 컴파일 비용과 동시 부하 (U01, U04)

전제: H2 통과(A 역할은 제약 디코딩이라 첫 호출에서 문법을 컴파일한다).

```bash
# [서버] 컴파일 비용: 컨테이너를 재시작해 첫 호출과 둘째 호출을 분리해 잰다
docker compose -p deploy-demo restart model-serving
# /readyz 200 이 되면 키오스크에서 같은 입력으로 두 번 말하고, 로그 시각으로 각 extract 호출 시간을 비교
docker compose -p deploy-demo logs --no-color --timestamps --tail 100 model-serving
```
측정 도구: `scripts/probe-serving.py`(docs/RUN.md 7-2-3). model-serving의 extract에 입력 묶음을 보내 성공/OUTPUT_INVALID 건수, 위반 키워드별 빈도, 첫 호출 대 이후 중앙값 지연, `X-Openit-Outcome` 분포를 표로 낸다. 일회용 스크립트를 새로 쓰지 않는다.
```bash
# [서버] 재시작 직후 첫 호출(문법 컴파일)과 이후 호출이 분리되어 나온다. 동시 N개(N=1,2,4,8; 프로파일 max_num_seqs=8)는 --concurrency
bash scripts/demo.sh status        # 떠 있는지
python3 scripts/probe-serving.py --demo --repeat 3
python3 scripts/probe-serving.py --demo --repeat 5 --concurrency 4 --inputs 내_발화.json   # 입력 파일은 선택
```
이 도구는 model-serving의 extract만 잰다(서비스·게이트웨이 경유 전체 턴이 아니다). 키오스크 세션 전체의 동시 부하는 이 리포지토리에 도구가 없다(미구현): 필요하면 브라우저 탭이나 게이트웨이 키오스크 경로(`/v1/sessions`, `/v1/sessions/{id}/turns`)를 `curl` 병렬로 부르거나 헤드에게 요청한다.

합격 기준: 첫 호출 이후 지연이 안정되고, 동시 N개에서 `OUTPUT_INVALID`·시간 초과가 없거나 그 빈도가 기록된다. (합격선 수치는 정해진 바 없다: 사용자 결정 전. 측정값만 적는다.)

실패 시 모을 것: model-serving 로그(타임스탬프 포함), `nvidia-smi`, `demo.sh diag`.

측정해서 OPEN_GAPS에 적을 것: **U01** 24GB·12GB에서 A·B 동시 적재 확인과 지연(첫 호출 대 이후 호출 분리). **U04** 문법 컴파일 비용(첫 호출 대 둘째 호출 시간), 동시 N개에서 형식 통과율, `minItems`/`maxItems` 강제 여부는 출력 항목 수로 확인.

## 끝나면

```bash
bash scripts/demo.sh down              # 데모 컨테이너·볼륨 제거(모델 캐시는 남는다. 지우려면 down --purge-cache)
bash scripts/check-secrets-hidden.sh   # 상시 구성과 (떠 있으면) 데모 스택의 비밀 노출 점검, 값은 출력하지 않는다
```
