import 'package:flutter/material.dart';

import '../services/monitor_controller.dart';
import 'files_page.dart';
import 'shared.dart';
import 'preview_navigation.dart';

class TasksPage extends StatefulWidget {
  const TasksPage({super.key, required this.controller});
  final MonitorController controller;
  @override
  State<TasksPage> createState() => _TasksPageState();
}

class _TasksPageState extends State<TasksPage> {
  String _filter = '全部';
  String _search = '';
  @override
  Widget build(BuildContext context) {
    final jobs = records(widget.controller.snapshot?['jobs']);
    final filtered = jobs.where((j) {
      final state = textValue(j['state']);
      final match =
          _filter == '全部' ||
          (_filter == '需关注'
              ? state == '失败' || state.contains('检查') || j['stalled'] == true
              : state == _filter);
      return match &&
          '${j['name']} ${j['path']} ${j['solver']}'.toLowerCase().contains(
            _search.toLowerCase(),
          );
    }).toList();
    return RefreshIndicator(
      onRefresh: () => runWithFeedback(context, widget.controller.refresh),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 26),
        children: [
          Text('仿真任务', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 6),
          Text(
            '近期求解任务与管线 · ${jobs.length} 项',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 20),
          TextField(
            onChanged: (v) => setState(() => _search = v),
            decoration: const InputDecoration(
              hintText: '搜索任务、路径或求解器',
              prefixIcon: Icon(Icons.search_rounded),
              isDense: true,
            ),
          ),
          const SizedBox(height: 14),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: ['全部', '运行中', '已完成', '需关注']
                  .map(
                    (filter) => Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(filter),
                        selected: _filter == filter,
                        onSelected: (_) => setState(() => _filter = filter),
                        showCheckmark: false,
                      ),
                    ),
                  )
                  .toList(),
            ),
          ),
          const SizedBox(height: 18),
          if (filtered.isEmpty)
            EmptyState(
              title: widget.controller.snapshot == null
                  ? '连接后查看仿真任务'
                  : '没有匹配的任务',
              message: widget.controller.snapshot == null
                  ? '在设置中添加服务器连接，或从概览查看演示。'
                  : '可以切换筛选条件，或稍后刷新。',
              icon: Icons.layers_outlined,
            )
          else
            ...spaced(
              filtered.map(
                (job) => TaskCard(job: job, controller: widget.controller),
              ),
            ),
          const SizedBox(height: 18),
          Text(
            '状态由可见进程和日志推断。日志长期未更新会提示检查，不代表求解一定失败。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class TaskCard extends StatelessWidget {
  const TaskCard({super.key, required this.job, required this.controller});
  final Map<String, dynamic> job;
  final MonitorController controller;
  @override
  Widget build(BuildContext context) {
    final state = textValue(job['state'], '未知/未完成');
    final progress = number(job['progress']);
    final resources = object(job['resources']);
    return Semantics(
      button: true,
      label: '查看任务 ${textValue(job['name'])}',
      child: SurfaceCard(
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) => TaskDetailPage(job: job, controller: controller),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  textValue(job['solver'], 'Lumerical'),
                  style: TextStyle(
                    color: stateColor(state),
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .8,
                  ),
                ),
                StatusPill(state, color: stateColor(state)),
                if (job['stalled'] == true)
                  const StatusPill('日志待检查', color: clay, icon: Icons.schedule),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: Text(
                    textValue(job['name'], textValue(job['path'], '未命名任务')),
                    style: Theme.of(context).textTheme.titleMedium,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 8),
                Icon(
                  Icons.chevron_right_rounded,
                  size: 19,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ],
            ),
            const SizedBox(height: 5),
            Text(
              textValue(job['path']),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 17),
            Row(
              children: [
                Expanded(
                  child: Text(
                    textValue(job['stage'], state == '运行中' ? '求解中' : '任务记录'),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
                Text(
                  progress == null ? '进度未知' : percent(progress),
                  style: TextStyle(
                    fontSize: 12,
                    color: stateColor(state),
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            MetricBar(
              value: progress == null ? null : progress / 100,
              color: stateColor(state),
            ),
            const SizedBox(height: 13),
            Wrap(
              spacing: 14,
              runSpacing: 5,
              children: [
                Text(
                  'CPU ${percent(resources['cpu_percent'])}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                Text(
                  '内存 ${bytes(resources['rss_bytes'])}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (textValue(job['remaining'], '').isNotEmpty)
                  Text(
                    '剩余 ${job['remaining']}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class TaskDetailPage extends StatelessWidget {
  const TaskDetailPage({
    super.key,
    required this.job,
    required this.controller,
  });
  final Map<String, dynamic> job;
  final MonitorController controller;
  @override
  Widget build(BuildContext context) {
    final resources = object(job['resources']);
    final errors = job['errors'] is List ? job['errors'] as List : const [];
    return Scaffold(
      appBar: AppBar(title: const Text('仿真详情')),
      body: ListView(
        padding: const EdgeInsets.all(22),
        children: [
          if (controller.isDemo)
            const Padding(
              padding: EdgeInsets.only(bottom: 16),
              child: StatusPill('演示详情 · 合成数据', color: clay),
            ),
          Text(
            textValue(job['name'], '未命名任务'),
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 10),
          StatusPill(
            textValue(job['state']),
            color: stateColor(textValue(job['state'])),
          ),
          const SizedBox(height: 22),
          SurfaceCard(
            child: Column(
              children: [
                DetailRow('求解器', textValue(job['solver'])),
                DetailRow('项目路径', textValue(job['path'])),
                DetailRow('计算阶段', textValue(job['stage'])),
                DetailRow('进度', percent(job['progress'])),
                DetailRow('预计剩余', textValue(job['remaining'])),
                DetailRow('运行时间', elapsed(resources['elapsed_seconds'])),
                DetailRow('CPU 使用', percent(resources['cpu_percent'])),
                DetailRow('内存', bytes(resources['rss_bytes'])),
                DetailRow(
                  '线程 / PID',
                  '${textValue(resources['threads'])} / ${job['pids'] is List ? (job['pids'] as List).join(', ') : '—'}',
                ),
                DetailRow('GPU 显存', bytes(resources['gpu_memory'])),
                DetailRow('Auto Shutoff', textValue(job['shutoff'])),
              ],
            ),
          ),
          if (errors.isNotEmpty) ...[
            const SectionTitle('日志中的异常'),
            SurfaceCard(
              child: SelectableText(
                errors.join('\n'),
                style: const TextStyle(color: clay, fontSize: 12, height: 1.6),
              ),
            ),
          ],
          if (textValue(job['path'], '').isNotEmpty) ...[
            const SectionTitle('模型与结果'),
            TaskModelPreview(
              controller: controller,
              path: textValue(job['path']),
            ),
          ],
          const SectionTitle('日志与文件'),
          ...spaced(
            ['log', 'engine_log']
                .where((key) => textValue(job[key], '').isNotEmpty)
                .map(
                  (key) => SurfaceCard(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 4,
                    ),
                    child: ListTile(
                      leading: const Icon(Icons.article_outlined, color: clay),
                      title: Text(key == 'log' ? '求解器日志' : '引擎日志'),
                      subtitle: Text(
                        textValue(job[key]),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute<void>(
                          builder: (_) => LogPreviewPage(
                            controller: controller,
                            path: '${job[key]}',
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
          ),
          if (textValue(job['log'], '').isEmpty &&
              textValue(job['engine_log'], '').isEmpty)
            const SurfaceCard(child: Text('此任务暂无可读取的日志路径。')),
          const SizedBox(height: 20),
          Text(
            '详情来自打开时的快照。返回列表并刷新可获取最新进展。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
