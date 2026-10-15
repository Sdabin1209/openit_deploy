# CR-D11: 실패 사례 검토를 HTTP로 게시할 면이 없다 (7단계)

- 상태: 제안
- 보내는 곳: deploy -> head (영향: ops-feedback, question-authoring, synthetic-data)

## 확인한 것

- 7단계의 시드는 `review_status=CONFIRMED`이고 `expected`가 있는 FailureCase만 쓴다(I7 규정). 잡이 만든 사례는 `PENDING`이다.
- 검토를 게시하는 길은 `ReviewQueue(store).review(...)`라는 파이썬 호출뿐이고(런북: "검토 화면(UI)은 아직 없다"), `publish_case`는 HTTP로 열려 있지 않다(HTTP.md). 그래서 사람이 UI 없이 확인을 남길 수 없고, 자동 실행에서는 7단계가 끊긴다.
- deploy는 ops-feedback **이미지 안에서** 그 API를 불러 검토자 확인을 대신했다(TEST-SUB). 그러면 새 데이터셋 버전이 사례 ID를 시드로 인용하는 것까지 확인됐다.
- `expected`의 형태를 알아야 한다: 시드로 쓰이려면 trace의 `parser_input`이 있고 `expected`가 그 입력에 맞는 ParserOutput이어야 한다. 맞지 않으면 synthetic-data가 `skipped_seeds`에 "expected의 종류와 trace 입력이 맞지 않음"으로 조용히 넘긴다(시험 중 확인).
- 학습(model-lab)과 저작(question-authoring)으로의 환류: model-lab은 E2E_GPU=1 경로에서만, question-authoring은 개선 신호(I7) 소비 구현이 이 구성에서 확인되지 않았다.

## 요청

검토 게시용 서비스 면(예: `POST /v1/cases/{id}/review`, 검토자 역할 토큰) 또는 헤드가 정한 대체 경로를 낸다. 시드로 쓸 수 없는 사례를 건너뛸 때 이유를 사람이 볼 곳(보고서 외 경고)도 정한다.
