# CR-D21: release-gate `scripts/build_image.sh`가 WSL에서 표준 리눅스 docker와 맞지 않는다

- 상태: 제안 (영향: release-gate 빌드 스크립트)
- 확인: `build_image.sh`는 `DOCKER`가 없으면 `docker.exe`를 우선 고르고, 컨텍스트 경로를 `$(wslpath -w "$ctx" 2>/dev/null || echo "$ctx")`로 바꾼다. WSL에는 `wslpath`가 있으므로 `DOCKER=docker`(리눅스 CLI)로 부르면 윈도 UNC 경로(윈도 UNC 경로)가 리눅스 docker에 넘어가 `path ... not found`로 실패한다. 리눅스 서버(wslpath 없음)에서는 경로가 그대로라 동작한다.
- deploy의 대응: deploy는 어떤 환경에서도 표준 `docker`와 일반 경로만 쓰고 WSL 분기를 두지 않는다. `build-images.sh`는 `DOCKER="$DOCKER"`로 `build_image.sh`를 그대로 부른다.
- 요청(release-gate): `build_image.sh`가 `docker.exe`를 가정하지 않고(표준 `docker`와 `DOCKER` 변수만) 경로 변환(`wslpath -w`)도 하지 않게 한다. **이 수정이 push되기 전에는 WSL/사용자 서버에서 release-gate 이미지 빌드가 위 경로 오류로 실패한다.**
