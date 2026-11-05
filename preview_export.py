"""Read bounded preview sidecars; optionally export saved FDTD/MODE data.

The exporter never solves, switches to layout, or saves the original project.
Only an explicit prepare request imports Lumerical and checks out a license.
"""
import base64
import datetime as dt
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import zlib

MAX_CACHE_BYTES = 12 * 1024 * 1024
MAX_PROJECT_BYTES = 512 * 1024 * 1024
MAX_FIELD_VALUES = 2_000_000
SUPPORTED = {'.fsp', '.lms'}
REPLY_MARKER = 'LUMERICAL_PREVIEW_V1:'


def contained(root, path):
    root = Path(root).resolve(strict=True)
    candidate = Path(path)
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not target.is_relative_to(root):
        raise ValueError('预览路径超出项目根目录')
    return target.resolve(strict=True)


def choose_project(root, path):
    root = Path(root).resolve(strict=True)
    target = contained(root, path)
    if target.is_file():
        if target.suffix.lower() not in SUPPORTED:
            raise ValueError('自动预览目前支持 FDTD .fsp 和 MODE .lms 文件')
        return target, [target]
    if not target.is_dir():
        raise ValueError('预览对象不是普通工程文件或目录')
    files, stack, visited, scanned = [], [(target, 0)], 0, 0
    while stack and visited < 100 and scanned < 10000 and len(files) < 64:
        folder, depth = stack.pop()
        visited += 1
        for entry in folder.iterdir():
            scanned += 1
            if scanned > 10000:
                break
            if entry.is_symlink():
                continue
            if entry.is_file() and entry.suffix.lower() in SUPPORTED:
                files.append(entry)
                if len(files) == 64:
                    break
            elif depth < 2 and entry.is_dir() and not entry.name.startswith('.'):
                stack.append((entry, depth + 1))
    files.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
    return (files[0] if files else None), files


def source_signature(project, root):
    # Windows short and long names can refer to the same temporary directory.
    project = Path(project).resolve(strict=True)
    info = project.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('预览只接受普通工程文件')
    return {'path': project.relative_to(Path(root).resolve()).as_posix(),
            'size': info.st_size, 'mtime_ns': info.st_mtime_ns}


def empty_document(project, root):
    return {'version': 1, 'source': source_signature(project, root),
            'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'model': {'layers': [], 'plane': 'xy', 'z_m': 0},
            'fields': [], 'spectra': [], 'parameters': [], 'warnings': []}


