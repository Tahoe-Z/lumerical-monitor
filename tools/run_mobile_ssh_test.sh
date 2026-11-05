#!/usr/bin/env bash
set -euo pipefail

# All host/client keys in this test are generated at runtime outside the repository.
ssh_test_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/lumerical-ssh.XXXXXX")"
ssh_test_pid=''
cleanup() {
  if [[ -n "$ssh_test_pid" ]]; then sudo kill "$ssh_test_pid" 2>/dev/null || true; fi
  rm -rf -- "$ssh_test_root"
}
trap cleanup EXIT
chmod 700 "$ssh_test_root"
mkdir "$ssh_test_root/project"
printf 'synthetic log\n' > "$ssh_test_root/project/sample.txt"
printf '\000\015\012\377\052' > "$ssh_test_root/project/binary.bin"
printf 'outside root\n' > "$ssh_test_root/outside.txt"
ssh-keygen -q -t ed25519 -N '' -C '' -f "$ssh_test_root/client"
ssh-keygen -q -t ed25519 -N '' -C '' -f "$ssh_test_root/host"
cp "$ssh_test_root/client.pub" "$ssh_test_root/authorized_keys"
chmod 600 "$ssh_test_root/authorized_keys"
ssh_test_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("localhost",0)); print(s.getsockname()[1]); s.close()')"
cat > "$ssh_test_root/sshd_config" <<EOF
Port $ssh_test_port
ListenAddress localhost
HostKey $ssh_test_root/host
AuthorizedKeysFile $ssh_test_root/authorized_keys
PidFile $ssh_test_root/sshd.pid
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
UsePAM no
StrictModes no
AllowUsers $(id -un)
Subsystem sftp internal-sftp
LogLevel ERROR
EOF
sudo mkdir -p /run/sshd
sudo /usr/sbin/sshd -D -e -f "$ssh_test_root/sshd_config" &
ssh_test_pid=$!
for attempt in {1..30}; do
  if ssh-keyscan -p "$ssh_test_port" localhost >/dev/null 2>&1; then break; fi
  sleep 0.2
done

export LUM_SSH_INTEGRATION=1
export LUM_SSH_HOST=localhost
export LUM_SSH_PORT="$ssh_test_port"
export LUM_SSH_USER="$(id -un)"
export LUM_SSH_ROOT="$ssh_test_root/project"
export LUM_SSH_PRIVATE_KEY_FILE="$ssh_test_root/client"
export LUM_SSH_FINGERPRINT="$(ssh-keygen -lf "$ssh_test_root/host.pub" -E sha256 | awk '{print $2}')"
cd mobile
flutter test test/ssh_test.dart
