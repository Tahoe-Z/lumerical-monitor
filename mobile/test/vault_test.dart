import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/domain/profile.dart';
import 'package:lumerical_monitor/src/domain/connection.dart';
import 'package:lumerical_monitor/src/services/vault.dart';

const sample = ConnectionProfile(
  host: 'compute.example.invalid',
  username: 'monitor',
  root: '/srv/demo',
  privateKey: 'synthetic-unparsed-key',
);
const hostKey = HostTrustRequest(
  host: 'compute.example.invalid',
  port: 22,
  keyType: 'ssh-ed25519',
  fingerprint: 'SHA256:synthetic-test-fingerprint',
);

void main() {
  test(
    'persists the whole profile and trust through the encrypted store boundary',
    () async {
      final store = MemorySecretStore();
      final vault = SecureVault(store: store);
      await vault.saveConnection(sample, [hostKey], isCurrent: () => true);
      final restored = SecureVault(store: store);
      expect((await restored.loadProfile())!.toJson(), sample.toJson());
      expect(await restored.checkHost(hostKey), isTrue);
      await expectLater(
        restored.checkHost(
          const HostTrustRequest(
            host: 'compute.example.invalid',
            port: 22,
            keyType: 'ssh-ed25519',
            fingerprint: 'SHA256:changed',
          ),
        ),
        throwsA(isA<HostKeyChanged>()),
      );
      await restored.clearHostTrust();
      expect(await restored.checkHost(hostKey), isNull);
      expect(await restored.loadProfile(), isNotNull);
      await restored.clearConnection();
      expect(await restored.loadProfile(), isNull);
    },
  );

  test(
    'canceled transactions cannot retain a profile or newly approved trust',
    () async {
      final store = BlockingStore();
      final vault = SecureVault(store: store);
      var current = true;
      final saving = vault.saveConnection(sample, [
        hostKey,
      ], isCurrent: () => current);
      await store.started.future;
      current = false;
      store.release.complete();
      await saving;
      expect(await vault.loadProfile(), isNull);
      expect(await vault.checkHost(hostKey), isNull);
    },
  );

  test('a storage failure is surfaced without exposing source text', () async {
    final vault = SecureVault(store: FailingStore());
    await expectLater(vault.loadProfile(), throwsA(isA<VaultException>()));
    try {
      await vault.loadProfile();
    } catch (error) {
      expect('$error', isNot(contains(sample.privateKey)));
    }
  });
}

class MemorySecretStore implements SecretStore {
  final values = <String, String>{};
  @override
  Future<String?> read(String key) async => values[key];
  @override
  Future<void> write(String key, String value) async {
    values[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    values.remove(key);
  }
}

class BlockingStore extends MemorySecretStore {
  final started = Completer<void>();
  final release = Completer<void>();
  @override
  Future<void> write(String key, String value) async {
    if (!started.isCompleted) {
      started.complete();
      await release.future;
    }
    await super.write(key, value);
  }
}

class FailingStore extends MemorySecretStore {
  @override
  Future<String?> read(String key) async => throw StateError(sample.privateKey);
}
