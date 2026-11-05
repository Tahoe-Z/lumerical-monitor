import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'shared.dart';

/// Infer physical cell boundaries from samples, including nonuniform spacing.
List<double> previewCellEdges(List<double> centers) {
  if (centers.isEmpty || centers.any((value) => !value.isFinite)) {
    throw const FormatException('场坐标无效');
  }
  if (centers.length == 1) return [centers.first - .5, centers.first + .5];
  final direction = (centers[1] - centers[0]).sign;
  if (direction == 0) throw const FormatException('场坐标必须严格单调');
  for (var i = 1; i < centers.length; i++) {
    if ((centers[i] - centers[i - 1]).sign != direction) {
      throw const FormatException('场坐标必须严格单调');
    }
  }
  return [
    centers.first - (centers[1] - centers.first) / 2,
    for (var i = 1; i < centers.length; i++) (centers[i - 1] + centers[i]) / 2,
    centers.last + (centers.last - centers[centers.length - 2]) / 2,
  ];
}

/// All rings of a polygon share even-odd fill so inner contours remain holes.
Path previewPolygonPath(
  List<dynamic> contours,
  Offset Function(Offset) transform,
) {
  final path = Path()..fillType = PathFillType.evenOdd;
  for (final contour in contours) {
    if (contour is! List || contour.length < 3) {
      throw const FormatException('几何轮廓无效');
    }
    for (var i = 0; i < contour.length; i++) {
      final point = contour[i];
      if (point is! List || point.length != 2) {
        throw const FormatException('几何轮廓无效');
      }
      final x = number(point[0]), y = number(point[1]);
      if (x == null || y == null) throw const FormatException('几何轮廓无效');
      final mapped = transform(Offset(x, y));
      if (i == 0) {
        path.moveTo(mapped.dx, mapped.dy);
      } else {
        path.lineTo(mapped.dx, mapped.dy);
      }
    }
    path.close();
  }
  return path;
}

/// Use the saved data range rather than clamping transmission to [0, 1].
(double, double) previewAxisRange(List<double> values) {
  if (values.isEmpty || values.any((value) => !value.isFinite)) {
    throw const FormatException('绘图数值无效');
  }
  final low = values.reduce(math.min), high = values.reduce(math.max);
  final pad = low == high ? math.max(low.abs() * .05, .05) : (high - low) * .05;
  return (low - pad, high + pad);
}

const _layerColors = [
  clay,
  Color(0xFF3F6FA0),
  Color(0xFF4C7D3F),
  Color(0xFF7A63B8),
  Color(0xFFB7791F),
  Color(0xFFA3A29B),
];

const _magma = [
  Color(0xFF000004),
  Color(0xFF221150),
  Color(0xFF5F187F),
  Color(0xFF9E2F7F),
  Color(0xFFDE4968),
  Color(0xFFFE9F6D),
  Color(0xFFFCFDBF),
];

String _format(double value) => value == 0
    ? '0'
    : value.abs() >= 10000 || value.abs() < .001
    ? value.toStringAsExponential(2)
    : value.toStringAsPrecision(5).replaceFirst(RegExp(r'\.?0+$'), '');

List<double> _numbers(dynamic input) {
  if (input is! List || input.isEmpty) {
    throw const FormatException('绘图数据为空');
  }
  return input.map((value) {
    final parsed = number(value);
    if (parsed == null) throw const FormatException('绘图数值无效');
    return parsed;
  }).toList();
}

class ModelPreviewChart extends StatelessWidget {
  const ModelPreviewChart({super.key, required this.entry});
  final Map<String, dynamic> entry;

