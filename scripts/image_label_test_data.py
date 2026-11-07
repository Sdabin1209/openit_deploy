"""이미지 라벨 시험의 정상 입력 선언. 스키마 사본이 아닌 시험 데이터다."""
import json


def inputs_label(image):
    return json.dumps({"schema_version": 1, "image": image, "read_only_root": True,
                       "exec_absolute_argv": True, "role_env": None,
                       "roles": {"default": {"env_schema": "CommonEnv", "process": {"uid": 10001, "gid": 10001},
                                              "files": [], "writable": [], "capabilities": [], "sysctls": {}}},
                       "jobs": {}})


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--docker-label":
        print("LABEL io.openit.inputs=" + json.dumps(inputs_label(sys.argv[2])))
    else:
        document = json.load(sys.stdin)
        labels = document.get("labels", document)
        labels.setdefault("io.openit.inputs", inputs_label(labels["io.openit.service"]))
        print(json.dumps(document))
