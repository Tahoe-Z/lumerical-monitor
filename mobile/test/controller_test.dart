import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/services/monitor_controller.dart';
import 'package:lumerical_monitor/src/services/ssh_monitor.dart';
import 'package:lumerical_monitor/src/services/vault.dart';

import 'vault_test.dart' show MemorySecretStore, sample, hostKey;

void main() {
  test(
    'refreshes never overlap and disconnected late replies are discarded',
    () async {
      final remote = FakeRemote();
      final controller = MonitorController(
        vault: SecureVault(store: MemorySecretStore()),
        remoteFactory: () => remote,
      );
      addTearDown(controller.dispose);
      await controller.saveAndConnect(sample, (_) async => true);
      expect(controller.phase, ConnectionPhase.connected);
      remote.wait = Completer<Map<String, dynamic>>();
      final first = controller.refresh();
      final second = controller.refresh();
      await Future<void>.delayed(Duration.zero);
      expect(remote.active, 1);
      await controller.disconnect();
      remote.wait!.complete({'cpu_percent': 99});
      await Future.wait([first, second]);
      expect(controller.phase, ConnectionPhase.disconnected);
      expect(controller.snapshot!['cpu_percent'], 1);
      expect(remote.maxActive, 1);
    },
  );

  test(
    'pause closes resources and resume respects an explicit disconnect',
    () async {
      final remotes = <FakeRemote>[];
      final controller = MonitorController(
        vault: SecureVault(store: MemorySecretStore()),
        remoteFactory: () {
          final remote = FakeRemote();
          remotes.add(remote);
          return remote;
        },
      );
      addTearDown(controller.dispose);
      await controller.saveAndConnect(sample, (_) async => true);
      await controller.pause();
      expect(controller.phase, ConnectionPhase.paused);
      expect(remotes.single.closed, isTrue);
      await controller.resume((_) async => true);
      expect(remotes.length, 2);
      await controller.disconnect();
      await controller.pause();
      await controller.resume((_) async => true);
      expect(remotes.length, 2);
    },
  );

  test('canceling the host prompt saves neither profile nor trust', () async {
    final vault = SecureVault(store: MemorySecretStore());
    final remote = FakeRemote()..askTrust = true;
    final controller = MonitorController(
      vault: vault,
      remoteFactory: () => remote,
    );
    addTearDown(controller.dispose);
    final asked = Completer<void>();
    final decision = Completer<bool>();
    final connecting = controller.saveAndConnect(sample, (_) {
      asked.complete();
      return decision.future;
    });
    await asked.future;
    await controller.pause();
    decision.complete(true);
    await connecting;
    expect(await vault.loadProfile(), isNull);
    expect(await vault.checkHost(hostKey), isNull);
    expect(controller.phase, ConnectionPhase.paused);
  });

  test('remembered changed host fails closed without asking again', () async {
    final vault = SecureVault(store: MemorySecretStore());
    await vault.saveConnection(sample, [hostKey], isCurrent: () => true);
    final remote = FakeRemote()
      ..askTrust = true
      ..trust = const HostTrustRequest(
        host: 'compute.example.invalid',
        port: 22,
        keyType: 'ssh-ed25519',
        fingerprint: 'SHA256:changed',
      );
    final controller = MonitorController(
      vault: vault,
      remoteFactory: () => remote,
    );
    addTearDown(controller.dispose);
    var prompts = 0;
    await controller.initialize();
    await controller.connect((_) async {
      prompts++;
      return true;
    });
    expect(prompts, 0);
    expect(controller.phase, ConnectionPhase.error);
    expect(controller.errorMessage, contains('指纹'));
  });

  test(
    'a failed refresh retains timestamp and uses a redacted diagnostic',
    () async {
      final remote = FakeRemote();
      final controller = MonitorController(
        vault: SecureVault(store: MemorySecretStore()),
        remoteFactory: () => remote,
      );
      addTearDown(controller.dispose);
      await controller.saveAndConnect(sample, (_) async => true);
      final updated = controller.lastUpdated;
      remote.failure = StateError(sample.privateKey);
      await controller.refresh();
      expect(controller.lastUpdated, updated);
      expect(controller.snapshot, isNotNull);
      expect(controller.phase, ConnectionPhase.error);
      expect(controller.errorMessage, isNot(contains(sample.privateKey)));
    },
  );

  test('demo file and log operations do not open a transport', () async {
    final controller = MonitorController(
      remoteFactory: () => throw StateError('network forbidden'),
    );
    addTearDown(controller.dispose);
    controller.showDemo();
    expect((await controller.listFiles('.'))['entries'], isNotEmpty);
    expect((await controller.readLog('demo/run.log'))['text'], contains('合成'));
  });
}

class FakeRemote implements RemoteMonitor {
  bool closed = false, askTrust = false;
  HostTrustRequest trust = hostKey;
  int active = 0, maxActive = 0;
  Object? failure;
  Completer<Map<String, dynamic>>? wait;
  @override
  Future<void> connect(
    ConnectionProfile profile,
    HostTrustPrompt prompt,
  ) async {
    if (askTrust && !await prompt(trust)) {
      throw const MonitorException('未信任服务器');
    }
  }

  @override
  Future<Map<String, dynamic>> request(
    String op, {
    String path = '.',
    Map<String, dynamic> options = const {},
  }) async {
    active++;
    if (active > maxActive) maxActive = active;
    try {
      if (failure != null) throw failure!;
      return await (wait?.future ?? Future.value({'cpu_percent': 1}));
    } finally {
      active--;
    }
  }

  @override
  Future<void> close() async {
    closed = true;
  }

  @override
  Future<void> cancelDownload() async {}
  @override
  Future<File> download(
    String path, {
    void Function(int, int)? onProgress,
  }) async => throw UnimplementedError();
}
