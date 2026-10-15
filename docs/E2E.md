# 끝에서 끝까지 한 바퀴 (합격 시나리오)

> 헤드 전달본(2026-10-15). 이 시나리오를 한 번에 실행하는 스크립트는 deploy가 소유한다. 모델 단계(3)는 GPU 호스트가 필요하므로, 이 환경에서는 model-runtime의 가짜 백엔드와 시험용 어댑터 디렉터리로 단계를 대신하고 그 사실을 보고서에 표시한다(시험 자료는 이름에 test를 넣는다).

시스템이 모델 성능을 제외하고 완성되었는지 확인하는 기준이다(D38). 품질은 보지 않고 **각 단계가 다음 단계의 입력을 만들고 순환이 닫히는지**만 본다. 이 시나리오를 한 번에 실행하는 스크립트는 deploy가 소유하며, 각 단계의 시험 자료(작은 문항 자료, 작은 기반 모델, 짧은 학습 설정)는 시험용임을 이름에 표시한다. 시험 자료가 운영 설정으로 흘러들어가면 안 된다.

| # | 단계 | 담당 | 인터페이스 | 확인할 것 |
| --- | --- | --- | --- | --- |
| 1 | 저자가 문항 자료를 올리고 미리보기를 확인한다 | question-authoring | I1 | `QuestionBank` 버전, `ReviewRecord`(clinical_basis_approved), `ChangeClassification`, 원본 해시 출처 |
| 2 | 문항을 읽어 학습·평가 데이터를 만든다(보지 못한 문항 평가 포함) | synthetic-data | I1→I2 | `DatasetManifest`, 평가 시나리오가 학습과 겹치지 않음 |
| 3 | 설정 하나로 학습·평가·패키징·게시가 돈다 | model-lab | I2→I3 | `ModelPackageManifest`(어댑터 해시, 계보), 같은 설정과 시드로 재실행 시 같은 결과 |
| 4 | 후보 수집기가 새 조합을 찾아 판정하고, 통과하면 릴리스와 번들을 만든다 | release-gate | I1,I3→I4,I5 | `GateDecision`, `ReleaseManifest`, 번들 해시 검증 |
| 5 | 서비스가 새 포인터를 보고 새 세션부터 새 릴리스로 한 턴 이상을 처리한다 | survey-service | I4,I8,I9→I6 | 턴 처리, `TraceEnvelope` 전송, 재전송해도 중복 없음 |
| 6 | Trace를 수집·비식별해 실패 사례를 만든다(보지 못한 문항 발화를 일부러 넣어 유도) | ops-feedback | I6→I7 | `FailureCase`에 비식별 전 데이터 없음 |
| 7 | 실패 사례가 데이터 생성·학습·저작으로 돌아간다 | synthetic-data, model-lab, question-authoring | I7 | 새 데이터셋 버전이 실패 사례를 시드로 인용 |
| 8 | 롤백 요청이 활성 릴리스를 되돌린다 | ops-feedback→release-gate | I5 | `RollbackReceipt`, 서비스가 새 세션부터 이전 릴리스 사용 |
| 9 | 모든 서비스가 Compose에서 이미지로 뜨고 주기 잡이 스케줄러로 돈다 | deploy | — | `/healthz`, digest 잠금으로 코드 축 롤백 |

합격 조건: 1~9가 사람 손 없이 순서대로 실행되고, 모든 레코드가 계약 스키마와 해시 검증을 통과한다.
