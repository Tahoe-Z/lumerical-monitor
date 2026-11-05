import 'dart:async';
import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../domain/connection.dart';
import '../domain/profile.dart';

abstract interface class SecretStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class PlatformSecretStore implements SecretStore {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(resetOnError: false, migrateWithBackup: true),
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.unlocked_this_device,
      synchronizable: false,
    ),
  );
  @override
  Future<String?> read(String key) => _storage.read(key: key);
  @override
  Future<void> write(String key, String value) =>
      _storage.write(key: key, value: value);
  @override
  Future<void> delete(String key) => _storage.delete(key: key);
}

class VaultException extends MonitorException {
  const VaultException() : super('无法访问设备安全存储。请解锁设备后重试；连接资料尚未更改。');
}

/// One encrypted document keeps profile/trust changes atomic at the store boundary.
class SecureVault {
  SecureVault({SecretStore? store}) : _store = store ?? PlatformSecretStore();
  final SecretStore _store;
  static const _key = 'monitor.secure.connection.v1';
  Future<void> _tail = Future.value();

  Future<T> _serialized<T>(Future<T> Function() action) {
    final result = _tail.then((_) async {
      try {
        return await action();
      } on MonitorException {
        rethrow;
      } catch (_) {
        throw const VaultException();
      }
    });
    _tail = result.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return result;
  }

  Map<String, dynamic> _decode(String? raw) {
    if (raw == null) return {'trust': <dynamic>[]};
    final json = jsonDecode(raw);
    if (json is! Map<String, dynamic> || json['trust'] is! List) {
      throw const VaultException();
    }
    return json;
  }

  Future<ConnectionProfile?> loadProfile() => _serialized(() async {
    final data = _decode(await _store.read(_key));
    final profile = data['profile'];
    return profile == null
        ? null
        : ConnectionProfile.fromJson(Map<String, dynamic>.from(profile as Map));
  });

  /// null means unknown. Any remembered endpoint with a different key fails closed.
  Future<bool?> checkHost(HostTrustRequest request) => _serialized(() async {
    final data = _decode(await _store.read(_key));
    final endpoint = (data['trust'] as List)
        .map(
          (item) =>
              HostTrustRequest.fromJson(Map<String, dynamic>.from(item as Map)),
        )
        .where(
          (item) =>
              item.host.toLowerCase() == request.host.toLowerCase() &&
              item.port == request.port,
        )
        .toList();
    if (endpoint.isEmpty) return null;
    if (endpoint.any(
      (item) =>
          item.keyType == request.keyType &&
          item.fingerprint == request.fingerprint,
    )) {
      return true;
    }
    throw const HostKeyChanged();
  });

  Future<void> saveConnection(
    ConnectionProfile profile,
    List<HostTrustRequest> approved, {
    required bool Function() isCurrent,
  }) => _serialized(() async {
    profile.validate();
    if (!isCurrent()) return;
    final previous = await _store.read(_key);
    if (!isCurrent()) return;
    final data = _decode(previous);
    final trust = List<dynamic>.from(data['trust'] as List);
    for (final item in approved) {
      trust.removeWhere(
        (entry) =>
            entry['host'] == item.host.toLowerCase() &&
            entry['port'] == item.port,
      );
      trust.add(item.toJson());
    }
    data['profile'] = profile.toJson();
    data['trust'] = trust;
    if (!isCurrent()) return;
    await _store.write(_key, jsonEncode(data));
    // A platform write cannot be interrupted. Roll back before queued operations
    // can observe a connection canceled while that write was in flight.
    if (!isCurrent()) {
      if (previous == null) {
        await _store.delete(_key);
      } else {
        await _store.write(_key, previous);
      }
    }
  });

  Future<void> clearConnection() => _serialized(() => _store.delete(_key));
  Future<void> clearHostTrust() => _serialized(() async {
    final data = _decode(await _store.read(_key));
    data['trust'] = <dynamic>[];
    await _store.write(_key, jsonEncode(data));
  });
}
