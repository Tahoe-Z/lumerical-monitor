import 'package:flutter/material.dart';

const clay = Color(0xFFC6613F);
const warmPaper = Color(0xFFFAF9F5);
const success = Color(0xFF477561);

Map<String, dynamic> object(dynamic value) => value is Map
    ? value.map((key, value) => MapEntry(key.toString(), value))
    : <String, dynamic>{};
List<Map<String, dynamic>> records(dynamic value) => value is List
    ? value.whereType<Map>().map(object).toList()
    : <Map<String, dynamic>>[];
double? number(dynamic value) {
  final parsed = value is num ? value.toDouble() : double.tryParse('$value');
  return parsed != null && parsed.isFinite ? parsed : null;
}

String textValue(dynamic value, [String fallback = '—']) =>
    value == null || '$value'.isEmpty ? fallback : '$value';
String percent(dynamic value) {
  final n = number(value);
  return n == null ? '—' : '${n.toStringAsFixed(1)}%';
}

String bytes(dynamic value) {
  final parsed = number(value);
  if (parsed == null || parsed < 0) return '—';
  var n = parsed;
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  var i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return '${n.toStringAsFixed(i < 2 ? 0 : 1)} ${units[i]}';
}

String elapsed(dynamic value) {
  final seconds = number(value)?.floor();
  if (seconds == null) return '—';
  final duration = Duration(seconds: seconds);
  if (duration.inDays > 0) {
    return '${duration.inDays} 天 ${duration.inHours % 24} 小时';
  }
  if (duration.inHours > 0) {
    return '${duration.inHours} 小时 ${duration.inMinutes % 60} 分';
  }
  return '${duration.inMinutes} 分 ${seconds % 60} 秒';
}

Color stateColor(String state) => state == '运行中'
    ? success
    : state == '已完成'
    ? const Color(0xFF64718A)
    : state.contains('失败') || state.contains('检查')
    ? clay
    : const Color(0xFF857C6F);

class SurfaceCard extends StatelessWidget {
  const SurfaceCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(20),
    this.onTap,
  });
  final Widget child;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => Material(
    color: Theme.of(context).colorScheme.surface,
    clipBehavior: Clip.antiAlias,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(22),
      side: BorderSide(
        color: Theme.of(context).dividerColor.withValues(alpha: .5),
      ),
    ),
    child: onTap == null
        ? Padding(padding: padding, child: child)
        : InkWell(
            onTap: onTap,
            child: Padding(padding: padding, child: child),
          ),
  );
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.title, {super.key, this.trailing, this.subtitle});
  final String title;
  final String? subtitle;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 10, bottom: 14),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              if (subtitle != null) ...[
                const SizedBox(height: 5),
                Text(subtitle!, style: Theme.of(context).textTheme.bodySmall),
              ],
            ],
          ),
        ),
        ?trailing,
      ],
    ),
  );
}

class StatusPill extends StatelessWidget {
  const StatusPill(this.label, {super.key, this.color = success, this.icon});
  final String label;
  final Color color;
  final IconData? icon;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .11),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon ?? Icons.circle, size: icon == null ? 6 : 13, color: color),
        const SizedBox(width: 6),
        Flexible(
          child: Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    ),
  );
}

class MetricBar extends StatelessWidget {
  const MetricBar({super.key, required this.value, this.color = clay});
  final double? value;
  final Color color;
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(8),
    child: LinearProgressIndicator(
      value: value == null ? 0 : value!.clamp(0, 1),
      minHeight: 5,
      color: color,
      backgroundColor: color.withValues(alpha: .1),
    ),
  );
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.title,
    required this.message,
    this.icon = Icons.inbox_outlined,
    this.actions,
  });
  final String title;
  final String message;
  final IconData icon;
  final Widget? actions;
  @override
  Widget build(BuildContext context) => SurfaceCard(
    child: Column(
      children: [
        const SizedBox(height: 20),
        Container(
          padding: const EdgeInsets.all(19),
          decoration: BoxDecoration(
            color: clay.withValues(alpha: .09),
            shape: BoxShape.circle,
          ),
          child: Icon(icon, size: 32, color: clay),
        ),
        const SizedBox(height: 22),
        Text(
          title,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 10),
        Text(
          message,
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodyMedium,
        ),
        if (actions != null) ...[const SizedBox(height: 25), actions!],
        const SizedBox(height: 20),
      ],
    ),
  );
}

class DetailRow extends StatelessWidget {
  const DetailRow(this.label, this.value, {super.key});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 88,
          child: Text(label, style: Theme.of(context).textTheme.bodySmall),
        ),
        Expanded(
          child: Text(value, style: Theme.of(context).textTheme.bodyMedium),
        ),
      ],
    ),
  );
}

void showMessage(BuildContext context, Object message) {
  ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text('$message')));
}

Future<void> runWithFeedback(
  BuildContext context,
  Future<void> Function() action,
) async {
  try {
    await action();
  } catch (e) {
    if (context.mounted) showMessage(context, e);
  }
}

List<Widget> spaced(Iterable<Widget> children, [double gap = 12]) {
  final result = <Widget>[];
  for (final child in children) {
    if (result.isNotEmpty) result.add(SizedBox(height: gap));
    result.add(child);
  }
  return result;
}
