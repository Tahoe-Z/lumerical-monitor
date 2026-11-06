import 'package:flutter/material.dart';

import '../services/monitor_controller.dart';
import 'preview_charts.dart';
import 'simulation_preview_page.dart';
import 'shared.dart';

Future<void> openSimulationPreview(
  BuildContext context,
  MonitorController controller,
  String path,
) async {
  if (path.isEmpty) return;
  try {
    await Navigator.push<void>(
      context,
      MaterialPageRoute(
        builder: (_) => AnimatedBuilder(
          animation: controller,
          builder: (_, _) => SimulationPreviewPage(
            path: path,
            load: controller.readPreview,
            generate: controller.generatePreview,
            running: controller.isPreviewRunning(path),
          ),
        ),
      ),
    );
  } finally {
    await controller.cancelPreview();
  }
}

class TaskModelPreview extends StatefulWidget {
  const TaskModelPreview({
    super.key,
    required this.controller,
    required this.path,
  });
  final MonitorController controller;
  final String path;
  @override
  State<TaskModelPreview> createState() => _TaskModelPreviewState();
}

class _TaskModelPreviewState extends State<TaskModelPreview> {
  late Future<Map<String, dynamic>> _preview;
  @override
  void initState() {
    super.initState();
    _preview = widget.controller.readPreview(widget.path);
  }

  @override
  Widget build(BuildContext context) => SurfaceCard(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        FutureBuilder<Map<String, dynamic>>(
          future: _preview,
          builder: (context, snapshot) {
            final info = snapshot.data;
            final model = object(object(info?['document'])['model']);
            if (info?['available'] == true &&
                records(model['layers']).isNotEmpty) {
              return GestureDetector(
                onTap: () => openSimulationPreview(
                  context,
                  widget.controller,
                  widget.path,
                ),
                child: ModelPreviewChart(entry: model),
              );
            }
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 18),
              child: Text(
                snapshot.connectionState == ConnectionState.waiting
                    ? '正在读取模型缓存…'
                    : '打开模型与结果，读取或生成预览缓存。',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            );
          },
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: () =>
              openSimulationPreview(context, widget.controller, widget.path),
          icon: const Icon(Icons.view_in_ar_outlined),
          label: const Text('模型、模场与 T 结果'),
        ),
      ],
    ),
  );
}
