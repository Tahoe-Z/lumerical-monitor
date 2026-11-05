"""Stateless read-only Linux probe, streamed to python3 over SSH."""
import datetime
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import time

MAX_READ = 256 * 1024


def gpu_number(text):
    try:
        value=float(text.strip())
        return value if math.isfinite(value) and value>=0 else None
    except ValueError:
        return None


def parse_gpus(text):
    devices=[]
    for row in csv.reader(io.StringIO(text),skipinitialspace=True):
        if not row:
            continue
        if len(row)!=9:
            raise ValueError('GPU 返回字段数量不正确')
        index,name,uuid,util,used,total,temp,power,limit=[x.strip() for x in row]
        used,total=gpu_number(used),gpu_number(total)
        devices.append({'index':int(index),'name':name,'uuid':uuid,
                        'utilization_percent':gpu_number(util),
                        'memory_used_bytes':used*1024**2 if used is not None else None,
                        'memory_total_bytes':total*1024**2 if total is not None else None,
                        'temperature_c':gpu_number(temp),'power_watts':gpu_number(power),
                        'power_limit_watts':gpu_number(limit)})
    return devices


def process_owner(pid):
    try:
        import pwd
        uid=Path('/proc',str(pid)).stat().st_uid
        try:
            name=pwd.getpwuid(uid).pw_name
        except KeyError:
            name=str(uid)
        return {'uid':uid,'user':name,'mine':uid==os.getuid()}
    except OSError:
        return {'uid':None,'user':'未知/不可见','mine':False}


def parse_gpu_processes(text):
    rows=[]
    for row in csv.reader(io.StringIO(text),skipinitialspace=True):
        if len(row)!=4:
            continue
        uuid,pid,name,memory=[x.strip() for x in row]
        if not pid.isdigit():
            continue
        value=gpu_number(memory)
        owner=process_owner(int(pid))
        rows.append({'uuid':uuid,'pid':int(pid),'name':Path(name).name,**owner,
                     'memory_bytes':value*1024**2 if value is not None else None})
    return rows


def gpu_snapshot():
    result={'available':False,'devices':[],'processes':[],'error':'','process_error':''}
    executable=shutil.which('nvidia-smi')
    if not executable:
        result['error']='未找到 nvidia-smi；未检测到可查询的 NVIDIA 驱动'
        return result
    env=dict(os.environ,LC_ALL='C')
    try:
        query='index,name,uuid,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit'
        r=subprocess.run([executable,'--query-gpu='+query,'--format=csv,noheader,nounits'],
                         capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=4,env=env)
        if r.returncode:
            raise ValueError((r.stderr or r.stdout).strip()[:400] or 'GPU 查询失败')
        result['devices']=parse_gpus(r.stdout)
        result['available']=True
    except (OSError,ValueError,subprocess.TimeoutExpired) as e:
        result['error']=str(e)
        return result
    try:
        r=subprocess.run([executable,'--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory','--format=csv,noheader,nounits'],
                         capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=4,env=env)
        if r.returncode:
            raise ValueError((r.stderr or r.stdout).strip()[:400] or 'GPU 计算进程查询失败')
        result['processes']=parse_gpu_processes(r.stdout)
    except (OSError,ValueError,subprocess.TimeoutExpired) as e:
        result['process_error']=str(e)
    return result

def project_path(root, relative):
    root = Path(root).resolve(strict=True)
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('路径超出项目目录（包括符号链接）')
    if not path.exists():
        raise FileNotFoundError('项目路径不存在')
    return path


def open_regular(path):
    if Path(path).is_dir():
        raise ValueError('只允许读取普通文件')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
    handle = os.fdopen(fd, 'rb')
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        handle.close()
        raise ValueError('只允许读取普通文件')
    return handle


def tail_file(path, limit=MAX_READ, lines=500):
    with open_regular(path) as f:
        size = os.fstat(f.fileno()).st_size
        f.seek(max(0, size-limit))
        data = f.read(limit)
    text = data.decode('utf-8', errors='replace')
    parts = text.splitlines()
    return {'text': '\n'.join(parts[-lines:]), 'size': size,
            'truncated': size > limit or len(parts) > lines}


def small_text(path, limit=32768):
    try:
        # Job metadata must not follow a link out of its own directory.
        path = project_path(path.parent, path)
        return tail_file(path, limit=limit, lines=1000)['text']
    except (OSError, ValueError):
        return ''


