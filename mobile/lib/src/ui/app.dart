import 'dart:async';

import 'package:flutter/material.dart';

import '../services/monitor_controller.dart';
import 'files_page.dart';
import 'overview_page.dart';
import 'resources_page.dart';
import 'settings_page.dart';
import 'shared.dart';
import 'tasks_page.dart';

typedef MobileMonitorApp = LumericalMonitorApp;

class LumericalMonitorApp extends StatefulWidget {
  const LumericalMonitorApp({
    super.key,
    this.controller,
    this.initialize = true,
  });
  final MonitorController? controller;
  final bool initialize;
  @override
  State<LumericalMonitorApp> createState() => _LumericalMonitorAppState();
}

class _LumericalMonitorAppState extends State<LumericalMonitorApp> {
  late final MonitorController _controller =
      widget.controller ?? MonitorController();
  ThemeMode _themeMode = ThemeMode.system;

  @override
  void dispose() {
    if (widget.controller == null) _controller.dispose();
    super.dispose();
  }

  ThemeData _theme(Brightness brightness) {
    final dark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(seedColor: clay, brightness: brightness)
        .copyWith(
          primary: dark ? const Color(0xFFE69979) : clay,
          surface: dark ? const Color(0xFF24231F) : const Color(0xFFFFFFFF),
        );
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      brightness: brightness,
    );
    return base.copyWith(
      scaffoldBackgroundColor: dark ? const Color(0xFF191A17) : warmPaper,
      textTheme: base.textTheme.copyWith(
        headlineMedium: base.textTheme.headlineMedium?.copyWith(
          fontSize: 29,
          fontWeight: FontWeight.w700,
          letterSpacing: -.7,
        ),
        titleLarge: base.textTheme.titleLarge?.copyWith(
          fontSize: 19,
          fontWeight: FontWeight.w700,
          letterSpacing: -.3,
        ),
        titleMedium: base.textTheme.titleMedium?.copyWith(
          fontSize: 15,
          fontWeight: FontWeight.w600,
        ),
        bodyMedium: base.textTheme.bodyMedium?.copyWith(
          fontSize: 13,
          height: 1.65,
        ),
        bodySmall: base.textTheme.bodySmall?.copyWith(
          fontSize: 11,
          height: 1.55,
          color: scheme.onSurfaceVariant,
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: dark ? const Color(0xFF191A17) : warmPaper,
        scrolledUnderElevation: 0,
        centerTitle: false,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: scheme.surface,
        indicatorColor: clay.withValues(alpha: dark ? .28 : .12),
        height: 74,
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => TextStyle(
            fontSize: 11,
            fontWeight: states.contains(WidgetState.selected)
                ? FontWeight.w700
                : FontWeight.w500,
            color: states.contains(WidgetState.selected)
                ? scheme.primary
                : scheme.onSurfaceVariant,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: dark ? const Color(0xFF292A25) : const Color(0xFFF5F4EF),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(13),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(13),
          borderSide: BorderSide.none,
        ),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 17,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, 48),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(13),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 48),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(13),
          ),
        ),
      ),
      dividerColor: scheme.outlineVariant,
    );
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Lumerical Monitor',
    debugShowCheckedModeBanner: false,
    theme: _theme(Brightness.light),
    darkTheme: _theme(Brightness.dark),
    themeMode: _themeMode,
    home: MonitorHome(
      controller: _controller,
      initialize: widget.initialize,
      themeMode: _themeMode,
      onThemeChanged: (mode) => setState(() => _themeMode = mode),
    ),
  );
}

class MonitorHome extends StatefulWidget {
  const MonitorHome({
    super.key,
    required this.controller,
    required this.initialize,
    required this.themeMode,
    required this.onThemeChanged,
  });
  final MonitorController controller;
  final bool initialize;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeChanged;
  @override
  State<MonitorHome> createState() => _MonitorHomeState();
}

