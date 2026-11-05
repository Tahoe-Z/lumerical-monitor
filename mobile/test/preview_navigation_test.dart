import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/services/monitor_controller.dart';
import 'package:lumerical_monitor/src/services/vault.dart';
import 'package:lumerical_monitor/src/ui/preview_navigation.dart';
import 'package:lumerical_monitor/src/ui/preview_charts.dart';

import 'controller_test.dart' show FakeRemote;
import 'vault_test.dart' show MemorySecretStore, sample;

class CachedRemote extends FakeRemote {
  @override
  Future<Map<String, dynamic>> request(
    String op, {
    String path = '.',
    Map<String, dynamic> options = const {},
  }) async => op == 'preview'
      ? {
          'available': true,
          'document': {
            'model': {
              'plane': 'xy',
              'z_m': 0,
              'layers': [
                {
                  'name': 'synthetic',
                  'polygons': [
                    {
                      'contours': [
                        [
                          [0, 0],
                          [1e-6, 0],
                          [0, 1e-6],
                        ],
                      ],
                    },
                  ],
                },
              ],
            },
          },
        }
      : super.request(op, path: path, options: options);
}

void main() {
  testWidgets('cached task model fits a narrow task details page', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = MonitorController(
      vault: SecureVault(store: MemorySecretStore()),
      remoteFactory: CachedRemote.new,
    );
    addTearDown(controller.dispose);
    await controller.saveAndConnect(sample, (_) async => true);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: TaskModelPreview(controller: controller, path: 'sample.fsp'),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byType(ModelPreviewChart), findsOneWidget);
    expect(tester.takeException(), isNull);
    await controller.disconnect();
  });
}
