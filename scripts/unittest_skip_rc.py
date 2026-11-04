"""unittest 시험의 공용 진입점. skipTest 가 하나라도 있으면 종료 코드 77(SKIP)로 끝난다.
왜: unittest 는 skip 이 있어도 rc 0 이라 검증하지 않은 것이 PASS 로 센다. 셸 시험의 77=SKIP(automake 관례)과 같은 규칙으로 맞춘다(run-self-checks.sh 가 77 을 따로 센다).
사용: if __name__ == "__main__": from unittest_skip_rc import main; main()"""
import sys, unittest

SKIP_RC = 77


def main(verbosity=2):
    prog = unittest.main(module="__main__", verbosity=verbosity, exit=False)
    r = prog.result
    if r.failures or r.errors or not r.wasSuccessful(): sys.exit(1)
    if r.skipped:
        print(f"SKIP: skipTest {len(r.skipped)}건: 검증하지 않은 것이 있어 통과로 세지 않는다 (종료 77)", file=sys.stderr)
        sys.exit(SKIP_RC)
    sys.exit(0)
