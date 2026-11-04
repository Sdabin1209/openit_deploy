# 0066. 백업·복구 확인은 BackupJobResult 와 공개 API 까지

- 상태: 채택됨 (계약 v3.4.16~3.4.17, RUNTIME R10.1, DATA_OWNERSHIP 백업 행, 구조 규칙 1·6, 헤드 판단)

## 맥락
예전 E2E 는 pg_dump·docker exec psql·볼륨 복사로 영역 데이터를 직접 읽어 행 지문을 비교했다. 이는 deploy 가 영역 안으로 들어가는 일이다.

## 결정
deploy 는 영역의 backup/restore 잡(io.openit.jobs)을 돌리고 마지막 줄 BackupJobResult(계약 검증)와 공개 API 로 읽은 값까지만 판정한다(`scripts/e2e_backup_jobs.py`, 5p·5pj). DB 행 지문은 쓰지 않는다.

## 왜
DB 행 수준 정합(묶음의 내용·복구)은 데이터 주인 영역의 몫이고 각 영역이 백업→복구 왕복 시험을 rc=0 으로 냈다(R10.1, DATA_OWNERSHIP). deploy 가 같은 것을 다시 직접 읽으면 영역 구조를 알게 된다.

## 검토한 대안과 버리는 이유
행 지문 유지: 구조 규칙 1·6 위반. 영역별 공개 API 추가 요구: 계약 변경이 필요하고 주인 시험이 이미 다룬다.

## 결과
얻는 것: deploy 가 영역 DB 를 모른다. 감수하는 것: 공개 API 로 보이지 않는 행의 보존은 deploy E2E 가 보지 않는다.

## 되돌리는 조건
계약이 영역 데이터 정합을 공개 API 로 노출하라고 정하면 그 값을 판정에 더한다.
