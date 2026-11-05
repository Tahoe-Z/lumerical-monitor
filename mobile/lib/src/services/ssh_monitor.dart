import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import '../domain/connection.dart';
import '../domain/profile.dart';
import 'protocol.dart';

export '../domain/connection.dart';

abstract interface class RemoteMonitor {
  Future<void> connect(ConnectionProfile profile, HostTrustPrompt prompt);
  Future<Map<String, dynamic>> request(
    String op, {
    String path,
    Map<String, dynamic> options,
  });
  Future<File> download(String path, {void Function(int, int)? onProgress});
  Future<void> cancelDownload();
  Future<void> close();
}

class CancellationToken {
  final _cancelled = Completer<void>();
  bool get isCancelled => _cancelled.isCompleted;
  void cancel() {
    if (!isCancelled) _cancelled.complete();
  }

  void check() {
    if (isCancelled) throw const MonitorCancelled();
  }

  Future<T> wait<T>(Future<T> operation) {
    check();
    return Future.any([
      operation,
      _cancelled.future.then<T>((_) => throw const MonitorCancelled()),
    ]);
  }
}

/// Closes resources that arrive after a canceled or timed-out asynchronous open.
Future<T> acquireResource<T>(
  Future<T> pending, {
  required CancellationToken cancellation,
  required bool Function() isCurrent,
  required void Function(T) dispose,
  Duration timeout = const Duration(seconds: 40),
}) async {
  var abandoned = false, disposed = false;
  void discard(T value) {
    if (!disposed) {
      disposed = true;
      dispose(value);
    }
  }

  unawaited(
    pending.then<void>((value) {
      if (abandoned || cancellation.isCancelled || !isCurrent()) discard(value);
    }, onError: (Object _, StackTrace _) {}),
  );
  try {
    final value = await cancellation.wait(pending.timeout(timeout));
    cancellation.check();
    if (!isCurrent()) throw const MonitorCancelled();
    return value;
  } catch (_) {
    abandoned = true;
    unawaited(
      pending.then<void>(discard, onError: (Object _, StackTrace _) {}),
    );
    rethrow;
  }
}

const probeCommand =
    "python3 -u -c 'import sys,base64;exec(base64.b64decode(sys.stdin.buffer.readline()))'";
const _serveCode = r'''
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
    if len(_text) > 4096:
        _text = json.dumps({'z': _b64.b64encode(_zlib.compress(_text.encode(), 6)).decode()})
    _sys.stdout.write(_text+'\n'); _sys.stdout.flush()
''';

String downloadSource(String probe, Map<String, dynamic> payload) {
  final encoded = base64Encode(utf8.encode(jsonEncode(payload)));
  return '$probe\nimport base64\nmain(json.loads(base64.b64decode("$encoded")))\n';
}

/// Discards stderr continuously, retaining no remote text or credential data.
Future<void> _drainErrors(Stream<Uint8List> stream) async {
  await for (final _ in stream) {
    /* Drain independently of stdout. */
  }
}