  @override
  Widget build(BuildContext context) {
    final layers = records(entry['layers']);
    final points = <Offset>[];
    try {
      for (final layer in layers) {
        for (final polygon in records(layer['polygons'])) {
          final contours = polygon['contours'];
          if (contours is! List) throw const FormatException('几何轮廓无效');
          previewPolygonPath(contours, (point) {
            points.add(point * 1e6);
            return point;
          });
        }
      }
    } on FormatException catch (error) {
      return _ChartMessage(error.message);
    }
    final local = entry['plane'] == 'gds_local_xy';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          local
              ? '保存的 GDS 局部 XY 图案 · 不是 z 截面'
              : '模型 XY 截面 · z = ${_format((number(entry['z_m']) ?? 0) * 1e6)} µm',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 12),
        if (points.isEmpty)
          const _ChartMessage('此截面没有保存的几何轮廓')
        else ...[
          _ChartCanvas(
            painter: _ModelPainter(
              layers,
              previewAxisRange(points.map((p) => p.dx).toList()),
              previewAxisRange(points.map((p) => p.dy).toList()),
              Theme.of(context).colorScheme,
              local,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 14,
            runSpacing: 8,
            children: [
              for (var i = 0; i < layers.length; i++)
                Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text: '● ',
                        style: TextStyle(
                          color: _layerColors[i % _layerColors.length],
                        ),
                      ),
                      TextSpan(text: textValue(layers[i]['name'], '未命名层')),
                    ],
                  ),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
            ],
          ),
        ],
      ],
    );
  }
}

class FieldPreviewChart extends StatelessWidget {
  const FieldPreviewChart({super.key, required this.entry});
  final Map<String, dynamic> entry;

  @override
  Widget build(BuildContext context) {
    late final _FieldData data;
    try {
      data = _FieldData(entry);
    } on FormatException {
      return const _ChartMessage('场数据维度或数值无效');
    }
    final quantity = textValue(entry['quantity'], '|E|²');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          '${textValue(entry['name'], '场结果')} · $quantity\n'
          'λ = ${_format((number(entry['wavelength_m']) ?? 0) * 1e9)} nm · '
          '${textValue(entry['fixed_axis'], 'z')} = '
          '${_format((number(entry['fixed_position_m']) ?? 0) * 1e6)} µm',
          style: Theme.of(context).textTheme.titleSmall,
        ),
        if (entry['sampled'] == true) ...[
          const SizedBox(height: 5),
          const Text('预览已抽样；数值与坐标来自保存的场结果。'),
        ],
        const SizedBox(height: 12),
        _ChartCanvas(
          painter: _FieldPainter(data, entry, Theme.of(context).colorScheme),
        ),
        const SizedBox(height: 12),
        Semantics(
          label: '$quantity 最小值 ${_format(data.low)}，最大值 ${_format(data.high)}',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                height: 12,
                decoration: const BoxDecoration(
                  gradient: LinearGradient(colors: _magma),
                ),
              ),
              const SizedBox(height: 4),
              Row(
                children: [
                  Text(_format(data.low)),
                  Expanded(child: Text(quantity, textAlign: TextAlign.center)),
                  Text(_format(data.high)),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class SpectrumPreviewChart extends StatelessWidget {
  const SpectrumPreviewChart({super.key, required this.entry});
  final Map<String, dynamic> entry;

  @override
  Widget build(BuildContext context) {
    late final List<double> wavelengths, values;
    try {
      wavelengths = _numbers(entry['wavelength_m'])
          .map((v) => v * 1e9)
          .toList();
      values = _numbers(entry['values']);
      if (wavelengths.length != values.length) {
        throw const FormatException('光谱数据维度或数值无效');
      }
    } on FormatException {
      return const _ChartMessage('光谱数据维度或数值无效');
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          textValue(entry['name'], '透射谱 T'),
          style: Theme.of(context).textTheme.titleSmall,
        ),
        const SizedBox(height: 8),
        const Text('T 保留监视器的方向符号；不等同于某个模式的耦合效率。'),
        if (entry['normalization'] != null) ...[
          const SizedBox(height: 4),
          Text('归一化：${entry['normalization']}'),
        ],
        const SizedBox(height: 12),
        _ChartCanvas(
          painter: _SpectrumPainter(
            wavelengths,
            values,
            Theme.of(context).colorScheme,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          '保存值范围：${_format(values.reduce(math.min))} ～ ${_format(values.reduce(math.max))}',
        ),
      ],
    );
  }
}

class _ChartMessage extends StatelessWidget {
  const _ChartMessage(this.message);
  final String message;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 12),
    child: Text(message, textAlign: TextAlign.center),
  );
}

class _ChartCanvas extends StatelessWidget {
  const _ChartCanvas({required this.painter});
  final CustomPainter painter;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      SizedBox(
        height: 300,
        child: LayoutBuilder(
          builder: (context, constraints) {
            return InteractiveViewer(
              minScale: 1,
              maxScale: 8,
              child: CustomPaint(
                size: Size(constraints.maxWidth, 300),
                painter: painter,
              ),
            );
          },
        ),
      ),
      const SizedBox(height: 5),
      Text('双指缩放 · 拖动查看', style: Theme.of(context).textTheme.bodySmall),
    ],
  );
}

