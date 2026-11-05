import 'dart:convert';
import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/services/preview_transport.dart';
import 'package:lumerical_monitor/src/domain/connection.dart';

void main() {
  test('cancellation sends TERM before destroying the SSH channel', () async {
    final calls = <String>[];
    final done = Completer<void>();
    await stopPreviewChannel(
      sendTerm: () {
        calls.add('TERM');
        done.complete();
      },
      exited: done.future,
      destroy: () => calls.add('destroy'),
    );
    expect(calls, ['TERM', 'destroy']);
  });
  test('preview source and file names travel as encoded data', () {
    const helper = 'def emit(request, source=None): pass\n';
    final source = previewToolSource(helper, {
      'path': "space/'\n文件.fsp",
      'root': '/srv/simulations',
    });
    expect(source, contains(base64Encode(utf8.encode(helper))));
    expect(source, isNot(contains("space/'\n文件.fsp")));
    expect(attachPreviewHelper('PROBE', helper), endsWith('PROBE'));
  });
  test('complete compressed preview survives other API stdout', () {
    final data = {
      'available': true,
      'document': {'version': 1},
    };
    final payload = base64Encode(
      zlib.encode(utf8.encode(jsonEncode({'ok': true, 'data': data}))),
    );
    expect(
      decodePreviewOutput('API message\nLUMERICAL_PREVIEW_V1:$payload\n', 0),
      data,
    );
  });
  test('incomplete or interrupted replies recommend cache recovery', () {
    for (final status in [0, 255]) {
      expect(
        () => decodePreviewOutput('LUMERICAL_PREVIEW_V1:abc', status),
        throwsA(isA<MonitorException>()),
      );
    }
  });
  test('missing marker does not become an empty success', () {
    expect(
      () => decodePreviewOutput('API log only', 0),
      throwsA(isA<MonitorException>()),
    );
  });
}
