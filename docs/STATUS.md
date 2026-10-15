# STATUS (2026-10-15)

## 한 일

- Compose 구성(gateway=Caddy, 서비스 4개), digest 잠금, 로컬 레지스트리, 빌드·게시·롤백 스크립트, 비밀 값 생성, 백업·복구, 주기 잡 스케줄러, E2E 스크립트. 설계·경계·런북·변경 이력·변경 요청 8건(CR-D01..D08).
- 실제로 돌린 시험: `bash scripts/e2e.sh` (전체 빌드 포함) -> 검사 62개 PASS, FAIL 0, 종료 코드 0. 끝에 임시 프로젝트·레지스트리·이미지·임시 폴더를 모두 지웠다(다른 이름의 `ownplace-db-1`은 건드리지 않음).

## E2E 단계별 (docs/E2E.md)

| 단계 | 상태 | 내용 |
| --- | --- | --- |
| 1 | REAL | question-authoring: 자료 등록→미리보기→확인 x2. QuestionBank 2버전(해시·문진 스키마), ReviewRecord(clinical_basis_approved), ChangeClassification, 원본 해시 출처 모두 통과 |
| 2 | BLOCKED | synthetic-data 정보 없음(CR-D04) |
| 3 | TEST-SUB | 시험용 어댑터(`test/fixtures/e2e-test-adapter`)+model-runtime FakeBackend 적재, ModelPackageManifest 2건 스키마 통과. model-lab 파이프라인은 실행하지 않음 |
| 4 | 일부 REAL | 접수(202), 중복 접수, 역할 불일치 403. 판정·릴리스·번들은 BLOCKED(CR-D01, CR-D02) |
| 5 | BLOCKED | survey-service는 시험 대역 I4/I6로 `/readyz` 200만 확인. 공개 API(O06)와 실제 클라이언트가 없다 |
| 6 | 일부 TEST-SUB | 봉투를 e2e가 만들어 보냄(ACCEPTED→DUPLICATE, 403, 400). 비식별 잡·FailureCase는 BLOCKED(CR-D05) |
| 7 | BLOCKED | 2, 3, 6b에 의존 |
| 8 | 일부 REAL | 롤백 요청 경로(REJECTED 영수증, 멱등, 역할 403). APPLIED는 BLOCKED(릴리스 없음) |
| 9 | REAL | 4개 서비스+gateway 기동·healthz·readyz, 네트워크 분리, 비root, digest 참조, 라벨, 스케줄러, 백업·복구(실제 삭제 후 복구), digest 잠금 롤백 |

합격 조건 "1~9가 사람 손 없이 순서대로 실행되고 모든 레코드가 스키마·해시 검증을 통과"는 **아직 충족하지 못했다**: 2, 4(판정 이후), 5, 6(FailureCase), 7, 8(APPLIED)이 영역 구현이 이어지지 않아 막혀 있다.

## 남은 일

1. CR-D01(원격 클라이언트 패키징)이 가장 크다. 풀리면 survey-service 연결, 게이트 판정, E2E 4~8단계를 이어 붙일 수 있다.
2. 사용자 결정: O16(백업 주기·보관·복구 시점), 스케줄 주기(`config/jobs.yaml`), 공개 도메인·TLS(O06), 외부 감시 서비스, GPU 서버 위치(D40), 정책(O11).
3. CI가 생기면 이미지 digest 제출(D24)을 CI에 맡긴다.
4. 운영 `compose.yaml`의 survey-service는 팩토리가 없어 시작하지 않는다(CR-D01). `SURVEY_MODEL_BACKEND=fake`를 운영에서 막는 책임은 survey-service에 있다(CR-D08).
5. 라벨 표(CR-D06 후), GPU 서버용 잡 호출 스크립트(CR-D04 후).

## 막힌 것

진행 자체를 막는 것은 없다. 위 BLOCKED는 변경 요청으로 헤드에 넘겼다.

## 알아 둘 것

- 이 환경(Docker Desktop, WSL)에서는 데몬이 VM 안에 있어 임의 배정 호스트 포트·`127.0.0.1` 게시 포트로 push가 안 된다. 시험 레지스트리만 빈 포트를 골라 `0.0.0.0`에 잠시 띄운다. 서비스 컨테이너의 호스트 포트는 Docker 배정을 읽는다.
- `locks/images.lock`의 서비스 digest는 이 환경의 임시 레지스트리에서 한 번 게시한 값이다. 다른 서버에서는 `publish-images.sh`로 다시 만든다.
- 이웃 리포지토리는 수정하지 않았다(`git status` 변화 없음). 빌드는 `git archive`/bare 사본(`build/ctx`, gitignore).