def job_state(path, running):
    if running:
        return {'state': '运行中'}
    code = small_text(path/'service-exit-code.txt').strip()
    failure = small_text(path/'failure.txt')
    try:
        exits = json.loads(small_text(path/'exit_codes.json') or '{}')
        bad_exit = any(v != 0 for v in exits.values())
    except (ValueError, AttributeError):
        bad_exit = False
    if failure or bad_exit or (code and code != '0'):
        return {'state': '失败'}
    logs = list(path.glob('*_p0.log'))[:5]
    completed = any('Simulation completed successfully' in small_text(p) for p in logs)
    if code == '0' and completed:
        result = small_text(path/'result.json') or small_text(path/'validation.json')
        try:
            result = json.loads(result or '{}')
            if result.get('trial_pass') is False or result.get('physics_and_status_pass') is False:
                return {'state': '需检查结果'}
        except ValueError:
            return {'state': '需检查结果'}
        return {'state': '已完成'}
    return {'state': '未知/未完成'}


def cpu_ticks():
    values = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3]+values[4]


def parse_process_stat(text,uptime,hz):
    fields=text.rsplit(')',1)[1].split()
    elapsed=max(.01,uptime-float(fields[19])/hz)
    return {'elapsed_seconds':elapsed,
            'cpu_average_percent':(int(fields[11])+int(fields[12]))/hz/elapsed*100}


def process_ticks():
    """CPU ticks (utime+stime) per visible PID, sampled for instantaneous usage."""
    ticks={}
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            try:
                fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                ticks[int(entry.name)]=int(fields[11])+int(fields[12])
            except (OSError, ValueError, IndexError):
                pass
    return ticks


def process_inventory(root, before=None, started=None):
    rows,owned = [],[]
    unreadable=0
    users={}
    hz = os.sysconf('SC_CLK_TCK')
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            owner=process_owner(int(entry.name))
            name = (entry/'comm').read_text().strip()
            text=(entry/'stat').read_text()
            usage=parse_process_stat(text,uptime,hz)
            usage['cpu_percent']=None
            if before is not None and int(entry.name) in before:
                fields=text.rsplit(')',1)[1].split()
                wall=max(.05,time.monotonic()-started)
                usage['cpu_percent']=max(0.,(int(fields[11])+int(fields[12])-before[int(entry.name)])/hz/wall*100)
            info = (entry/'status').read_text()
            rss = re.search(r'^VmRSS:\s+(\d+)', info, re.M)
            threads = re.search(r'^Threads:\s+(\d+)', info, re.M)
            row={'pid':int(entry.name),'name':name,**owner,**usage,
                         'rss_bytes': int(rss[1])*1024 if rss else 0,
                         'threads': int(threads[1]) if threads else 0}
            rows.append(row)
            agg=users.setdefault(owner['user'],{'user':owner['user'],'mine':owner['mine'],'processes':0,
                                                'cpu_percent':0.,'rss_bytes':0,'threads':0})
            agg['processes']+=1
            agg['cpu_percent']+=usage['cpu_percent'] or 0
            agg['rss_bytes']+=row['rss_bytes']
            agg['threads']+=row['threads']
            # Read command line/CWD only for our own Lumerical engines, CAD sessions and drivers.
            if owner['mine'] and LUM_COMM.search(name):
                try:
                    argv=[a.decode('utf-8','replace') for a in (entry/'cmdline').read_bytes().split(b'\0') if a]
                    cwd=(entry/'cwd').resolve()
                    try:
                        exe=os.path.basename(os.readlink(entry/'exe'))
                    except OSError:
                        exe=name
                    kind,solver=classify_process(exe)
                    if kind=='python' and not cwd.is_relative_to(root):
                        continue
                    owned.append({**row,'command':' '.join(argv)[:2000],'argv':argv[:60],'cwd':str(cwd),'exe':exe,
                                  'kind':kind,'solver':solver,'ppid':int(text.rsplit(')',1)[1].split()[1])})
                except (OSError, ValueError, IndexError):
                    pass
        except (OSError, ValueError, IndexError):
            unreadable+=1
            continue
    rows.sort(key=lambda x:(x['cpu_percent'] or 0,x['cpu_average_percent'],x['rss_bytes']),reverse=True)
    return {'all':rows[:300],'owned_project':owned,'visible_count':len(rows),
            'unreadable':unreadable,'truncated':len(rows)>300,
            'users':sorted(users.values(),key=lambda x:(x['cpu_percent'],x['rss_bytes']),reverse=True)}


# ------------------------------------------------------------------ Lumerical runs
# Engine executables (checked in order, by prefix) and the solver each one runs.
LUM_ENGINES = [('varfdtd-engine', 'varFDTD'), ('fdtd-engine', 'FDTD'), ('eme-engine', 'EME'), ('fd-engine', 'FDE'),
               ('dgtd-engine', 'DGTD'), ('feem-engine', 'FEEM'), ('device-engine', 'CHARGE'), ('thermal-engine', 'HEAT'),
               ('mqw-engine', 'MQW'), ('rcwa-engine', 'RCWA')]