def _finite(value, depth=0):
    if depth > 30:
        raise ValueError('预览数据嵌套过深')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('预览含有非有限数值')
    if isinstance(value, dict):
        for item in value.values():
            _finite(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite(item, depth + 1)


def validate_document(doc):
    if not isinstance(doc, dict) or doc.get('version') != 1 or not isinstance(doc.get('source'), dict):
        raise ValueError('预览数据格式无效')
    if not isinstance(doc.get('model'), dict):
        raise ValueError('预览缺少模型元数据')
    for key in ('fields', 'spectra', 'parameters', 'warnings'):
        if not isinstance(doc.get(key), list):
            raise ValueError('预览结果列表无效')
    if any(not isinstance(item, dict) for key in ('fields', 'spectra', 'parameters') for item in doc[key]):
        raise ValueError('预览结果条目无效')
    if not isinstance(doc['model'].get('layers'), list) or any(not isinstance(item, str) for item in doc['warnings']):
        raise ValueError('预览模型或说明无效')
    _finite(doc)
    return doc


def read_preview(root, path):
    root = Path(root).resolve(strict=True)
    project, projects = choose_project(root, path)
    result = {'available': False, 'stale': False,
              'projects': [item.relative_to(root).as_posix() for item in projects]}
    if project is None:
        return {**result, 'message': '该目录未发现 FDTD/MODE 工程文件'}
    signature = source_signature(project, root)
    result['project'] = signature['path']
    sidecar = Path(str(project) + '.preview.json')
    if not sidecar.exists():
        return {**result, 'message': '尚未生成模型与结果预览；可按需生成，或从仿真脚本导出'}
    # Do not follow a sidecar link, even when it currently resolves inside root.
    if sidecar.is_symlink():
        raise ValueError('预览缓存不能是符号链接')
    sidecar = contained(root, sidecar)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(sidecar, flags), 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CACHE_BYTES:
            raise ValueError('预览缓存不是普通文件或超出大小上限')
        data = handle.read(MAX_CACHE_BYTES + 1)
    if len(data) > MAX_CACHE_BYTES:
        raise ValueError('预览缓存超出大小上限')
    try:
        doc = json.loads(data.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法数值')))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('预览缓存不是有效 JSON') from error
    validate_document(doc)
    if doc['source'].get('path') != signature['path']:
        raise ValueError('预览缓存属于另一个工程文件')
    return {**result, 'available': True, 'stale': doc['source'] != signature,
            'document': doc, 'message': '原工程已更新，当前显示上次缓存' if doc['source'] != signature else '已读取预览缓存'}


def write_preview(root, path, document):
    root = Path(root).resolve(strict=True)
    project, _ = choose_project(root, path)
    if project is None:
        raise ValueError('未选择工程文件')
    validate_document(document)
    if document['source'] != source_signature(project, root):
        raise ValueError('读取期间工程文件发生变化；请等待写入结束后重试')
    data = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_CACHE_BYTES:
        raise ValueError('导出的预览超出大小上限')
    target = Path(str(project) + '.preview.json')
    if target.is_symlink():
        raise ValueError('预览缓存不能是符号链接')
    descriptor, temporary = tempfile.mkstemp(prefix='.' + project.name + '.preview-', suffix='.tmp', dir=project.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return read_preview(root, project)


def _wavelength(data):
    import numpy as np
    if 'lambda' in data:
        values = np.asarray(data['lambda'], dtype=float).reshape(-1)
    elif 'f' in data:
        values = 299792458.0 / np.asarray(data['f'], dtype=float).reshape(-1)
    else:
        raise ValueError('数据未记录波长或频率')
    if not len(values) or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('波长坐标无效')
    return values


def field_slice(data, name, wavelength_m=1.55e-6, z_m=0, limit=160):
    import numpy as np
    axes = [np.asarray(data[key], dtype=float).reshape(-1) for key in ('x', 'y', 'z')]
    if any(not len(axis) or not np.isfinite(axis).all() for axis in axes):
        raise ValueError('场坐标无效')
    wavelengths = _wavelength(data)
    frequency = int(np.argmin(np.abs(wavelengths - wavelength_m)))
    raw = np.asarray(data.get('E', data.get('E2')))
    if raw.size > MAX_FIELD_VALUES:
        raise ValueError('场数据过大，请在仿真脚本中导出所需截面')
    shape = tuple(len(axis) for axis in axes) + (len(wavelengths),)
    if 'E' in data and raw.size == math.prod(shape) * 3:
        intensity = np.sum(np.abs(raw.reshape(shape + (3,))) ** 2, axis=-1)
    elif 'E2' in data and raw.size == math.prod(shape):
        intensity = np.real(raw.reshape(shape))
    else:
        raise ValueError('该电场结果不是受支持的直角坐标数据集')
    varying = [index for index, axis in enumerate(axes) if len(axis) > 1]
    if len(varying) < 2:
        raise ValueError('该结果不包含二维场切片')
    horizontal, vertical = varying[:2]
    fixed = next(index for index in range(3) if index not in (horizontal, vertical))
    fixed_index = int(np.argmin(np.abs(axes[fixed] - z_m))) if fixed == 2 else len(axes[fixed]) // 2
    values = np.take(intensity[..., frequency], fixed_index, axis=fixed)
    if not np.isfinite(values).all():
        raise ValueError('场数据含非有限值')
    ix = np.unique(np.linspace(0, len(axes[horizontal]) - 1, min(limit, len(axes[horizontal])), dtype=int))
    iy = np.unique(np.linspace(0, len(axes[vertical]) - 1, min(limit, len(axes[vertical])), dtype=int))
    return {'name': name, 'monitor': name, 'quantity': '|E|²', 'normalization': 'recorded Lumerical field units',
            'x_axis': 'xyz'[horizontal], 'y_axis': 'xyz'[vertical], 'fixed_axis': 'xyz'[fixed],
            'fixed_position_m': float(axes[fixed][fixed_index]), 'wavelength_m': float(wavelengths[frequency]),
            'x': axes[horizontal][ix].tolist(), 'y': axes[vertical][iy].tolist(),
            'values': values[np.ix_(ix, iy)].tolist(), 'sampled': len(ix) < len(axes[horizontal]) or len(iy) < len(axes[vertical])}


def spectrum(data, name):
    import numpy as np
    wavelengths = _wavelength(data)
    values = np.asarray(data['T']).reshape(-1)
    if len(values) != len(wavelengths) or len(values) > 1_000_000:
        raise ValueError('透射谱维度无效或过大')
    if np.iscomplexobj(values) and np.max(np.abs(values.imag)) > 1e-9:
        raise ValueError('T 不是实数功率透射率')
    values = values.real
    if not np.isfinite(values).all():
        raise ValueError('透射谱含非有限值')
    order = np.argsort(wavelengths, kind='stable')
    if len(order) > 2048:
        order = order[np.unique(np.linspace(0, len(order) - 1, 2048, dtype=int))]
    return {'name': name, 'monitor': name, 'quantity': 'T',
            'normalization': 'source-normalized signed power flux',
            'wavelength_m': wavelengths[order].tolist(), 'values': values[order].tolist()}


def _get(obj, key, default=None):
    try:
        return obj[key]
    except Exception:
        return default


def _objects(session):
    session.groupscope('::model')
    session.selectall()
    stack = [(obj, '::model') for obj in session.getAllSelectedObjects()]
    output, seen = [], set()
    while stack and len(output) < 512:
        obj, parent = stack.pop()
        name = str(_get(obj, 'name', ''))
        full = name if name.startswith('::') else parent + '::' + name
        if not name or full in seen:
            continue
        seen.add(full)
        output.append((full, obj))
        kind = str(_get(obj, 'type', '')).lower()
        if 'group' in kind or kind == 'layerbuilder':
            try:
                stack.extend((child, full) for child in obj.getChildren())
            except Exception:
                pass
            finally:
                # getChildren can change scope before throwing in some API versions.
                session.groupscope('::model')
    return output


def _contours(raw):
    import numpy as np
    output = []
    for polygon in list(raw[0]) if raw is not None and len(raw) else []:
        try:
            array = np.asarray(polygon, dtype=float)
        except (ValueError, TypeError):
            array = None
        candidates = [array] if array is not None and array.ndim == 2 else polygon
        rings = []
        for ring in candidates:
            points = np.asarray(ring, dtype=float)
            if points.ndim == 2 and points.shape[1] == 2 and 3 <= len(points) <= 20000 and np.isfinite(points).all():
                rings.append(points.tolist())
        if rings:
            output.append({'contours': rings})
    return output


def _layer_builder_pattern(objects):
    """Saved GDS vertices are useful even when process-derived solids are hidden.

    Keep the first builder in its documented local GDS frame. Never label these
    raw mask polygons as a material cross section or combine unrelated frames.
    """
    import numpy as np
    for name, obj in objects:
        if str(_get(obj, 'type', '')).lower() != 'layerbuilder':
            continue
        geometry = _get(obj, 'geometry')
        if not isinstance(geometry, dict):
            continue
        layers, vertices = [], 0
        for layer, polygons in list(geometry.items())[:32]:
            output = []
            for polygon in list(polygons)[:2000]:
                points = np.asarray(polygon, dtype=float)
                if points.ndim == 2 and points.shape[1] == 2 and 3 <= len(points) <= 20000 and np.isfinite(points).all():
                    vertices += len(points)
                    if vertices > 100000:
                        raise ValueError('GDS 图形过大，请从仿真脚本导出简化预览')
                    output.append({'contours': [points.tolist()]})
            if output:
                layers.append({'name': 'GDS ' + str(layer), 'polygons': output})
        if layers:
            return {'plane': 'gds_local_xy', 'builder': name, 'layers': layers}
    return None


def extract_session(session, project, root, wavelength_m=1.55e-6, z_m=0):
    import numpy as np
    doc = empty_document(project, root)
    doc['model']['z_m'] = float(z_m)
    try:
        objects = _objects(session)
    except Exception:
        objects = []
        doc['warnings'].append('此 Lumerical 版本无法列出结构对象；模型截面未导出')
    materials = set()
    for _, obj in objects:
        material = _get(obj, 'material')
        if isinstance(material, str) and material:
            if material == '<Object defined dielectric>':
                try:
                    material = str(float(np.asarray(_get(obj, 'index')).reshape(-1)[0]))
                except (TypeError, ValueError):
                    continue
            materials.add(material)
    for material in sorted(materials)[:32]:
        try:
            raw = session.polystencil({'material': material, 'partialname': '', 'z': [float(z_m)],
                                      'options': {'ignore_disabled': True, 'curve_chord_tol': 1e-9}})
            polygons = _contours(raw)
            if polygons:
                doc['model']['layers'].append({'name': material, 'polygons': polygons})
        except Exception:
            doc['warnings'].append('材料 ' + material + ' 的几何截面不可用')
    if not doc['model']['layers']:
        try:
            pattern = _layer_builder_pattern(objects)
        except Exception:
            pattern = None
        if pattern:
            doc['model'].update(pattern)
            doc['warnings'].append('模型图显示首个 Layer Builder 已保存的 GDS 图形，使用局部坐标；未应用工艺厚度、偏置和旋转，不代表指定 z 截面。')
        else:
            doc['warnings'].append('当前 z 截面没有可显示的结构；可调整 z 后重新生成')

    names = [name for name, _ in objects]
    try:
        names = str(session.getresult()).splitlines() + names
    except Exception:
        pass
    names = [name.strip() if name.strip().startswith('::') else '::model::' + name.strip() for name in names if name.strip()]
    for name in list(dict.fromkeys(names))[:128]:
        try:
            available = [line.strip() for line in str(session.getresult(name)).splitlines()]
        except Exception:
            continue
        if 'T' in available and len(doc['spectra']) < 12:
            try:
                entry = spectrum(session.getresult(name, 'T'), name)
                doc['spectra'].append(entry)
                nearest = min(range(len(entry['values'])), key=lambda i: abs(entry['wavelength_m'][i] - wavelength_m))
                doc['parameters'].append({'name': name + ' T', 'value': entry['values'][nearest], 'unit': '',
                                          'wavelength_m': entry['wavelength_m'][nearest]})
            except Exception:
                doc['warnings'].append(name + ' 的透射数据不可用或超出预览上限')
        if 'E' in available and len(doc['fields']) < 6:
            try:
                # Inspect cheap axes first to avoid transferring an enormous field volume into Python.
                count = 3
                for axis in ('x', 'y', 'z', 'f'):
                    count *= max(1, np.asarray(session.getdata(name, axis)).size)
                if count > MAX_FIELD_VALUES:
                    raise ValueError('field too large')
                doc['fields'].append(field_slice(session.getresult(name, 'E'), name, wavelength_m, z_m))
            except Exception:
                doc['warnings'].append(name + ' 的二维场不可用或过大；建议在仿真脚本中导出所需截面')
        for quantity in ('neff', 'loss'):
            if quantity in available:
                try:
                    value = np.asarray(session.getresult(name, quantity)).reshape(-1)
                    if len(value) == 1 and np.isfinite(value[0]):
                        scalar = complex(value[0])
                        doc['parameters'].append({'name': name + ' ' + quantity, 'value': scalar.real,
                                                  'imag': scalar.imag, 'unit': 'dB/m' if quantity == 'loss' else ''})
                except Exception:
                    pass
    if not doc['fields']:
        doc['warnings'].append('没有已保存且可预览的场监视器/模式数据；不会从日志推断模场')
    if not doc['spectra']:
        doc['warnings'].append('没有已保存的 T 数据集；不会从文件名或进度推断透射率')
    return doc


def _api_candidates():
    candidates = []
    custom = os.environ.get('LUMERICAL_API_DIR')
    if custom:
        candidates.append(Path(custom) / 'lumapi.py')
    for parent, pattern in [(Path('/opt/lumerical'), 'v*/api/python/lumapi.py'),
                            (Path('/opt/ansys_inc'), 'v*/Lumerical/api/python/lumapi.py'),
                            (Path.home() / 'ansys_inc', 'v*/Lumerical/api/python/lumapi.py'),
                            (Path.home() / 'Ansys/ansys_inc', 'v*/Lumerical/api/python/lumapi.py')]:
        candidates.extend(sorted(parent.glob(pattern), reverse=True))
    return candidates


def preview_interpreter():
    """Use existing Lumerical Python if system Python has no numerical modules."""
    custom = os.environ.get('LUMERICAL_PYTHON')
    if custom:
        path = Path(custom)
        if path.is_file() and os.access(path, os.X_OK) and path.resolve() != Path(sys.executable).resolve():
            return path
    if importlib.util.find_spec('numpy') is not None:
        return None
    for api in _api_candidates():
        for name in ('python3', 'python'):
            path = api.parents[2] / 'python' / 'bin' / name
            if path.is_file() and os.access(path, os.X_OK) and path.resolve() != Path(sys.executable).resolve():
                return path
    return None


def _api_session(suffix):
    try:
        lumapi = importlib.import_module('lumapi')
    except ImportError:
        found = next((item for item in _api_candidates() if item.is_file()), None)
        if found is None:
            raise RuntimeError('服务器 Python 未找到 lumapi；请配置 LUMERICAL_API_DIR 和 NumPy，或在已有仿真会话中导出预览')
        sys.path.insert(0, str(found.parent))
        spec = importlib.util.spec_from_file_location('lumapi', found)
        lumapi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lumapi)
    constructor = lumapi.FDTD if suffix == '.fsp' else lumapi.MODE
    arguments = {'threads': '1'}
    if os.name != 'nt':
        arguments['platform'] = 'offscreen'
    return constructor(hide=True, serverArgs=arguments)


def prepare_preview(root, path, wavelength_m=1.55e-6, z_m=0, session_factory=None):
    root = Path(root).resolve(strict=True)
    project, _ = choose_project(root, path)
    if project is None:
        raise ValueError('未选择工程文件')
    if project.stat().st_size > MAX_PROJECT_BYTES:
        raise ValueError('工程大于 512 MiB，请在已有仿真会话中调用 export_from_session，避免重复加载大型结果')
    if not math.isfinite(float(wavelength_m)) or not 0 < float(wavelength_m) < 1 or not math.isfinite(float(z_m)):
        raise ValueError('波长或截面参数无效')
    initial = source_signature(project, root)
    session = None
    try:
        session = (session_factory or _api_session)(project.suffix.lower())
        session.load(str(project))
        document = extract_session(session, project, root, float(wavelength_m), float(z_m))
        if source_signature(project, root) != initial:
            raise ValueError('工程在读取期间发生变化，请等待写入完成后重试')
        document['source'] = initial
        return write_preview(root, project, document)
    finally:
        if session is not None:
            session.close()


def export_from_session(session, root, project, wavelength_m=1.55e-6, z_m=0):
    """Call after saving a completed solve, while its existing API session is open."""
    root = Path(root).resolve(strict=True)
    selected, _ = choose_project(root, project)
    if selected is None:
        raise ValueError('未选择工程文件')
    return write_preview(root, selected, extract_session(session, selected, root, wavelength_m, z_m))


def emit(request, source=None):
    """One explicit SSH tool request. Redirect API chatter away from its reply marker."""
    import contextlib
    if source and os.name != 'nt':
        python = preview_interpreter()
        if python:
            # Replace this process, retaining SSH stdin/stdout and cancellation signals.
            code = f"_ns={{'__name__':'preview_tool'}}\nexec({source!r},_ns)\n_ns['emit']({request!r})\n"
            os.execv(str(python), [str(python), '-c', code])
    previous = {}
    def interrupted(signum, frame):
        raise RuntimeError('预览会话已取消或超时')
    if hasattr(signal, 'SIGALRM'):
        for kind in (signal.SIGALRM, signal.SIGHUP, signal.SIGTERM):
            previous[kind] = signal.signal(kind, interrupted)
        signal.alarm(150)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            data = prepare_preview(request['root'], request['path'], request.get('wavelength_m', 1.55e-6), request.get('z_m', 0))
        reply = {'ok': True, 'data': data}
    except Exception as error:
        reply = {'ok': False, 'error': str(error)}
    finally:
        if previous:
            signal.alarm(0)
            for kind, handler in previous.items():
                signal.signal(kind, handler)
    encoded = base64.b64encode(zlib.compress(json.dumps(reply, ensure_ascii=True, allow_nan=False).encode('utf-8'))).decode('ascii')
    print(REPLY_MARKER + encoded, flush=True)


def cli():
    import argparse
    parser = argparse.ArgumentParser(description='Export a saved FDTD/MODE project preview without solving or saving it')
    parser.add_argument('project')
    parser.add_argument('--root', required=True)
    parser.add_argument('--wavelength-nm', type=float, default=1550)
    parser.add_argument('--z-um', type=float, default=0)
    options = parser.parse_args()
    result = prepare_preview(options.root, options.project, options.wavelength_nm * 1e-9, options.z_um * 1e-6)
    print('Preview written: ' + result['project'] + '.preview.json')


if __name__ == '__main__':
    cli()
