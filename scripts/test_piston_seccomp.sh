#!/bin/bash
set -e

echo "=== 1. Creating internal network ==="
docker network create --internal piston_internal_test 2>/dev/null || true

echo "=== 2. Stopping existing test container if any ==="
docker rm -f piston_test 2>/dev/null || true

echo "=== 3. Starting Piston with custom seccomp profile ==="
docker run -d --name piston_test \
  --network piston_internal_test \
  --cap-drop ALL \
  --cap-add SYS_ADMIN \
  --cap-add SYS_CHROOT \
  --cap-add SETUID \
  --cap-add SETGID \
  --cap-add CHOWN \
  --cap-add DAC_OVERRIDE \
  --cap-add FOWNER \
  --cap-add KILL \
  --cap-add SYS_RESOURCE \
  --cap-add SYS_PTRACE \
  --cap-add NET_ADMIN \
  --security-opt seccomp=/mnt/d/Projects/Reverse/docker/piston-seccomp.json \
  --security-opt apparmor=unconfined \
  --cgroupns host \
  --read-only \
  --tmpfs /tmp:exec,mode=1777 \
  --tmpfs /var/local/lib/isolate:exec,mode=1777 \
  --tmpfs /run:exec,mode=755 \
  --tmpfs /piston:exec,mode=755 \
  -v piston_packages:/piston/packages \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  -e PISTON_BIND_ADDRESS=0.0.0.0:2000 \
  -e PISTON_DISABLE_NETWORKING=true \
  --entrypoint /bin/bash ghcr.io/engineer-man/piston:latest -c '
    mkdir -p /sys/fs/cgroup/isolate/init 2>/dev/null || true
    echo 1 > /sys/fs/cgroup/isolate/cgroup.procs 2>/dev/null || true
    echo "+cpuset +cpu +io +memory +pids" > /sys/fs/cgroup/cgroup.subtree_control 2>/dev/null || true
    echo 1 > /sys/fs/cgroup/isolate/init/cgroup.procs 2>/dev/null || true
    echo "+cpuset +memory" > /sys/fs/cgroup/isolate/cgroup.subtree_control 2>/dev/null || true
    chown -R piston:piston /piston
    exec su -- piston -c "ulimit -n 65536 && node /piston_api/src"
  '

echo "=== 4. Waiting for Piston to initialize ==="
sleep 4
docker logs piston_test

echo "=== 5. Testing execution from another container on the same internal network ==="
docker run --rm --network piston_internal_test curlimages/curl:latest -s http://piston_test:2000/api/v2/runtimes | head -c 200
echo ""

echo "=== 6. Testing code execution in Python via Piston ==="
docker run --rm --network piston_internal_test curlimages/curl:latest -s -X POST http://piston_test:2000/api/v2/execute \
  -H "Content-Type: application/json" \
  -d '{"language":"python","version":"3.10.0","files":[{"content":"print(\"SECCOMP_PYTHON_OK\", 40+2)"}]}'
echo ""

echo "=== 6b. Testing code execution in JavaScript via Piston ==="
docker run --rm --network piston_internal_test curlimages/curl:latest -s -X POST http://piston_test:2000/api/v2/execute \
  -H "Content-Type: application/json" \
  -d '{"language":"javascript","version":"18.15.0","files":[{"content":"console.log(\"SECCOMP_NODE_OK\", 100 * 2)"}]}'
echo ""

echo "=== 6c. Testing code execution in Bash via Piston ==="
docker run --rm --network piston_internal_test curlimages/curl:latest -s -X POST http://piston_test:2000/api/v2/execute \
  -H "Content-Type: application/json" \
  -d '{"language":"bash","version":"5.2.0","files":[{"content":"echo SECCOMP_BASH_OK"}]}'
echo ""

echo "=== 6d. Testing that blocked syscalls (e.g. reboot/kexec/swapon/open_by_handle_at) are denied by Seccomp ==="
docker run --rm --network piston_internal_test curlimages/curl:latest -s -X POST http://piston_test:2000/api/v2/execute \
  -H "Content-Type: application/json" \
  -d '{"language":"python","version":"3.10.0","files":[{"content":"import ctypes, os\nlibc = ctypes.CDLL(None)\ntry:\n    res = libc.reboot(0)\n    print(\"REBOOT_RES:\", res)\nexcept Exception as e:\n    print(\"REBOOT_BLOCKED:\", e)"}]}'
echo ""

echo "=== 7. Testing that internal network has ZERO outbound internet access ==="
docker run --rm --network piston_internal_test curlimages/curl:latest --connect-timeout 3 -s https://google.com || echo "SUCCESS: Network is fully isolated (egress blocked at Docker network bridge layer)"

echo "=== 8. Cleanup test container ==="
docker rm -f piston_test
docker network rm piston_internal_test
