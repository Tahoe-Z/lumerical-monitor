"""Local OpenSSH transport; previews write a sidecar only on explicit request."""
import base64
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import zlib

RESOURCES = Path(__file__).resolve().parent
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


HERE = Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else RESOURCES


def remote_source():
    """Send the public preview helper as an in-memory module, without installing files remotely."""
    helper = (RESOURCES/'preview_export.py').read_text(encoding='utf-8')
    loader = ("import types as _types, sys as _sys\n"
              "_preview_module = _types.ModuleType('preview_export')\n"
              f"exec({helper!r}, _preview_module.__dict__)\n"
              "_sys.modules['preview_export'] = _preview_module\n")
    return loader + (RESOURCES/'remote_probe.py').read_text(encoding='utf-8')


@dataclass(frozen=True)
class Profile:
    host: str = 'server.example.invalid'
    user: str = 'monitor'
    key: str = '.ssh/id_ed25519'
    port: int = 22
    root: str = '/srv/simulations'

    @classmethod
    def load(cls):
        data = load_settings()
        return cls(**{k:v for k,v in data.items() if k in cls.__dataclass_fields__})


def load_settings():
    """profile.json holds the connection plus optional UI keys such as refresh_seconds."""
    path = HERE/'profile.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    except ValueError:
        data = {}
    return data if isinstance(data,dict) else {}


def save_settings(profile, **extra):
    ssh_command(profile)  # validate before writing
    data = {**load_settings(), **asdict(profile), **extra}
    data['port'] = int(data['port'])
    _write_settings(data)


def update_settings(**extra):
    """Merge UI-only keys (window geometry, last page) without touching the connection fields."""
    _write_settings({**load_settings(), **extra})


def _write_settings(data):
    path = HERE/'profile.json'
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    os.replace(temp,path)


def ssh_command(profile, remote='python3 -'):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*',profile.host):
        raise ValueError('服务器地址格式不正确')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',profile.user):
        raise ValueError('SSH 用户名格式不正确')
    if not 1 <= int(profile.port) <= 65535:
        raise ValueError('SSH 端口范围必须为 1–65535')
    return ['ssh.exe' if os.name=='nt' else 'ssh', '-T', '-o','BatchMode=yes',
            '-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=8','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
            '-p',str(profile.port),'-i',profile.key,'-l',profile.user,profile.host,remote]


# A long-lived session receives the probe as one base64 line, then answers one JSON
# request per line. The remote command is a fixed string; requests travel only as data.
BOOT_CODE = 'import sys,base64;exec(base64.b64decode(sys.stdin.buffer.readline()))'
SERVE_CODE = r'''
import sys as _sys, zlib as _zlib, base64 as _b64
_sys.stdout.write('{"ready": true}\n'); _sys.stdout.flush()
for _line in _sys.stdin.buffer:
    if not _line.strip():
        continue
    try:
        _reply = {'ok': True, 'data': dispatch(json.loads(_line))}
    except Exception as _e:
        _reply = {'ok': False, 'error': str(_e)}
    _text = json.dumps(_reply, ensure_ascii=True)
    if len(_text) > 4096:  # snapshots are repetitive JSON; compress for the slow link
        _text = json.dumps({'z': _b64.b64encode(_zlib.compress(_text.encode(), 6)).decode()})
    _sys.stdout.write(_text+'\n'); _sys.stdout.flush()
'''


def unpack(reply):
    if isinstance(reply, dict) and 'z' in reply:
        return json.loads(zlib.decompress(base64.b64decode(reply['z'])))
    return reply


def session_command(profile):
    return ssh_command(profile, "python3 -u -c '"+BOOT_CODE+"'")


class SessionError(RuntimeError):
    """Transport failure: the session is discarded and may be restarted."""


