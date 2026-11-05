enum ConnectionPhase {
  disconnected,
  connecting,
  connected,
  paused,
  error,
  demo,
}

class HostTrustRequest {
  const HostTrustRequest({
    required this.host,
    required this.port,
    required this.keyType,
    required this.fingerprint,
  });
  final String host, keyType, fingerprint;
  final int port;
  Map<String, dynamic> toJson() => {
    'host': host.toLowerCase(),
    'port': port,
    'keyType': keyType,
    'fingerprint': fingerprint,
  };
  factory HostTrustRequest.fromJson(Map<String, dynamic> json) =>
      HostTrustRequest(
        host: json['host'] as String,
        port: json['port'] as int,
        keyType: json['keyType'] as String,
        fingerprint: json['fingerprint'] as String,
      );
  @override
  String toString() => 'HostTrustRequest(<已隐藏服务器资料>)';
}

typedef HostTrustPrompt = Future<bool> Function(HostTrustRequest request);

class MonitorException implements Exception {
  const MonitorException(this.message);
  final String message;
  @override
  String toString() => message;
}

class MonitorCancelled extends MonitorException {
  const MonitorCancelled() : super('操作已取消');
}

class HostKeyChanged extends MonitorException {
  const HostKeyChanged() : super('服务器指纹与已信任记录不一致。请先核对服务器，再到设置中清除信任记录。');
}
