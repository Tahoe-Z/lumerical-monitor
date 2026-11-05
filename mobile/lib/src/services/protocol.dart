import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

const maxReplyBytes = 32 * 1024 * 1024;

Map<String, dynamic> decodeReply(String line) {
  try {
    if (line.length > maxReplyBytes) throw const FormatException();
    var result = jsonDecode(line);
    if (result is Map<String, dynamic> && result.containsKey('z')) {
      final builder = _LimitedSink(maxReplyBytes);
      final decoder = zlib.decoder.startChunkedConversion(builder);
      decoder.add(base64Decode(result['z'] as String));
      decoder.close();
      result = jsonDecode(utf8.decode(builder.bytes.takeBytes()));
    }
    if (result is! Map<String, dynamic>) throw const FormatException();
    return result;
  } catch (_) {
    throw const FormatException('远端响应无效或超出大小上限');
  }
}

class _LimitedSink implements Sink<List<int>> {
  _LimitedSink(this.limit);
  final int limit;
  final bytes = BytesBuilder(copy: false);
  int length = 0;
  @override
  void add(List<int> data) {
    length += data.length;
    if (length > limit) throw const FormatException('响应过大');
    bytes.add(data);
  }

  @override
  void close() {}
}

class DownloadHeader {
  const DownloadHeader(this.size, this.mtimeNanoseconds);
  final int size, mtimeNanoseconds;
}

/// Reads the newline-delimited header without consuming any binary body bytes.
class DownloadReader {
  DownloadReader(Stream<Uint8List> source, {this.maxHeaderBytes = 4096})
    : _iterator = StreamIterator(source);
  final StreamIterator<Uint8List> _iterator;
  final int maxHeaderBytes;
  Uint8List _buffer = Uint8List(0);
  int _offset = 0;
  bool _headerRead = false, _bodyRead = false;

  Future<bool> _available() async {
    while (_offset == _buffer.length) {
      if (!await _iterator.moveNext()) return false;
      _buffer = _iterator.current;
      _offset = 0;
    }
    return true;
  }

  Future<DownloadHeader> readHeader() async {
    if (_headerRead) throw const FormatException('下载信息重复读取');
    _headerRead = true;
    final header = <int>[];
    while (await _available()) {
      final byte = _buffer[_offset++];
      if (byte == 10) {
        try {
          final json = jsonDecode(utf8.decode(header));
          if (json is! Map ||
              json['size'] is! int ||
              json['size'] < 0 ||
              json['mtime_ns'] is! int ||
              json['mtime_ns'] < 0) {
            throw const FormatException();
          }
          return DownloadHeader(json['size'] as int, json['mtime_ns'] as int);
        } catch (_) {
          throw const FormatException('下载信息无效');
        }
      }
      header.add(byte);
      if (header.length >= maxHeaderBytes) {
        throw const FormatException('下载信息超出上限');
      }
    }
    throw const FormatException('下载信息不完整');
  }

  Stream<Uint8List> readBody(int size) async* {
    if (!_headerRead || _bodyRead || size < 0) {
      throw const FormatException('下载状态无效');
    }
    _bodyRead = true;
    var remaining = size;
    while (await _available()) {
      final available = _buffer.length - _offset;
      if (available > remaining) throw const FormatException('下载数据超出声明大小');
      final data = Uint8List.sublistView(_buffer, _offset);
      _offset = _buffer.length;
      remaining -= data.length;
      if (data.isNotEmpty) yield data;
    }
    if (remaining != 0) throw const FormatException('下载数据不完整');
  }

  Future<void> cancel() => _iterator.cancel();
}

/// A bounded line reader avoids buffering a malformed server's unlimited line.
class ReplyLines {
  ReplyLines(Stream<Uint8List> source) : _iterator = StreamIterator(source);
  final StreamIterator<Uint8List> _iterator;
  Uint8List _buffer = Uint8List(0);
  int _offset = 0;
  Future<String> next() async {
    final bytes = BytesBuilder(copy: false);
    while (true) {
      if (_offset == _buffer.length) {
        if (!await _iterator.moveNext()) throw const FormatException('远端会话已关闭');
        _buffer = _iterator.current;
        _offset = 0;
      }
      final end = _buffer.indexOf(10, _offset);
      final count = (end < 0 ? _buffer.length : end) - _offset;
      if (bytes.length + count > maxReplyBytes) {
        throw const FormatException('远端响应超出大小上限');
      }
      bytes.add(Uint8List.sublistView(_buffer, _offset, _offset + count));
      _offset += count;
      if (end >= 0) {
        _offset++;
        return utf8.decode(bytes.takeBytes());
      }
    }
  }

  Future<void> cancel() => _iterator.cancel();
}
