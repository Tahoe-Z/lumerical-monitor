import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/services/protocol.dart';

void main() {
  test('reads plain and compressed JSON replies without altering values', () {
    const reply = {
      'ok': true,
      'data': {'name': '合成样例', 'cpu_percent': 12.5},
    };
    expect(decodeReply(jsonEncode(reply)), reply);
    final compressed = base64Encode(
      zlib.encode(utf8.encode(jsonEncode(reply))),
    );
    expect(decodeReply(jsonEncode({'z': compressed})), reply);
    expect(() => decodeReply('not json'), throwsFormatException);
  });

  test(
    'binary download handles a header split across arbitrary chunks',
    () async {
      final bytes = <int>[0, 13, 10, 255, 42];
      final wire =
          utf8.encode(
            '${jsonEncode({'size': bytes.length, 'mtime_ns': 1})}\n',
          ) +
          bytes;
      final chunks = wire.map((byte) => Uint8List.fromList([byte]));
      final parser = DownloadReader(Stream<Uint8List>.fromIterable(chunks));
      final header = await parser.readHeader();
      expect(header.size, bytes.length);
      final received = <int>[];
      await for (final chunk in parser.readBody(header.size)) {
        received.addAll(chunk);
      }
      expect(received, bytes);
    },
  );

  test(
    'binary download rejects incomplete, oversized and invalid responses',
    () async {
      for (final wire in [
        utf8.encode('{"size":4,"mtime_ns":1}\na'),
        utf8.encode('{"size":1,"mtime_ns":1}\nabc'),
        utf8.encode('{"size":-1,"mtime_ns":1}\n'),
      ]) {
        final reader = DownloadReader(Stream.value(Uint8List.fromList(wire)));
        await expectLater(() async {
          final header = await reader.readHeader();
          await reader.readBody(header.size).drain<void>();
        }(), throwsA(isA<Exception>()));
      }
    },
  );
}