class Session:
    """One persistent SSH connection; avoids a full handshake for every request."""
    def __init__(self, profile, timeout=35):
        self.profile, self.timeout = profile, timeout
        self.proc = None
        self.stopped = False
        self.lock = threading.Lock()

    def _start(self):
        self.close()
        proc = subprocess.Popen(session_command(self.profile),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,creationflags=NO_WINDOW)
        lines, errors = queue.Queue(), []
        def pump_out():
            try:
                for line in proc.stdout:
                    lines.put(line)
            except (OSError, ValueError):
                pass
            lines.put(None)
        def pump_err():
            try:
                for line in proc.stderr:
                    errors.append(line.decode('utf-8','replace'))
                    del errors[:-20]
            except (OSError, ValueError):
                pass
        threading.Thread(target=pump_out,daemon=True).start()
        threading.Thread(target=pump_err,daemon=True).start()
        self.proc, self.lines, self.errors = proc, lines, errors
        source = remote_source()+'\n'+SERVE_CODE
        try:
            proc.stdin.write(base64.b64encode(source.encode())+b'\n')
            proc.stdin.flush()
        except OSError:
            pass
        reply = self._read()
        if not reply.get('ready'):
            self.close()
            raise SessionError('远端会话未就绪')

    def _read(self):
        try:
            line = self.lines.get(timeout=self.timeout)
        except queue.Empty:
            self.close()
            raise SessionError('SSH 请求超时；检查网络或 Tailscale 连接') from None
        if line is None:
            proc = self.proc
            code = proc.wait() if proc else '已关闭'
            message = ''.join(self.errors).strip() or f'SSH 退出码 {code}'
            self.close()
            raise SessionError(message)
        try:
            return unpack(json.loads(line))
        except ValueError:
            self.close()
            raise SessionError('远端响应不是有效 JSON，请检查 SSH 登录脚本的额外输出') from None

    def request(self, payload):
        with self.lock:
            for attempt in (0, 1):
                if self.stopped:
                    raise SessionError('程序正在退出，SSH 会话已关闭')
                fresh = self.proc is None or self.proc.poll() is not None
                if fresh:
                    self._start()
                proc = self.proc  # close() from the UI thread may clear self.proc at any moment
                try:
                    if proc is None:
                        raise SessionError('SSH 会话已关闭')
                    proc.stdin.write(json.dumps(payload).encode()+b'\n')
                    proc.stdin.flush()
                    return self._read()
                except (OSError, SessionError):
                    self.close()
                    if fresh or attempt:
                        raise
                    # An idle connection may have been dropped; retry once on a new one.
            raise SessionError('SSH 会话不可用')

    def shutdown(self):
        """Final close: later requests fail fast instead of reconnecting."""
        self.stopped = True
        self.close()

    def close(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass


def remote_script(request):
    source = remote_source()
    payload = base64.b64encode(json.dumps(request).encode()).decode()
    return source+'\nimport base64\nmain(json.loads(base64.b64decode("'+payload+'")))\n'


class Client:
    def __init__(self, profile=None, persistent=True):
        self.profile = profile or Profile.load()
        self.session = Session(self.profile) if persistent else None

    def request(self, op, path='.', **options):
        if self.session:
            try:
                envelope = self.session.request({**options,'op':op,'root':self.profile.root,'path':path})
            except OSError as e:
                raise RuntimeError(f'无法启动 ssh：{e}') from e
            if not envelope.get('ok'):
                raise RuntimeError(envelope.get('error','远端读取失败'))
            return envelope['data']
        return self.request_once(op, path, **options)

    def close(self):
        if self.session:
            self.session.shutdown()

    def prepare_preview(self, path, *, wavelength_m=1.55e-6, z_m=0, cancel=None):
        """Explicit licensed analysis in a separate SSH connection; writes only a preview sidecar."""
        from preview_export import REPLY_MARKER
        cancel = cancel or threading.Event()
        request = {'root': self.profile.root, 'path': path, 'wavelength_m': wavelength_m, 'z_m': z_m}
        payload = base64.b64encode(json.dumps(request).encode()).decode('ascii')
        helper = (RESOURCES/'preview_export.py').read_text(encoding='utf-8')
        script = ("import json,base64\n_ns={'__name__':'preview_tool'}\n"
                  f"_source={helper!r}\nexec(_source,_ns)\n_ns['emit'](json.loads(base64.b64decode('{payload}')),source=_source)\n")
        process = subprocess.Popen(ssh_command(self.profile), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        finished = threading.Event()
        def watch():
            while not finished.wait(.2):
                if cancel.is_set():
                    process.kill()
                    return
        threading.Thread(target=watch,daemon=True).start()
        try:
            stdout, stderr = process.communicate(script.encode('utf-8'), timeout=180)
            if cancel.is_set():
                raise RuntimeError('预览生成已取消')
            if process.returncode:
                raise RuntimeError('预览连接中断，导出可能已完成；请点击“读取缓存”重试')
            marker = next((line[len(REPLY_MARKER):] for line in stdout.decode('utf-8','replace').splitlines()[::-1]
                           if line.startswith(REPLY_MARKER)), None)
            if marker is None:
                raise RuntimeError('预览导出器未返回有效数据；请检查远端 lumapi、NumPy 和许可证配置')
            try:
                reply = json.loads(zlib.decompress(base64.b64decode(marker, validate=True)))
            except (ValueError, zlib.error):
                raise RuntimeError('预览响应不完整；请点击“读取缓存”重试') from None
            if not isinstance(reply, dict):
                raise RuntimeError('预览响应格式无效；请点击“读取缓存”重试')
            if not reply.get('ok'):
                raise RuntimeError(reply.get('error','预览生成失败'))
            return reply['data']
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError('预览生成超过 180 秒；请在已有仿真会话中导出预览') from None
        finally:
            finished.set()

    def request_once(self, op, path='.', **options):
        script = remote_script({**options,'op':op,'root':self.profile.root,'path':path})
        try:
            r = subprocess.run(ssh_command(self.profile),input=script.encode(),stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,timeout=35,creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError('SSH 请求超时；检查网络或 Tailscale 连接') from e
        if r.returncode:
            raise RuntimeError(r.stderr.decode('utf-8','replace').strip() or f'SSH 退出码 {r.returncode}')
        try:
            envelope = json.loads(r.stdout)
        except ValueError as e:
            raise RuntimeError('远端响应不是有效 JSON，请检查 SSH 登录脚本的额外输出') from e
        if not envelope.get('ok'):
            raise RuntimeError(envelope.get('error','远端读取失败'))
        return envelope['data']

    def download(self, relative, destination, progress=None, cancel=None):
        """Download into a private local .part file, then atomically replace destination."""
        cancel = cancel or threading.Event()
        dest = Path(destination)
        fd, temp = tempfile.mkstemp(prefix=dest.name+'.',suffix='.part',dir=dest.parent)
        p = None
        error_file = tempfile.TemporaryFile()
        timer = None
        timed_out = threading.Event()
        try:
            p = subprocess.Popen(ssh_command(self.profile),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                 stderr=error_file,creationflags=NO_WINDOW)
            def timeout():
                timed_out.set()
                p.kill()
            timer = threading.Timer(60,timeout)  # header/handshake only; data stream has keepalives
            timer.daemon = True
            timer.start()
            def watch_cancel():
                while p.poll() is None:
                    if cancel.wait(.2):
                        p.kill()
                        return
            threading.Thread(target=watch_cancel,daemon=True).start()
            # Cancellation/watchdog must already be active while writing stdin:
            # an SSH connection can stall before it consumes the probe script.
            p.stdin.write(remote_script({'op':'download','root':self.profile.root,'path':relative}).encode())
            p.stdin.close()
            header = p.stdout.readline(4096)
            timer.cancel()
            try:
                info = json.loads(header)
                total = int(info['size'])
                if total < 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError) as e:
                raise RuntimeError('无法读取下载信息；文件可能不可读或超出项目目录') from e
            received = 0
            with os.fdopen(fd,'wb') as out:
                fd = None
                while received < total:
                    block = p.stdout.read(min(1024*1024,total-received))
                    if not block:
                        break
                    out.write(block)
                    received += len(block)
                    if progress:
                        progress(received,total)
            rc = p.wait()
            error_file.seek(0)
            error = error_file.read().decode('utf-8','replace')
            if cancel.is_set():
                raise RuntimeError('已取消下载')
            if timed_out.is_set():
                raise RuntimeError('下载连接超时')
            if rc or received != total:
                raise RuntimeError(error.strip() or '下载未完成；本地原文件未更改')
            os.replace(temp,dest)
            return received
        except Exception as e:
            if cancel.is_set():
                raise RuntimeError('已取消下载') from e
            if timed_out.is_set():
                raise RuntimeError('下载连接超时') from e
            raise
        finally:
            if timer:
                timer.cancel()
            if p and p.poll() is None:
                p.kill()
                p.wait()
            if p and p.stdout:
                p.stdout.close()
            if p and p.stdin and not p.stdin.closed:
                try:
                    p.stdin.close()
                except OSError:
                    pass
            if fd is not None:
                os.close(fd)
            error_file.close()
            Path(temp).unlink(missing_ok=True)
