import 'package:flutter/material.dart';

import '../services/monitor_controller.dart';
import 'shared.dart';

class ResourcesPage extends StatefulWidget {
  const ResourcesPage({super.key, required this.controller});
  final MonitorController controller;
  @override
  State<ResourcesPage> createState() => _ResourcesPageState();
}

class _ResourcesPageState extends State<ResourcesPage> {
  bool _allProcesses = false;
  @override
  Widget build(BuildContext context) {
    final data = widget.controller.snapshot;
    if (data == null) {
      return ListView(
        padding: const EdgeInsets.all(22),
        children: const [
          SectionTitle('计算资源'),
          EmptyState(
            title: '连接后查看资源',
            message: 'GPU、进程、用户使用与 FlexLM 许可将在此显示。',
            icon: Icons.memory_outlined,
          ),
        ],
      );
    }
    final gpu = object(data['gpu']);
    final devices = records(gpu['devices']);
    final gpuProcesses = records(gpu['processes']);
    final processes = records(data['all_processes']);
    final users = records(data['users']);
    final license = object(data['license']);
    final features = records(license['features']);
    final visibility = object(data['process_visibility']);
    return RefreshIndicator(
      onRefresh: () => runWithFeedback(context, widget.controller.refresh),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 26),
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          Text('计算资源', style: Theme.of(context).textTheme.headlineMedium),
          const SizedBox(height: 6),
          Text(
            '查看设备、可见进程与许可证使用情况',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 16),
          SectionTitle(
            'GPU 设备',
            trailing: StatusPill('${devices.length} 块', color: success),
          ),
          if (devices.isEmpty)
            SurfaceCard(child: Text(textValue(gpu['error'], '暂无可查询的 GPU 数据')))
          else
            ...spaced(devices.map((device) => _GpuCard(device))),
          if (gpuProcesses.isNotEmpty) ...[
            const SizedBox(height: 12),
            _ExpandableSection(
              title: 'GPU 进程',
              subtitle: '${gpuProcesses.length} 个可见计算进程',
              children: gpuProcesses
                  .map(
                    (p) => _ResourceItem(
                      title:
                          '${textValue(p['name'])} · PID ${textValue(p['pid'])}',
                      subtitle: '用户 ${textValue(p['user'])}',
                      value: bytes(p['memory_bytes']),
                    ),
                  )
                  .toList(),
            ),
          ],
          if (textValue(gpu['process_error'], '').isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'GPU 进程：${gpu['process_error']}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          const SizedBox(height: 20),
          SectionTitle(
            '进程',
            subtitle: 'CPU 为采样区间占用率，多线程进程可能超过 100%。',
            trailing: Text(
              '${processes.length}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          if (processes.isEmpty)
            const SurfaceCard(child: Text('暂无可见进程数据。'))
          else
            SurfaceCard(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  ...processes
                      .take(_allProcesses ? processes.length : 8)
                      .map(
                        (p) => _ResourceItem(
                          title: textValue(p['name']),
                          subtitle:
                              '${textValue(p['user'])} · PID ${textValue(p['pid'])} · ${bytes(p['rss_bytes'])}',
                          value: percent(p['cpu_percent']),
                          mine: p['mine'] == true,
                        ),
                      ),
                  if (processes.length > 8)
                    TextButton(
                      onPressed: () =>
                          setState(() => _allProcesses = !_allProcesses),
                      child: Text(
                        _allProcesses ? '收起进程' : '显示全部 ${processes.length} 个进程',
                      ),
                    ),
                ],
              ),
            ),
          const SizedBox(height: 8),
          Text(
            '可见 ${textValue(visibility['visible_count'], '${processes.length}')} 个进程；不可读取 ${textValue(visibility['unreadable'], '0')} 个${visibility['truncated'] == true ? '，列表已按采集上限截断' : ''}。仅展示当前账号有权读取的信息。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 18),
          const SectionTitle('用户资源占用'),
          if (users.isEmpty)
            const SurfaceCard(child: Text('暂无用户使用数据。'))
          else
            SurfaceCard(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: users
                    .map(
                      (user) => _ResourceItem(
                        title: textValue(user['user']),
                        subtitle:
                            '${textValue(user['processes'])} 个进程 · 内存 ${bytes(user['rss_bytes'])}',
                        value: percent(user['cpu_percent']),
                        mine: user['mine'] == true,
                      ),
                    )
                    .toList(),
              ),
            ),
          const SizedBox(height: 20),
          SectionTitle(
            'FlexLM 许可证',
            trailing: StatusPill(
              license['disabled'] == true
                  ? '已关闭'
                  : license['available'] == true
                  ? '可查询'
                  : '不可用',
              color: license['available'] == true
                  ? success
                  : const Color(0xFF857C6F),
            ),
          ),
          if (features.isEmpty)
            SurfaceCard(
              child: Text(
                textValue(
                  license['error'],
                  license['disabled'] == true ? '可在设置中启用许可证查询。' : '暂无许可证特性数据。',
                ),
              ),
            )
          else
            ...spaced(features.map((feature) => _LicenseCard(feature))),
          const SizedBox(height: 14),
          Text(
            '许可证为只读查询结果，可能有采集延迟；可用席位不保证任务一定取得授权。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _GpuCard extends StatelessWidget {
  const _GpuCard(this.device);
  final Map<String, dynamic> device;
  @override
  Widget build(BuildContext context) => SurfaceCard(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(9),
              decoration: BoxDecoration(
                color: success.withValues(alpha: .1),
                borderRadius: BorderRadius.circular(11),
              ),
              child: const Icon(
                Icons.developer_board,
                color: success,
                size: 23,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'GPU ${textValue(device['index'])}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  Text(
                    textValue(device['name']),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 20),
        Row(
          children: [
            Expanded(
              child: Text(
                '计算使用率',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            Text(
              percent(device['utilization_percent']),
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ],
        ),
        const SizedBox(height: 9),
        MetricBar(
          value: number(device['utilization_percent']) == null
              ? null
              : number(device['utilization_percent'])! / 100,
          color: success,
        ),
        const SizedBox(height: 13),
        DetailRow(
          '显存',
          '${bytes(device['memory_used_bytes'])} / ${bytes(device['memory_total_bytes'])}',
        ),
        DetailRow(
          '温度 / 功率',
          '${textValue(device['temperature_c'])} °C · ${textValue(device['power_watts'])} W',
        ),
      ],
    ),
  );
}

class _ResourceItem extends StatelessWidget {
  const _ResourceItem({
    required this.title,
    required this.subtitle,
    required this.value,
    this.mine = false,
  });
  final String title, subtitle, value;
  final bool mine;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 10),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                mine ? '$title · 我' : title,
                style: Theme.of(context).textTheme.titleMedium,
                overflow: TextOverflow.ellipsis,
                maxLines: 2,
              ),
              const SizedBox(height: 3),
              Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
            ],
          ),
        ),
        const SizedBox(width: 12),
        Text(
          value,
          style: TextStyle(
            color: Theme.of(context).colorScheme.primary,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ),
  );
}

