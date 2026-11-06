import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:lumerical_monitor/src/ui/preview_charts.dart';
import 'package:lumerical_monitor/src/ui/simulation_preview_page.dart';

Map<String, dynamic> previewFixture({bool stale = false}) => {
  'available': true,
  'stale': stale,
  'message': '已读取预览缓存',
  'project': 'synthetic/design.fsp',
  'projects': ['synthetic/design.fsp', 'synthetic/other.fsp'],
  'document': {
    'version': 1,
    'source': {'path': 'synthetic/design.fsp', 'size': 42, 'mtime_ns': 1},
    'generated_utc': '2026-11-05T12:00:00Z',
    'model': {
      'plane': 'xy',
      'z_m': 0.5e-6,
      'layers': [
        {
          'name': 'Synthetic ring',
          'polygons': [
            {
              'contours': [
                [
                  [0, 0],
                  [4e-6, 0],
                  [4e-6, 4e-6],
                  [0, 4e-6],
                ],
                [
                  [1e-6, 1e-6],
                  [3e-6, 1e-6],
                  [3e-6, 3e-6],
                  [1e-6, 3e-6],
                ],
              ],
            },
          ],
        },
      ],
    },
    'fields': [
      {
        'name': 'Synthetic field',
        'quantity': '|E|²',
        'x_axis': 'x',
        'y_axis': 'z',
        'fixed_axis': 'y',
        'fixed_position_m': 0.25e-6,
        'wavelength_m': 1.54e-6,
        'x': [0, 1e-6, 4e-6],
        'y': [0, 2e-6],
        'values': [
          [0, 1],
          [2, 3],
          [4, 5],
        ],
        'sampled': true,
      },
    ],
    'spectra': [
      {
        'name': 'Synthetic transmission',
        'normalization': 'monitor signed power',
        'wavelength_m': [1.5e-6, 1.6e-6],
        'values': [-0.2, 1.4],
      },
    ],
    'parameters': [
      {
        'name': 'n_eff',
        'value': 2.4,
        'imag': -0.01,
        'unit': '',
        'wavelength_m': 1.54e-6,
      },
    ],
    'warnings': ['Synthetic warning'],
  },
};

