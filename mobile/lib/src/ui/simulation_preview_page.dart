import 'dart:async';

import 'package:flutter/material.dart';

import 'preview_charts.dart';
import 'shared.dart';

/// Displays the same saved preview document used by the desktop client.
class SimulationPreviewPage extends StatefulWidget {
  const SimulationPreviewPage({
    super.key,
    required this.path,
    required this.load,
    required this.generate,
    this.running = false,
  });

  final String path;
  final Future<Map<String, dynamic>> Function(String) load;
  final Future<Map<String, dynamic>> Function(
    String,
    double wavelengthM,
    double zM,
  )
  generate;
  final bool running;

  @override
  State<SimulationPreviewPage> createState() => _SimulationPreviewPageState();
}

class _SimulationPreviewPageState extends State<SimulationPreviewPage> {
  final _wavelength = TextEditingController(text: '1550');
  final _z = TextEditingController(text: '0');
  late String _project;
  Map<String, dynamic>? _info;
  String? _error;
  String? _settingsError;
  bool _loading = false;
  bool _generating = false;
  int _request = 0;
  int _tab = 0;
  int _field = 0;
  int _spectrum = 0;

  bool get _busy => _loading || _generating;
  Map<String, dynamic>? get _document {
    if (_info?['available'] != true || _info?['document'] is! Map) return null;
    return object(_info!['document']);
  }

  @override
  void initState() {
    super.initState();
    _project = widget.path;
    unawaited(_read(_project));
  }