/// Completes only when framing, both streams, and remote status are verified.
Future<File> receiveDownload({
  required Stream<Uint8List> stdout,
  required Stream<Uint8List> stderr,
  required Future<void> done,
  required int? Function() exitCode,
  required Directory directory,
  required CancellationToken cancellation,
  String filename = 'download.bin',
  void Function(int, int)? onProgress,
  Duration inactivityTimeout = const Duration(seconds: 40),
}) async {
  final reader = DownloadReader(stdout.timeout(inactivityTimeout));
  final errorsDone = _drainErrors(stderr);
  // Install error handlers immediately even while stdout is being consumed.
  final completion = Future.wait<void>([errorsDone, done]);
  unawaited(
    completion.then<void>((_) {}, onError: (Object _, StackTrace _) {}),
  );
  final safeName = filename
      .split(RegExp(r'[/\\]'))
      .last
      .replaceAll(RegExp(r'[\x00-\x1f<>:"/\\|?*]'), '_');
  final name = safeName.isEmpty || safeName == '.' || safeName == '..'
      ? 'download.bin'
      : safeName;
  final id =
      '${DateTime.now().microsecondsSinceEpoch}_${Random.secure().nextInt(1 << 30)}';
  final partial = File('${directory.path}/transfer_$id.part');
  final destination = File(
    '${directory.path}/$id-${name.length > 120 ? name.substring(name.length - 120) : name}',
  );
  RandomAccessFile? out;
  var published = false;
  try {
    cancellation.check();
    await directory.create(recursive: true);
    final header = await cancellation.wait(reader.readHeader());
    cancellation.check();
    out = await partial.open(mode: FileMode.write);
    var received = 0;
    final body = StreamIterator(reader.readBody(header.size));
    try {
      while (await cancellation.wait(body.moveNext())) {
        cancellation.check();
        // Finish an already-started local write before closing/deleting its file.
        await out.writeFrom(body.current);
        cancellation.check();
        received += body.current.length;
        onProgress?.call(received, header.size);
      }
    } finally {
      // Cancel the underlying iterator first: an async generator can otherwise
      // wait forever for a stalled socket before processing its own cancel.
      if (cancellation.isCancelled) await reader.cancel();
      await body.cancel();
    }
    await cancellation.wait(completion.timeout(inactivityTimeout));
    cancellation.check();
    if (received != header.size || exitCode() != 0) {
      throw const MonitorException('下载未完成或远端文件发生变化，请重试');
    }
    await out.flush();
    await out.close();
    out = null;
    cancellation.check();
    final file = await partial.rename(destination.path);
    published = true;
    cancellation.check();
    onProgress?.call(received, header.size);
    return file;
  } on MonitorCancelled {
    rethrow;
  } on MonitorException {
    rethrow;
  } catch (_) {
    throw const MonitorException('下载失败：数据不完整、网络超时或设备空间不足');
  } finally {
    await reader.cancel();
    if (out != null) {
      try {
        await out.close();
      } catch (_) {}
    }
    if (await partial.exists()) {
      await partial.delete();
    }
    if (published && cancellation.isCancelled && await destination.exists()) {
      await destination.delete();
    }
  }
}

class SshMonitor implements RemoteMonitor {
  SshMonitor({
    Future<String> Function()? loadProbe,
    Future<Directory> Function()? downloadDirectory,
    this.requestTimeout = const Duration(seconds: 40),
  }) : _loadProbe = loadProbe ?? _defaultLoadProbe,
       _downloadDirectory =
           downloadDirectory ?? getApplicationDocumentsDirectory;

  static Future<String> _defaultLoadProbe() async {
    try {
      return await rootBundle.loadString('assets/remote_probe.py');
    } catch (_) {
      for (final path in [
        'assets/remote_probe.py',
        'mobile/assets/remote_probe.py',
      ]) {
        final file = File(path);
        if (await file.exists()) return file.readAsString();
      }
      rethrow;
    }
  }

  final Future<String> Function() _loadProbe;
  final Future<Directory> Function() _downloadDirectory;
  final Duration requestTimeout;
  SSHClient? _client;
  SSHSocket? _socket;
  SSHSession? _session, _downloadSession;
  ReplyLines? _lines;
  ConnectionProfile? _profile;
  CancellationToken _connection = CancellationToken();
  CancellationToken? _downloadCancellation;
  Future<File>? _downloadFuture;
  Future<void> _requestTail = Future.value();