class _FieldData {
  _FieldData(Map<String, dynamic> entry) {
    x = previewCellEdges(_numbers(entry['x']).map((v) => v * 1e6).toList());
    y = previewCellEdges(_numbers(entry['y']).map((v) => v * 1e6).toList());
    final raw = entry['values'];
    if (raw is! List || raw.length != x.length - 1) {
      throw const FormatException('场数据维度或数值无效');
    }
    values = raw.map(_numbers).toList();
    if (values.any((row) => row.length != y.length - 1)) {
      throw const FormatException('场数据维度或数值无效');
    }
    final flat = values.expand((row) => row);
    low = flat.reduce(math.min);
    high = flat.reduce(math.max);
  }
  late final List<double> x, y;
  late final List<List<double>> values;
  late final double low, high;
}

class _Plot {
  _Plot(Size size, this.xRange, this.yRange, {bool equalAspect = false}) {
    final available = Rect.fromLTRB(
      54,
      18,
      math.max(55, size.width - 16),
      size.height - 49,
    );
    if (equalAspect) {
      final scale = math.min(
        available.width / (xRange.$2 - xRange.$1),
        available.height / (yRange.$2 - yRange.$1),
      );
      area = Rect.fromCenter(
        center: available.center,
        width: (xRange.$2 - xRange.$1) * scale,
        height: (yRange.$2 - yRange.$1) * scale,
      );
    } else {
      area = available;
    }
  }
  final (double, double) xRange, yRange;
  late final Rect area;
  Offset point(Offset value) => Offset(
    area.left + (value.dx - xRange.$1) / (xRange.$2 - xRange.$1) * area.width,
    area.bottom -
        (value.dy - yRange.$1) / (yRange.$2 - yRange.$1) * area.height,
  );

  void axes(
    Canvas canvas,
    ColorScheme scheme,
    String xLabel,
    String yLabel, {
    bool grid = false,
  }) {
    final line = Paint()
      ..color = scheme.outlineVariant
      ..strokeWidth = .7;
    canvas.drawRect(area, Paint()..color = scheme.surface);
    for (var i = 0; i <= 4; i++) {
      final t = i / 4;
      final x = area.left + area.width * t, y = area.bottom - area.height * t;
      if (grid) {
        canvas.drawLine(Offset(x, area.top), Offset(x, area.bottom), line);
        canvas.drawLine(Offset(area.left, y), Offset(area.right, y), line);
      }
      canvas.drawLine(Offset(x, area.bottom), Offset(x, area.bottom + 4), line);
      canvas.drawLine(Offset(area.left - 4, y), Offset(area.left, y), line);
      _label(
        canvas,
        _format(xRange.$1 + (xRange.$2 - xRange.$1) * t),
        Offset(x, area.bottom + 7),
        scheme.onSurfaceVariant,
        center: true,
      );
      _label(
        canvas,
        _format(yRange.$1 + (yRange.$2 - yRange.$1) * t),
        Offset(area.left - 7, y - 5),
        scheme.onSurfaceVariant,
        right: true,
      );
    }
    canvas.drawRect(area, line..style = PaintingStyle.stroke);
    _label(
      canvas,
      xLabel,
      Offset(area.center.dx, area.bottom + 29),
      scheme.onSurface,
      center: true,
      size: 11,
    );
    canvas.save();
    canvas.translate(10, area.center.dy);
    canvas.rotate(-math.pi / 2);
    _label(
      canvas,
      yLabel,
      Offset.zero,
      scheme.onSurface,
      center: true,
      size: 11,
    );
    canvas.restore();
  }
}

void _label(
  Canvas canvas,
  String text,
  Offset point,
  Color color, {
  bool center = false,
  bool right = false,
  double size = 9,
}) {
  final label = TextPainter(
    text: TextSpan(
      text: text,
      style: TextStyle(color: color, fontSize: size),
    ),
    textDirection: TextDirection.ltr,
  )..layout();
  label.paint(
    canvas,
    point -
        Offset(
          center
              ? label.width / 2
              : right
              ? label.width
              : 0,
          0,
        ),
  );
}

