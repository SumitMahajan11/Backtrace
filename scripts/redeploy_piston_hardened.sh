#!/bin/bash
set -e

echo "=== Stopping backtrace_piston ==="
docker rm -f backtrace_piston 2>/dev/null || true

echo "=== Starting backtrace_piston with custom seccomp profile ==="
docker run -d --name backtrace_piston \
  --restart unless-stopped \
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
  -p 2000:2000 \
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

sleep 3
docker logs backtrace_piston | tail -n 10
curl -s http://localhost:2000/api/v2/runtimes | head -c 120
echo ""
