import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../demo_data.dart';
import '../domain/profile.dart';
import 'ssh_monitor.dart';
import 'vault.dart';

export '../domain/connection.dart';
export '../domain/profile.dart';

class MonitorController extends ChangeNotifier {
  MonitorController({
    SecureVault? vault,
    RemoteMonitor Function()? remoteFactory,
  }) : _vault = vault ?? SecureVault(),
       _remoteFactory = remoteFactory ?? SshMonitor.new;
  final SecureVault _vault;
  final RemoteMonitor Function() _remoteFactory;
  ConnectionProfile? _profile;
  Map<String, dynamic>? _snapshot;
  DateTime? _lastUpdated;
  String? _errorMessage;
  ConnectionPhase _phase = ConnectionPhase.disconnected;
  double? _downloadProgress;
  RemoteMonitor? _remote;
  Timer? _timer;
  Future<void>? _refreshing;
  bool _requested = false, _paused = false, _disposed = false;
  int _generation = 0, _downloadGeneration = 0;

  ConnectionProfile? get profile => _profile;
  Map<String, dynamic>? get snapshot => _snapshot;
  DateTime? get lastUpdated => _lastUpdated;
  String? get errorMessage => _errorMessage;
  ConnectionPhase get phase => _phase;
  bool get isBusy =>
      _phase == ConnectionPhase.connecting || _refreshing != null;
  bool get isDemo => _phase == ConnectionPhase.demo;
  double? get downloadProgress => _downloadProgress;

  bool _current(int generation) =>
      !_disposed && !_paused && generation == _generation;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize() async {
    final generation = _generation;
    try {
      final saved = await _vault.loadProfile();
      if (_current(generation)) {
        _profile = saved;
        _notify();
      }
    } catch (_) {
      if (_current(generation)) {
        _errorMessage = const VaultException().message;
        _phase = ConnectionPhase.error;
        _notify();
      }
    }
  }

  Future<void> saveAndConnect(
    ConnectionProfile value,
    HostTrustPrompt prompt,
  ) async {
    try {
      value.validate();
    } on FormatException catch (error) {
      _errorMessage = error.message;
      _notify();
      return;
    }
    _profile = value;
    _snapshot = null;
    _lastUpdated = null;
    await _connect(value, prompt);
  }

  Future<void> connect(HostTrustPrompt prompt) async {
    final value = _profile;
    if (value == null || _disposed || _phase == ConnectionPhase.connecting) {
      return;
    }
    await _connect(value, prompt);
  }

  Future<void> _connect(ConnectionProfile value, HostTrustPrompt prompt) async {
    if (_disposed) return;
    _requested = true;
    _paused = false;
    final previous = _remote;
    _remote = null;
    final generation = ++_generation;
    _timer?.cancel();
    _timer = null;
    _refreshing = null;
    _phase = ConnectionPhase.connecting;
    _errorMessage = null;
    _notify();
    RemoteMonitor? remote;
    try {
      if (previous != null) await previous.close();
      if (!_current(generation)) return;
      remote = _remoteFactory();
      _remote = remote;
      final approved = <HostTrustRequest>[];
      await remote.connect(value, (request) async {
        if (!_current(generation)) return false;
        final known = await _vault.checkHost(request);
        if (!_current(generation)) return false;
        if (known == true) return true;
        final accepted = await prompt(request);
        if (!_current(generation) || !accepted) return false;
        approved.add(request);
        return true;
      });
      if (!_current(generation)) return;
      final data = await remote.request(
        'snapshot',
        options: {'licenses': value.queryLicenses},
      );
      if (!_current(generation)) return;
      await _vault.saveConnection(
        value,
        approved,
        isCurrent: () => _current(generation),
      );
      if (!_current(generation)) return;
      _snapshot = data;
      _lastUpdated = DateTime.now();
      _phase = ConnectionPhase.connected;
      _errorMessage = null;
      _schedule(generation);
      _notify();
    } catch (error) {
      if (_current(generation)) {
        _phase = ConnectionPhase.error;
        _errorMessage = _safeError(error, '连接失败，请检查网络、私钥和项目目录后重试');
        if (identical(remote, _remote)) _remote = null;
        _notify();
      }
      if (remote != null) {
        try {
          await remote.close();
        } catch (_) {}
      }
    } finally {
      if (!_current(generation) && remote != null) {
        try {
          await remote.close();
        } catch (_) {}
      }
    }
  }

