import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';

import '../services/monitor_controller.dart';
import 'shared.dart';

class FilesPage extends StatefulWidget {
  const FilesPage({super.key, required this.controller});
  final MonitorController controller;
  @override
  State<FilesPage> createState() => _FilesPageState();
}

class _FilesPageState extends State<FilesPage> {
  String _path = '.';
  Map<String, dynamic>? _listing;
  String? _error;
  bool _loading = false;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    if (widget.controller.snapshot != null) unawaited(_load('.'));
  }

  Future<void> _load(String path) async {
    final generation = ++_generation;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.controller.listFiles(path);
      if (mounted && generation == _generation) {
        setState(() {
          _listing = result;
          _path = textValue(result['path'], path);
        });
      }
    } catch (e) {
      if (mounted && generation == _generation) setState(() => _error = '$e');
    } finally {
      if (mounted && generation == _generation) {
        setState(() => _loading = false);
      }
    }
  }

  void _up() {
    final parts = _path
        .split('/')
        .where((part) => part.isNotEmpty && part != '.')
        .toList();
    if (parts.isNotEmpty) parts.removeLast();
    unawaited(_load(parts.isEmpty ? '.' : parts.join('/')));
  }

  Future<void> _openFile(Map<String, dynamic> entry) async {
    final path = textValue(entry['path'], '');
    if (path.isEmpty) return;
    final action = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 0, 22, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                textValue(entry['name']),
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 5),
              Text(
                bytes(entry['size']),
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 20),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.article_outlined),
                title: const Text('预览日志 / 文本尾部'),
                subtitle: const Text('仅加载有上限的末尾内容'),
                onTap: () => Navigator.pop(context, 'preview'),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.download_outlined),
                title: const Text('下载并导出'),
                subtitle: const Text('下载完成后选择保存或分享'),
                onTap: () => Navigator.pop(context, 'download'),
              ),
            ],
          ),
        ),
      ),
    );
    if (!mounted || action == null) return;
    if (action == 'preview') {
      await Navigator.push(
        context,
        MaterialPageRoute<void>(
          builder: (_) =>
              LogPreviewPage(controller: widget.controller, path: path),
        ),
      );
    } else {
      await Navigator.push(
        context,
        MaterialPageRoute<void>(
          builder: (_) =>
              DownloadPage(controller: widget.controller, path: path),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.controller.snapshot == null) {
      return ListView(
        padding: const EdgeInsets.all(22),
        children: const [
          SectionTitle('项目文件'),
          EmptyState(
            title: '连接后浏览文件',
            message: '查看项目目录、预览日志，并下载需要的结果文件。',
            icon: Icons.folder_outlined,
          ),
        ],
      );
    }
    final entries = records(_listing?['entries']);
    return RefreshIndicator(
      onRefresh: () => _load(_path),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 26),
        children: [
          Text('项目文件', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 6),
          Text(
            '只读浏览 · 范围限定在设置的项目根目录',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 22),
          SurfaceCard(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                IconButton(
                  onPressed: _path == '.' || _path.isEmpty || _loading
                      ? null
                      : _up,
                  tooltip: '上一级目录',
                  icon: const Icon(Icons.arrow_upward_rounded, size: 19),
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    _path == '.' || _path.isEmpty ? '项目根目录' : _path,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (_loading)
                  const Padding(
                    padding: EdgeInsets.all(12),
                    child: SizedBox(
                      width: 17,
                      height: 17,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  )
                else
                  IconButton(
                    onPressed: () => _load(_path),
                    tooltip: '刷新目录',
                    icon: const Icon(Icons.refresh_rounded, size: 19),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 15),
          if (_error != null)
            EmptyState(
              title: '无法读取目录',
              message: _error!,
              icon: Icons.folder_off_outlined,
              actions: OutlinedButton(
                onPressed: () => _load(_path),
                child: const Text('重试'),
              ),
            )
          else if (!_loading && entries.isEmpty)
            const EmptyState(
              title: '目录为空',
              message: '此目录没有可显示的文件。',
              icon: Icons.folder_open_rounded,
            )
          else
            ...spaced(
              entries.map(
                (entry) => SurfaceCard(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 2,
                  ),
                  child: ListTile(
                    onTap: _loading
                        ? null
                        : () => entry['directory'] == true
                              ? _load(textValue(entry['path'], '.'))
                              : _openFile(entry),
                    leading: Container(
                      padding: const EdgeInsets.all(9),
                      decoration: BoxDecoration(
                        color:
                            (entry['directory'] == true
                                    ? clay
                                    : const Color(0xFF64718A))
                                .withValues(alpha: .09),
                        borderRadius: BorderRadius.circular(11),
                      ),
                      child: Icon(
                        entry['directory'] == true
                            ? Icons.folder_outlined
                            : Icons.insert_drive_file_outlined,
                        size: 21,
                        color: entry['directory'] == true
                            ? clay
                            : const Color(0xFF64718A),
                      ),
                    ),
                    title: Text(
                      textValue(entry['name']),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    subtitle: Text(
                      entry['directory'] == true
                          ? '目录${entry['symlink'] == true ? ' · 符号链接' : ''}'
                          : bytes(entry['size']),
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    trailing: const Icon(Icons.chevron_right_rounded, size: 19),
                  ),
                ),
              ),
              9,
            ),
          if (_listing?['limit_reached'] == true)
            Padding(
              padding: const EdgeInsets.only(top: 15),
              child: Text(
                '目录项目已达到采集上限，请进入子目录继续查找。',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        ],
      ),
    );
  }
}

class LogPreviewPage extends StatefulWidget {
  const LogPreviewPage({
    super.key,
    required this.controller,
    required this.path,
  });
  final MonitorController controller;
  final String path;
  @override
  State<LogPreviewPage> createState() => _LogPreviewPageState();
}

class _LogPreviewPageState extends State<LogPreviewPage> {
  late Future<Map<String, dynamic>> _future = widget.controller.readLog(
    widget.path,
  );
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('日志预览'),
      actions: [
        IconButton(
          tooltip: '重新读取日志',
          onPressed: () =>
              setState(() => _future = widget.controller.readLog(widget.path)),
          icon: const Icon(Icons.refresh_rounded),
        ),
      ],
    ),
    body: FutureBuilder<Map<String, dynamic>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return ListView(
            padding: const EdgeInsets.all(22),
            children: [
              EmptyState(
                title: '无法读取日志',
                message: '${snapshot.error}',
                icon: Icons.article_outlined,
              ),
            ],
          );
        }
        final data = snapshot.data ?? {};
        final raw = textValue(data['text'], '（文件内容为空）');
        const maxCharacters = 131072;
        final clipped = raw.length > maxCharacters;
        final text = clipped ? raw.substring(raw.length - maxCharacters) : raw;
        return ListView(
          padding: const EdgeInsets.all(22),
          children: [
            if (widget.controller.isDemo)
              const Padding(
                padding: EdgeInsets.only(bottom: 12),
                child: StatusPill('演示日志 · 合成数据', color: clay),
              ),
            Text(widget.path, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              '文件 ${bytes(data['size'])} · 仅显示有上限的尾部文本${clipped || data['truncated'] == true ? ' · 内容已截断' : ''}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 18),
            SurfaceCard(
              padding: const EdgeInsets.all(15),
              child: SelectableText(
                text,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 11,
                  height: 1.65,
                ),
              ),
            ),
            const SizedBox(height: 18),
            OutlinedButton.icon(
              onPressed: () => Navigator.push(
                context,
                MaterialPageRoute<void>(
                  builder: (_) => DownloadPage(
                    controller: widget.controller,
                    path: widget.path,
                  ),
                ),
              ),
              icon: const Icon(Icons.download_outlined),
              label: const Text('下载完整文件'),
            ),
          ],
        );
      },
    ),
  );
}

