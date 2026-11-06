import 'dart:convert';
import 'dart:async';

import '../domain/connection.dart';
import 'protocol.dart';

const previewMarker = 'LUMERICAL_PREVIEW_V1:';

Future<void> stopPreviewChannel({
  required void Function() sendTerm,
  required Future<void> exited,
  required void Function() destroy,
}) async {
  try {
    sendTerm();
    await exited.timeout(const Duration(seconds: 2));
  } catch (_) {
    // Cleanup remains bounded if a server cannot acknowledge the signal.
  } finally {
    destroy();
  }
}

String attachPreviewHelper(String probe, String helper) {
  final encoded = base64Encode(utf8.encode(helper));
  return "import types as _types,sys as _sys,base64 as _b64\n"
      "_pm=_types.ModuleType('preview_export')\n"
      "exec(_b64.b64decode('$encoded'),_pm.__dict__)\n"
      "_sys.modules['preview_export']=_pm\n$probe";
}

String previewToolSource(String helper, Map<String, dynamic> request) {
  final source = base64Encode(utf8.encode(helper));
  final payload = base64Encode(utf8.encode(jsonEncode(request)));
  return "import base64,json\n_ns={'__name__':'preview_tool'}\n"
      "_source=base64.b64decode('$source').decode('utf-8')\n"
      "exec(_source,_ns)\n"
      "_ns['emit'](json.loads(base64.b64decode('$payload')),source=_source)\n";
}

Map<String, dynamic> decodePreviewOutput(String output, int? exitCode) {
  if (exitCode != 0) {
    throw const MonitorException('预览连接中断，生成可能已完成；连接恢复后请读取缓存');
  }
  final frames = output
      .split('\n')
      .where((line) => line.startsWith(previewMarker));
  if (frames.isEmpty) {
    throw const MonitorException('预览没有返回数据，请检查服务器 Lumerical、NumPy 和 GUI 许可证');
  }
  late Map<String, dynamic> reply;
  try {
    reply = decodeReply(
      jsonEncode({'z': frames.last.substring(previewMarker.length).trim()}),
    );
  } catch (_) {
    throw const MonitorException('预览响应不完整，请重新读取缓存');
  }
  if (reply['ok'] != true) {
    final message = '${reply['error'] ?? '预览生成失败'}';
    throw MonitorException(
      message.length > 400 ? message.substring(0, 400) : message,
    );
  }
  final data = reply['data'];
  if (data is! Map<String, dynamic>) {
    throw const MonitorException('预览响应格式无效，请重新读取缓存');
  }
  return data;
}