LUM_CAD = [('fdtd-solutions', 'FDTD'), ('mode-solutions', 'MODE'), ('device', 'DEVICE'), ('interconnect', 'INTERCONNECT')]
LUM_COMM = re.compile(r'engine|solutions|^device|interconnect|^python|^mpirun|^mpiexec|^hydra')
PROJECT_TYPES = {'.fsp': 'FDTD', '.lms': 'MODE', '.ldev': 'DEVICE', '.icp': 'INTERCONNECT'}
SOLVER_WORDS = r'varFDTD|FDTD|EME|FDE|CHARGE|HEAT|DGTD|FEEM|MQW|RCWA'
ERROR_RE = re.compile(r'\bERROR\b|\bError:|Segmentation fault|\bKilled\b|terminate called|core dumped|'
                      r'(?i:license\S*\s[^\n]*(?:fail|denied|unavailable))')
STATUS_TEXT = {'UPDATE_MODES': '更新模式', 'MESH_START': '网格划分', 'MESH_FINISH': '网格完成',
               'BUILD_SOURCES_START': '构建光源', 'BUILD_SOURCES_FINISH': '光源完成',
               'WRITE_START': '写出结果', 'WRITE_FINISH': '写出完成'}
SKIP_DIRS = {'home', 'cache', 'config', '__pycache__', 'node_modules', 'site-packages', 'venv'}
STALL_SECONDS = 20*60
_SCAN_CACHE = {}
_PARSE_CACHE = {}


def classify_process(exe):
    for prefix, solver in LUM_ENGINES:
        if exe.startswith(prefix):
            return 'engine', solver
    for prefix, product in LUM_CAD:
        if exe.startswith(prefix):
            return 'cad', product
    if exe.startswith('python'):
        return 'python', None
    if exe.startswith(('mpirun', 'mpiexec', 'hydra')):
        return 'mpi', None
    return 'other', None


def read_head_tail(path, head=4096, tail=65536):
    with open_regular(path) as f:
        size = os.fstat(f.fileno()).st_size
        if size <= head+tail:
            return f.read().decode('utf-8', 'replace')
        first = f.read(head)
        f.seek(size-tail)
        return (first+b'\n'+f.read()).decode('utf-8', 'replace')


def number(text):
    try:
        value = float(text)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def parse_engine_log(text):
    """Lumerical -remote XML protocol (shared by the solver engines): columns, updates, status, completion."""
    columns = {tag: title for title, tag in re.findall(
        r'<column><title>([^<]*)</title>(?:<type>[^<]*</type>)?<tagname>([^<]*)</tagname></column>', text)}
    updates = [dict(re.findall(r'<(\w+)>([^<]*)</\1>', u)) for u in re.findall(r'<update>(.*?)</update>', text, re.S)]
    statuses = re.findall(r'<status>([^<]*)</status>', text)
    solving = [u for u in updates if len(u) > 1] or updates
    last = solving[-1] if solving else {}
    series_tag = 'shutoff' if any('shutoff' in u for u in updates) else next(
        (t for t in columns if t != 'progress' and any(number(u.get(t)) is not None for u in updates)), None)
    errors = re.findall(r'<error>([^<]*)</error>', text)+[l.strip() for l in text.splitlines()
                                                          if not l.lstrip().startswith('<') and ERROR_RE.search(l)]
    return {'progress': number(last.get('progress')),
            'remaining': last.get('time', ''),
            'metrics': {columns.get(k, k): v for k, v in last.items() if k != 'progress'},
            'series_title': columns.get(series_tag, series_tag) if series_tag else '',
            'series': [v for v in (number(u.get(series_tag)) for u in updates) if v is not None][-120:] if series_tag else [],
            'shutoff': last.get('shutoff', ''),
            'stage': statuses[-1] if statuses else '',
            'complete': '<simComplete/>' in text or '<complete/>' in text,
            'errors': errors[-3:]}