  void _schedule(int generation) {
    _timer?.cancel();
    if (!_current(generation) || _phase != ConnectionPhase.connected) return;
    _timer = Timer(Duration(seconds: _profile!.refreshSeconds), () {
      unawaited(refresh());
    });
  }

  Future<void> refresh() {
    if (_disposed || _paused) return Future.value();
    if (isDemo) {
      _snapshot = demoSnapshot();
      _lastUpdated = DateTime.now();
      _notify();
      return Future.value();
    }
    final existing = _refreshing;
    if (existing != null) return existing;
    final remote = _remote;
    if (remote == null || _phase != ConnectionPhase.connected) {
      return Future.value();
    }
    final generation = _generation;
    final future = _refresh(remote, generation);
    _refreshing = future;
    _notify();
    unawaited(
      future.then<void>(
        (_) {
          if (identical(_refreshing, future)) {
            _refreshing = null;
            _notify();
          }
        },
        onError: (Object _, StackTrace _) {
          if (identical(_refreshing, future)) {
            _refreshing = null;
            _notify();
          }
        },
      ),
    );
    return future;
  }

  Future<void> _refresh(RemoteMonitor remote, int generation) async {
    _timer?.cancel();
    try {
      final data = await remote.request(
        'snapshot',
        options: {'licenses': _profile!.queryLicenses},
      );
      if (!_current(generation)) return;
      _snapshot = data;
      _lastUpdated = DateTime.now();
      _errorMessage = null;
    } catch (error) {
      if (!_current(generation)) return;
      _errorMessage = _safeError(error, '采集失败，请检查网络后重新连接');
      _phase = ConnectionPhase.error;
      if (identical(remote, _remote)) _remote = null;
      try {
        await remote.close();
      } catch (_) {}
    } finally {
      if (_current(generation)) {
        _schedule(generation);
        _notify();
      }
    }
  }

  Future<void> _stop(ConnectionPhase next, {required bool requested}) async {
    ++_generation;
    _requested = requested;
    _timer?.cancel();
    _timer = null;
    _refreshing = null;
    final remote = _remote;
    _remote = null;
    ++_downloadGeneration;
    _downloadProgress = null;
    _phase = next;
    _notify();
    if (remote != null) {
      try {
        await remote.cancelDownload();
        await remote.close();
      } catch (_) {}
    }
  }

  Future<void> disconnect() =>
      _stop(ConnectionPhase.disconnected, requested: false);
  Future<void> pause() async {
    _paused = true;
    await _stop(
      isDemo
          ? ConnectionPhase.demo
          : _requested
          ? ConnectionPhase.paused
          : ConnectionPhase.disconnected,
      requested: _requested,
    );
  }

  Future<void> resume(HostTrustPrompt prompt) async {
    _paused = false;
    if (_requested && _profile != null && !isDemo) await connect(prompt);
    if (!_requested && _phase == ConnectionPhase.paused) {
      _phase = ConnectionPhase.disconnected;
      _notify();
    }
  }

  Future<void> clearSavedConnection() async {
    await disconnect();
    try {
      await _vault.clearConnection();
      if (_disposed) return;
      _profile = null;
      _snapshot = null;
      _lastUpdated = null;
      _errorMessage = null;
    } catch (_) {
      _errorMessage = const VaultException().message;
      _notify();
      throw const VaultException();
    }
    _notify();
  }

  Future<void> clearHostTrust() async {
    await disconnect();
    try {
      await _vault.clearHostTrust();
      _errorMessage = null;
    } catch (_) {
      _errorMessage = const VaultException().message;
      _notify();
      throw const VaultException();
    }
    _notify();
  }

  void showDemo() {
    final remote = _remote;
    _remote = null;
    ++_generation;
    ++_downloadGeneration;
    _requested = false;
    _paused = false;
    _timer?.cancel();
    _timer = null;
    _refreshing = null;
    _downloadProgress = null;
    _phase = ConnectionPhase.demo;
    _snapshot = demoSnapshot();
    _lastUpdated = DateTime.now();
    _errorMessage = null;
    if (remote != null) unawaited(_quietClose(remote));
    _notify();
  }