class _ModelPainter extends CustomPainter {
  _ModelPainter(this.layers, this.xRange, this.yRange, this.scheme, this.local);
  final List<Map<String, dynamic>> layers;
  final (double, double) xRange, yRange;
  final ColorScheme scheme;
  final bool local;
  @override
  void paint(Canvas canvas, Size size) {
    final plot = _Plot(size, xRange, yRange, equalAspect: true);
    plot.axes(
      canvas,
      scheme,
      local ? 'GDS local x (µm)' : 'x (µm)',
      local ? 'GDS local y (µm)' : 'y (µm)',
    );
    canvas.save();
    canvas.clipRect(plot.area);
    for (var i = 0; i < layers.length; i++) {
      for (final polygon in records(layers[i]['polygons'])) {
        final path = previewPolygonPath(
          polygon['contours'] as List,
          (point) => plot.point(point * 1e6),
        );
        canvas.drawPath(
          path,
          Paint()
            ..color = _layerColors[i % _layerColors.length].withValues(
              alpha: .65,
            ),
        );
        canvas.drawPath(
          path,
          Paint()
            ..color = scheme.onSurface.withValues(alpha: .65)
            ..style = PaintingStyle.stroke
            ..strokeWidth = .7,
        );
      }
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_ModelPainter oldDelegate) =>
      layers != oldDelegate.layers || scheme != oldDelegate.scheme;
}

class _FieldPainter extends CustomPainter {
  _FieldPainter(this.data, this.entry, this.scheme);
  final _FieldData data;
  final Map<String, dynamic> entry;
  final ColorScheme scheme;
  @override
  void paint(Canvas canvas, Size size) {
    final plot = _Plot(
      size,
      (data.x.reduce(math.min), data.x.reduce(math.max)),
      (data.y.reduce(math.min), data.y.reduce(math.max)),
      equalAspect: true,
    );
    plot.axes(
      canvas,
      scheme,
      '${textValue(entry['x_axis'], 'x')} (µm)',
      '${textValue(entry['y_axis'], 'y')} (µm)',
    );
    canvas.save();
    canvas.clipRect(plot.area);
    for (var i = 0; i < data.values.length; i++) {
      for (var j = 0; j < data.values[i].length; j++) {
        final t = data.low == data.high
            ? .5
            : (data.values[i][j] - data.low) / (data.high - data.low);
        final position = t * (_magma.length - 1);
        final index = math.min(position.floor(), _magma.length - 2);
        final color = Color.lerp(
          _magma[index],
          _magma[index + 1],
          position - index,
        )!;
        canvas.drawRect(
          Rect.fromPoints(
            plot.point(Offset(data.x[i], data.y[j])),
            plot.point(Offset(data.x[i + 1], data.y[j + 1])),
          ),
          Paint()..color = color,
        );
      }
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(_FieldPainter oldDelegate) =>
      data != oldDelegate.data || scheme != oldDelegate.scheme;
}

class _SpectrumPainter extends CustomPainter {
  _SpectrumPainter(this.wavelengths, this.values, this.scheme);
  final List<double> wavelengths, values;
  final ColorScheme scheme;
  @override
  void paint(Canvas canvas, Size size) {
    final plot = _Plot(
      size,
      previewAxisRange(wavelengths),
      previewAxisRange(values),
    );
    plot.axes(canvas, scheme, 'λ (nm)', 'Signed T', grid: true);
    canvas.save();
    canvas.clipRect(plot.area);
    if (plot.yRange.$1 <= 0 && plot.yRange.$2 >= 0) {
      canvas.drawLine(
        plot.point(Offset(plot.xRange.$1, 0)),
        plot.point(Offset(plot.xRange.$2, 0)),
        Paint()
          ..color = scheme.outline
          ..strokeWidth = 1,
      );
    }
    final path = Path();
    for (var i = 0; i < values.length; i++) {
      final point = plot.point(Offset(wavelengths[i], values[i]));
      if (i == 0) {
        path.moveTo(point.dx, point.dy);
      } else {
        path.lineTo(point.dx, point.dy);
      }
      if (values.length <= 8) {
        canvas.drawCircle(point, 3.5, Paint()..color = clay);
      }
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = clay
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_SpectrumPainter oldDelegate) =>
      wavelengths != oldDelegate.wavelengths ||
      values != oldDelegate.values ||
      scheme != oldDelegate.scheme;
}
