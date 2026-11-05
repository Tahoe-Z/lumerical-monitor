import 'dart:convert';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/monitor_controller.dart';
import 'shared.dart';

class SettingsPage extends StatelessWidget {
  const SettingsPage({
    super.key,
    required this.controller,
    required this.trustPrompt,
    required this.onEdit,
    required this.themeMode,
    required this.onThemeChanged,
  });
  final MonitorController controller;
  final HostTrustPrompt trustPrompt;
  final VoidCallback onEdit;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeChanged;

  Future<void> _action(
    BuildContext context,
    Future<void> Function() action,
    String message,
  ) async {
    try {
      await action();
      if (context.mounted) showMessage(context, message);
    } catch (e) {
      if (context.mounted) showMessage(context, e);
    }
  }

  Future<bool> _confirm(
    BuildContext context,
    String title,
    String message,
    String action,
  ) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(title),
          content: Text(message),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: Text(action),
            ),
          ],
        ),
      ) ??
      false;

  @override
  Widget build(BuildContext context) {
    final profile = controller.profile;
    return ListView(
      padding: const EdgeInsets.fromLTRB(22, 10, 22, 26),
      children: [
        Text('设置', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 6),
        Text('连接与本机偏好', style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 20),
        const SectionTitle('服务器连接'),
        SurfaceCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Icon(Icons.dns_outlined, color: clay, size: 25),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          profile?.name ?? '添加服务器',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 3),
                        Text(
                          profile == null
                              ? '使用 SSH 私钥安全连接'
                              : '${profile.username}@${profile.host}:${profile.port}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              if (profile != null) ...[
                const SizedBox(height: 17),
                DetailRow('项目根目录', profile.root),
                DetailRow('刷新间隔', '${profile.refreshSeconds} 秒'),
                DetailRow('许可证查询', profile.queryLicenses ? '已启用' : '已关闭'),
                const DetailRow('凭据', '私钥与口令已隐藏'),
              ],
              const SizedBox(height: 19),
              FilledButton.icon(
                onPressed: controller.isBusy ? null : onEdit,
                icon: const Icon(Icons.edit_outlined, size: 18),
                label: Text(profile == null ? '添加连接' : '编辑连接'),
              ),
              if (profile != null) ...[
                const SizedBox(height: 9),
                OutlinedButton(
                  onPressed: controller.isBusy
                      ? null
                      : () => _action(
                          context,
                          () => controller.connect(trustPrompt),
                          '已尝试重新连接',
                        ),
                  child: const Text('重新连接'),
                ),
                TextButton(
                  onPressed: () =>
                      _action(context, controller.disconnect, '连接已断开'),
                  child: const Text('断开连接'),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 20),
        const SectionTitle('外观'),
        SurfaceCard(
          child: DropdownButtonFormField<ThemeMode>(
            initialValue: themeMode,
            decoration: const InputDecoration(
              labelText: '显示模式',
              prefixIcon: Icon(Icons.brightness_6_outlined),
            ),
            items: const [
              DropdownMenuItem(value: ThemeMode.system, child: Text('跟随系统')),
              DropdownMenuItem(value: ThemeMode.light, child: Text('浅色')),
              DropdownMenuItem(value: ThemeMode.dark, child: Text('深色')),
            ],
            onChanged: (value) {
              if (value != null) onThemeChanged(value);
            },
          ),
        ),
        const SizedBox(height: 20),
        const SectionTitle('本机安全存储'),
        SurfaceCard(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.key_off_outlined, size: 22),
                title: const Text('清除连接与凭据'),
                subtitle: const Text('移除已保存的服务器、私钥和口令'),
                trailing: const Icon(Icons.chevron_right, size: 19),
                onTap: () async {
                  if (await _confirm(
                        context,
                        '清除连接与凭据？',
                        '将断开连接并移除此设备保存的连接资料。之后可重新添加。',
                        '清除',
                      ) &&
                      context.mounted) {
                    await _action(
                      context,
                      controller.clearSavedConnection,
                      '连接与凭据已清除',
                    );
                  }
                },
              ),
              const Divider(indent: 16, endIndent: 16),
              ListTile(
                leading: const Icon(Icons.verified_user_outlined, size: 22),
                title: const Text('重置主机信任'),
                subtitle: const Text('下次连接时重新核对 SSH 指纹'),
                trailing: const Icon(Icons.chevron_right, size: 19),
                onTap: () async {
                  if (await _confirm(
                        context,
                        '重置主机信任？',
                        '请先向管理员确认服务器的新指纹。重置后，下次连接必须再次明确批准指纹。',
                        '重置信任',
                      ) &&
                      context.mounted) {
                    await _action(
                      context,
                      controller.clearHostTrust,
                      '主机信任已重置',
                    );
                  }
                },
              ),
            ],
          ),
        ),
        const SizedBox(height: 24),
        const SurfaceCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Lumerical Monitor',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              SizedBox(height: 8),
              Text(
                '通过 SSH 直接连接您的服务器。只读采集，不启动或停止仿真，不上传遥测数据。进入后台会暂停监控。',
                style: TextStyle(fontSize: 12, height: 1.7),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class ConnectionEditor extends StatefulWidget {
  const ConnectionEditor({
    super.key,
    required this.controller,
    required this.trustPrompt,
  });
  final MonitorController controller;
  final HostTrustPrompt trustPrompt;
  @override
  State<ConnectionEditor> createState() => _ConnectionEditorState();
}

class _ConnectionEditorState extends State<ConnectionEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _name,
      _host,
      _port,
      _username,
      _root,
      _key,
      _passphrase,
      _interval;
  bool _licenses = true, _busy = false, _showPassphrase = false;
  String? _message;
  String? _importedName;

  @override
  void initState() {
    super.initState();
    final profile = widget.controller.profile;
    _name = TextEditingController(text: profile?.name ?? '我的服务器');
    _host = TextEditingController(text: profile?.host ?? '');
    _port = TextEditingController(text: '${profile?.port ?? 22}');
    _username = TextEditingController(text: profile?.username ?? '');
    _root = TextEditingController(text: profile?.root ?? '');
    _key = TextEditingController(text: profile?.privateKey ?? '');
    _passphrase = TextEditingController(text: profile?.passphrase ?? '');
    _interval = TextEditingController(text: '${profile?.refreshSeconds ?? 15}');
    _licenses = profile?.queryLicenses ?? true;
  }

  @override
  void dispose() {
    for (final controller in [
      _name,
      _host,
      _port,
      _username,
      _root,
      _key,
      _passphrase,
      _interval,
    ]) {
      controller.clear();
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _importKey() async {
    try {
      final file = await FilePicker.pickFile(
        dialogTitle: '选择 SSH 私钥',
        type: FileType.any,
      );
      if (!mounted || file == null) return;
      const limit = 1024 * 1024;
      final length = file.lengthSync() ?? await file.length();
      if (length != null && length > limit) {
        throw const FormatException('密钥文件过大，请选择小于 1 MiB 的文本私钥。');
      }
      final data = BytesBuilder(copy: false);
      await for (final chunk in file.readAsByteStream()) {
        if (!mounted) return;
        if (data.length + chunk.length > limit) {
          throw const FormatException('密钥文件过大，请选择小于 1 MiB 的文本私钥。');
        }
        data.add(chunk);
      }
      if (!mounted) return;
      final content = utf8.decode(data.takeBytes(), allowMalformed: false);
      setState(() {
        _key.text = content;
        _importedName = file.name;
        _message = null;
      });
    } catch (e) {
      if (mounted) {
        setState(
          () => _message = e is FormatException ? e.message : '无法导入密钥文件：$e',
        );
      }
    }
  }

  Future<void> _pasteKey() async {
    try {
      final data = await Clipboard.getData(Clipboard.kTextPlain);
      if (!mounted) return;
      final content = data?.text;
      if (content == null || content.isEmpty) {
        setState(() => _message = '剪贴板中没有文本内容。');
      } else if (content.length > 1024 * 1024) {
        setState(() => _message = '剪贴板文本过大，请粘贴私钥文本。');
      } else {
        setState(() {
          _key.text = content;
          _importedName = '从剪贴板粘贴';
          _message = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _message = '无法读取剪贴板：$e');
    }
  }

  Future<void> _save() async {
    FocusScope.of(context).unfocus();
    final valid = _form.currentState!.validate();
    final requiredIssue = _host.text.trim().isEmpty
        ? '请输入服务器地址'
        : _username.text.trim().isEmpty
        ? '请输入 SSH 用户名'
        : _root.text.trim().isEmpty
        ? '请输入项目根目录'
        : _key.text.trim().isEmpty
        ? '请导入或粘贴 SSH 私钥'
        : null;
    if (!valid || requiredIssue != null) {
      setState(() => _message = requiredIssue ?? '请检查连接信息中的提示。');
      return;
    }
    final profile = ConnectionProfile(
      name: _name.text.trim().isEmpty ? '我的服务器' : _name.text.trim(),
      host: _host.text.trim(),
      port: int.tryParse(_port.text) ?? 0,
      username: _username.text.trim(),
      root: _root.text.trim(),
      privateKey: _key.text.trim(),
      passphrase: _passphrase.text,
      refreshSeconds: int.tryParse(_interval.text) ?? 0,
      queryLicenses: _licenses,
    );
    try {
      profile.validate();
      setState(() {
        _busy = true;
        _message = null;
      });
      await widget.controller.saveAndConnect(profile, widget.trustPrompt);
      if (mounted) {
        if (widget.controller.phase == ConnectionPhase.connected) {
          Navigator.pop(context);
        } else {
          setState(
            () =>
                _message = widget.controller.errorMessage ?? '连接未建立，可检查资料后重试。',
          );
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => _message = e is FormatException ? e.message : '$e');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _required(String? value, String message) =>
      value?.trim().isNotEmpty == true ? null : message;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('连接服务器')),
    body: Form(
      key: _form,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(22, 10, 22, 32),
        children: [
          const Text(
            '添加您的 SSH 连接',
            style: TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          Text(
            '使用私钥认证。连接资料仅保存在此设备的安全存储中。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 24),
          ...spaced([
            TextFormField(
              controller: _name,
              enabled: !_busy,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(labelText: '连接名称'),
            ),
            TextFormField(
              controller: _host,
              enabled: !_busy,
              autocorrect: false,
              keyboardType: TextInputType.url,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(
                labelText: '服务器地址',
                hintText: '主机名或 IP 地址',
              ),
              validator: (v) => _required(v, '请输入服务器地址'),
            ),
            TextFormField(
              controller: _port,
              enabled: !_busy,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(labelText: 'SSH 端口'),
              validator: (v) {
                final p = int.tryParse(v ?? '');
                return p == null || p < 1 || p > 65535 ? '端口范围为 1–65535' : null;
              },
            ),
            TextFormField(
              controller: _username,
              enabled: !_busy,
              autocorrect: false,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(labelText: 'SSH 用户名'),
              validator: (v) => _required(v, '请输入 SSH 用户名'),
            ),
            TextFormField(
              controller: _root,
              enabled: !_busy,
              autocorrect: false,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(
                labelText: '项目根目录',
                hintText: '服务器上的绝对目录',
              ),
              validator: (v) => _required(v, '请输入项目根目录'),
            ),
          ]),
          const SizedBox(height: 22),
          const SectionTitle('SSH 私钥'),
          TextFormField(
            controller: _key,
            enabled: !_busy,
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            decoration: const InputDecoration(
              labelText: '私钥内容',
              prefixIcon: Icon(Icons.key_outlined),
            ),
            validator: (v) => _required(v, '请导入或粘贴 SSH 私钥'),
          ),
          if (_importedName != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                '已载入：$_importedName',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: _busy ? null : _importKey,
                icon: const Icon(Icons.upload_file_outlined, size: 18),
                label: const Text('选择密钥文件'),
              ),
              OutlinedButton.icon(
                onPressed: _busy ? null : _pasteKey,
                icon: const Icon(Icons.content_paste_rounded, size: 18),
                label: const Text('粘贴'),
              ),
            ],
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _passphrase,
            enabled: !_busy,
            obscureText: !_showPassphrase,
            autocorrect: false,
            enableSuggestions: false,
            decoration: InputDecoration(
              labelText: '私钥口令（可选）',
              suffixIcon: IconButton(
                tooltip: _showPassphrase ? '隐藏口令' : '显示口令',
                onPressed: () =>
                    setState(() => _showPassphrase = !_showPassphrase),
                icon: Icon(
                  _showPassphrase
                      ? Icons.visibility_off_outlined
                      : Icons.visibility_outlined,
                ),
              ),
            ),
          ),
          const SizedBox(height: 24),
          const SectionTitle('采集设置'),
          TextFormField(
            controller: _interval,
            enabled: !_busy,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(labelText: '自动刷新间隔（秒）'),
            validator: (v) {
              final n = int.tryParse(v ?? '');
              return n == null || n < 5 || n > 600 ? '请输入 5–600 秒' : null;
            },
          ),
          const SizedBox(height: 12),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            title: const Text('查询 FlexLM 许可证'),
            subtitle: const Text('读取可用席位和占用情况'),
            value: _licenses,
            onChanged: _busy ? null : (v) => setState(() => _licenses = v),
          ),
          const SizedBox(height: 22),
          if (_message != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 15),
              child: Text(
                _message!,
                style: const TextStyle(color: clay, fontSize: 12, height: 1.6),
              ),
            ),
          FilledButton.icon(
            onPressed: _busy ? null : _save,
            icon: _busy
                ? const SizedBox(
                    width: 17,
                    height: 17,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.link_rounded, size: 19),
            label: Text(_busy ? '正在安全连接…' : '保存并连接'),
          ),
          const SizedBox(height: 13),
          Text(
            '首次连接时，请向管理员核对主机指纹。指纹发生变化会阻止连接；确认变更后可在设置中重置信任。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    ),
  );
}