class DownloadPage extends StatefulWidget {
  const DownloadPage({super.key, required this.controller, required this.path});
  final MonitorController controller;
  final String path;
  @override
  State<DownloadPage> createState() => _DownloadPageState();
}

class _DownloadPageState extends State<DownloadPage> {
  File? _file;
  String? _error;
  bool _finished = false;
  bool _sharing = false;
  int _received = 0, _total = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_download());
  }

  Future<void> _download() async {
    try {
      final file = await widget.controller.download(
        widget.path,
        onProgress: (received, total) {
          if (mounted) {
            setState(() {
              _received = received;
              _total = total;
            });
          }
        },
      );
      if (mounted) setState(() => _file = file);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      _finished = true;
      if (mounted) setState(() {});
    }
  }

  Future<void> _share(BuildContext buttonContext) async {
    if (_file == null || _sharing) return;
    final renderBox = buttonContext.findRenderObject() as RenderBox?;
    final origin = renderBox == null
        ? const Rect.fromLTWH(0, 0, 1, 1)
        : renderBox.localToGlobal(Offset.zero) & renderBox.size;
    setState(() => _sharing = true);
    try {
      await SharePlus.instance.share(
        ShareParams(files: [XFile(_file!.path)], sharePositionOrigin: origin),
      );
    } catch (e) {
      if (mounted) showMessage(context, '无法导出文件：$e');
    } finally {
      if (mounted) setState(() => _sharing = false);
    }
  }

  @override
  void dispose() {
    if (!_finished) unawaited(widget.controller.cancelDownload());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('下载与导出')),
    body: ListView(
      padding: const EdgeInsets.all(22),
      children: [
        if (widget.controller.isDemo)
          const Padding(
            padding: EdgeInsets.only(bottom: 16),
            child: StatusPill('演示文件 · 合成数据', color: clay),
          ),
        EmptyState(
          title: _error != null
              ? '下载未完成'
              : _finished
              ? '文件已准备好'
              : '正在下载文件',
          message: _error ?? widget.path,
          icon: _error != null
              ? Icons.error_outline
              : _finished
              ? Icons.task_alt_rounded
              : Icons.downloading_rounded,
          actions: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (!_finished) ...[
                LinearProgressIndicator(
                  value: _total > 0 ? (_received / _total).clamp(0, 1) : null,
                ),
                const SizedBox(height: 10),
                Text(
                  '${bytes(_received)} / ${_total > 0 ? bytes(_total) : '等待文件大小'}',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 20),
                OutlinedButton(
                  onPressed: () async {
                    await widget.controller.cancelDownload();
                    if (context.mounted) Navigator.pop(context);
                  },
                  child: const Text('取消下载'),
                ),
              ],
              if (_file != null)
                Builder(
                  builder: (buttonContext) => FilledButton.icon(
                    onPressed: _sharing ? null : () => _share(buttonContext),
                    icon: const Icon(Icons.ios_share_rounded, size: 19),
                    label: Text(_sharing ? '正在打开导出…' : '保存或分享文件'),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 18),
        Text(
          '文件以流式方式下载到本机临时目录。导出时可选择系统“文件”或其他应用。',
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    ),
  );
}
