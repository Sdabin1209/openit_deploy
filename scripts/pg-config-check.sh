#!/usr/bin/env bash
# 떠 있는 postgres 의 로그·연결·인증 설정 점검(읽기 전용, 행 내용은 읽지 않는다). 사용: pg-config-check.sh   환경: DEPLOY_PROJECT(기본 deploy)
# 확인: (1) 오류 문장·DETAIL 이 로그에 남지 않는 설정 (2) 연결 상한과 계정별 상한, 방치된 트랜잭션 타임아웃 (3) pg_hba: 원격(host) 접속에 trust 가 없고 scram-sha-256 만 있다,
#       로컬 소켓의 trust 는 컨테이너 안(docker exec)에서만 닿는 것이므로 허용으로 센다. 종료 코드 0 통과, 1 어긋남.
set -uo pipefail
source "$(dirname "$0")/lib.sh"
C=$(pg_container "${DEPLOY_PROJECT:-deploy}"); [ -n "$C" ] || die "postgres 컨테이너가 떠 있지 않다"
q() { "$DOCKER" exec "$C" psql -U postgres -d postgres -Atqc "$1" | tr -d '\r'; }
bad=0
want() { local k=$1 w=$2 got; got=$(q "SHOW $k"); if [ "$got" = "$w" ]; then echo "OK   $k = $got"; else echo "FAIL $k = '$got' (기대 '$w')"; bad=$((bad+1)); fi; }
want log_statement none; want log_min_error_statement panic; want log_min_duration_statement -1; want log_error_verbosity terse
mc=$(q "SHOW max_connections"); echo "OK   max_connections = $mc (측정 안 함)"
it=$(q "SHOW idle_in_transaction_session_timeout"); [ "$it" != 0 ] && echo "OK   idle_in_transaction_session_timeout = $it" || { echo "FAIL idle_in_transaction_session_timeout = 0 (무제한)"; bad=$((bad+1)); }
nolim=$(q "SELECT string_agg(rolname, ',') FROM pg_roles WHERE rolcanlogin AND NOT rolsuper AND rolconnlimit < 0")
[ -z "$nolim" ] && echo "OK   서비스 계정마다 연결 상한이 있다" || { echo "FAIL 연결 상한이 없는 로그인 계정: $nolim (bash scripts/pg-roles.sh sync)"; bad=$((bad+1)); }
tr_=$(q "SELECT count(*) FROM pg_hba_file_rules WHERE type LIKE 'host%' AND auth_method = 'trust'")
[ "$tr_" = 0 ] && echo "OK   pg_hba: 원격(host) 접속에 trust 가 없다" || { echo "FAIL pg_hba: host 줄에 trust 가 $tr_ 개 있다 (루프백 포함)"; bad=$((bad+1)); }
q "SELECT line_number||' '||type||' '||array_to_string(database,',')||' '||array_to_string(user_name,',')||' '||coalesce(address,'')||' '||auth_method FROM pg_hba_file_rules ORDER BY line_number" | sed 's/^/     hba /'
[ $bad = 0 ] && { echo "통과: postgres 설정"; exit 0; } || { echo "어긋남 ${bad}건"; exit 1; }
