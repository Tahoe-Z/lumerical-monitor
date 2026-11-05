import 'package:flutter_test/flutter_test.dart';
import 'package:lumerical_monitor/src/domain/profile.dart';

ConnectionProfile example() => const ConnectionProfile(
  host: 'compute.example.invalid',
  username: 'monitor',
  root: '/srv/simulations',
  privateKey: 'synthetic-unparsed-key',
);

void main() {
  test('validates a normal connection and preserves secure JSON fields', () {
    final value = example().copyWith(passphrase: 'synthetic-passphrase');
    value.validate();
    final restored = ConnectionProfile.fromJson(value.toJson());
    expect(restored.toJson(), value.toJson());
    expect(value.toString(), isNot(contains(value.privateKey)));
    expect(value.toString(), isNot(contains(value.passphrase)));
    expect(value.toString(), isNot(contains(value.host)));
  });

  test('rejects malformed or option-like hostnames and usernames', () {
    for (final host in ['', '-oProxyCommand=x', 'host;bad', 'host\nother']) {
      expect(
        () => example().copyWith(host: host).validate(),
        throwsFormatException,
      );
    }
    for (final username in ['', '-root', 'user;bad', 'user\nother']) {
      expect(
        () => example().copyWith(username: username).validate(),
        throwsFormatException,
      );
    }
    example().copyWith(host: '2001:db8::1').validate();
  });

  test('rejects invalid ports, relative roots, empty keys and intervals', () {
    for (final port in [0, -1, 65536]) {
      expect(
        () => example().copyWith(port: port).validate(),
        throwsFormatException,
      );
    }
    for (final root in ['relative', '', '/srv/\u0000bad']) {
      expect(
        () => example().copyWith(root: root).validate(),
        throwsFormatException,
      );
    }
    expect(
      () => example().copyWith(privateKey: '').validate(),
      throwsFormatException,
    );
    for (final seconds in [0, 4, 601]) {
      expect(
        () => example().copyWith(refreshSeconds: seconds).validate(),
        throwsFormatException,
      );
    }
    example().copyWith(refreshSeconds: 5).validate();
    example().copyWith(refreshSeconds: 600).validate();
  });
}