class _MonitorHomeState extends State<MonitorHome> with WidgetsBindingObserver {
  int _tab = 0;
  bool _initializing = false;
  MonitorController get controller => widget.controller;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.initialize) {
      _initializing = true;
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => unawaited(_initialize()),
      );
    }
  }

  Future<void> _initialize() async {
    try {
      await controller.initialize();
      if (mounted &&
          controller.profile != null &&
          controller.phase == ConnectionPhase.disconnected) {
        await controller.connect(_trustHost);
      }
    } catch (e) {
      if (mounted) showMessage(context, e);
    } finally {
      if (mounted) setState(() => _initializing = false);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(_run(() => controller.resume(_trustHost)));
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden ||
        state == AppLifecycleState.detached) {
      unawaited(_run(controller.pause));
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    try {
      await action();
    } catch (e) {
      if (mounted) showMessage(context, e);
    }
  }

  Future<bool> _trustHost(HostTrustRequest request) async {
    if (!mounted) return false;
    return await showDialog<bool>(
          context: context,
          barrierDismissible: false,
          builder: (context) => AlertDialog(
            title: const Text('确认服务器指纹'),
            content: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('这是首次连接此服务器。请通过可信渠道向管理员核对以下 SSH 主机指纹，再决定是否信任。'),
                  const SizedBox(height: 18),
                  DetailRow('服务器', '${request.host}:${request.port}'),
                  DetailRow('密钥类型', request.keyType),
                  const SizedBox(height: 8),
                  SelectableText(
                    request.fingerprint,
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消连接'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('已核对并信任'),
              ),
            ],
          ),
        ) ??
        false;
  }

  void _editConnection() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) =>
          ConnectionEditor(controller: controller, trustPrompt: _trustHost),
    ),
  );

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: controller,
    builder: (context, _) {
      final hasData = controller.snapshot != null;
      final pages = <Widget>[
        OverviewPage(
          controller: controller,
          onConnect: _editConnection,
          onShowTasks: () => setState(() => _tab = 1),
        ),
        TasksPage(controller: controller),
        ResourcesPage(controller: controller),
        FilesPage(
          key: ValueKey('${controller.isDemo}-${controller.profile?.root}'),
          controller: controller,
        ),
        SettingsPage(
          controller: controller,
          trustPrompt: _trustHost,
          onEdit: _editConnection,
          themeMode: widget.themeMode,
          onThemeChanged: widget.onThemeChanged,
        ),
      ];
      return Scaffold(
        appBar: AppBar(
          toolbarHeight: 64,
          titleSpacing: 22,
          title: Row(
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: clay,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: const Icon(
                  Icons.waves_rounded,
                  color: Colors.white,
                  size: 21,
                ),
              ),
              const SizedBox(width: 10),
              const Flexible(
                child: Text(
                  'Lumerical',
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 19,
                    letterSpacing: -.5,
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Text(
                'MONITOR',
                style: TextStyle(
                  fontSize: 8,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.3,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
          actions: [
            if (controller.isBusy || _initializing)
              const Padding(
                padding: EdgeInsets.all(19),
                child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              )
            else if (hasData || controller.profile != null)
              IconButton(
                tooltip: '刷新数据',
                onPressed: () => _run(
                  () =>
                      controller.phase == ConnectionPhase.connected ||
                          controller.isDemo
                      ? controller.refresh()
                      : controller.connect(_trustHost),
                ),
                icon: const Icon(Icons.refresh_rounded, size: 22),
              ),
            const SizedBox(width: 9),
          ],
        ),
        body: SafeArea(
          top: false,
          bottom: false,
          child: Column(
            children: [
              _ConnectionStrip(controller: controller),
              if (_initializing) const LinearProgressIndicator(minHeight: 2),
              if (controller.errorMessage?.isNotEmpty == true)
                _ErrorStrip(
                  message: controller.errorMessage!,
                  onSettings: () => setState(() => _tab = 4),
                ),
              Expanded(child: pages[_tab]),
            ],
          ),
        ),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _tab,
          onDestinationSelected: (value) => setState(() => _tab = value),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.space_dashboard_outlined),
              selectedIcon: Icon(Icons.space_dashboard_rounded),
              label: '概览',
            ),
            NavigationDestination(
              icon: Icon(Icons.layers_outlined),
              selectedIcon: Icon(Icons.layers_rounded),
              label: '仿真',
            ),
            NavigationDestination(
              icon: Icon(Icons.memory_outlined),
              selectedIcon: Icon(Icons.memory_rounded),
              label: '资源',
            ),
            NavigationDestination(
              icon: Icon(Icons.folder_outlined),
              selectedIcon: Icon(Icons.folder_rounded),
              label: '文件',
            ),
            NavigationDestination(
              icon: Icon(Icons.tune_outlined),
              selectedIcon: Icon(Icons.tune_rounded),
              label: '设置',
            ),
          ],
        ),
      );
    },
  );
}

class _ConnectionStrip extends StatelessWidget {
  const _ConnectionStrip({required this.controller});
  final MonitorController controller;
  @override
  Widget build(BuildContext context) {
    final phase = controller.phase;
    final label = switch (phase) {
      ConnectionPhase.demo => '演示 · 合成数据',
      ConnectionPhase.connected => '已连接',
      ConnectionPhase.connecting => '正在连接',
      ConnectionPhase.paused => '后台已暂停',
      ConnectionPhase.error => '连接异常',
      ConnectionPhase.disconnected => '未连接',
    };
    final updated = controller.lastUpdated?.toLocal();
    final stale =
        updated != null &&
        !controller.isDemo &&
        (phase != ConnectionPhase.connected ||
            DateTime.now().difference(updated).inSeconds >
                (controller.profile?.refreshSeconds ?? 15) * 2);
    return Padding(
      padding: const EdgeInsets.fromLTRB(22, 0, 22, 10),
      child: Row(
        children: [
          StatusPill(
            label,
            color: controller.isDemo
                ? clay
                : phase == ConnectionPhase.connected
                ? success
                : const Color(0xFF857C6F),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              controller.isDemo
                  ? '仅供体验 · 未连接服务器'
                  : updated == null
                  ? '通过 SSH 安全直连'
                  : '更新于 ${updated.hour.toString().padLeft(2, '0')}:${updated.minute.toString().padLeft(2, '0')}:${updated.second.toString().padLeft(2, '0')}',
              maxLines: 2,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          if (stale)
            const StatusPill('数据较旧', color: clay, icon: Icons.schedule),
        ],
      ),
    );
  }
}

class _ErrorStrip extends StatelessWidget {
  const _ErrorStrip({required this.message, required this.onSettings});
  final String message;
  final VoidCallback onSettings;
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: const EdgeInsets.fromLTRB(22, 0, 22, 10),
    padding: const EdgeInsets.fromLTRB(13, 8, 6, 8),
    decoration: BoxDecoration(
      color: clay.withValues(alpha: .1),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      children: [
        const Icon(Icons.info_outline, size: 17, color: clay),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            message,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 11),
          ),
        ),
        TextButton(onPressed: onSettings, child: const Text('设置')),
      ],
    ),
  );
}
