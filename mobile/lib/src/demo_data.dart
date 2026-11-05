/// All values in this file are synthetic and never describe a real server.
Map<String, dynamic> demoSnapshot() => {
  'hostname': '演示工作站',
  'timestamp_utc': DateTime.now().toUtc().toIso8601String(),
  'cpu_count': 32,
  'cpu_percent': 67.4,
  'load_average': [14.2, 13.7, 12.9],
  'uptime_seconds': 172800,
  'memory_total': 137438953472,
  'memory_available': 51539607552,
  'swap_total': 8589934592,
  'swap_free': 8589934592,
  'disk_total': 2199023255552,
  'disk_free': 879609302220,
  'project_size': 75161927680,
  'root': '/synthetic/project',
  'filesystem': {'type': 'ext4'},
  'process_visibility': {
    'visible_count': 3,
    'unreadable': 0,
    'truncated': false,
  },
  'users': [
    {
      'user': 'demo',
      'processes': 3,
      'rss_bytes': 25769803776,
      'cpu_percent': 67.4,
      'mine': true,
    },
  ],
  'all_processes': [
    {
      'name': 'fdtd-engine',
      'pid': 1001,
      'user': 'demo',
      'cpu_percent': 65.2,
      'rss_bytes': 21474836480,
      'mine': true,
    },
  ],
  'processes': [],
  'cad_sessions': [],
  'jobs': [
    {
      'name': '纳米结构透射 · 合成样例',
      'path': 'demo/transmission',
      'dir': 'demo/transmission',
      'solver': 'FDTD',
      'state': '运行中',
      'progress': 64.5,
      'stage': '时域求解',
      'remaining': '12 分钟',
      'log': 'demo/transmission/run.log',
      'pids': [1001],
      'resources': {
        'cpu_percent': 65.2,
        'rss_bytes': 21474836480,
        'threads': 24,
        'elapsed_seconds': 1350,
        'gpu_memory': 6442450944,
      },
      'errors': [],
      'shutoff': 0.0001,
    },
    {
      'name': '波导模式 · 合成样例',
      'path': 'demo/waveguide',
      'dir': 'demo/waveguide',
      'solver': 'MODE',
      'state': '已完成',
      'progress': 100,
      'stage': '结果已保存',
      'log': 'demo/waveguide/run.log',
      'resources': {},
      'errors': [],
    },
    {
      'name': '参数扫描 · 合成样例',
      'path': 'demo/sweep',
      'dir': 'demo/sweep',
      'solver': 'FDTD',
      'state': '失败',
      'stage': '请检查网格设置',
      'log': 'demo/sweep/run.log',
      'resources': {},
      'errors': ['合成提示：请调整网格后重试'],
    },
  ],
  'gpu': {
    'available': true,
    'devices': [
      {
        'index': 0,
        'name': '演示 GPU',
        'utilization_percent': 72,
        'memory_used_bytes': 6442450944,
        'memory_total_bytes': 17179869184,
        'temperature_c': 61,
        'power_watts': 145,
      },
    ],
    'processes': [
      {
        'name': 'fdtd-engine',
        'pid': 1001,
        'user': 'demo',
        'memory_bytes': 6442450944,
      },
    ],
  },
  'license': {
    'available': true,
    'features': [
      {
        'name': 'FDTD · 合成许可',
        'issued': 8,
        'in_use': 3,
        'checkouts': [
          {'user': 'demo', 'count': 3, 'start': '演示会话'},
        ],
      },
    ],
  },
};

Map<String, dynamic> demoFiles(String path) => {
  'path': path == '.' ? '.' : 'demo',
  'limit_reached': false,
  'entries': [
    if (path == '.')
      {
        'name': 'demo',
        'path': 'demo',
        'directory': true,
        'size': 0,
        'symlink': false,
      },
    {
      'name': 'run.log',
      'path': 'demo/run.log',
      'directory': false,
      'size': 128,
      'symlink': false,
    },
    {
      'name': 'results.fsp',
      'path': 'demo/results.fsp',
      'directory': false,
      'size': 3145728,
      'symlink': false,
    },
  ],
};

Map<String, dynamic> demoLog(String path) => {
  'path': path,
  'size': 128,
  'truncated': false,
  'text': '演示日志 · 以下均为合成数据\n初始化完成\n网格生成完成\n求解进度 64.5%\n',
};
