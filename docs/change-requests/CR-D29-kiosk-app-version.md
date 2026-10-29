# CR-D29. kiosk-frontend: `io.openit.app-version`을 영역 빌드 안에서 package.json 버전으로 정한다

- 보내는 곳: deploy (헤드에게)
- 배경: deploy `build-images.sh`는 이전에 kiosk-frontend의 `package.json` version을 직접 읽어 `APP_VERSION` 빌드 인자로 넘겼다. 구조 규칙(영역은 서로의 내부 파일을 읽지 않는다)에 어긋나 deploy는 인자를 넘기지 않게 바꿨다(deploy ADR 0041). 이제 라벨 값은 kiosk Dockerfile의 `ARG APP_VERSION=0.1.0` 기본값이다.
- 문제: 그 기본값이 `package.json`의 version과 어긋나도(앱 버전을 올렸는데 Dockerfile 기본값을 잊는 경우) 라벨이 틀린 채 나간다.
- 요청: 영역 Dockerfile 안에서 `package.json`의 version을 읽어 라벨에 쓰게 한다(예: 빌드 스테이지에서 `node -p "require('./package.json').version"` 결과를 최종 스테이지로 복사해 LABEL에 반영). 또는 영역 시험이 기본값과 package.json의 일치를 확인한다.
- 영향: deploy 쪽 변경 없음(인자를 넘기지 않는다). 라벨 키·값 형식(ImageLabels 확장 `io.openit.app-version`)은 그대로다.