  @override
  Future<void> connect(
    ConnectionProfile profile,
    HostTrustPrompt prompt,
  ) async {
    profile.validate();
    await close();
    final token = CancellationToken();
    _connection = token;
    _profile = profile;
    MonitorException? trustFailure;
    try {
      List<SSHKeyPair> identities;
      try {
        identities = SSHKeyPair.fromPem(
          profile.privateKey,
          profile.passphrase.isEmpty ? null : profile.passphrase,
        );
      } catch (_) {
        throw const MonitorException('无法读取 SSH 私钥，请检查格式或密钥口令');
      }
      token.check();
      final socketFuture = SSHSocket.connect(
        profile.host,
        profile.port,
        timeout: const Duration(seconds: 15),
      );
      // A canceled TCP dial can still resolve later; destroy that late socket.
      unawaited(
        socketFuture.then<void>((socket) {
          if (token.isCancelled) socket.destroy();
        }, onError: (Object _, StackTrace _) {}),
      );
      final socket = await token.wait(socketFuture);
      token.check();
      _socket = socket;
      final client = SSHClient(
        socket,
        username: profile.username,
        identities: identities,
        handshakeTimeout: const Duration(seconds: 120),
        authTimeout: const Duration(seconds: 20),
        onVerifyHostKey: (type, fingerprint) async {
          try {
            token.check();
            final result = await token.wait(
              prompt(
                HostTrustRequest(
                  host: profile.host,
                  port: profile.port,
                  keyType: type,
                  fingerprint: utf8.decode(fingerprint),
                ),
              ),
            );
            token.check();
            return result;
          } on MonitorException catch (error) {
            trustFailure = error;
            return false;
          } catch (_) {
            trustFailure = const MonitorException('无法确认服务器指纹');
            return false;
          }
        },
      );
      _client = client;
      unawaited(
        client.done.then<void>((_) {}, onError: (Object _, StackTrace _) {}),
      );
      await token.wait(client.authenticated);
      token.check();
      final probe = await token.wait(_loadProbe());
      final session = await acquireResource(
        client.execute(probeCommand),
        cancellation: token,
        isCurrent: () => identical(token, _connection),
        dispose: (session) => session.channel.destroy(),
        timeout: requestTimeout,
      );
      _session = session;
      token.check();
      unawaited(_drainErrors(session.stderr).catchError((Object _) {}));
      final lines = ReplyLines(session.stdout);
      _lines = lines;
      session.stdin.add(
        Uint8List.fromList(
          utf8.encode('${base64Encode(utf8.encode('$probe\n$_serveCode'))}\n'),
        ),
      );
      await token.wait(session.flush().timeout(requestTimeout));
      final ready = decodeReply(
        await token.wait(lines.next().timeout(requestTimeout)),
      );
      if (ready['ready'] != true) throw const MonitorException('远端采集会话未就绪');
    } catch (error) {
      if (identical(token, _connection)) await close();
      if (trustFailure != null) throw trustFailure!;
      if (error is MonitorException) rethrow;
      throw const MonitorException('SSH 连接失败：请检查网络、私钥权限及远端 Python 3');
    }
  }

  @override
  Future<Map<String, dynamic>> request(
    String op, {
    String path = '.',
    Map<String, dynamic> options = const {},
  }) {
    final token = _connection;
    final result = _requestTail.then((_) async {
      token.check();
      final session = _session;
      final lines = _lines;
      if (session == null || lines == null || _client?.isClosed != false) {
        throw const MonitorException('SSH 连接已关闭，请重新连接');
      }
      try {
        final payload = {
          ...options,
          'op': op,
          'root': _profile!.root,
          'path': path,
        };
        session.stdin.add(
          Uint8List.fromList(utf8.encode('${jsonEncode(payload)}\n')),
        );
        await token.wait(session.flush().timeout(requestTimeout));
        final reply = decodeReply(
          await token.wait(lines.next().timeout(requestTimeout)),
        );
        token.check();
        if (reply['ok'] != true) throw const _RemoteReadError();
        final data = reply['data'];
        if (data is! Map<String, dynamic>) {
          throw const FormatException('响应类型无效');
        }
        return data;
      } on _RemoteReadError {
        throw const MonitorException('远端无法读取所选项目或文件，请检查权限及项目范围');
      } catch (error) {
        if (identical(token, _connection)) await close();
        if (error is MonitorCancelled) rethrow;
        throw const MonitorException('采集请求失败或超时，请重新连接');
      }
    });
    _requestTail = result.then<void>(
      (_) {},
      onError: (Object _, StackTrace _) {},
    );
    return result;
  }

