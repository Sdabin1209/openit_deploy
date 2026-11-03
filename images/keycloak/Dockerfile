# Keycloak "optimized image"(공식 권고: https://www.keycloak.org/server/containers 의 "Building your optimized Keycloak image"): 빌드 때 `kc.sh build` 로 Quarkus 증강을 미리 끝내고 실행은 `start --optimized` 로 한다.
# 왜: 기본 이미지는 시작할 때마다 /opt/keycloak/lib/quarkus 에 다시 빌드한 결과를 써서 읽기 전용 루트를 쓸 수 없다. 미리 빌드하면 런타임에 이미지 안을 쓰지 않는다(ADR 0058).
# 기반 이미지는 locks/images.lock 의 KEYCLOAK_IMAGE(digest 고정)를 build arg 로 받는다. 빌드 옵션은 실행 때의 같은 이름 옵션과 같아야 한다(다르면 Keycloak 이 시작을 거부한다).
ARG KEYCLOAK_BASE
FROM ${KEYCLOAK_BASE}
RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true --http-relative-path=/auth
