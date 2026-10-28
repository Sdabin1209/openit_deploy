#!/usr/bin/env python3
"""bash 스크립트에서 함수가 정의보다 먼저 최상위에서 쓰이는지 정적으로 검사한다(bash -n 은 못 잡는다: 정의 전 호출은 실행 때 command not found).
왜 필요한가: e2e.sh 에서 net_is 가 정의(201행)보다 앞(196행)에서 쓰여 실행 때 깨졌다. 함수 본문 안의 호출은 본문이 실행될 때 정의되어 있으면 되므로 보지 않고, 최상위(함수 밖) 줄만 본다.
한계: 휴리스틱이다. 문자열 안의 같은 단어도 사용으로 센다(오탐 가능, 그때는 이름을 바꾸거나 allow 에 적는다). source 한 파일의 함수는 모르는 것으로 둔다.
사용: test_function_order.py [파일 ...]  (기본 scripts/*.sh)"""
import pathlib, re, sys
DEF = re.compile(r'^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{')
def check(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    defs = {}; depth_fn = False; top = []
    for n, ln in enumerate(lines, 1):
        m = DEF.match(ln)
        if not depth_fn and m:
            defs.setdefault(m.group(1), n)
            # 한 줄 정의(같은 줄에서 닫힘)는 본문 시작이 아니다
            if not re.search(r'\}\s*(#.*)?$', ln): depth_fn = True
            continue
        if depth_fn:
            if re.match(r'^\}', ln): depth_fn = False
            continue
        if ln.lstrip().startswith("#"): continue
        top.append((n, ln))
    bad = []
    for name, dn in defs.items():
        pat = re.compile(r'(?<![A-Za-z0-9_./-])' + re.escape(name) + r'(?![A-Za-z0-9_-])')
        for n, ln in top:
            if n < dn and pat.search(re.sub(r'#.*$', '', ln) if '"' not in ln else ln):
                bad.append(f"{path.name}:{n}: {name} 가 정의({dn}행)보다 앞에서 쓰인다"); break
    return bad
def main(argv):
    files = [pathlib.Path(a) for a in argv] or sorted(pathlib.Path(__file__).resolve().parent.glob("*.sh"))
    bad = [b for f in files for b in check(f)]
    for b in bad: print("  FAIL", b)
    print(f"함수 정의 순서: 파일 {len(files)}개, 위반 {len(bad)}건"); return 1 if bad else 0
if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