  @override
  Future<File> download(String path, {void Function(int, int)? onProgress}) {
    if (_downloadFuture != null) {
      return Future.error(const MonitorException('已有下载正在进行'));
    }
    final cancellation = CancellationToken();
    _downloadCancellation = cancellation;
    final future = _download(path, cancellation, onProgress);
    _downloadFuture = future;
    unawaited(
      future.then<void>(
        (_) {
          _clearDownload(cancellation);
        },
        onError: (Object _, StackTrace _) {
          _clearDownload(cancellation);
        },
      ),
    );
    return future;
  }

  void _clearDownload(CancellationToken token) {
    if (identical(token, _downloadCancellation)) {
      _downloadFuture = null;
      _downloadCancellation = null;
    }
  }

  Future<File> _download(
    String path,
    CancellationToken cancellation,
    void Function(int, int)? onProgress,
  ) async {
    final connection = _connection;
    SSHSession? session;
    try {
      connection.check();
      cancellation.check();
      final client = _client;
      if (client == null || client.isClosed) {
        throw const MonitorException('请先连接服务器');
      }
      final probe = await cancellation.wait(_loadProbe());
      connection.check();
      final activeSession = await acquireResource(
        client.execute(probeCommand),
        cancellation: cancellation,
        isCurrent: () => !connection.isCancelled,
        dispose: (session) => session.channel.destroy(),
        timeout: requestTimeout,
      );
      session = activeSession;
      connection.check();
      cancellation.check();
      _downloadSession = session;
      final source = downloadSource(probe, {
        'op': 'download',
        'root': _profile!.root,
        'path': path,
      });
      final directory = await cancellation.wait(_downloadDirectory());
      final receiving = receiveDownload(
        stdout: activeSession.stdout,
        stderr: activeSession.stderr,
        done: activeSession.done,
        exitCode: () => activeSession.exitCode,
        directory: directory,
        cancellation: cancellation,
        filename: path,
        onProgress: onProgress,
        inactivityTimeout: requestTimeout,
      );
      // Begin consuming both streams before sending the source/EOF.
      unawaited(
        receiving.then<void>((_) {}, onError: (Object _, StackTrace _) {}),
      );
      activeSession.stdin.add(
        Uint8List.fromList(
          utf8.encode('${base64Encode(utf8.encode(source))}\n'),
        ),
      );
      await cancellation.wait(
        activeSession.stdin.close().timeout(requestTimeout),
      );
      return await receiving;
    } on MonitorException {
      rethrow;
    } catch (_) {
      throw const MonitorException('下载通道失败，请检查网络后重试');
    } finally {
      session?.channel.destroy();
      if (identical(session, _downloadSession)) _downloadSession = null;
    }
  }

  @override
  Future<void> cancelDownload() async {
    _downloadCancellation?.cancel();
    _downloadSession?.channel.destroy();
    final future = _downloadFuture;
    if (future != null) {
      try {
        await future;
      } catch (_) {}
    }
  }

  @override
  Future<void> close() async {
    _connection.cancel();
    final client = _client, socket = _socket, lines = _lines;
    _client = null;
    _socket = null;
    _session = null;
    _lines = null;
    await cancelDownload();
    // Destroy first so blocked stream readers and writes wake immediately.
    socket?.destroy();
    if (client != null) {
      try {
        await client.close().timeout(const Duration(seconds: 2));
      } catch (_) {}
    }
    if (lines != null) {
      try {
        await lines.cancel();
      } catch (_) {}
    }
  }
}

class _RemoteReadError implements Exception {
  const _RemoteReadError();
}
