# 변경 요청: Exposure 에 기계 토큰 인증 종류가 없다 (deploy -> 헤드)

- 요청자: deploy (wo-440), 대상: boundary-contracts `Exposure` 스키마, release-gate 이미지 라벨 `io.openit.exposure`
- 상태: **닫힘(필요 없어짐)** — 계약 4.0.0 R3.23 이 `machine-token` 종류와 기계 호출자의 공개 입구 경로를 없앴다. compose 밖 기계 호출자는 R1.5 로 받는 영역 게이트웨이에 바로 간다(deploy ADR 0070). 아래는 당시 기록이다.

## 무엇이 부족한가
원격 추론 서버(model-runtime)는 기동 때 release-gate 의 `GET /v1/active-pointer`, `/v1/releases/{id}`, `/v1/releases/{id}/bundle` 을 읽는다. 게이트웨이는 이제 이 세 경로를 **추론 서버 기계 토큰**(Bearer)으로만 연다(`config/Caddyfile` `@inferencemachine`, `docs/adr/0049-remote-inference-reads-release-gate-via-gateway.md`).
`Exposure.auth.kind` 는 `device-token | account | none | denied` 뿐이라 이 경로를 선언할 수 없다. 지금 release-gate 라벨은 `/v1/releases/*` 를 `denied` 로 적고 `/v1/active-pointer` 를 operator 계정 전용으로 적는다.

## 제안
1. `auth.kind` 에 `machine-token`(호출하는 서비스가 정해진 기계 토큰, 계정 아님)을 더한다.
2. release-gate 라벨에 `GET /v1/active-pointer`, `GET /v1/releases/*`(번들 포함)를 `machine-token`, `upstream_token: gate-read-model-serving`, `user_header: strip` 으로 적고, `denied` 의 `/v1/releases/*` 는 사람 계정에게 닫힌다는 뜻으로 구분한다(같은 경로가 인증 종류에 따라 다르다).

## 그때까지
deploy 의 `openit_deploy/components/exposure_check.py` 는 `@inferencemachine`, `@inferencedenied` 두 핸들을 라벨 대조에서 제외한다(통과가 아니라 대조하지 않음). 이 경로의 동작은 `scripts/test-inference-location.sh` 가 시험한다. 계약이 바뀌면 제외를 지우고 라벨 대조로 되돌린다.
