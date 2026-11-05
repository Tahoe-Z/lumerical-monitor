import 'package:flutter/material.dart';

import '../services/monitor_controller.dart';
import 'shared.dart';
import 'tasks_page.dart';

class OverviewPage extends StatelessWidget {
  const OverviewPage({
    super.key,
    required this.controller,
    required this.onConnect,
    required this.onShowTasks,
  });
  final MonitorController controller;
  final VoidCallback onConnect;
  final VoidCallback onShowTasks;
  @override
  Widget build(BuildContext context) {
    final data = controller.snapshot;
    if (data == null) {
      return ListView(
        padding: const EdgeInsets.all(22),
        children: [
          const SectionTitle('随时掌握仿真进展', subtitle: '服务器状态、求解进度与文件，尽在掌中。'),
          const SizedBox(height: 16),
          EmptyState(
            title: '尚未连接服务器',
            message: '连接您的 Linux 服务器，查看 Lumerical 仿真与资源使用情况。',
            icon: Icons.dns_outlined,
            actions: SizedBox(
              width: double.infinity,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  FilledButton.icon(
                    onPressed: onConnect,
                    icon: const Icon(Icons.add_link_rounded, size: 19),
                    label: const Text('连接服务器'),
                  ),
                  const SizedBox(height: 10),
                  OutlinedButton(
                    onPressed: controller.showDemo,
                    child: const Text('查看演示'),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 22),
          const Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.lock_outline_rounded, size: 16, color: success),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'SSH 直连 · 只读监控\n密钥保存在本机安全存储，无需托管后端。',
                  style: TextStyle(fontSize: 11, height: 1.7),
                ),
              ),
            ],
          ),
        ],
      );
    }
    final jobs = records(data['jobs']);
    final running = jobs.where((j) => j['state'] == '运行中').toList();
    final needsAttention = jobs
        .where(
          (j) =>
              j['state'] == '失败' ||
              j['stalled'] == true ||
              '${j['state']}'.contains('检查'),
        )
        .length;
    final gpu = object(data['gpu']);
    final devices = records(gpu['devices']);
    final gpuValues = devices
        .map((d) => number(d['utilization_percent']))
        .whereType<double>()
        .toList();
    final gpuAverage = gpuValues.isEmpty
        ? null
        : gpuValues.reduce((a, b) => a + b) / gpuValues.length;
    final memoryTotal = number(data['memory_total']);
    final memoryAvailable = number(data['memory_available']);
    final memoryUsed = memoryTotal != null && memoryAvailable != null
        ? memoryTotal - memoryAvailable
        : null;
    final memoryRatio =
        memoryTotal != null && memoryTotal > 0 && memoryUsed != null
        ? memoryUsed / memoryTotal
        : null;
    return RefreshIndicator(
      onRefresh: () => runWithFeedback(context, controller.refresh),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 26),
        children: [
          Text('服务器概览', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 6),
          Text(
            controller.isDemo
                ? '演示工作站 · 所有数值均为合成数据'
                : textValue(data['hostname'], '我的服务器'),
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 22),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 580 ? 4 : 2;
              final cardWidth =
                  (constraints.maxWidth - (columns - 1) * 12) / columns;
              return Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  SizedBox(
                    width: cardWidth,
                    child: _MetricCard(
                      title: 'CPU 使用率',
                      value: percent(data['cpu_percent']),
                      subtitle: '${textValue(data['cpu_count'])} 个逻辑核心',
                      icon: Icons.memory_rounded,
                      ratio: number(data['cpu_percent']) == null
                          ? null
                          : number(data['cpu_percent'])! / 100,
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: _MetricCard(
                      title: '内存使用',
                      value: memoryRatio == null
                          ? '—'
                          : percent(memoryRatio * 100),
                      subtitle: '${bytes(memoryUsed)} / ${bytes(memoryTotal)}',
                      icon: Icons.storage_rounded,
                      ratio: memoryRatio,
                      color: const Color(0xFF8A7C65),
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: _MetricCard(
                      title: 'GPU 使用率',
                      value: percent(gpuAverage),
                      subtitle: devices.isEmpty
                          ? '暂无可用 GPU 数据'
                          : '${devices.length} 块设备 · 平均使用率',
                      icon: Icons.developer_board_rounded,
                      ratio: gpuAverage == null ? null : gpuAverage / 100,
                      color: success,
                    ),
                  ),
                  SizedBox(
                    width: cardWidth,
                    child: _MetricCard(
                      title: '运行中仿真',
                      value: '${running.length}',
                      subtitle: '共 ${jobs.length} 项近期任务',
                      icon: Icons.play_circle_outline_rounded,
                      color: const Color(0xFF64718A),
                    ),
                  ),
                ],
              );
            },
          ),
          const SizedBox(height: 20),
          SectionTitle(
            '当前仿真',
            trailing: TextButton(
              onPressed: onShowTasks,
              child: const Text('查看全部'),
            ),
          ),
          if (running.isEmpty)
            const SurfaceCard(child: Text('当前没有检测到运行中的仿真。'))
          else
            ...spaced(
              running
                  .take(3)
                  .map((job) => TaskCard(job: job, controller: controller)),
            ),
          const SizedBox(height: 18),
          const SectionTitle('运行环境'),
          SurfaceCard(
            child: Column(
              children: [
                DetailRow('运行时间', elapsed(data['uptime_seconds'])),
                DetailRow(
                  '项目存储',
                  '${bytes(data['project_size'])} · 磁盘剩余 ${bytes(data['disk_free'])}',
                ),
                DetailRow(
                  '需要关注',
                  needsAttention == 0 ? '暂无异常信号' : '$needsAttention 项任务建议检查',
                ),
                DetailRow(
                  '自动刷新',
                  controller.isDemo
                      ? '演示数据不代表服务器状态'
                      : '每 ${controller.profile?.refreshSeconds ?? 15} 秒',
                ),
              ],
            ),
          ),
          const SizedBox(height: 15),
          Text(
            '任务状态来自进程与近期日志。已结束的任务仍需结合结果文件确认。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.title,
    required this.value,
    required this.subtitle,
    required this.icon,
    this.ratio,
    this.color = clay,
  });
  final String title, value, subtitle;
  final IconData icon;
  final double? ratio;
  final Color color;
  @override
  Widget build(BuildContext context) => SurfaceCard(
    padding: const EdgeInsets.all(16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 20, color: color),
        const SizedBox(height: 12),
        Text(title, style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 5),
        Text(
          value,
          style: Theme.of(context).textTheme.headlineMedium
              ?.copyWith(fontSize: 27),
        ),
        const SizedBox(height: 9),
        Text(
          subtitle,
          maxLines: 2,
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 15),
        MetricBar(value: ratio, color: color),
      ],
    ),
  );
}
