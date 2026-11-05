import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/services/monitor_controller.dart';
import 'package:lumerical_monitor/src/services/ssh_monitor.dart';
import 'package:lumerical_monitor/src/services/vault.dart';

import 'controller_test.dart' show FakeRemote;
import 'vault_test.dart' show MemorySecretStore, sample;

class PreviewFake extends FakeRemote implements PreviewRemote {
  int preparations = 0;
  @override
  Future<Map<String, dynamic>> preparePreview(
    String path,
    double wavelengthM,
    double zM,
  ) async {
    preparations++;
    return {'available': false, 'message': 'synthetic'};
  }

  @override
  Future<void> cancelPreview() async {}
}

void main() {
  test('active pipeline blocks generation using current snapshot', () async {
    final remote = PreviewFake();
    final controller = MonitorController(
      vault: SecureVault(store: MemorySecretStore()),
      remoteFactory: () => remote,
    );
    addTearDown(controller.dispose);
    await controller.saveAndConnect(sample, (_) async => true);
    controller.snapshot!['jobs'] = [
      {
        'path': 'batch',
        'kind': 'pipeline',
        'pids': [123],
      },
    ];
    expect(controller.isPreviewRunning('batch/sample.fsp'), isTrue);
    expect(controller.isPreviewRunning('another/sample.fsp'), isFalse);
    await expectLater(
      controller.generatePreview('batch/sample.fsp', 1.55e-6, 0),
      throwsA(isA<MonitorException>()),
    );
    expect(remote.preparations, 0);
    controller.snapshot!['jobs'] = [];
    await controller.generatePreview('batch/sample.fsp', 1.55e-6, 0);
    expect(remote.preparations, 1);
  });
  test(
    'preview operations do not rewrite existing secure connection',
    () async {
      final store = MemorySecretStore();
      final vault = SecureVault(store: store);
      final controller = MonitorController(
        vault: vault,
        remoteFactory: PreviewFake.new,
      );
      addTearDown(controller.dispose);
      await controller.saveAndConnect(sample, (_) async => true);
      final before = await vault.loadProfile();
      await controller.readPreview('sample.fsp');
      await controller.generatePreview('sample.fsp', 1.55e-6, 0);
      expect((await vault.loadProfile())!.toJson(), before!.toJson());
    },
  );
}
