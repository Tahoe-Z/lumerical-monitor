import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/services/ssh_monitor.dart';
import 'package:lumerical_monitor/src/domain/profile.dart';

void main() {
  late Directory directory;
  setUp(() async {
    directory = await Directory.systemTemp.createTemp('monitor-test-');
  });
  tearDown(() async {
    await directory.delete(recursive: true);
  });

  test(
    'publishes only a complete download with a reported zero status',
    () async {
      final wire = Uint8List.fromList(
        utf8.encode('{"size":3,"mtime_ns":1}\n') + [0, 255, 13],
      );
      final file = await receiveDownload(
        stdout: Stream.value(wire),
        stderr: const Stream.empty(),
        done: Future.value(),
        exitCode: () => 0,
        directory: directory,
        cancellation: CancellationToken(),
      );
      expect(await file.readAsBytes(), [0, 255, 13]);
      expect(
        directory.listSync().whereType<File>().any(
          (f) => f.path.endsWith('.part'),
        ),
        isFalse,
      );
    },
  );

  test('missing or nonzero exit status removes all partial output', () async {
    for (final status in <int?>[null, 1]) {
      await expectLater(
        receiveDownload(
          stdout: Stream.value(
            Uint8List.fromList(utf8.encode('{"size":1,"mtime_ns":1}\nx')),
          ),
          stderr: const Stream.empty(),
          done: Future.value(),
          exitCode: () => status,
          directory: directory,
          cancellation: CancellationToken(),
        ),
        throwsA(isA<MonitorException>()),
      );
      expect(directory.listSync(), isEmpty);
    }
  });

  test('canceling a stalled download removes its temporary file', () async {
    final wire = StreamController<Uint8List>();
    final cancellation = CancellationToken();
    final started = Completer<void>();
    final result = receiveDownload(
      stdout: wire.stream,
      stderr: const Stream.empty(),
      done: Future.value(),
      exitCode: () => 0,
      directory: directory,
      cancellation: cancellation,
      onProgress: (received, _) {
        if (!started.isCompleted) started.complete();
      },
    );
    final expectation = expectLater(result, throwsA(isA<MonitorCancelled>()));
    wire.add(Uint8List.fromList(utf8.encode('{"size":100,"mtime_ns":1}\nx')));
    await started.future;
    cancellation.cancel();
    await expectation;
    await wire.close();
    expect(directory.listSync(), isEmpty);
  });

  test(
    'a channel that opens after cancellation is destroyed exactly once',
    () async {
      final pending = Completer<String>();
      final cancellation = CancellationToken();
      final disposed = <String>[];
      final resource = acquireResource(
        pending.future,
        cancellation: cancellation,
        isCurrent: () => true,
        dispose: disposed.add,
      );
      final expectation = expectLater(
        resource,
        throwsA(isA<MonitorCancelled>()),
      );
      cancellation.cancel();
      await expectation;
      pending.complete('synthetic-channel');
      await Future<void>.delayed(Duration.zero);
      expect(disposed, ['synthetic-channel']);
    },
  );

  test(
    'a channel that opens after timeout is destroyed exactly once',
    () async {
      final pending = Completer<String>();
      final disposed = <String>[];
      final resource = acquireResource(
        pending.future,
        cancellation: CancellationToken(),
        isCurrent: () => true,
        dispose: disposed.add,
        timeout: Duration.zero,
      );
      await expectLater(resource, throwsA(isA<TimeoutException>()));
      pending.complete('synthetic-channel');
      await Future<void>.delayed(Duration.zero);
      expect(disposed, ['synthetic-channel']);
    },
  );

  test('probe command is fixed and a request travels only in stdin data', () {
    expect(probeCommand, contains('python3 -u -c'));
    final source = downloadSource('PUBLIC PROBE', {
      'op': 'download',
      'root': '/srv/demo',
      'path': 'a\'; echo nope',
    });
    expect(source, isNot(contains("a'; echo nope")));
    expect(source, startsWith('PUBLIC PROBE\n'));
  });

  test(
    'real OpenSSH probe verifies trust, reads data and contains paths',
    () async {
      final env = Platform.environment;
      final profile = ConnectionProfile(
        host: env['LUM_SSH_HOST']!,
        port: int.parse(env['LUM_SSH_PORT']!),
        username: env['LUM_SSH_USER']!,
        root: env['LUM_SSH_ROOT']!,
        privateKey: await File(env['LUM_SSH_PRIVATE_KEY_FILE']!).readAsString(),
        queryLicenses: false,
      );
      final rejected = SshMonitor();
      addTearDown(rejected.close);
      var asked = false;
      await expectLater(
        rejected.connect(profile, (request) async {
          asked = true;
          expect(request.fingerprint, env['LUM_SSH_FINGERPRINT']);
          return false;
        }),
        throwsA(isA<MonitorException>()),
      );
      expect(asked, isTrue);
      final remote = SshMonitor(downloadDirectory: () async => directory);
      addTearDown(remote.close);
      await remote.connect(
        profile,
        (request) async => request.fingerprint == env['LUM_SSH_FINGERPRINT'],
      );
      final snapshot = await remote.request(
        'snapshot',
        options: {'licenses': false},
      );
      expect(snapshot['cpu_count'], isA<int>());
      expect(snapshot['memory_total'], greaterThan(0));
      final listing = await remote.request('list');
      expect(
        (listing['entries'] as List).any(
          (entry) => entry['name'] == 'binary.bin',
        ),
        isTrue,
      );
      expect(
        (await remote.request('tail', path: 'sample.txt'))['text'],
        contains('synthetic log'),
      );
      final file = await remote.download('binary.bin');
      expect(await file.readAsBytes(), [0, 13, 10, 255, 42]);
      final preview = await remote.request('preview', path: 'synthetic.fsp');
      expect(preview['available'], isTrue);
      expect(preview['stale'], isFalse);
      expect((preview['document'] as Map)['spectra'][0]['values'], [-.1, 1.1]);
      await expectLater(
        remote.request('tail', path: '../outside.txt'),
        throwsA(isA<MonitorException>()),
      );
      // A rejected read is an application error; the serialized session stays usable.
      expect((await remote.request('list'))['entries'], isA<List>());
    },
    skip: Platform.environment['LUM_SSH_INTEGRATION'] != '1',
    timeout: const Timeout(Duration(minutes: 3)),
  );
}