def parse_solver_log(text):
    """Process-0 text log (*_p0.log): solver banner, progress, ETA, shutoff, completion and errors."""
    banner = re.search(r'Lumerical[^\n]*?\b(' + SOLVER_WORDS + r')\b', text)
    progress = re.findall(r'([\d.]+)% complete', text)
    shutoff = re.findall(r'Auto Shutoff:\s*([\deE.+-]+)', text)
    remaining = re.findall(r'Max time remaining:\s*([^.\n]+)', text)
    speed = re.findall(r'(?:loop runs at|solver speed on \d+ processes \(Mnodes/s\)):?\s*([\d.]+)', text)
    memory = re.search(r'Estimate of memory required:\s*([\d.]+\s*\w+)', text)
    grid = re.search(r'Simulation size in gridpoints:\s*([^\n]+)', text)
    cuda = re.search(r'CUDA_VISIBLE_DEVICES=(\S+)', text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return {'solver': banner[1] if banner else '',
            'progress': number(progress[-1]) if progress else None,
            'remaining': remaining[-1].strip() if remaining else '',
            'shutoff': shutoff[-1] if shutoff else '',
            'series': [v for v in map(number, shutoff[-120:]) if v is not None],
            'speed': number(speed[-1]) if speed else None,
            'memory_estimate': memory[1] if memory else '',
            'grid': grid[1].strip() if grid else '',
            'cuda': cuda[1] if cuda else '',
            'complete': 'completed successfully' in text.lower(),
            'errors': [l for l in lines if ERROR_RE.search(l)][-3:],
            'last_line': lines[-1][:200] if lines else ''}


def parsed_log(path, parser):
    """Parse a log, reusing the previous result while its size and mtime are unchanged."""
    try:
        info = path.stat()
    except OSError:
        return None
    key = (info.st_mtime_ns, info.st_size)
    cached = _PARSE_CACHE.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    try:
        result = {**parser(read_head_tail(path)), 'mtime': info.st_mtime}
    except (OSError, ValueError):
        return None
    _PARSE_CACHE[str(path)] = (key, result)
    return result


def scan_run_files(root, days=14, max_dirs=5000, max_depth=8, budget=1.5):
    """Bounded walk of the project tree for recent Lumerical logs/projects; cached for a minute per session."""
    cached = _SCAN_CACHE.get(str(root))
    if cached and time.monotonic()-cached[0] < 60:
        return cached[1]
    started, horizon = time.monotonic(), time.time()-days*86400
    found, stack, visited = {}, [(str(root), 0)], 0
    while stack and visited < max_dirs and time.monotonic()-started < budget:
        folder, depth = stack.pop()
        visited += 1
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    if depth < max_depth and e.name not in SKIP_DIRS and not e.name.startswith('.'):
                        stack.append((e.path, depth+1))
                    continue
                m = re.fullmatch(r'(.+)_(p0|engine)\.log', e.name)
                stem, ext = os.path.splitext(e.name)
                if m:
                    stem, kind = m[1], m[2]
                elif ext.lower() in PROJECT_TYPES:
                    kind = 'project'
                else:
                    continue
                mtime = e.stat().st_mtime
            except OSError:
                continue
            record = found.setdefault((folder, stem), {'dir': folder, 'stem': stem, 'files': {}, 'mtime': 0})
            record['files'][kind] = e.path
            if kind != 'project':
                record['mtime'] = max(record['mtime'], mtime)
    runs = {k: v for k, v in found.items() if v['mtime'] >= horizon and ('p0' in v['files'] or 'engine' in v['files'])}
    data = {'runs': runs, 'dirs': visited, 'truncated': bool(stack)}
    _SCAN_CACHE[str(root)] = (time.monotonic(), data)
    return data


def project_argument(proc):
    for arg in reversed(proc['argv'][1:]):
        if os.path.splitext(arg)[1].lower() in PROJECT_TYPES:
            return os.path.realpath(os.path.join(proc['cwd'], arg))
    return None


def driver_of(proc, by_pid):
    """Walk up the parent chain to the Python/lumapi script that launched this engine."""
    seen, current = 0, by_pid.get(proc['ppid'])
    while current and seen < 6:
        if current['kind'] == 'python':
            return ' '.join(os.path.basename(a) if i == 0 else a for i, a in enumerate(current['argv']))[:240]
        current, seen = by_pid.get(current['ppid']), seen+1
    return ''


def lumerical_runs(root, owned, gpu=None, limit=60):
    """Running engines (from processes) merged with recent runs found on disk, one record per project file."""
    gpu = gpu or {}
    gpu_index = {d['uuid']: d['index'] for d in gpu.get('devices', [])}
    gpu_by_pid = {}
    for p in gpu.get('processes', []):
        gpu_by_pid.setdefault(p['pid'], []).append((gpu_index.get(p['uuid']), p['memory_bytes'] or 0))
    by_pid = {p['pid']: p for p in owned}
    runs = {}

    def record(key, folder, stem):
        return runs.setdefault(key, {'key': key, 'dir': folder, 'stem': stem, 'pids': [], 'cpu_percent': 0., 'rss_bytes': 0,
                                     'threads': 0, 'elapsed_seconds': 0, 'gpus': [], 'gpu_memory': 0, 'flags': [],
                                     'engine': '', 'solver': '', 'driver': '', 'files': {}})

    for p in owned:
        if p['kind'] != 'engine':
            continue
        project = project_argument(p)
        folder, stem = (os.path.dirname(project), os.path.splitext(os.path.basename(project))[0]) if project else (p['cwd'], '')
        r = record(project or f'pid:{p["pid"]}', folder, stem)
        r['pids'].append(p['pid'])
        r['cpu_percent'] += p.get('cpu_percent') or 0
        r['rss_bytes'] += p['rss_bytes']
        r['threads'] += p['threads']
        r['elapsed_seconds'] = max(r['elapsed_seconds'], p['elapsed_seconds'])
        r['engine'], r['solver'] = p['exe'], p['solver']
        argv = p['argv']
        if '-gpu' in argv and 'GPU' not in r['flags']:
            r['flags'].append('GPU')
        if '-t' in argv[:-1]:
            r['flags'].append(f'{argv[argv.index("-t")+1]} 线程')
        if re.search(r'impi|ompi|mpich', p['exe']) or by_pid.get(p['ppid'], {}).get('kind') == 'mpi':
            r['flags'].append('MPI')
        for index, memory in gpu_by_pid.get(p['pid'], []):
            if index not in r['gpus']:
                r['gpus'].append(index)
            r['gpu_memory'] += memory
        r['driver'] = r['driver'] or driver_of(p, by_pid)
        if project:
            r['files']['project'] = project
            for kind, suffix in (('p0', '_p0.log'), ('engine', '_engine.log')):
                if os.path.isfile(os.path.join(folder, stem+suffix)):
                    r['files'][kind] = os.path.join(folder, stem+suffix)

    scan = scan_run_files(root)
    for (folder, stem), found in scan['runs'].items():
        project = found['files'].get('project')
        key = os.path.realpath(project) if project else os.path.join(folder, stem)
        r = record(key, folder, stem)
        r['seen'] = found['mtime']
        for kind, path in found['files'].items():
            r['files'].setdefault(kind, path)

    rows = []
    now = time.time()
    root_text = str(root)
    # Parse logs only for what will be shown: every running run plus the most recent others.
    ordered = sorted(runs.values(), key=lambda r: (bool(r['pids']), r.get('seen', now)), reverse=True)
    keep = sum(bool(r['pids']) for r in ordered)
    for r in ordered[:max(limit, keep)]:
        inside = Path(r['dir']).is_relative_to(root)
        p0 = parsed_log(Path(r['files']['p0']), parse_solver_log) if inside and 'p0' in r['files'] else None
        xml = parsed_log(Path(r['files']['engine']), parse_engine_log) if inside and 'engine' in r['files'] else None
        p0, xml = p0 or {}, xml or {}
        running = bool(r['pids'])
        project = r['files'].get('project', '')
        solver = r['solver'] or p0.get('solver') or PROJECT_TYPES.get(os.path.splitext(project)[1].lower(), '')
        errors = xml.get('errors') or p0.get('errors') or []
        complete = xml.get('complete') or p0.get('complete')
        state = '运行中' if running else '已完成' if complete and not errors else '失败' if errors else '未知/未完成'
        log_mtime = max(xml.get('mtime', 0), p0.get('mtime', 0))
        progress = xml.get('progress') if xml.get('progress') is not None else p0.get('progress')
        series = [float(f'{v:.4g}') for v in (xml.get('series') or p0.get('series') or [])][-(120 if running else 40):]
        relative = lambda path: os.path.relpath(path, root_text) if inside and path else ''
        display = relative(project) or relative(os.path.join(r['dir'], r['stem'])) or r['key']
        rows.append({'kind': 'run', 'path': display, 'name': r['stem'] or os.path.basename(r['dir']),
                     'dir': relative(r['dir']) if inside else None, 'solver': solver, 'engine': r['engine'],
                     'state': state, 'pids': r['pids'], 'flags': r['flags'], 'driver': r['driver'],
                     'progress': 100.0 if state == '已完成' and progress is None else progress,
                     'remaining': (xml.get('remaining') or p0.get('remaining')) if running else '',
                     'shutoff': xml.get('shutoff') or p0.get('shutoff', ''),
                     'shutoff_history': series, 'series_title': xml.get('series_title') or ('Auto Shutoff' if series else ''),
                     'stage': STATUS_TEXT.get(xml.get('stage', ''), xml.get('stage', '')),
                     'metrics': xml.get('metrics', {}), 'errors': errors,
                     'speed': p0.get('speed'), 'memory_estimate': p0.get('memory_estimate', ''), 'grid': p0.get('grid', ''),
                     'last_line': p0.get('last_line', ''),
                     'stalled': running and log_mtime > 0 and now-log_mtime > STALL_SECONDS,
                     'log': relative(r['files'].get('p0', '')), 'engine_log': relative(r['files'].get('engine', '')),
                     'resources': {'cpu_percent': r['cpu_percent'], 'rss_bytes': r['rss_bytes'], 'threads': r['threads'],
                                   'elapsed_seconds': r['elapsed_seconds'], 'gpus': r['gpus'], 'gpu_memory': r['gpu_memory']},
                     'mesh_accuracy': '', 'total_transmission': None, 'loss_db': None,
                     'mtime': log_mtime or now})
    rows.sort(key=lambda x: (x['state'] == '运行中', x['mtime']), reverse=True)
    running_rows = [x for x in rows if x['state'] == '运行中']
    return running_rows+[x for x in rows if x['state'] != '运行中'][:max(0, limit-len(running_rows))], \
        {'dirs': scan['dirs'], 'truncated': scan['truncated']}


def jobs(root, procs, runs=()):
    """Pipeline job directories (commands.json / service.log), enriched with any Lumerical run inside them."""
    rows = []
    # Bounded two-level discovery; no walking HOME, config or cache trees.
    first = sorted([p for p in root.iterdir() if p.is_dir() and not p.is_symlink()],
                   key=lambda p: p.stat().st_mtime, reverse=True)[:120]
    candidates = list(first)
    for p in first:
        candidates.extend(q for q in p.iterdir()
                          if q.is_dir() and not q.is_symlink() and q.name.startswith('attempt-'))
    for p in candidates[:240]:
        if not ((p/'commands.json').exists() or (p/'service.log').exists()):
            continue
        rel = str(p.relative_to(root))
        inner = [r for r in runs if r.get('dir') == rel]
        running = [x['pid'] for x in procs if x['cwd'] == str(p)]+[pid for r in inner for pid in r['pids']]
        logs = sorted(list(p.glob('*_p0.log'))[:5], key=lambda x:x.stat().st_mtime, reverse=True)
        p0 = (parsed_log(logs[0], parse_solver_log) if logs else None) or {}
        xml = next((parsed_log(q, parse_engine_log) for q in [p/'solve.log', *p.glob('*_engine.log')] if q.is_file()), None) or {}
        result = {}
        try:
            result = json.loads(small_text(p/'result.json') or '{}')
        except ValueError:
            pass
        log = logs[0] if logs else (p/'service.log' if (p/'service.log').is_file() else None)
        base = inner[0] if inner else {}
        series = xml.get('series') or p0.get('series') or []
        rows.append({**base, 'kind': 'pipeline', 'path': rel, 'name': p.name, 'dir': rel,
                     'solver': base.get('solver') or p0.get('solver') or 'FDTD',
                     'log': str(log.relative_to(root)) if log else '',
                     'state': job_state(p, bool(running))['state'], 'pids': running,
                     'progress': xml.get('progress') if xml.get('progress') is not None else p0.get('progress'),
                     'shutoff': xml.get('shutoff') or p0.get('shutoff', ''),
                     'shutoff_history': series, 'series_title': xml.get('series_title') or ('Auto Shutoff' if series else ''),
                     'remaining': (xml.get('remaining') or p0.get('remaining', '')) if running else '',
                     'mesh_accuracy': result.get('mesh_accuracy', small_text(p/'mesh_accuracy.txt').strip()),
                     'total_transmission': result.get('Tsum_TE0'),
                     'loss_db': result.get('excess_loss_dB'),
                     'mtime': max([p.stat().st_mtime]+[q.stat().st_mtime for q in logs])})
    return rows


# ------------------------------------------------------------------ licenses (FlexLM, read-only query)
LICENSE_FEATURES = re.compile(r'^(lumerical|lum_|ema_|anshpc|ansys_hpc|fdtd|mode|interconnect)', re.I)
_LICENSE_CACHE = {}


def find_lmutil():
    candidates = [Path.home()/'ansys_inc/shared_files/licensing/linx64/lmutil',
                  Path('/ansys_inc/shared_files/licensing/linx64/lmutil'),
                  Path('/usr/ansys_inc/shared_files/licensing/linx64/lmutil')]
    found = next((str(p) for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)
    return found or shutil.which('lmutil')


def parse_lmstat(text):
    """Server/daemon state, per-feature seat counts and the checkouts of features that are in use."""
    server_up = bool(re.search(r'license server UP', text))
    daemons = dict(re.findall(r'^\s*(\w+):\s+(UP|DOWN)\b', text, re.M))
    features, current = [], None
    for line in text.splitlines():
        m = re.match(r'Users of ([^:]+):\s+\(Total of (\d+) licenses? issued;\s+Total of (\d+) licenses? in use\)', line)
        if m:
            current = {'name': m[1], 'issued': int(m[2]), 'in_use': int(m[3]), 'expiry': '', 'checkouts': []}
            features.append(current)
            continue
        m = re.match(r'Users of ([^:]+):\s+\(Uncounted', line)
        if m:
            current = {'name': m[1], 'issued': None, 'in_use': 0, 'expiry': '', 'checkouts': []}
            features.append(current)
            continue
        if current is None:
            continue
        m = re.search(r'expiry:\s*(\S+)', line)
        if m and line.lstrip().startswith('"'):
            current['expiry'] = m[1]
            continue
        # "    user host display (version) (server/port handle), start Tue 1/1 12:00, 3 licenses, PID: 1202"
        m = re.match(r'\s+(\S+)\s+(\S+)\s+(\S+)\s+(?:(\d+)\s+)?\(v[^)]*\)\s+\([^)]*\),\s+start\s+([^,]+?)(?:,\s+(\d+)\s+licenses?)?(?:,|$)', line)
        if m:
            current['checkouts'].append({'user': m[1], 'host': m[2], 'pid': int(m[4]) if m[4] else None,
                                         'start': m[5].strip(), 'count': int(m[6]) if m[6] else 1})
    return {'server_up': server_up, 'daemons': daemons, 'features': features}


def license_status(spec=None, max_age=60):
    """Query the FlexLM server with lmutil lmstat (no license files are read); cached for a minute per session."""
    spec = spec or os.environ.get('ANSYSLMD_LICENSE_FILE') or os.environ.get('LM_LICENSE_FILE') or '1055@localhost'
    spec = spec.split(':')[0] if spec.count('@') == 1 and ':' in spec else spec
    cached = _LICENSE_CACHE.get(spec)
    if cached and time.monotonic()-cached[0] < max_age:
        return cached[1]
    result = {'available': False, 'server': spec, 'error': '', 'features': [], 'total_features': 0,
              'server_up': False, 'daemons': {}, 'queried_at': time.time()}
    lmutil = find_lmutil()
    if not lmutil:
        result['error'] = '未找到 lmutil（Ansys 许可证工具）'
    else:
        try:
            r = subprocess.run([lmutil, 'lmstat', '-a', '-c', spec], capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=10, env=dict(os.environ, LC_ALL='C'))
            parsed = parse_lmstat(r.stdout)
            result.update(server_up=parsed['server_up'], daemons=parsed['daemons'], total_features=len(parsed['features']),
                          available=bool(parsed['features']) or parsed['server_up'],
                          features=[f for f in parsed['features'] if f['in_use'] or LICENSE_FEATURES.match(f['name'])])
            if not result['available']:
                result['error'] = (r.stdout.strip().splitlines() or [r.stderr.strip() or 'lmstat 没有返回许可证信息'])[-1][:300]
        except (OSError, subprocess.TimeoutExpired) as e:
            result['error'] = f'lmstat 查询失败：{e}'
    _LICENSE_CACHE[spec] = (time.monotonic(), result)
    return result


def attach_licenses(rows, licenses):
    by_pid = {}
    for feature in licenses.get('features', []):
        for c in feature['checkouts']:
            if c['pid'] is not None:
                by_pid.setdefault(c['pid'], []).append({'feature': feature['name'], 'count': c['count']})
    for row in rows:
        row['licenses'] = [l for pid in row.get('pids', []) for l in by_pid.get(pid, [])]


_SIZE_CACHE = {}


def filesystem_info(root):
    """Same numbers as df: used excludes the root-reserved blocks, which are reported separately."""
    s = os.statvfs(root)
    unit = s.f_frsize
    total, free, avail = s.f_blocks*unit, s.f_bfree*unit, s.f_bavail*unit
    mount, device, fstype = '/', '', ''
    try:
        best = -1
        for line in Path('/proc/mounts').read_text().splitlines():
            dev, point, kind = line.split()[:3]
            point = point.replace('\\040', ' ')
            if (str(root) == point or str(root).startswith(point.rstrip('/')+'/')) and len(point) > best:
                best, mount, device, fstype = len(point), point, dev, kind
    except OSError:
        pass
    return {'total': total, 'used': total-free, 'reserved': free-avail, 'available': avail,
            'mount': mount, 'device': device, 'fstype': fstype}


def tree_size(root, budget=4.0, max_age=600):
    """Disk space taken by the project root (like du -s), cached for ten minutes per session."""
    cached = _SIZE_CACHE.get(str(root))
    if cached and time.monotonic()-cached[0] < max_age:
        return cached[1]
    started, total, complete = time.monotonic(), 0, True
    stack, seen = [str(root)], set()
    while stack:
        if time.monotonic()-started > budget:
            complete = False
            break
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            try:
                info = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if info.st_nlink > 1 and info.st_ino and not stat.S_ISDIR(info.st_mode):  # count hard links once, like du
                if (info.st_dev, info.st_ino) in seen:
                    continue
                seen.add((info.st_dev, info.st_ino))
            blocks = getattr(info, 'st_blocks', None)  # allocated size like du; apparent size where unavailable
            total += blocks*512 if blocks is not None else info.st_size
            if e.is_dir(follow_symlinks=False):
                stack.append(e.path)
    result = {'bytes': total, 'complete': complete}
    _SIZE_CACHE[str(root)] = (time.monotonic(), result)
    return result


def snapshot(root, licenses=True):
    a = cpu_ticks()
    started = time.monotonic()
    before = process_ticks()
    time.sleep(.5)
    b = cpu_ticks()
    delta = b[0]-a[0]
    busy = 100*(1-(b[1]-a[1])/delta) if delta > 0 else None
    mem = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        mem[key] = int(value.split()[0])*1024
    disk = shutil.disk_usage(root)
    inventory=process_inventory(root,before,started)
    procs=inventory['owned_project']
    gpu=gpu_snapshot()
    runs,scan=lumerical_runs(root,procs,gpu)
    pipeline=jobs(root,procs,runs)
    covered={r['dir'] for r in pipeline}
    merged=sorted(pipeline+[r for r in runs if r.get('dir') not in covered],
                  key=lambda x:(x['state']=='运行中',x['mtime']),reverse=True)
    sessions=[{'pid':p['pid'],'product':p['solver'],'cwd':p['cwd'],'elapsed_seconds':p['elapsed_seconds'],
               'rss_bytes':p['rss_bytes']} for p in procs if p['kind']=='cad']
    procs=[{k:v for k,v in p.items() if k!='argv'} for p in procs]
    license=license_status() if licenses else {'available':False,'disabled':True,'features':[],'error':'已在设置中关闭'}
    attach_licenses(merged,license)
    return {'license': license,'hostname': socket.gethostname(), 'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'cpu_count': os.cpu_count(), 'cpu_percent': busy, 'load_average': os.getloadavg(),
            'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
            'memory_total': mem['MemTotal'], 'memory_available': mem.get('MemAvailable', mem.get('MemFree', 0)),
            'swap_total': mem.get('SwapTotal',0), 'swap_free': mem.get('SwapFree',0),
            'disk_total': disk.total, 'disk_free': disk.free, 'root': str(root),
            'filesystem': filesystem_info(root), 'project_size': tree_size(root),
            'processes': procs, 'all_processes':inventory['all'],
            'process_visibility':{k:inventory[k] for k in ['visible_count','unreadable','truncated']},
            'users':inventory['users'],
            'jobs': merged, 'run_scan': scan, 'cad_sessions': sessions, 'gpu':gpu}


def dispatch(request):
    root = Path(request['root']).resolve(strict=True)
    op = request['op']
    if op == 'snapshot':
        return snapshot(root, licenses=request.get('licenses', True) is not False)
    path = project_path(root, request.get('path', '.'))
    if op == 'tail':
        result = tail_file(path)
        result['path'] = str(path.relative_to(root))
        return result
    if op == 'list':
        if not path.is_dir():
            raise ValueError('所选路径不是目录')
        entries = []
        for p in path.iterdir():
            try:
                target = project_path(root, str(p))
                info = target.stat()
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    continue
                entries.append({'name': p.name, 'path': str(p.relative_to(root)),
                                'directory': target.is_dir(), 'symlink': p.is_symlink(),
                                'size': info.st_size, 'mtime': info.st_mtime})
            except (OSError, ValueError):
                continue
            if len(entries) >= 2000:
                break
        return {'path': str(path.relative_to(root)), 'entries': sorted(entries,key=lambda x:(not x['directory'],x['name'])),
                'limit_reached': len(entries)>=2000}
    if op == 'stat':
        with open_regular(path) as f:
            s = os.fstat(f.fileno())
        return {'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'path': str(path.relative_to(root))}
    raise ValueError('不支持的只读操作')


def stream_download(request):
    """Length-prefixed metadata followed by raw file bytes; no temporary remote file."""
    import sys
    path = project_path(request['root'], request['path'])
    with open_regular(path) as f:
        info = os.fstat(f.fileno())
        header = json.dumps({'size': info.st_size, 'mtime_ns': info.st_mtime_ns}).encode()+b'\n'
        sys.stdout.buffer.write(header)
        sys.stdout.buffer.flush()
        remaining = info.st_size
        while remaining:
            block = f.read(min(1024*1024, remaining))
            if not block:
                raise ValueError('远端文件在下载期间变短，请重试')
            sys.stdout.buffer.write(block)
            remaining -= len(block)
        if os.fstat(f.fileno()).st_mtime_ns != info.st_mtime_ns:
            raise ValueError('远端文件在下载期间被修改，请等待写入结束后重试')


def main(request):
    import sys
    if request['op'] == 'download':
        stream_download(request)
        return
    try:
        data = {'ok': True, 'data': dispatch(request)}
    except Exception as e:
        data = {'ok': False, 'error': str(e)}
    sys.stdout.write(json.dumps(data, ensure_ascii=True))
