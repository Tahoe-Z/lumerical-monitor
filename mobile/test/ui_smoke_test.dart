import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:share_plus/share_plus.dart' show XFile;

import 'package:lumerical_monitor/src/services/monitor_controller.dart';
import 'package:lumerical_monitor/src/ui/app.dart';
import 'package:lumerical_monitor/src/ui/tasks_page.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    final fontPath = Platform.environment['LM_UI_FONT_PATH'];
    if (fontPath == null) return;
    final font = await File(fontPath).readAsBytes();
    final loader = FontLoader('Roboto')
      ..addFont(Future.value(ByteData.sublistView(font)));
    await loader.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  const previewKey = ValueKey('ui-preview');
  Future<void> scrollTo(WidgetTester tester, Finder target, double delta) =>
      tester.scrollUntilVisible(
        target,
        delta,
        scrollable: find
            .descendant(
              of: find.byType(ListView).first,
              matching: find.byType(Scrollable),
            )
            .first,
      );
  Future<void> capturePreview(WidgetTester tester, String name) async {
    final directory = Platform.environment['LM_UI_PREVIEW_DIR'];
    if (directory == null) return;
    final boundary = tester.renderObject<RenderRepaintBoundary>(
      find.byKey(previewKey),
    );
    await tester.runAsync(() async {
      final image = await boundary.toImage(pixelRatio: 2);
      try {
        final data = await image.toByteData(format: ui.ImageByteFormat.png);
        if (data == null) throw StateError('Preview PNG encoding failed');
        await Directory(directory).create(recursive: true);
        await File('$directory/$name.png')
            .writeAsBytes(data.buffer.asUint8List());
      } finally {
        image.dispose();
      }
    });
  }

  Future<void> renderPhone(
    WidgetTester tester,
    MonitorController controller,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      RepaintBoundary(
        key: previewKey,
        child: LumericalMonitorApp(controller: controller, initialize: false),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('first launch offers connection and clearly labeled demo', (
    tester,
  ) async {
    final controller = MonitorController();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    expect(find.text('尚未连接服务器'), findsOneWidget);
    expect(find.text('连接服务器'), findsOneWidget);
    expect(find.text('查看演示'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('startup credential loading respects a user selecting demo', (
    tester,
  ) async {
    final controller = _InitializingController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(LumericalMonitorApp(controller: controller));
    await tester.pump();
    await tester.tap(find.text('查看演示'));
    await tester.pump();
    controller.ready.complete();
    await tester.pumpAndSettle();
    expect(controller.connections, 0);
    expect(find.text('演示 · 合成数据'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('synthetic demo renders without overflow and opens every tab', (
    tester,
  ) async {
    final controller = MonitorController()..showDemo();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    expect(find.text('演示 · 合成数据'), findsOneWidget);
    expect(find.text('CPU 使用率'), findsOneWidget);
    await capturePreview(tester, 'overview');
    for (final label in ['仿真', '资源', '文件', '设置', '概览']) {
      await tester.tap(find.widgetWithText(NavigationDestination, label));
      await tester.pumpAndSettle();
      expect(
        tester.takeException(),
        isNull,
        reason: '$label tab must fit phone',
      );
      expect(find.text('演示 · 合成数据'), findsOneWidget);
      await capturePreview(
        tester,
        'tab-${['概览', '仿真', '资源', '文件', '设置'].indexOf(label)}',
      );
    }
  });

  testWidgets('empty connection form is validated before network work', (
    tester,
  ) async {
    final controller = MonitorController();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    await tester.tap(find.text('连接服务器'));
    await tester.pumpAndSettle();
    await scrollTo(tester, find.text('保存并连接'), 300);
    await tester.tap(find.text('保存并连接'));
    await tester.pumpAndSettle();
    expect(find.text('请输入服务器地址'), findsOneWidget);
    expect(controller.phase, ConnectionPhase.disconnected);
    expect(controller.isBusy, isFalse);
    expect(tester.takeException(), isNull);
  });

  testWidgets('large text remains scrollable at a narrow phone width', (
    tester,
  ) async {
    final controller = MonitorController()..showDemo();
    addTearDown(controller.dispose);
    tester.view.physicalSize = const Size(320, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(textScaler: TextScaler.linear(1.4)),
        child: LumericalMonitorApp(controller: controller, initialize: false),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.tap(find.widgetWithText(NavigationDestination, '资源'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('clipboard is read only after an explicit paste tap', (
    tester,
  ) async {
    var reads = 0;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.getData') reads++;
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );
    final controller = MonitorController();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    await tester.tap(find.text('连接服务器'));
    await tester.pumpAndSettle();
    expect(reads, 0);
    await scrollTo(tester, find.text('粘贴'), 250);
    await tester.tap(find.text('粘贴'));
    await tester.pumpAndSettle();
    expect(reads, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'selected file is imported through the current picker API and masked',
    (tester) async {
      final previous = FilePickerPlatform.instance;
      final selected = _PickedFile(utf8.encode('synthetic import content'));
      final picker = _Picker(selected);
      FilePickerPlatform.instance = picker;
      addTearDown(() => FilePickerPlatform.instance = previous);
      final controller = MonitorController();
      addTearDown(controller.dispose);
      await renderPhone(tester, controller);
      await tester.tap(find.text('连接服务器'));
      await tester.pumpAndSettle();
      expect(picker.calls, 0);
      await scrollTo(tester, find.text('选择密钥文件'), 200);
      await tester.tap(find.text('选择密钥文件'));
      await tester.pumpAndSettle();
      expect(picker.calls, 1);
      expect(selected.reads, 1);
      final field = tester.widget<TextField>(
        find.byWidgetPredicate(
          (widget) =>
              widget is TextField &&
              widget.controller?.text == 'synthetic import content',
        ),
      );
      expect(field.controller?.text, 'synthetic import content');
      expect(field.obscureText, isTrue);
      expect(find.text('已载入：synthetic-key.txt'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('oversized imported files are rejected before reading content', (
    tester,
  ) async {
    final previous = FilePickerPlatform.instance;
    final selected = _PickedFile(const [], reportedLength: 2 * 1024 * 1024);
    FilePickerPlatform.instance = _Picker(selected);
    addTearDown(() => FilePickerPlatform.instance = previous);
    final controller = MonitorController();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    await tester.tap(find.text('连接服务器'));
    await tester.pumpAndSettle();
    await scrollTo(tester, find.text('选择密钥文件'), 200);
    await tester.tap(find.text('选择密钥文件'));
    await tester.pumpAndSettle();
    expect(selected.reads, 0);
    await scrollTo(tester, find.text('密钥文件过大，请选择小于 1 MiB 的文本私钥。'), 200);
    expect(find.text('密钥文件过大，请选择小于 1 MiB 的文本私钥。'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('background pauses and foreground resumes through trust prompt', (
    tester,
  ) async {
    final controller = _LifecycleController();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    expect(controller.pauses, 1);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(controller.resumes, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('unknown host requires an explicit fingerprint approval', (
    tester,
  ) async {
    final controller = _TrustController();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(find.text('确认服务器指纹'), findsOneWidget);
    expect(controller.approved, isNull);
    await tester.tapAt(const Offset(5, 5));
    await tester.pumpAndSettle();
    expect(find.text('确认服务器指纹'), findsOneWidget);
    expect(controller.approved, isNull);
    await tester.tap(find.text('已核对并信任'));
    await tester.pumpAndSettle();
    expect(controller.approved, isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('task cards open readable simulation details', (tester) async {
    final controller = MonitorController()..showDemo();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    await tester.tap(find.widgetWithText(NavigationDestination, '仿真'));
    await tester.pumpAndSettle();
    await scrollTo(tester, find.byType(TaskCard).first, 200);
    await tester.tap(find.byType(TaskCard).first);
    await tester.pumpAndSettle();
    expect(find.text('仿真详情'), findsOneWidget);
    expect(find.text('演示详情 · 合成数据'), findsOneWidget);
    expect(find.text('求解器'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('dark appearance can be selected in settings', (tester) async {
    final controller = MonitorController()..showDemo();
    addTearDown(controller.dispose);
    await renderPhone(tester, controller);
    await tester.tap(find.widgetWithText(NavigationDestination, '设置'));
    await tester.pumpAndSettle();
    await scrollTo(tester, find.text('跟随系统'), 200);
    await tester.tap(find.text('跟随系统'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('深色').last);
    await tester.pumpAndSettle();
    expect(
      tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode,
      ThemeMode.dark,
    );
    await capturePreview(tester, 'settings-dark');
    expect(tester.takeException(), isNull);
  });
}

class _LifecycleController extends MonitorController {
  int pauses = 0, resumes = 0;

  @override
  Future<void> pause() async {
    pauses++;
  }

  @override
  Future<void> resume(HostTrustPrompt prompt) async {
    resumes++;
  }
}

class _InitializingController extends MonitorController {
  final ready = Completer<void>();
  int connections = 0;

  @override
  ConnectionProfile? get profile => const ConnectionProfile(
    host: 'simulation.example',
    username: 'demo',
    root: '/simulation',
    privateKey: '',
  );

  @override
  Future<void> initialize() => ready.future;

  @override
  Future<void> connect(HostTrustPrompt prompt) async {
    connections++;
  }
}

class _TrustController extends MonitorController {
  bool? approved;

  @override
  Future<void> pause() async {}

  @override
  Future<void> resume(HostTrustPrompt prompt) async {
    approved = await prompt(
      const HostTrustRequest(
        host: 'simulation.example',
        port: 22,
        keyType: 'ssh-ed25519',
        fingerprint: 'SHA256:synthetic-fingerprint-for-ui-test',
      ),
    );
  }
}

class _Picker extends FilePickerPlatform {
  _Picker(this.file);
  final PlatformFile file;
  int calls = 0;

  @override
  Future<PlatformFile?> pickFile({
    String? dialogTitle,
    String? initialDirectory,
    FileType type = FileType.any,
    List<String>? allowedExtensions,
    Function(FilePickerStatus)? onFileLoading,
    int compressionQuality = 0,
    AndroidOptions androidOptions = const AndroidOptions(),
    DarwinOptions darwinOptions = const DarwinOptions(),
    WindowsOptions windowsOptions = const WindowsOptions(),
    LinuxOptions linuxOptions = const LinuxOptions(),
    WebOptions webOptions = const WebOptions(),
  }) async {
    calls++;
    return file;
  }
}

final class _PickedFile extends PlatformFile {
  _PickedFile(List<int> content, {this.reportedLength})
    : content = Uint8List.fromList(content);
  final Uint8List content;
  final int? reportedLength;
  int reads = 0;

  @override
  String get name => 'synthetic-key.txt';
  @override
  Uri get uri => Uri.dataFromBytes(content);
  @override
  XFile get xFile => XFile.fromData(content, name: name);
  @override
  int? lengthSync() => reportedLength ?? content.length;
  @override
  Future<int?> length() async => lengthSync();
  @override
  Future<Uint8List> readAsBytes() async {
    reads++;
    return content;
  }

  @override
  Stream<Uint8List> readAsByteStream() async* {
    reads++;
    yield content;
  }
}