Future<void> mountPreview(
  WidgetTester tester, {
  Future<Map<String, dynamic>> Function(String)? load,
  Future<Map<String, dynamic>> Function(String, double, double)? generate,
  bool running = false,
  double width = 390,
  double textScale = 1,
}) async {
  tester.view.physicalSize = Size(width, 844);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
        child: SimulationPreviewPage(
          path: 'synthetic/design.fsp',
          load: load ?? (_) async => previewFixture(),
          generate: generate ?? (_, _, _) async => previewFixture(),
          running: running,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  test('nonuniform center coordinates produce physical cell edges', () {
    expect(previewCellEdges([0, 1, 4]), [-0.5, 0.5, 2.5, 5.5]);
    expect(previewCellEdges([2]), [1.5, 2.5]);
    expect(() => previewCellEdges([0, 0]), throwsFormatException);
  });

  test('compound geometry keeps an interior ring as a hole', () {
    final path = previewPolygonPath([
      [
        [0, 0],
        [4, 0],
        [4, 4],
        [0, 4],
      ],
      [
        [1, 1],
        [3, 1],
        [3, 3],
        [1, 3],
      ],
    ], (point) => point);
    expect(path.contains(const Offset(0.5, 0.5)), isTrue);
    expect(path.contains(const Offset(2, 2)), isFalse);
  });

  test('spectrum range retains negative and greater than one transmission', () {
    final range = previewAxisRange([-0.2, 1.4]);
    expect(range.$1, lessThanOrEqualTo(-0.2));
    expect(range.$2, greaterThanOrEqualTo(1.4));
    final single = previewAxisRange([1.2]);
    expect(single.$1, lessThan(1.2));
    expect(single.$2, greaterThan(1.2));
  });

  testWidgets(
    'cache loads automatically without generating and exposes four views',
    (tester) async {
      var generated = 0;
      final loaded = <String>[];
      await mountPreview(
        tester,
        load: (path) async {
          loaded.add(path);
          return previewFixture(stale: true);
        },
        generate: (_, _, _) async {
          generated++;
          return previewFixture();
        },
      );
      expect(loaded, ['synthetic/design.fsp']);
      expect(generated, 0);
      expect(find.textContaining('缓存已过期'), findsOneWidget);
      for (final tab in ['模型示意', '模场电场', '透射谱T', '参数']) {
        await tester.tap(find.text(tab));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      }
      expect(find.textContaining('n_eff'), findsOneWidget);
      expect(find.textContaining('Synthetic warning'), findsOneWidget);
    },
  );

  testWidgets(
    'generation requires explicit confirmation and converts nm and micrometers',
    (tester) async {
      final requests = <(String, double, double)>[];
      await mountPreview(
        tester,
        generate: (path, wavelength, z) async {
          requests.add((path, wavelength, z));
          return previewFixture();
        },
      );
      await tester.enterText(
        find.byKey(const ValueKey('preview-wavelength')),
        '1600',
      );
      await tester.enterText(find.byKey(const ValueKey('preview-z')), '-0.25');
      await tester.tap(find.text('生成 / 更新预览'));
      await tester.pumpAndSettle();
      expect(requests, isEmpty);
      expect(find.textContaining('GUI 许可证'), findsOneWidget);
      expect(find.textContaining('.preview.json'), findsOneWidget);
      await tester.tap(find.text('确认生成'));
      await tester.pumpAndSettle();
      expect(requests, hasLength(1));
      expect(requests.single.$1, 'synthetic/design.fsp');
      expect(requests.single.$2, closeTo(1.6e-6, 1e-15));
      expect(requests.single.$3, closeTo(-0.25e-6, 1e-15));
    },
  );

  testWidgets(
    'running tasks keep cached results visible and disable generation',
    (tester) async {
      await mountPreview(tester, running: true);
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, '生成 / 更新预览'),
      );
      expect(button.onPressed, isNull);
      expect(find.textContaining('任务运行中'), findsOneWidget);
      expect(find.byType(ModelPreviewChart), findsOneWidget);
    },
  );

  testWidgets('invalid generation settings do not invoke remote work', (
    tester,
  ) async {
    var generated = 0;
    await mountPreview(
      tester,
      generate: (_, _, _) async {
        generated++;
        return previewFixture();
      },
    );
    await tester.enterText(
      find.byKey(const ValueKey('preview-wavelength')),
      'NaN',
    );
    await tester.tap(find.text('生成 / 更新预览'));
    await tester.pumpAndSettle();
    expect(generated, 0);
    expect(find.textContaining('波长必须是大于 0 的有限数字'), findsOneWidget);
  });

  testWidgets('project picker reads the selected project cache', (
    tester,
  ) async {
    final loaded = <String>[];
    await mountPreview(
      tester,
      load: (path) async {
        loaded.add(path);
        return {...previewFixture(), 'project': path};
      },
    );
    await tester.tap(find.byKey(const ValueKey('preview-project')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('synthetic/other.fsp').last);
    await tester.pumpAndSettle();
    expect(loaded.last, 'synthetic/other.fsp');
    expect(tester.takeException(), isNull);
  });

  testWidgets('missing caches and load errors stay actionable', (tester) async {
    var loads = 0;
    await mountPreview(
      tester,
      load: (_) async {
        loads++;
        if (loads == 1) throw StateError('synthetic failure');
        return {
          'available': false,
          'message': '还没有预览缓存',
          'project': 'synthetic/design.fsp',
        };
      },
    );
    expect(find.textContaining('synthetic failure'), findsOneWidget);
    await tester.tap(find.text('读取缓存'));
    await tester.pumpAndSettle();
    expect(find.textContaining('还没有预览缓存'), findsOneWidget);
    expect(find.byType(ModelPreviewChart), findsNothing);
  });

  testWidgets('phone tabs fit large text and show actual field coordinates', (
    tester,
  ) async {
    await mountPreview(tester, width: 320, textScale: 1.4);
    await tester.tap(find.text('模场电场'));
    await tester.pumpAndSettle();
    expect(find.textContaining('1540'), findsWidgets);
    expect(find.textContaining('y = 0.25'), findsOneWidget);
    expect(find.textContaining('|E|²'), findsWidgets);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('透射谱T'));
    await tester.pumpAndSettle();
    expect(find.textContaining('方向符号'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'GDS fallback is identified as a local pattern rather than a z slice',
    (tester) async {
      final envelope = previewFixture();
      (envelope['document'] as Map)['model']['plane'] = 'gds_local_xy';
      await mountPreview(tester, load: (_) async => envelope);
      expect(find.textContaining('局部 XY 图案'), findsOneWidget);
      expect(find.textContaining('不是 z 截面'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'single point transmission and malformed field data are handled',
    (tester) async {
      final envelope = previewFixture();
      final document = envelope['document'] as Map;
      document['spectra'] = [
        {
          'name': 'Single saved point',
          'wavelength_m': [1.55e-6],
          'values': [-0.4],
        },
      ];
      document['fields'][0]['values'] = [
        [1],
      ];
      await mountPreview(tester, load: (_) async => envelope);
      await tester.tap(find.text('模场电场'));
      await tester.pumpAndSettle();
      expect(find.textContaining('场数据维度或数值无效'), findsOneWidget);
      await tester.tap(find.text('透射谱T'));
      await tester.pumpAndSettle();
      expect(find.byType(SpectrumPreviewChart), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'changing the project during generation releases the busy state',
    (tester) async {
      final path = ValueNotifier('synthetic/design.fsp');
      addTearDown(path.dispose);
      final generated = Completer<Map<String, dynamic>>();
      await tester.pumpWidget(
        MaterialApp(
          home: ValueListenableBuilder<String>(
            valueListenable: path,
            builder: (context, selected, _) => SimulationPreviewPage(
              path: selected,
              load: (project) async => {
                ...previewFixture(),
                'project': project,
              },
              generate: (_, _, _) => generated.future,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('生成 / 更新预览'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('确认生成'));
      await tester.pump();
      path.value = 'synthetic/other.fsp';
      await tester.pump();
      await tester.pump();
      generated.complete(previewFixture());
      await tester.pump();
      final button = tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, '生成 / 更新预览'),
      );
      expect(button.onPressed, isNotNull);
      expect(find.text('synthetic/other.fsp'), findsOneWidget);
    },
  );
}