  @override
  void didUpdateWidget(SimulationPreviewPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.path != oldWidget.path) unawaited(_read(widget.path));
  }

  @override
  void dispose() {
    _request++;
    _wavelength.dispose();
    _z.dispose();
    super.dispose();
  }

  void _accept(Map<String, dynamic> result) {
    final previous = _project;
    _info = result;
    _project = textValue(result['project'], _project);
    if (previous != _project) {
      _field = 0;
      _spectrum = 0;
    }
  }

  Future<void> _read(String path) async {
    final request = ++_request;
    setState(() {
      if (path != _project) {
        _info = null;
        _field = 0;
        _spectrum = 0;
      }
      _project = path;
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.load(path);
      if (!mounted || request != _request) return;
      setState(() => _accept(result));
    } catch (error) {
      if (mounted && request == _request) {
        setState(() => _error = '预览不可用：$error');
      }
    } finally {
      if (mounted && request == _request) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _confirmGeneration() async {
    if (_busy || widget.running) return;
    final wavelengthNm = double.tryParse(_wavelength.text.trim());
    final zUm = double.tryParse(_z.text.trim());
    String? error;
    if (wavelengthNm == null || !wavelengthNm.isFinite || wavelengthNm <= 0) {
      error = '波长必须是大于 0 的有限数字';
    } else if (zUm == null || !zUm.isFinite) {
      error = '截面位置必须是有限数字';
    }
    setState(() => _settingsError = error);
    if (error != null) return;

    final project = _project;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('生成预览缓存'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '此操作会启动 Lumerical GUI，可能占用 GUI 许可证。'
                '只读取已保存的模型与结果，写入独立 .preview.json 缓存；'
                '不会运行求解器，也不会覆盖原工程。',
              ),
              const SizedBox(height: 14),
              Text(project),
              const SizedBox(height: 8),
              Text(
                '目标波长：${_wavelength.text.trim()} nm\n'
                '模型 XY 截面：z = ${_z.text.trim()} µm',
              ),
              const SizedBox(height: 8),
              const Text('场图会标注实际保存的波长与截面，可能与目标不同。'),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认生成'),
          ),
        ],
      ),
    );
    if (!mounted ||
        confirmed != true ||
        widget.running ||
        _busy ||
        project != _project) {
      return;
    }

    final request = ++_request;
    setState(() {
      _generating = true;
      _error = null;
    });
    try {
      final result = await widget.generate(
        project,
        wavelengthNm! * 1e-9,
        zUm! * 1e-6,
      );
      if (mounted && request == _request) setState(() => _accept(result));
    } catch (error) {
      if (mounted && request == _request) {
        setState(() => _error = '生成预览失败：$error');
      }
    } finally {
      // A project change rejects the result, but the operation still finished.
      if (mounted) {
        setState(() => _generating = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 4,
    child: Scaffold(
      appBar: AppBar(
        title: const Text('仿真预览'),
        bottom: TabBar(
          labelPadding: const EdgeInsets.symmetric(horizontal: 3),
          labelStyle: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
          onTap: (index) => setState(() => _tab = index),
          tabs: const [
            Tab(text: '模型示意'),
            Tab(text: '模场电场'),
            Tab(text: '透射谱T'),
            Tab(text: '参数'),
          ],
        ),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _controls(context),
            const SizedBox(height: 14),
            if (_busy) ...[
              const LinearProgressIndicator(),
              const SizedBox(height: 10),
              Text(_generating ? '正在生成预览缓存…' : '正在读取预览缓存…'),
              const SizedBox(height: 10),
            ],
            if (_error != null) ...[
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              const SizedBox(height: 10),
            ],
            if (_info != null) ...[
              Text(textValue(_info!['message'], '已读取预览缓存')),
              const SizedBox(height: 8),
            ],
            if (_info?['stale'] == true) ...[
              const StatusPill(
                '缓存已过期 · 原工程已变化',
                color: clay,
                icon: Icons.history,
              ),
              const SizedBox(height: 10),
            ],
            if (widget.running) ...[
              const StatusPill(
                '任务运行中 · 显示已保存缓存',
                icon: Icons.lock_clock_outlined,
              ),
              const SizedBox(height: 10),
            ],
            _content(context),
            const SizedBox(height: 24),
          ],
        ),
      ),
    ),
  );

  Widget _controls(BuildContext context) {
    final projects = <String>{
      _project,
      if (_info?['projects'] is List)
        for (final path in _info!['projects'])
          if (path is String && path.isNotEmpty) path,
    }.toList();
    return SurfaceCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (projects.length > 1)
            DropdownButtonFormField<String>(
              key: ValueKey('preview-project'),
              initialValue: _project,
              isExpanded: true,
              decoration: const InputDecoration(labelText: '工程文件'),
              items: projects
                  .map(
                    (path) => DropdownMenuItem(
                      value: path,
                      child: Text(
                        path,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  )
                  .toList(),
              onChanged: _busy
                  ? null
                  : (path) {
                      if (path != null) unawaited(_read(path));
                    },
            )
          else ...[
            Text('工程文件', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 4),
            SelectableText(_project),
          ],
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final fields = [
                TextField(
                  key: const ValueKey('preview-wavelength'),
                  controller: _wavelength,
                  enabled: !_busy && !widget.running,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(labelText: '目标波长 (nm)'),
                ),
                TextField(
                  key: const ValueKey('preview-z'),
                  controller: _z,
                  enabled: !_busy && !widget.running,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                    signed: true,
                  ),
                  decoration: const InputDecoration(labelText: 'XY 截面 z (µm)'),
                ),
              ];
              if (constraints.maxWidth < 300) {
                return Column(
                  children: [fields[0], const SizedBox(height: 14), fields[1]],
                );
              }
              return Row(
                children: [
                  Expanded(child: fields[0]),
                  const SizedBox(width: 12),
                  Expanded(child: fields[1]),
                ],
              );
            },
          ),
          if (_settingsError != null) ...[
            const SizedBox(height: 8),
            Text(
              _settingsError!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 16),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              OutlinedButton.icon(
                onPressed: _busy ? null : () => unawaited(_read(_project)),
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('读取缓存'),
              ),
              FilledButton(
                onPressed: _busy || widget.running ? null : _confirmGeneration,
                child: const Text('生成 / 更新预览'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _content(BuildContext context) {
    final document = _document;
    if (document == null) {
      return const EmptyState(
        title: '暂无可显示的预览',
        message: '读取已有缓存，或确认后生成模型、已保存场结果、透射谱和参数。',
        icon: Icons.area_chart_outlined,
      );
    }
    switch (_tab) {
      case 0:
        return ModelPreviewChart(entry: object(document['model']));
      case 1:
        final fields = records(document['fields']);
        if (fields.isEmpty) return _missing('未保存可显示的二维场结果');
        final selected = _field.clamp(0, fields.length - 1);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _entryPicker(
              '选择场监视器',
              fields,
              selected,
              (index) => setState(() => _field = index),
            ),
            const SizedBox(height: 14),
            FieldPreviewChart(entry: fields[selected]),
          ],
        );
      case 2:
        final spectra = records(document['spectra']);
        if (spectra.isEmpty) return _missing('未保存 T 光谱');
        final selected = _spectrum.clamp(0, spectra.length - 1);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _entryPicker(
              '选择透射监视器',
              spectra,
              selected,
              (index) => setState(() => _spectrum = index),
            ),
            const SizedBox(height: 14),
            SpectrumPreviewChart(entry: spectra[selected]),
          ],
        );
      default:
        return _parameters(context, document);
    }
  }

  Widget _entryPicker(
    String label,
    List<Map<String, dynamic>> entries,
    int selected,
    ValueChanged<int> onChanged,
  ) => DropdownButtonFormField<int>(
    key: ValueKey('$label-$_project'),
    initialValue: selected,
    isExpanded: true,
    decoration: InputDecoration(labelText: label),
    items: [
      for (var index = 0; index < entries.length; index++)
        DropdownMenuItem(
          value: index,
          child: Text(
            '${index + 1}. ${textValue(entries[index]['name'], '未命名')}',
            overflow: TextOverflow.ellipsis,
          ),
        ),
    ],
    onChanged: (index) {
      if (index != null) onChanged(index);
    },
  );

  Widget _missing(String message) => EmptyState(
    title: message,
    message: '只有工程中已保存的结果能够生成预览。',
    icon: Icons.query_stats,
  );

  Widget _parameters(BuildContext context, Map<String, dynamic> document) =>
      SurfaceCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('参数与说明', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 12),
            SelectableText(
              '工程：${textValue(object(document['source'])['path'], _project)}\n'
              '缓存生成：${textValue(document['generated_utc'])}',
            ),
            const SizedBox(height: 16),
            const Text(
              '场图显示记录单位下的 |E|²，实际波长与截面以图中标注为准。'
              '\nT 保留监视器的方向符号，不等同于某个模式的耦合效率。',
            ),
            const SizedBox(height: 16),
            for (final item in records(document['parameters'])) ...[
              SelectableText(_parameterText(item)),
              const SizedBox(height: 10),
            ],
            if (records(document['parameters']).isEmpty) const Text('未保存参数'),
            if (document['warnings'] is List)
              for (final warning in document['warnings']) ...[
                const SizedBox(height: 10),
                Text(
                  '• $warning',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
          ],
        ),
      );

  String _parameterText(Map<String, dynamic> item) {
    final value = number(item['value']);
    var display = value?.toStringAsPrecision(8) ?? textValue(item['value']);
    final imaginary = number(item['imag']);
    if (imaginary != null && imaginary != 0) {
      display +=
          ' ${imaginary < 0 ? '-' : '+'}${imaginary.abs().toStringAsPrecision(8)}j';
    }
    final wavelength = number(item['wavelength_m']);
    final unit = textValue(item['unit'], '');
    return '${textValue(item['name'])}：$display${unit.isEmpty ? '' : ' $unit'}'
        '${wavelength == null ? '' : ' · λ=${(wavelength * 1e9).toStringAsPrecision(5)} nm'}';
  }
}