  Future<Map<String, dynamic>> listFiles(String path) => _read('list', path);
  Future<Map<String, dynamic>> readLog(String path) => _read('tail', path);
  Future<Map<String, dynamic>> readPreview(String path) async {
    if (isDemo) {
      return {
        'available': false,
        'message': '演示模式没有真实模型与结果，请连接服务器后读取',
        'projects': <String>[],
      };
    }
    return _read('preview', path);
  }

  bool isPreviewRunning(String path) {
    final jobs = _snapshot?['jobs'];
    if (jobs is! List) return false;
    return jobs.whereType<Map>().any((job) {
      final pids = job['pids'];
      if (!(pids is List && pids.isNotEmpty) && job['state'] != '运行中') {
        return false;
      }
      final target = '${job['path'] ?? ''}';
      return target == path ||
          job['kind'] == 'pipeline' &&
              (target == '.' ||
                  target.isNotEmpty && path.startsWith('$target/'));
    });
  }

  Future<Map<String, dynamic>> generatePreview(
    String path,
    double wavelengthM,
    double zM,
  ) async {
    if (isDemo) throw const MonitorException('演示模式无法生成真实仿真预览');
    if (isPreviewRunning(path)) throw const MonitorException('任务正在运行，仅可读取已有缓存');
    final remote = _remote;
    if (_phase != ConnectionPhase.connected || remote is! PreviewRemote) {
      throw const MonitorException('请先连接服务器');
    }
    final generation = _generation;
    final result = await (remote as PreviewRemote).preparePreview(
      path,
      wavelengthM,
      zM,
    );
    if (!_current(generation)) throw const MonitorCancelled();
    return result;
  }

  Future<void> cancelPreview() async {
    final remote = _remote;
    if (remote is PreviewRemote) {
      try {
        await (remote as PreviewRemote).cancelPreview();
      } catch (_) {}
    }
  }

  Future<Map<String, dynamic>> _read(String operation, String path) async {
    if (isDemo) return operation == 'list' ? demoFiles(path) : demoLog(path);
    final remote = _remote;
    if (remote == null || _phase != ConnectionPhase.connected) {
      throw const MonitorException('请先连接服务器');
    }
    final generation = _generation;
    try {
      final data = await remote.request(operation, path: path);
      if (!_current(generation)) throw const MonitorCancelled();
      return data;
    } on MonitorException {
      rethrow;
    } catch (_) {
      throw const MonitorException('文件读取失败，请检查权限或重新连接');
    }
  }

  Future<File> download(
    String path, {
    void Function(int, int)? onProgress,
  }) async {
    if (isDemo) throw const MonitorException('演示文件为合成数据，无法下载');
    final remote = _remote;
    if (remote == null || _phase != ConnectionPhase.connected) {
      throw const MonitorException('请先连接服务器');
    }
    final generation = _generation, downloadGeneration = ++_downloadGeneration;
    _downloadProgress = 0;
    _notify();
    try {
      final file = await remote.download(
        path,
        onProgress: (received, total) {
          if (!_current(generation) ||
              downloadGeneration != _downloadGeneration) {
            return;
          }
          _downloadProgress = total == 0
              ? 1
              : (received / total).clamp(0, 1).toDouble();
          onProgress?.call(received, total);
          _notify();
        },
      );
      if (!_current(generation) || downloadGeneration != _downloadGeneration) {
        if (await file.exists()) await file.delete();
        throw const MonitorCancelled();
      }
      return file;
    } on MonitorException {
      rethrow;
    } catch (_) {
      throw const MonitorException('下载失败，请检查网络和设备空间后重试');
    } finally {
      if (downloadGeneration == _downloadGeneration) {
        _downloadProgress = null;
        _notify();
      }
    }
  }

  Future<void> cancelDownload() async {
    ++_downloadGeneration;
    _downloadProgress = null;
    _notify();
    try {
      await _remote?.cancelDownload();
    } catch (_) {}
  }

  String _safeError(Object error, String fallback) => error is HostKeyChanged
      ? error.message
      : error is VaultException
      ? error.message
      : fallback;
  Future<void> _quietClose(RemoteMonitor remote) async {
    try {
      await remote.close();
    } catch (_) {}
  }

  @override
  void dispose() {
    _disposed = true;
    ++_generation;
    ++_downloadGeneration;
    _timer?.cancel();
    final remote = _remote;
    _remote = null;
    if (remote != null) unawaited(_quietClose(remote));
    super.dispose();
  }
}
