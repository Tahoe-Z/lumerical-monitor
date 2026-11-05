/// Connection data belongs only in memory or platform secure storage.
class ConnectionProfile {
  const ConnectionProfile({
    required this.host,
    required this.username,
    required this.root,
    required this.privateKey,
    this.name = '我的服务器',
    this.port = 22,
    this.passphrase = '',
    this.refreshSeconds = 15,
    this.queryLicenses = true,
  });

  final String name, host, username, root, privateKey, passphrase;
  final int port, refreshSeconds;
  final bool queryLicenses;

  void validate() {
    if (!RegExp(r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$').hasMatch(host)) {
      throw const FormatException('服务器地址格式不正确');
    }
    if (!RegExp(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$').hasMatch(username)) {
      throw const FormatException('SSH 用户名格式不正确');
    }
    if (port < 1 || port > 65535) {
      throw const FormatException('SSH 端口范围必须为 1–65535');
    }
    if (!root.startsWith('/') || RegExp(r'[\x00-\x1f\x7f]').hasMatch(root)) {
      throw const FormatException('项目目录必须是有效的绝对路径');
    }
    if (privateKey.trim().isEmpty) {
      throw const FormatException('请输入或导入 SSH 私钥');
    }
    if (refreshSeconds < 5 || refreshSeconds > 600) {
      throw const FormatException('刷新间隔必须为 5–600 秒');
    }
  }

  Map<String, dynamic> toJson() => {
    'name': name,
    'host': host,
    'port': port,
    'username': username,
    'root': root,
    'privateKey': privateKey,
    'passphrase': passphrase,
    'refreshSeconds': refreshSeconds,
    'queryLicenses': queryLicenses,
  };

  factory ConnectionProfile.fromJson(Map<String, dynamic> json) {
    try {
      final result = ConnectionProfile(
        name: json['name'] as String? ?? '我的服务器',
        host: json['host'] as String,
        port: json['port'] as int? ?? 22,
        username: json['username'] as String,
        root: json['root'] as String,
        privateKey: json['privateKey'] as String,
        passphrase: json['passphrase'] as String? ?? '',
        refreshSeconds: json['refreshSeconds'] as int? ?? 15,
        queryLicenses: json['queryLicenses'] as bool? ?? true,
      );
      result.validate();
      return result;
    } catch (_) {
      throw const FormatException('已保存的连接资料无效，请重新设置');
    }
  }

  ConnectionProfile copyWith({
    String? name,
    String? host,
    int? port,
    String? username,
    String? root,
    String? privateKey,
    String? passphrase,
    int? refreshSeconds,
    bool? queryLicenses,
  }) => ConnectionProfile(
    name: name ?? this.name,
    host: host ?? this.host,
    port: port ?? this.port,
    username: username ?? this.username,
    root: root ?? this.root,
    privateKey: privateKey ?? this.privateKey,
    passphrase: passphrase ?? this.passphrase,
    refreshSeconds: refreshSeconds ?? this.refreshSeconds,
    queryLicenses: queryLicenses ?? this.queryLicenses,
  );

  @override
  String toString() => 'ConnectionProfile(<已隐藏连接资料>)';
}
