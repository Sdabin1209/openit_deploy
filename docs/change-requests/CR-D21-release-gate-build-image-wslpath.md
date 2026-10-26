# CR-D21: release-gate `scripts/build_image.sh`가 WSL에서 표준 리눅스 docker와 맞지 않는다

- 상태: 제안 (영향: release-gate 빌드 스크립트)
- 확인: `build_image.sh`는 `DOCKER`가 없으면 `docker.exe`를 우선 고르고, 컨텍스트 경로를 `$(wslpath -w "$ctx" 2>/dev/null || echo "$ctx")`로 바꾼다. WSL에는 `wslpath`가 있으므로 `DOCKER=docker`(리눅스 CLI)로 부르면 윈도 UNC 경로(`\\wsl.localhost\...`)가 리눅스 docker에 넘어가 `path ... not found`로 실패한다. 리눅스 서버(wslpath 없음)에서는 경로가 그대로라 동작한다.
- deploy의 대응: `build-images.sh`가 영역의 `stage_context.sh`로 컨텍스트를 만들고 영역의 Dockerfile로 표준 `docker build`를 직접 한다(`build_image.sh` 호출 없음).
- 요청: `build_image.sh`가 `docker.exe`를 가정하지 않고(표준 `docker`와 `DOCKER` 변수만) 경로 변환도 하지 않게 한다. 그러면 deploy는 다시 이 스크립트를 부를 수 있다.
