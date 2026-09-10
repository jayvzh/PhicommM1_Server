#!/bin/sh
# Phicomm M1 Server 镜像构建脚本
#
# 背景说明:
#   本机 Docker 客户端会从 ~/.docker/config.json 的 "proxies" 段自动把
#   HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:1080 注入到构建容器。
#   而该代理只监听宿主机回环地址,容器内的 127.0.0.1 指向容器自身,
#   因此代理不可达,pip install 会直接失败。
#   这里显式传空值覆盖这些构建参数,让容器绕过代理直连 pip 镜像源。
#
# 用法:
#   ./build.sh                 # 构建 jayvzh/phicomm-m1:latest
#   ./build.sh v1.0.4          # 同时打 v1.0.4 与 latest
#   PUSH=1 ./build.sh v1.0.4   # 构建后推送这两个标签
#   IMAGE=xxx/y ./build.sh     # 自定义镜像名
#
set -e

IMAGE="${IMAGE:-jayvzh/phicomm-m1}"
TAG="$1"

cd "$(dirname "$0")"

# 清空构建期代理,规避容器内 127.0.0.1:1080 不可达的问题
PROXY_ARGS="--build-arg HTTP_PROXY= --build-arg HTTPS_PROXY= \
--build-arg http_proxy= --build-arg https_proxy= \
--build-arg NO_PROXY=localhost,127.0.0.1"

if [ -n "$TAG" ]; then
    TAGS="-t ${IMAGE}:${TAG} -t ${IMAGE}:latest"
else
    TAGS="-t ${IMAGE}:latest"
fi

echo ">>> 构建镜像: ${IMAGE} ${TAG:-(latest)}"
# shellcheck disable=SC2086
docker build --provenance=false --sbom=false $PROXY_ARGS $TAGS .

if [ "${PUSH:-0}" = "1" ]; then
    if [ -n "$TAG" ]; then
        echo ">>> 推送 ${IMAGE}:${TAG}"
        docker push "${IMAGE}:${TAG}"
    fi
    echo ">>> 推送 ${IMAGE}:latest"
    docker push "${IMAGE}:latest"
fi

echo ">>> 完成"