class _ExpandableSection extends StatelessWidget {
  const _ExpandableSection({
    required this.title,
    required this.subtitle,
    required this.children,
  });
  final String title, subtitle;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => SurfaceCard(
    padding: const EdgeInsets.symmetric(horizontal: 8),
    child: ExpansionTile(
      shape: const Border(),
      collapsedShape: const Border(),
      title: Text(title),
      subtitle: Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
      childrenPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      children: children,
    ),
  );
}

class _LicenseCard extends StatelessWidget {
  const _LicenseCard(this.feature);
  final Map<String, dynamic> feature;
  @override
  Widget build(BuildContext context) {
    final issued = number(feature['issued']);
    final inUse = number(feature['in_use']);
    final checkouts = records(feature['checkouts']);
    return SurfaceCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            textValue(feature['name']),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 9),
          Text(
            '已用 ${textValue(feature['in_use'])} / ${issued == null ? '不限量' : issued.toInt()} 席位',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 10),
          MetricBar(
            value: issued == null || issued == 0 || inUse == null
                ? null
                : inUse / issued,
            color: const Color(0xFF8A7C65),
          ),
          if (textValue(feature['expiry'], '').isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                '到期 ${feature['expiry']}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          if (checkouts.isNotEmpty) ...[
            const SizedBox(height: 10),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              shape: const Border(),
              collapsedShape: const Border(),
              title: Text(
                '查看 ${checkouts.length} 条占用记录',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              children: checkouts
                  .map(
                    (entry) => _ResourceItem(
                      title: textValue(entry['user']),
                      subtitle:
                          '开始 ${textValue(entry['start'])}${entry['pid'] == null ? '' : ' · PID ${entry['pid']}'}',
                      value: '${textValue(entry['count'])} 席',
                    ),
                  )
                  .toList(),
            ),
          ],
        ],
      ),
    );
  }
}
