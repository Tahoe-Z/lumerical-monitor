"""Native Windows read-only SSH dashboard; Python standard library only."""
import argparse
import collections
import datetime as dt
import json
import logging
import os
from pathlib import Path, PurePosixPath
import queue
import re
import sys
import threading
import math
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from client import Client, Profile, HERE, RESOURCES, load_settings, save_settings, update_settings
from preview_ui import PreviewPanel
from ui_kit import (C, ICON, Theme, Card, Bar, Sparkline, Switch, IconButton, Table, SearchBox, Field,
                    Rounded, RoundButton, Chip, Toaster, Tooltip, mix, level_color, use_palette, dark_title_bar)

# Match Tk window coordinates to physical pixels on high-DPI Windows displays.
if os.name=='nt':
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError,OSError):
        ctypes.windll.user32.SetProcessDPIAware()

HISTORY=120
TEXT_SUFFIXES={'.log','.txt','.md','.json','.jsonl','.lsf','.py','.sh','.csv','.tsv','.xml','.ini','.out','.err','.yaml','.yml','.cfg','.toml'}
STATE_TAG={'运行中':'green','失败':'red','需检查结果':'amber','未知/未完成':'muted'}
STATE_ORDER=['运行中','已完成','失败','需检查结果','未知/未完成']
PAGES=[('overview','概览','整机资源与可见进程'),
       ('tasks','仿真任务','Lumerical 各求解器的运行（实时进程 + 最近 14 天的日志）；状态不等于物理验收'),
       ('files','文件与日志','项目目录浏览、日志跟踪与安全下载'),
       ('gpu','GPU','NVIDIA 显卡状态与计算进程'),
       ('users','用户占用','共享服务器上各用户的资源占用'),
       ('license','许可证','FlexLM 许可证服务器状态与席位占用（lmutil lmstat 只读查询，每分钟一次）'),
       ('preview','模型与结果','已保存的模型截面、模场、透射谱和参数')]
ICON['preview']=ICON['gpu']
FOLLOW_SECONDS=5
VERSION='v8-preview'
LICENSE_TEXT={'lumerical_solve':'Lumerical 求解器 · 每个运行中的引擎占 1 个','anshpc_pack':'Ansys HPC 包 · 并行 / GPU 加速',
              'lumerical_gui':'Lumerical CAD / lumapi 会话','lum_fdtd_gui':'FDTD 图形界面','lum_mode_gui':'MODE 图形界面',
              'lum_interconnect_gui':'INTERCONNECT 图形界面','lum_multiphysics_gui':'Multiphysics（CHARGE / HEAT 等）图形界面',
              'ema_charge_solve':'CHARGE 求解','ema_charge_gui':'CHARGE 图形界面'}
ENGINE_STATUS={'UPDATE_MODES':'更新模式','MESH_START':'开始网格划分','MESH_FINISH':'网格划分完成',
               'BUILD_SOURCES_START':'开始构建光源','BUILD_SOURCES_FINISH':'光源构建完成',
               'WRITE_START':'开始写出结果','WRITE_FINISH':'结果写出完成'}
ENGINE_TAGS={'progress':'进度','time':'剩余','shutoff':'Shutoff'}


def pretty_engine_log(text):
    """Render Lumerical's -remote XML protocol as readable lines; anything else passes through unchanged."""
    columns=dict((tag,title) for title,tag in re.findall(
        r'<column><title>([^<]*)</title>(?:<type>[^<]*</type>)?<tagname>([^<]*)</tagname></column>',text))
    out=[]
    for line in text.splitlines():
        stripped=line.strip()
        if stripped.startswith(('<addcolumn>','<propertylist>')):
            if columns and stripped.startswith('<addcolumn>'):
                out.append('# 引擎声明的列：'+'、'.join(columns.values()))
            continue
        status=re.fullmatch(r'<status>([^<]*)</status>',stripped)
        if status:
            out.append('▸ '+ENGINE_STATUS.get(status[1],status[1]))
            continue
        update=re.fullmatch(r'<update>(.*)</update>',stripped)
        if update:
            fields=re.findall(r'<(\w+)>([^<]*)</\1>',update[1])
            parts=[]
            for tag,value in fields:
                if tag=='progress':
                    try:
                        value=f'{float(value):.2f}%'
                    except ValueError:
                        pass
                parts.append(f'{ENGINE_TAGS.get(tag,columns.get(tag,tag))} {value}')
            out.append('  '+'   ·   '.join(parts))
            continue
        if stripped=='<simComplete/>':
            out.append('✓ 仿真完成')
            continue
        if stripped=='<complete/>':
            out.append('✓ 引擎正常结束')
            continue
        out.append(line)
    return '\n'.join(out)


def short_folder(path,keep=3):
    parts=PurePosixPath(path).parts if path else ()
    return '/'.join(parts) if len(parts)<=keep else '…/'+'/'.join(parts[-keep:])


def size(value):
    if value is None:
        return '—'
    for unit in ['B','KiB','MiB','GiB','TiB']:
        if abs(value)<1024 or unit=='TiB':
            return f'{value:.1f} {unit}'
        value/=1024


def stamp(value):
    return dt.datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M')


def duration(seconds):
    s=int(seconds or 0)
    d,r=divmod(s,86400)
    h,r=divmod(r,3600)
    m,s=divmod(r,60)
    if d:
        return f'{d}天 {h}时'
    if h:
        return f'{h}时 {m:02d}分'
    if m:
        return f'{m}分 {s:02d}秒'
    return f'{s}秒'


def ago(seconds):
    seconds=int(seconds)
    if seconds<5:
        return '刚刚'
    if seconds<60:
        return f'{seconds} 秒前'
    return f'{seconds//60} 分钟前'


def pct(value,digits=1):
    return '—' if value is None else f'{value:.{digits}f}%'


TOAST_SCRIPT=r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Security.SecurityElement]::Escape($env:LUM_TOAST_TITLE)
$b = [Security.SecurityElement]::Escape($env:LUM_TOAST_BODY)
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show($n)
'''


def system_toast(title,body=''):
    """Windows notification-centre toast. Text travels in environment variables and is XML-escaped by the script."""
    if os.name!='nt':
        return
    import base64,subprocess
    encoded=base64.b64encode(TOAST_SCRIPT.encode('utf-16-le')).decode()
    try:
        subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',encoded],
                         env={**os.environ,'LUM_TOAST_TITLE':title[:120],'LUM_TOAST_BODY':body[:240]},
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except OSError:
        pass


def remote_join(root,path):
    return str(PurePosixPath(root)/path) if path not in ('','.') else root


class Monitor(tk.Tk):
    def __init__(self, auto_connect=True):
        self.appearance=load_settings().get('theme','system')
        self.mode=use_palette(self.appearance)
        super().__init__()
        self.theme=t=Theme(self)
        t.apply(self)
        dark_title_bar(self,self.mode=='dark')
        self.title('Lumerical Monitor · 远程只读监控')
        self.geometry(f'{t.px(1320)}x{t.px(860)}')
        self.minsize(t.px(1080),t.px(700))
        if auto_connect:
            self._restore_window(load_settings())
        self.configure(bg=C['bg'])
        try:
            self.iconbitmap(default=str(RESOURCES/'icon.ico'))
        except tk.TclError:
            pass
        self.settings=load_settings()
        self.refresh_seconds=self._interval(self.settings.get('refresh_seconds',15))
        self.client=Client()
        self.offline=not auto_connect
        self.events=queue.Queue()
        self.busy=set()
        self.last_success=None
        self.next_refresh=None
        self.snapshot=None
        self.current_path='.'
        self.cancel_download=threading.Event()
        self.closed=False
        self.closing=False
        self.auto=tk.BooleanVar(value=True)
        self.mine_only=tk.BooleanVar(value=False)
        self.follow=tk.BooleanVar(value=False)
        self.connection=tk.StringVar(value='尚未连接')
        self.host_text=tk.StringVar()
        self.activity=tk.StringVar(value='只读模式：查看状态、文件和日志，支持下载到本地。')
        self.path_var=tk.StringVar(value='.')
        self.age=tk.StringVar(value='')
        self.download_text=tk.StringVar(value='')
        self.log_title=tk.StringVar(value='选择文本文件后双击或点“查看”；也可在任务页直接打开任务日志。')
        self.page_title=tk.StringVar()
        self.page_sub=tk.StringVar()
        self.history={k:collections.deque(maxlen=HISTORY) for k in ('cpu','gpu','memory','disk')}
        self.gpu_history=collections.defaultdict(lambda:collections.deque(maxlen=HISTORY))
        self.known_jobs=None
        self.failed_streak=0
        self.alerted=set()
        self.log_path=None
        self.log_loaded_at=0
        self.pending={}  # latest-wins follow-up request per key ('files' / 'tail')
        self.preview_path=''
        self.preview_target=''
        self.preview_generation=0
        self.preview_pending=None
        self.preview_checked=0
        self.preview_running=False
        self.preview_cancel=threading.Event()
        self.task_filter='全部'
        self.solver_filter='全部'
        self.solver_chips={}
        self.pretty=tk.BooleanVar(value=True)
        self.jobs=[]
        self.stall_alerted=set()
        self.toasts=bool(load_settings().get('toasts',True))
        self.license_query=bool(load_settings().get('license_query',True))
        self.license=None
        self.gpu_cards=[]
        self.page=None
        self._update_host_text()
        self._build()
        self.toaster=Toaster(self,t)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self._bind_keys()
        start=load_settings().get('page','overview') if auto_connect else 'overview'
        self.show_page(start if start in [k for k,_,_ in PAGES] else 'overview')
        self.after(100,self._drain)
        self.after(1000,self._tick)
        if auto_connect:
            self.after(250,self.refresh)

    def _restore_window(self,settings):
        geometry=str(settings.get('window',''))
        m=re.fullmatch(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)',geometry)
        if m:
            w,h,x,y=map(int,m.groups())
            # Only reuse the position if the title bar would still be on a screen we can see.
            on_screen=-w//2<x<self.winfo_screenwidth()-100 and 0<=y<self.winfo_screenheight()-100
            self.geometry(f'{w}x{h}+{x}+{y}' if on_screen else f'{w}x{h}')
        if settings.get('zoomed'):
            self.after(50,lambda:self.state('zoomed'))

    def _save_window(self):
        if self.offline:
            return
        try:
            zoomed=self.state()=='zoomed'
            if zoomed:
                self.state('normal')
            update_settings(window=self.geometry(),zoomed=zoomed,page=self.page)
        except (OSError,tk.TclError):
            pass

    @staticmethod
    def _interval(value):
        try:
            return max(5,min(600,int(value)))
        except (TypeError,ValueError):
            return 15

    def _update_host_text(self):
        p=self.client.profile
        self.host_text.set(f'{p.user}@{p.host}:{p.port}')

    # ------------------------------------------------------------------ layout
    def _build(self):
        t=self.theme
        self.columnconfigure(1,weight=1)
        self.rowconfigure(0,weight=1)
        side=tk.Frame(self,bg=C['side'],width=t.px(236))
        side.grid(row=0,column=0,sticky='nsw')
        side.pack_propagate(False)
        self._build_sidebar(side)
        self.columnconfigure(2,weight=1)
        self.columnconfigure(1,weight=0)
        tk.Frame(self,bg=C['border'],width=1).grid(row=0,column=1,sticky='ns')  # hairline like the desktop app
        main=tk.Frame(self,bg=C['bg'])
        main.grid(row=0,column=2,sticky='nsew')
        self._build_statusbar(main)
        self._build_topbar(main)
        stack=tk.Frame(main,bg=C['bg'])
        stack.pack(fill='both',expand=True,padx=t.px(32),pady=(0,t.px(12)))
        stack.rowconfigure(0,weight=1)
        stack.columnconfigure(0,weight=1)
        self.pages={}
        for key,_,_ in PAGES:
            frame=tk.Frame(stack,bg=C['bg'])
            frame.grid(row=0,column=0,sticky='nsew')
            self.pages[key]=frame
        self.file_page=self.pages['files']
        self._build_overview(self.pages['overview'])
        self._build_tasks(self.pages['tasks'])
        self._build_files(self.pages['files'])
        self._build_gpu(self.pages['gpu'])
        self._build_users(self.pages['users'])
        self._build_license(self.pages['license'])
        self._build_preview(self.pages['preview'])

    def _build_sidebar(self,side):
        t=self.theme
        logo=tk.Frame(side,bg=C['side'])
        logo.pack(fill='x',padx=t.px(20),pady=(t.px(22),t.px(26)))
        size_=t.px(30)
        mark=tk.Canvas(logo,width=size_,height=size_,bg=C['side'],highlightthickness=0)
        mark.pack(side='left')
        self._logo_mark=Rounded(mark,t,C['accent'],radius=8,outer=C['side'])
        mark.create_window(0,0,anchor='nw',window=self._logo_mark,width=size_,height=size_)
        pulse=tk.Canvas(self._logo_mark,width=t.px(18),height=t.px(14),bg=C['accent'],highlightthickness=0)
        pulse.place(relx=.5,rely=.5,anchor='center')
        u=t.px(18)/22
        pulse.create_line(1*u,8*u,6*u,8*u,9*u,2*u,13*u,13*u,16*u,6*u,21*u,6*u,fill=C['on_accent'],width=t.px(1.8),
                          joinstyle='round',capstyle='round')
        txt=tk.Frame(logo,bg=C['side'])
        txt.pack(side='left',padx=t.px(11))
        tk.Label(txt,text='Lumerical',bg=C['side'],fg=C['text'],font=t.serif_font(15,'bold')).pack(anchor='w')
        tk.Label(txt,text='Monitor · 远程仿真监控',bg=C['side'],fg=C['muted'],font=t.font(8)).pack(anchor='w')
        self.nav={}
        for n,(key,title,_) in enumerate(PAGES):
            item=Rounded(side,t,C['side'],radius=9,cursor='hand2')
            item.pack(fill='x',padx=t.px(12),pady=t.px(1))
            row=tk.Frame(item,bg=C['side'],cursor='hand2')
            row.pack(fill='x',padx=t.px(8),pady=t.px(4))
            icon=tk.Label(row,text=ICON[key],font=t.icon(12),bg=C['side'],fg=C['muted'],padx=t.px(4),pady=t.px(3))
            icon.pack(side='left')
            text=tk.Label(row,text=title,font=t.font(10),bg=C['side'],fg=C['sub'])
            text.pack(side='left',padx=(t.px(8),0))
            badge=tk.Label(row,text='',font=t.font(8,'bold'),bg=C['side'],fg=C['accent'])
            badge.pack(side='right',padx=t.px(4))
            for w in (item,item.canvas,row,icon,text,badge):
                w.bind('<Button-1>',lambda e,k=key:self.show_page(k))
                w.bind('<Enter>',lambda e,k=key:self._nav_hover(k,True))
                w.bind('<Leave>',lambda e,k=key:self._nav_hover(k,False))
            Tooltip(item,f'{title}  (Ctrl+{n+1})')
            self.nav[key]=dict(item=item,icon=icon,text=text,badge=badge)
        foot=tk.Frame(side,bg=C['side'])
        foot.pack(side='bottom',fill='x',padx=t.px(12),pady=t.px(14))
        box=Card(foot,t,pad=12)
        box.pack(fill='x')
        inner=box.body
        row=tk.Frame(inner,bg=C['surface'])
        row.pack(fill='x')
        d=t.px(9)
        self.conn_dot=tk.Canvas(row,width=d,height=d,bg=C['surface'],highlightthickness=0)
        self.conn_dot.pack(side='left',pady=t.px(2))
        self.conn_dot_item=self.conn_dot.create_oval(0,0,d-1,d-1,fill=C['muted'],outline='')
        self.connection_label=tk.Label(row,textvariable=self.connection,bg=C['surface'],fg=C['text'],font=t.font(9,'bold'),
                                       anchor='w',justify='left',wraplength=t.px(160))
        self.connection_label.pack(side='left',padx=(t.px(7),0),fill='x')
        tk.Label(inner,textvariable=self.host_text,bg=C['surface'],fg=C['muted'],font=(t.mono,8),anchor='w').pack(fill='x',pady=(t.px(5),0))
        tk.Label(inner,textvariable=self.age,bg=C['surface'],fg=C['muted'],font=t.font(8),anchor='w').pack(fill='x')
        RoundButton(foot,t,'设置',self.open_settings,kind='ghost',icon=ICON['settings'],size=9).pack(anchor='w',pady=(t.px(8),0))

    def _nav_hover(self,key,inside):
        if key==self.page:
            return
        self.nav[key]['item'].recolor(C['raised'] if inside else C['side'])

    def _build_topbar(self,main):
        t=self.theme
        top=tk.Frame(main,bg=C['bg'])
        top.pack(fill='x',padx=t.px(32),pady=(t.px(22),t.px(18)))
        left=tk.Frame(top,bg=C['bg'])
        left.pack(side='left',fill='x',expand=True)
        tk.Label(left,textvariable=self.page_title,bg=C['bg'],fg=C['text'],font=t.serif_font(21)).pack(anchor='w')
        tk.Label(left,textvariable=self.page_sub,bg=C['bg'],fg=C['muted'],font=t.font(9)).pack(anchor='w',pady=(t.px(1),0))
        right=tk.Frame(top,bg=C['bg'])
        right.pack(side='right')
        refresh=RoundButton(right,t,'刷新',self.refresh,kind='primary',icon=ICON['refresh'])
        refresh.pack(side='right')
        Tooltip(refresh,'立即刷新（F5）')
        self.auto_switch=Switch(right,t,self.auto,'',command=self._toggle_auto)
        self.auto_switch.pack(side='right',padx=(t.px(18),t.px(18)))
        self.auto_switch.text.configure(text=f'自动刷新 · {self.refresh_seconds}s')
        Switch(right,t,self.mine_only,'只看我的',command=self.filter_processes).pack(side='right')

    def _build_statusbar(self,main):
        t=self.theme
        bar=tk.Frame(main,bg=C['bg'])
        bar.pack(side='bottom',fill='x')
        tk.Frame(bar,bg=C['border'],height=1).pack(fill='x',side='top')
        tk.Label(bar,textvariable=self.activity,bg=C['bg'],fg=C['muted'],font=t.font(9),anchor='w').pack(
            side='left',fill='x',expand=True,padx=t.px(32),pady=t.px(7))
        self.countdown=tk.StringVar()
        tk.Label(bar,textvariable=self.countdown,bg=C['bg'],fg=C['faint'],font=t.font(9)).pack(side='right',padx=t.px(32))

    def _metric_card(self,parent,key,title,color):
        t=self.theme
        card=Card(parent,t,pad=18)
        b=card.body
        head=tk.Frame(b,bg=C['surface'])
        head.pack(fill='x')
        title_var=tk.StringVar(value=title)
        tk.Label(head,textvariable=title_var,bg=C['surface'],fg=C['muted'],font=t.font(9)).pack(side='left')
        chip=tk.StringVar()
        tk.Label(head,textvariable=chip,bg=C['surface'],fg=C['faint'],font=t.font(8)).pack(side='right')
        value=tk.StringVar(value='—')
        tk.Label(b,textvariable=value,bg=C['surface'],fg=C['text'],font=t.serif_font(26),anchor='w').pack(fill='x',pady=(t.px(4),t.px(6)))
        bar=Bar(b,t,height=6,color=color)
        bar.pack(fill='x')
        detail=tk.StringVar(value='等待连接')
        lbl=tk.Label(b,textvariable=detail,bg=C['surface'],fg=C['muted'],font=t.font(9),anchor='w',justify='left')
        lbl.pack(fill='x',pady=(t.px(8),t.px(6)))
        b.bind('<Configure>',lambda e,l=lbl:l.configure(wraplength=max(80,e.width-4)))
        spark=Sparkline(b,t,color,height=40,capacity=HISTORY)
        spark.pack(fill='x')
        self.metrics[key]=dict(value=value,detail=detail,bar=bar,spark=spark,chip=chip,color=color,title=title_var)
        if key=='disk':
            spark.pack_forget()  # a 0–100% trend of a slowly filling disk carries no information
        return card

    def _build_overview(self,page):
        t=self.theme
        cards=tk.Frame(page,bg=C['bg'])
        cards.pack(fill='x')
        self.metrics={}
        for col,(key,title,color) in enumerate([('cpu','CPU',C['accent']),('gpu','GPU · 峰值利用率',C['purple']),
                                                ('memory','内存',C['blue']),('disk','磁盘（共享）',C['amber'])]):
            cards.columnconfigure(col,weight=1,uniform='cards')
            self._metric_card(cards,key,title,color).grid(row=0,column=col,sticky='nsew',padx=(0,t.px(14)) if col<3 else 0)
        lower=tk.Frame(page,bg=C['bg'])
        lower.pack(fill='both',expand=True,pady=(t.px(14),0))
        lower.columnconfigure(0,weight=1)
        lower.columnconfigure(1,weight=0,minsize=t.px(320))
        lower.rowconfigure(0,weight=1)
        proc=Card(lower,t,title='进程')
        proc.grid(row=0,column=0,sticky='nsew',padx=(0,t.px(14)))
        self.process_heading=proc.title_var
        self.proc_search=SearchBox(proc.header,t,self._filter_proc,'搜索用户 / 进程 / PID',width=20)
        self.proc_search.pack(side='right')
        self.proc_table=Table(proc.body,t,[('user','用户',120),('pid','PID',84,'e'),('name','进程',190,'w',True),
                                            ('cpu','实时 CPU',90,'e'),('avg','平均 CPU',90,'e'),('rss','内存',100,'e'),
                                            ('threads','线程',60,'e'),('elapsed','已运行',100,'e')],empty='等待服务器数据')
        self.proc_table.pack(fill='both',expand=True)
        self._context(self.proc_table,lambda r:[('复制 PID',lambda:self._copy(r['data']['pid']))])
        self.process_note=tk.StringVar()
        tk.Label(proc.body,textvariable=self.process_note,bg=C['surface'],fg=C['muted'],font=t.font(8),anchor='w').pack(fill='x',pady=(t.px(8),0))
        side=tk.Frame(lower,bg=C['bg'],width=t.px(320))
        side.grid(row=0,column=1,sticky='nsew')
        running=Card(side,t,title='正在运行')
        running.pack(fill='x',pady=(0,t.px(14)))
        self.run_heading=running.title_var
        self.run_box=running.body
        host=Card(side,t,title='主机')
        host.pack(fill='x')
        self.host_rows={}
        for key,name in [('hostname','主机名'),('uptime','运行时长'),('load','负载 1/5/15'),('swap','交换内存'),
                         ('procs','可见进程'),('clock','服务器时间')]:
            row=tk.Frame(host.body,bg=C['surface'])
            row.pack(fill='x',pady=t.px(2))
            tk.Label(row,text=name,bg=C['surface'],fg=C['muted'],font=t.font(9)).pack(side='left')
            var=tk.StringVar(value='—')
            tk.Label(row,textvariable=var,bg=C['surface'],fg=C['text'],font=t.font(9)).pack(side='right')
            self.host_rows[key]=var
        feed=Card(side,t,title='动态')
        feed.pack(fill='both',expand=True,pady=(t.px(14),0))
        self.feed=tk.Text(feed.body,bg=C['surface'],fg=C['sub'],font=t.font(9),relief='flat',highlightthickness=0,
                          wrap='word',width=10,height=6,state='disabled',cursor='arrow',spacing1=t.px(3),spacing3=t.px(3))
        self.feed.pack(fill='both',expand=True)
        self.feed.tag_configure('time',foreground=C['muted'],font=(t.mono,8))
        for kind,color in [('ok',C['green']),('error',C['red']),('warn',C['amber']),('info',C['sub'])]:
            self.feed.tag_configure(kind,foreground=color)
        self._feed('info','程序已启动，等待第一次读取。')

    def _build_tasks(self,page):
        t=self.theme
        bar=tk.Frame(page,bg=C['bg'])
        bar.pack(fill='x',pady=(0,t.px(12)))
        self.chips={}
        for state in ['全部']+STATE_ORDER:
            chip=Chip(bar,t,state,lambda s=state:self._set_task_filter(s),
                      color=C[STATE_TAG[state]] if state in STATE_TAG else C['accent'])
            chip.pack(side='left',padx=(0,t.px(8)))
            self.chips[state]=chip
        self.task_search=SearchBox(bar,t,lambda q:self.task_table.filter(q),'搜索任务',width=22)
        self.task_search.pack(side='right')
        card=Card(page,t,title='任务列表')
        card.pack(fill='both',expand=True)
        self.task_heading=card.title_var
        self.solver_bar=tk.Frame(card.header,bg=C['surface'])
        self.solver_bar.pack(side='right')
        self.task_table=Table(card.body,t,[('state','状态',96),('solver','求解器',124),('name','任务',210,'w',True),
                                            ('where','位置',230),('progress','进度',70,'e'),('shutoff','Shutoff',96,'e'),
                                            ('eta','预计剩余',92,'e'),('res','资源',160,'e'),('time','更新',96,'e')],
                              on_open=lambda r:self.open_job(),on_select=self._show_job_detail,empty='没有发现任务')
        self.task_table.pack(fill='both',expand=True)
        self.task_tree=self.task_table.tree
        self._context(self.task_table,lambda r:[('浏览任务目录',self.open_job),('查看任务日志',self.open_job_log),
                                                ('复制远程路径',lambda:self._copy(remote_join(self.client.profile.root,r['data']['path']))),
                                                *([('复制 PID',lambda:self._copy(' '.join(map(str,r['data']['pids']))))] if r['data'].get('pids') else [])])
        detail=Card(page,t,pad=16)
        detail.pack(fill='x',pady=(t.px(14),0))
        b=detail.body
        head=tk.Frame(b,bg=C['surface'])
        head.pack(fill='x')
        self.job_state_label=tk.Label(head,text='',bg=C['surface'],fg=C['sub'],font=t.font(9,'bold'),padx=t.px(9),pady=t.px(2))
        self.job_state_label.pack(side='left')
        self.job_name=tk.StringVar(value='选择一个任务查看详情')
        tk.Label(head,textvariable=self.job_name,bg=C['surface'],fg=C['text'],font=t.font(11,'bold')).pack(side='left',padx=t.px(10))
        buttons=tk.Frame(head,bg=C['surface'])
        buttons.pack(side='right')
        RoundButton(buttons,t,'查看日志',self.open_job_log,kind='primary').pack(side='right')
        RoundButton(buttons,t,'浏览目录',self.open_job).pack(side='right',padx=t.px(8))
        RoundButton(buttons,t,'模型与结果',lambda:self.show_page('preview')).pack(side='right')
        row=tk.Frame(b,bg=C['surface'])
        row.pack(fill='x',pady=(t.px(10),0))
        chart=tk.Frame(row,bg=C['surface'])
        chart.pack(side='right',padx=(t.px(24),0))
        self.series_label=tk.StringVar(value='收敛曲线')
        tk.Label(chart,textvariable=self.series_label,bg=C['surface'],fg=C['muted'],font=t.font(8)).pack(anchor='w')
        self.shutoff_spark=Sparkline(chart,t,C['amber'],height=46,capacity=80,fit=True)
        self.shutoff_spark.configure(width=t.px(300))
        self.shutoff_spark.marker=(self._shutoff_scale(1e-5),C['faint'])
        self.shutoff_spark.pack()
        self.task_preview=PreviewPanel(chart,t,load=self._select_preview,
            open_full=lambda:self.show_page('preview'),compact=True)
        self.task_preview.pack(fill='x',pady=(t.px(8),0))
        info=tk.Frame(row,bg=C['surface'])
        info.pack(side='left',fill='both',expand=True)
        self.job_progress=tk.StringVar(value='')
        tk.Label(info,textvariable=self.job_progress,bg=C['surface'],fg=C['text'],font=t.serif_font(20),anchor='w').pack(fill='x')
        self.job_bar=Bar(info,t,height=8,color=C['green'])
        self.job_bar.pack(fill='x',pady=(t.px(6),t.px(8)))
        self.job_detail=tk.StringVar(value='双击任务打开目录；“查看日志”会跳到日志页并开启自动跟踪。')
        lbl=tk.Label(info,textvariable=self.job_detail,bg=C['surface'],fg=C['muted'],font=t.font(9),anchor='w',justify='left')
        lbl.pack(fill='x')
        self.job_alert=tk.StringVar()
        alert=tk.Label(info,textvariable=self.job_alert,bg=C['surface'],fg=C['red'],font=t.font(9),anchor='w',justify='left')
        alert.pack(fill='x',pady=(t.px(4),0))
        info.bind('<Configure>',lambda e:[w.configure(wraplength=max(200,e.width-8)) for w in (lbl,alert)])

    def _build_files(self,page):
        t=self.theme
        nav=tk.Frame(page,bg=C['bg'])
        nav.pack(fill='x',pady=(0,t.px(12)))
        IconButton(nav,t,ICON['home'],lambda:self.load_files('.'),'项目根目录').pack(side='left')
        IconButton(nav,t,ICON['up'],self.up_directory,'上一级').pack(side='left',padx=(t.px(4),t.px(8)))
        tk.Label(nav,text=self.client.profile.root.rstrip('/')+'/',bg=C['bg'],fg=C['muted'],font=(t.mono,9)).pack(side='left')
        self.root_label=nav.winfo_children()[-1]
        path_field=Field(nav,t,self.path_var,mono=True)
        path_field.pack(side='left',fill='x',expand=True,padx=(t.px(4),t.px(8)))
        path_field.entry.bind('<Return>',lambda e:self.load_files(self.path_var.get()))
        IconButton(nav,t,ICON['refresh'],lambda:self.load_files(self.path_var.get()),'刷新目录').pack(side='left')
        self.file_search=SearchBox(nav,t,lambda q:self._count_files(self.file_table.filter(q)),'筛选文件名',width=16)
        self.file_search.pack(side='left',padx=(t.px(8),0))
        panes=ttk.Panedwindow(page,orient='vertical')
        panes.pack(fill='both',expand=True)
        listing=Card(panes,t,title='目录')
        viewer=Card(panes,t,title='')
        panes.add(listing,weight=2)
        panes.add(viewer,weight=3)
        self.files_heading=listing.title_var
        self.file_table=Table(listing.body,t,[('name','名称',460,'w',True),('kind','类型',90),('size','大小',110,'e'),
                                              ('mtime','修改时间',150,'e')],on_open=self.open_selected,
                                              on_select=self._file_preview_selected,empty='尚未读取目录')
        self.file_table.pack(fill='both',expand=True)
        self.file_tree=self.file_table.tree
        self._context(self.file_table,lambda r:[('打开 / 查看',lambda:self.open_selected(r)),('下载…',self.download_selected),
                                                ('复制远程路径',lambda:self._copy(remote_join(self.client.profile.root,r['data']['path'])))])
        h=viewer.header
        viewer.title_var.set('')
        RoundButton(h,t,'查看',self.view_selected).pack(side='left')
        RoundButton(h,t,'下载…',self.download_selected,icon=ICON['download']).pack(side='left',padx=t.px(8))
        self.cancel_button=RoundButton(h,t,'取消下载',self.cancel_download.set,kind='ghost')
        self.cancel_button.set_enabled(False)
        self.cancel_button.pack(side='left')
        self.download_bar=Bar(h,t,height=5,color=C['accent'],bg=C['surface'])
        self.download_bar.configure(width=t.px(120))
        self.download_label=tk.Label(h,textvariable=self.download_text,bg=C['surface'],fg=C['muted'],font=t.font(9))
        self.download_label.pack(side='left',padx=t.px(10))
        self.log_search=SearchBox(h,t,self._search_log,'在日志中查找（回车下一个）',width=22)
        self.log_search.pack(side='right')
        self.log_search.entry.bind('<Return>',lambda e:self._next_match())
        Switch(h,t,self.follow,f'跟踪 · {FOLLOW_SECONDS}s',command=self._toggle_follow).pack(side='right',padx=t.px(14))
        pretty=Switch(h,t,self.pretty,'整理 XML',command=lambda:self._last_text and self.show_text(self._last_text))
        pretty.pack(side='right')
        Tooltip(pretty,'把 *_engine.log / solve.log 中的 Lumerical 引擎协议显示为可读文字')
        title=tk.Frame(viewer.body,bg=C['surface'])
        title.pack(fill='x',pady=(0,t.px(6)))
        tk.Label(title,textvariable=self.log_title,bg=C['surface'],fg=C['sub'],font=(t.mono,9),anchor='w').pack(side='left',fill='x',expand=True)
        self.match_text=tk.StringVar()
        tk.Label(title,textvariable=self.match_text,bg=C['surface'],fg=C['amber'],font=t.font(9)).pack(side='right')
        frame=tk.Frame(viewer.body,bg=C['log'],highlightthickness=1,highlightbackground=C['line'])
        frame.pack(fill='both',expand=True)
        self.log=tk.Text(frame,wrap='none',font=(t.mono,9),bg=C['log'],fg=C['log_text'],insertbackground=C['text'],
                         selectbackground=C['select'],relief='flat',highlightthickness=0,padx=t.px(10),pady=t.px(8),
                         state='disabled',spacing1=1)
        ybar=ttk.Scrollbar(frame,orient='vertical',command=self.log.yview)
        xbar=ttk.Scrollbar(frame,orient='horizontal',command=self.log.xview)
        self.log.configure(yscrollcommand=ybar.set,xscrollcommand=xbar.set)
        self.log.grid(row=0,column=0,sticky='nsew')
        ybar.grid(row=0,column=1,sticky='ns')
        xbar.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1)
        frame.columnconfigure(0,weight=1)
        self.log.tag_configure('err',foreground=C['red'])
        self.log.tag_configure('warn',foreground=C['amber'])
        self.log.tag_configure('ok',foreground=C['green'])
        self.log.tag_configure('match',background=mix(C['log'],C['amber'],.30),foreground=C['text'])
        self.log.tag_configure('current',background=C['amber'],foreground='#111111')
        self.log.tag_raise('match')
        self.log.tag_raise('current')

    def _build_preview(self,page):
        card=Card(page,self.theme,title='模型与结果 · 预览缓存')
        card.pack(fill='both',expand=True)
        self.preview_view=PreviewPanel(card.body,self.theme,load=lambda path:self._select_preview(path,force=True),
                                       generate=self._prepare_preview)
        self.preview_view.pack(fill='both',expand=True)

    def _file_preview_selected(self,row):
        if self.page=='files' and row and not row['data'].get('directory') and Path(row['data']['path']).suffix.lower() in {'.fsp','.lms'}:
            self._select_preview(row['data']['path'],open_page=True)

    def _select_preview(self,path,running=False,open_page=False,force=False):
        if not path:
            return
        if not running and self.snapshot:
            for job in self.snapshot.get('jobs',[]):
                if job.get('pids') and (job.get('path')==path or
                    job.get('kind')=='pipeline' and PurePosixPath(path).is_relative_to(PurePosixPath(job['path']))):
                    running=True
                    break
        if open_page:
            self.show_page('preview')
        self.preview_running=running
        for panel in (self.task_preview,self.preview_view):
            panel.set_running(running)
        if not force and path==self.preview_target and time.monotonic()-self.preview_checked<60:
            return
        self.preview_target=path
        self.preview_path=path
        self.preview_generation+=1
        generation=self.preview_generation
        for panel in (self.task_preview,self.preview_view):
            panel.loading(path)
        if self.offline:
            for panel in (self.task_preview,self.preview_view):
                panel.status.set('离线界面：连接服务器后读取已保存预览')
            return
        if 'preview-cache' in self.busy:
            self.preview_pending=(path,running)
            return
        client=self.client
        def work():
            try:
                return client.request('preview',path)
            except Exception as error:
                return {'_error':str(error)}
        def done(info):
            if client is self.client and generation==self.preview_generation:
                self.preview_checked=time.monotonic()
                if '_error' in info:
                    for panel in (self.task_preview,self.preview_view):
                        panel.error(info['_error'])
                else:
                    self.preview_path=info.get('project',path)
                    for panel in (self.task_preview,self.preview_view):
                        panel.set_document(info)
            pending=self.preview_pending
            self.preview_pending=None
            if pending:
                self._select_preview(pending[0],running=pending[1],force=True)
        self.submit('preview-cache',work,done)

    def _prepare_preview(self,path,wavelength_m,z_m):
        if self.offline or not path:
            self.preview_view.error('请先连接服务器并选择工程文件')
            return
        if self.preview_running:
            self.preview_view.error('任务运行中仅显示已保存缓存；请完成并保存工程后生成新预览')
            return
        if 'preview-build' in self.busy:
            self.activity.set('预览正在生成，请稍候。')
            return
        if not math.isfinite(wavelength_m) or wavelength_m<=0 or not math.isfinite(z_m):
            self.preview_view.error('波长和截面参数无效')
            return
        if not messagebox.askyesno('生成模型与结果预览',
            '将在服务器新开一个隐藏的 Lumerical 会话读取已保存工程，可能占用 GUI 许可证。\n\n'
            '此操作只写入该工程旁的 .preview.json 缓存，不重新求解、不保存覆盖原工程。\n'
            '大型工程建议在已有仿真脚本中导出。是否继续？',parent=self):
            return
        self.preview_cancel.clear()
        self.preview_view.generate_button.set_enabled(False)
        self.preview_view.status.set('正在读取工程并准备预览；原工程保持不变…')
        generation=self.preview_generation
        client=self.client
        def work():
            try:
                return client.prepare_preview(path,wavelength_m=wavelength_m,z_m=z_m,cancel=self.preview_cancel)
            except Exception as error:
                return {'_error':str(error)}
        def done(info):
            self.preview_view.generate_button.set_enabled(not self.preview_running)
            if client is not self.client or generation!=self.preview_generation:
                return
            if '_error' in info:
                self.preview_view.error(info['_error'])
                return
            for panel in (self.task_preview,self.preview_view):
                panel.set_document(info)
            self.preview_checked=time.monotonic()
            self.activity.set('模型与结果预览已更新。')
        self.submit('preview-build',work,done)

    def _build_gpu(self,page):
        t=self.theme
        self.gpu_summary=tk.StringVar(value='连接后读取 NVIDIA GPU 状态。')
        tk.Label(page,textvariable=self.gpu_summary,bg=C['bg'],fg=C['sub'],font=t.font(9),anchor='w').pack(fill='x',pady=(0,t.px(10)))
        self.gpu_grid=tk.Frame(page,bg=C['bg'])
        self.gpu_grid.pack(fill='x')
        procs=Card(page,t,title='GPU 计算进程')
        procs.pack(fill='both',expand=True,pady=(t.px(14),0))
        self.gpu_process_heading=procs.title_var
        self.gpu_process_note=tk.StringVar(value='列出权限范围内各用户的 GPU 计算进程。')
        tk.Label(procs.header,textvariable=self.gpu_process_note,bg=C['surface'],fg=C['muted'],font=t.font(9)).pack(side='right')
        self.gpu_process_table=Table(procs.body,t,[('gpu','GPU',70,'center'),('user','用户',140),('pid','PID',100,'e'),
                                                   ('name','进程',200),('task','所属任务',300,'w',True),('memory','显存',130,'e')],
                                     empty='当前没有可见的 GPU 计算进程')
        self.gpu_process_table.pack(fill='both',expand=True)
        self.gpu_process_tree=self.gpu_process_table.tree
        tk.Label(procs.body,text='利用率和显存为全卡数据；进程表不含图形进程，进程显存之和可能小于全卡用量。不可用指标显示“—”。',
                 bg=C['surface'],fg=C['muted'],font=t.font(8),anchor='w').pack(fill='x',pady=(t.px(8),0))

    def _gpu_card(self,parent):
        t=self.theme
        card=Card(parent,t,pad=16)
        b=card.body
        head=tk.Frame(b,bg=C['surface'])
        head.pack(fill='x')
        title=tk.StringVar()
        tk.Label(head,textvariable=title,bg=C['surface'],fg=C['text'],font=t.font(10,'bold')).pack(side='left')
        temp=tk.Label(head,text='',bg=C['surface'],fg=C['muted'],font=t.font(9))
        temp.pack(side='right')
        mid=tk.Frame(b,bg=C['surface'])
        mid.pack(fill='x',pady=(t.px(6),0))
        util=tk.StringVar(value='—')
        tk.Label(mid,textvariable=util,bg=C['surface'],fg=C['text'],font=t.serif_font(26)).pack(side='left')
        tk.Label(mid,text='利用率',bg=C['surface'],fg=C['muted'],font=t.font(9)).pack(side='left',padx=t.px(8),pady=(t.px(12),0))
        task=tk.StringVar(value='')
        tk.Label(b,textvariable=task,bg=C['surface'],fg=C['muted'],font=t.font(9),anchor='w').pack(fill='x')
        spark=Sparkline(b,t,C['purple'],height=48,capacity=HISTORY)
        spark.pack(fill='x',pady=(t.px(4),t.px(10)))
        rows={}
        for key,name,color in [('util','利用率',C['purple']),('mem','显存',C['blue']),('power','功耗',C['amber'])]:
            r=tk.Frame(b,bg=C['surface'])
            r.pack(fill='x',pady=t.px(3))
            tk.Label(r,text=name,bg=C['surface'],fg=C['muted'],font=t.font(9),width=6,anchor='w').pack(side='left')
            text=tk.StringVar(value='—')
            tk.Label(r,textvariable=text,bg=C['surface'],fg=C['sub'],font=t.font(9),anchor='e',width=22).pack(side='right')
            bar=Bar(r,t,height=6,color=color)
            bar.pack(side='left',fill='x',expand=True,padx=t.px(8))
            rows[key]=(text,bar,color)
        return dict(card=card,title=title,temp=temp,util=util,spark=spark,rows=rows,task=task)

    def _build_users(self,page):
        t=self.theme
        page.columnconfigure(0,weight=3)
        page.columnconfigure(1,weight=2)
        page.rowconfigure(0,weight=1)
        card=Card(page,t,title='各用户资源占用')
        card.grid(row=0,column=0,sticky='nsew',padx=(0,t.px(14)))
        self.users_heading=card.title_var
        self.user_table=Table(card.body,t,[('user','用户',120,'w',True),('procs','进程',70,'e'),('cpu','实时 CPU',96,'e'),
                                           ('cores','≈ 核',70,'e'),('rss','内存',110,'e'),('memp','内存占比',90,'e'),
                                           ('gpup','GPU 进程',100,'e'),('gpum','GPU 显存',110,'e')],empty='等待服务器数据')
        self.user_table.pack(fill='both',expand=True)
        tk.Label(card.body,text='汇总所有可读进程（不止前 300 项）。实时 CPU 为 0.5 秒采样；加粗为当前账号。',bg=C['surface'],
                 fg=C['muted'],font=t.font(8),anchor='w').pack(fill='x',pady=(t.px(8),0))
        chart=Card(page,t,title='占用排行')
        chart.grid(row=0,column=1,sticky='nsew')
        self.user_chart=tk.Canvas(chart.body,bg=C['surface'],highlightthickness=0)
        self.user_chart.pack(fill='both',expand=True)
        self.user_chart.bind('<Configure>',lambda e:self._draw_user_chart())
        self.user_rows=[]

    def _build_license(self,page):
        t=self.theme
        cards=tk.Frame(page,bg=C['bg'])
        cards.pack(fill='x')
        self.license_cards={}
        for col,(key,title) in enumerate([('lumerical_solve','Lumerical 求解'),('anshpc_pack','Ansys HPC 包'),
                                         ('lumerical_gui','Lumerical GUI / lumapi'),('server','许可证服务器')]):
            cards.columnconfigure(col,weight=1,uniform='lic')
            card=Card(cards,t,pad=18)
            card.grid(row=0,column=col,sticky='nsew',padx=(0,t.px(14)) if col<3 else 0)
            tk.Label(card.body,text=title,bg=C['surface'],fg=C['muted'],font=t.font(9),anchor='w').pack(fill='x')
            value=tk.StringVar(value='—')
            tk.Label(card.body,textvariable=value,bg=C['surface'],fg=C['text'],font=t.serif_font(24),anchor='w').pack(fill='x',pady=(t.px(4),t.px(6)))
            bar=Bar(card.body,t,height=6,color=C['accent'])
            bar.pack(fill='x')
            detail=tk.StringVar(value='等待查询')
            tk.Label(card.body,textvariable=detail,bg=C['surface'],fg=C['muted'],font=t.font(9),anchor='w',justify='left').pack(fill='x',pady=(t.px(8),0))
            self.license_cards[key]=dict(value=value,bar=bar,detail=detail)
        lower=tk.Frame(page,bg=C['bg'])
        lower.pack(fill='both',expand=True,pady=(t.px(14),0))
        lower.columnconfigure(0,weight=1)
        lower.rowconfigure(0,weight=3)
        lower.rowconfigure(1,weight=2)
        features=Card(lower,t,title='功能（Lumerical / HPC 相关及正在使用的）')
        features.grid(row=0,column=0,sticky='nsew',pady=(0,t.px(14)))
        self.license_feature_heading=features.title_var
        self.license_feature_table=Table(features.body,t,[('name','功能',170),('desc','说明',260,'w',True),('used','已用',60,'e'),
                                                          ('total','总数',60,'e'),('pct','占用',70,'e'),('mine','我的',60,'e'),
                                                          ('expiry','到期',110,'e')],empty='等待查询')
        self.license_feature_table.pack(fill='both',expand=True)
        checkouts=Card(lower,t,title='当前借出')
        checkouts.grid(row=1,column=0,sticky='nsew')
        self.license_checkout_heading=checkouts.title_var
        self.license_checkout_table=Table(checkouts.body,t,[('feature','功能',150),('user','用户',110),('task','任务',190,'w',True),
                                                           ('count','数量',56,'e'),('start','借出时间',120,'e')],empty='当前没有借出的许可证')
        self.license_checkout_table.pack(fill='both',expand=True)
        self._context(self.license_checkout_table,lambda r:[('复制 PID',lambda:self._copy(r['data'].get('pid') or ''))])
        self.license_note=tk.StringVar(value='只读：通过 lmutil lmstat 询问许可证服务器，不读取许可证文件。')
        tk.Label(page,textvariable=self.license_note,bg=C['bg'],fg=C['muted'],font=t.font(8),anchor='w').pack(fill='x',pady=(t.px(8),0))

    def show_license(self,lic):
        self.license=lic or {}
        lic=self.license
        cards=self.license_cards
        nav=self.nav['license']['badge']
        if not lic.get('available'):
            for key in ('lumerical_solve','anshpc_pack','lumerical_gui'):
                cards[key]['value'].set('—')
                cards[key]['bar'].set(0)
                cards[key]['detail'].set('没有许可证数据')
            cards['server']['value'].set('关闭' if lic.get('disabled') else '不可用')
            cards['server']['detail'].set(lic.get('error') or '尚未查询')
            cards['server']['bar'].set(0)
            nav.configure(text='' if lic.get('disabled') else '!',fg=C['red'])
            self.license_feature_table.set_rows([])
            self.license_checkout_table.set_rows([])
            if not lic.get('disabled') and lic.get('error') and self.snapshot is not None:
                self._license_alert('license-unavailable','许可证服务器无法查询',lic['error'],'error')
            return
        self.alerted.discard('license-unavailable')
        me=getattr(self.client.profile,'user','')
        features={f['name']:f for f in lic.get('features',[])}
        for key in ('lumerical_solve','anshpc_pack','lumerical_gui'):
            f=features.get(key)
            card=cards[key]
            if not f:
                card['value'].set('—')
                card['bar'].set(0)
                card['detail'].set('服务器上没有这个功能')
                continue
            issued=f['issued'] or 0
            percent=100*f['in_use']/issued if issued else None
            mine=sum(c['count'] for c in f['checkouts'] if c['user']==me)
            card['value'].set(f'{f["in_use"]} / {issued}' if issued else f'{f["in_use"]}')
            card['bar'].set(percent or 0,level_color(percent,C['accent']))
            card['detail'].set(f'我的 {mine} · 其他用户 {f["in_use"]-mine} · 占用 {pct(percent)}')
            if percent is not None:
                self._threshold(f'license-{key}',percent,90,f'许可证 {key} 即将用完',f'已用 {f["in_use"]} / {issued}')
        up=lic.get('server_up')
        daemons=lic.get('daemons',{})
        cards['server']['value'].set('正常' if up else '异常')
        cards['server']['bar'].set(100 if up else 0,C['green'] if up else C['red'])
        expiries=sorted({f['expiry'] for f in features.values() if f.get('expiry')})
        cards['server']['detail'].set(' · '.join([lic.get('server',''),*(f'{k} {v}' for k,v in daemons.items())])+
                                      (f'\n最早到期 {self._expiry_date(expiries[0])}' if expiries else ''))
        nav.configure(text='' if up else '!',fg=C['red'])
        if not up:
            self._license_alert('license-down','许可证服务器状态异常',lic.get('server',''),'error')
        else:
            self.alerted.discard('license-down')
        for expiry in expiries[:1]:
            try:
                left=(dt.datetime.strptime(expiry,'%d-%b-%Y')-dt.datetime.now()).days
            except ValueError:
                continue
            self._threshold('license-expiry',30-left,30,'许可证即将到期',f'{expiry}（还有 {left} 天）')
        runs=self._runs_by_pid()
        rows,checkouts=[],[]
        for f in lic.get('features',[]):
            issued=f['issued']
            mine=sum(c['count'] for c in f['checkouts'] if c['user']==me)
            percent=100*f['in_use']/issued if issued else None
            rows.append({'key':f['name'],'data':f,'tags':('strong',) if f['in_use'] else ('muted',),
                         'values':(f['name'],LICENSE_TEXT.get(f['name'],''),f['in_use'],issued if issued is not None else '不限',
                                   pct(percent),mine or '—',self._expiry_date(f['expiry']) if f.get('expiry') else '—'),
                         'sort':(f['name'],LICENSE_TEXT.get(f['name'],''),f['in_use'],issued or 0,percent,mine,f.get('expiry') or '')})
            for c in f['checkouts']:
                run=runs.get(c['pid'])
                task=run['name'] if run else ('CAD / lumapi 会话' if f['name'].endswith('_gui') else (f'PID {c["pid"]}' if c['pid'] else '—'))
                checkouts.append({'key':(f['name'],c['user'],c['pid'],c['start']),'data':c,'tags':('mine',) if c['user']==me else (),
                                  'values':(f['name'],c['user'],task,c['count'],re.sub(r'^[A-Za-z]{3}\s+','',c['start'])),
                                  'sort':(f['name'],c['user'],task,c['count'],c['start'])})
        rows.sort(key=lambda r:(-r['data']['in_use'],r['data']['name']))
        self.license_feature_table.set_rows(rows)
        self.license_checkout_table.set_rows(checkouts)
        used=sum(1 for f in lic.get('features',[]) if f['in_use'])
        self.license_feature_heading.set(f'功能  {len(rows)}（{used} 个在用）')
        self.license_checkout_heading.set(f'当前借出  {len(checkouts)}')
        age=int(time.time()-lic.get('queried_at',time.time()))
        self.license_note.set(f'只读：通过 lmutil lmstat 询问 {lic.get("server","")}，不读取许可证文件。服务器共 {lic.get("total_features",0)} 个功能，'
                              f'这里列出 Lumerical / HPC 相关及正在使用的。结果每分钟更新一次（本次为 {age} 秒前）。')

    @staticmethod
    def _expiry_date(text):
        try:
            return dt.datetime.strptime(text,'%d-%b-%Y').strftime('%Y-%m-%d')
        except ValueError:
            return text

    def _license_alert(self,key,title,body,kind):
        if key not in self.alerted:
            self.alerted.add(key)
            self.notify(title,body,kind,system=True)

    def _license_line(self):
        features={f['name']:f for f in (self.license or {}).get('features',[])}
        parts=[f'{label} {features[k]["in_use"]}/{features[k]["issued"]}' for k,label in
               (('lumerical_solve','求解'),('anshpc_pack','HPC')) if k in features and features[k]['issued']]
        return ('许可证 '+' · '.join(parts)) if parts else ''

    # ------------------------------------------------------------- utilities
    def _bind_keys(self):
        self.bind_all('<F5>',lambda e:self.refresh())
        for n,(key,_,_) in enumerate(PAGES):
            self.bind_all(f'<Control-Key-{n+1}>',lambda e,k=key:self.show_page(k))
        self.bind_all('<Control-f>',lambda e:self._focus_search())

    def _focus_search(self):
        box={'overview':self.proc_search,'tasks':self.task_search,'files':self.log_search if self.log_path else self.file_search}.get(self.page)
        if box:
            box.focus()

    def _context(self,table,items):
        menu=tk.Menu(self,tearoff=0,bg=C['surface'],fg=C['text'],activebackground=C['raised'],activeforeground=C['text'],
                     bd=0,relief='flat',font=self.theme.font(9))
        def popup(event):
            row=table.tree.identify_row(event.y)
            if not row:
                return
            table.tree.selection_set(row)
            table.tree.focus(row)
            r=table.items.get(row)
            menu.delete(0,'end')
            for name,command in items(r):
                menu.add_command(label=name,command=command)
            menu.add_separator()
            menu.add_command(label='复制此行',command=lambda:self._copy('\t'.join(str(v) for v in r['values'])))
            menu.tk_popup(event.x_root,event.y_root)
        table.tree.bind('<Button-3>',popup)

    def _copy(self,text):
        self.clipboard_clear()
        self.clipboard_append(str(text))
        self.activity.set(f'已复制：{text}')

    def show_page(self,key):
        if key==self.page:
            return
        self.page=key
        self.pages[key].tkraise()
        for k,n in self.nav.items():
            active=k==key
            n['item'].recolor(C['raised'] if active else C['side'])
            n['icon'].configure(fg=C['text'] if active else C['muted'])
            n['text'].configure(fg=C['text'] if active else C['sub'],font=self.theme.font(10,'bold' if active else 'normal'))
        title,sub=next((x[1],x[2]) for x in PAGES if x[0]==key)
        self.page_title.set(title)
        self.page_sub.set(sub)
        if key=='files' and not self.offline and not self.file_table.rows and 'files' not in self.busy and self.last_success:
            self.load_files(self.current_path)

    def _feed(self,kind,text):
        self.feed.configure(state='normal')
        self.feed.insert('1.0',f'{text}\n',(kind,))
        self.feed.insert('1.0',dt.datetime.now().strftime('%H:%M:%S')+'  ','time')
        if int(self.feed.index('end-1c').split('.')[0])>200:
            self.feed.delete('200.0','end')
        self.feed.configure(state='disabled')

    def notify(self,title,body='',kind='info',system=False):
        self._feed(kind,title+(f' · {body}' if body else ''))
        if hasattr(self,'toaster'):
            self.toaster.show(title,body,kind)
        self._flash()
        if system and self.toasts and not self.offline and not self._focused():
            system_toast(title,body)

    def _focused(self):
        try:
            return self.state()!='iconic' and self.focus_get() is not None
        except (KeyError,tk.TclError):
            return False

    def _flash(self):
        if os.name!='nt' or self.offline:
            return
        try:
            if self.focus_get() is not None:
                return
        except (KeyError,tk.TclError):
            return
        try:
            class FLASHWINFO(ctypes.Structure):
                _fields_=[('cbSize',ctypes.c_uint),('hwnd',ctypes.c_void_p),('dwFlags',ctypes.c_uint),
                          ('uCount',ctypes.c_uint),('dwTimeout',ctypes.c_uint)]
            hwnd=ctypes.windll.user32.GetParent(self.winfo_id())
            info=FLASHWINFO(ctypes.sizeof(FLASHWINFO),hwnd,0x3|0xC,0,0)  # tray+caption until foreground
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except (AttributeError,OSError):
            pass

    def _threshold(self,key,value,limit,title,body):
        if value is None:
            return
        if value>=limit and key not in self.alerted:
            self.alerted.add(key)
            self.notify(title,body,'warn')
        elif value<limit-5:
            self.alerted.discard(key)

    def _set_connection(self,state,text):
        color={'ok':C['green'],'busy':C['amber'],'error':C['red']}.get(state,C['muted'])
        self.conn_dot.itemconfigure(self.conn_dot_item,fill=color)
        self.connection.set(text)

    # ----------------------------------------------------------- background
    def submit(self,key,work,done):
        if key in self.busy:
            self.activity.set('上一项请求仍在执行，请稍候。')
            return
        self.busy.add(key)
        def run():
            try: self.events.put(('done',key,done,work()))
            except Exception as e:
                if not self.closing:  # requests cut off by closing the window are expected
                    logging.exception('%s failed',key)
                self.events.put(('error',key,None,str(e)))
        threading.Thread(target=run,daemon=True).start()

    def _drain(self):
        if self.closed:
            return
        try:
            while True:
                kind,key,callback,value=self.events.get_nowait()
                if kind=='progress':
                    n,total=value
                    self.download_text.set(f'{size(n)} / {size(total)}')
                    self.download_bar.set(100*n/total if total else 100)
                    continue
                self.busy.discard(key)
                if key=='download':
                    self.cancel_button.set_enabled(False)
                if key=='snapshot':
                    self.next_refresh=time.monotonic()+self.refresh_seconds
                if kind=='error':
                    self.activity.set(f'读取失败：{value}')
                    self._run_pending(key)
                    if key=='snapshot':
                        self.failed_streak+=1
                        self._set_connection('error','连接失败 · 显示旧数据' if self.snapshot else '连接失败')
                        if self.failed_streak==1:
                            self.notify('无法读取服务器',value.splitlines()[0][:160] if value else '','error')
                    if key=='download':
                        self.download_text.set('下载失败 / 已取消')
                        self.download_bar.pack_forget()
                    if key=='tail' and self.follow.get():
                        self.log_loaded_at=time.monotonic()
                else:
                    callback(value)
        except queue.Empty:
            pass
        self.after(100,self._drain)

    def _tick(self):
        if self.closed:
            return
        now=time.monotonic()
        if self.last_success is not None:
            self.age.set(f'数据更新于 {ago(now-self.last_success)}')
        if 'snapshot' in self.busy:
            self.countdown.set('正在读取…')
        elif self.auto.get() and self.next_refresh is not None:
            self.countdown.set(f'{max(0,int(self.next_refresh-now))} 秒后刷新')
        else:
            self.countdown.set('自动刷新已关闭' if not self.auto.get() else '')
        if not self.closing and self.auto.get() and self.next_refresh is not None and now>=self.next_refresh and 'snapshot' not in self.busy:
            self.refresh()
        if (not self.closing and self.follow.get() and self.log_path and 'tail' not in self.busy
                and now-self.log_loaded_at>=FOLLOW_SECONDS):
            self._request_tail(self.log_path)
        self.after(1000,self._tick)

    def _toggle_auto(self):
        if self.auto.get():
            self.next_refresh=time.monotonic()

    # -------------------------------------------------------------- snapshot
    def refresh(self):
        if 'snapshot' in self.busy:
            return
        if self.snapshot is None:
            self._set_connection('busy','正在建立 SSH 会话…')
            self.activity.set('首次连接需要 SSH 握手并扫描项目目录，约 10–15 秒；之后每次刷新约 2–3 秒。')
        else:
            self._set_connection('busy','正在读取服务器…')
        self.submit('snapshot',lambda:self.client.request('snapshot',licenses=self.license_query),self.show_snapshot)

    def show_snapshot(self,data):
        recovered=self.failed_streak>0 and self.snapshot is not None
        first=self.snapshot is None
        self.snapshot=data
        self.last_success=time.monotonic()
        self.failed_streak=0
        self._set_connection('ok',f'已连接 · {data["hostname"]}')
        if recovered:
            self.notify('连接已恢复',data['hostname'],'ok')
        elif first:
            self._feed('ok',f'已连接 {data["hostname"]}')
        used=data['memory_total']-data['memory_available']
        mem_p=used/data['memory_total']*100 if data['memory_total'] else None
        fs=data.get('filesystem')
        if fs:  # df convention: used / (used + available); root-reserved blocks shown separately
            disk_p=100*fs['used']/(fs['used']+fs['available']) if fs['used']+fs['available'] else None
        else:
            disk_p=(data['disk_total']-data['disk_free'])/data['disk_total']*100 if data['disk_total'] else None
        load=data['load_average']
        cpu=data['cpu_percent']
        self.history['cpu'].append(cpu)
        self.history['memory'].append(mem_p)
        self.history['disk'].append(disk_p)
        self._metric('cpu',cpu,f'{data["cpu_count"]} 逻辑核 · 负载 {load[0]:.2f}',f'{data["cpu_count"]} 核')
        self._metric('memory',mem_p,f'{size(used)} / {size(data["memory_total"])}',size(data['memory_total']))
        self._show_disk(data,disk_p)
        self._threshold('memory',mem_p,90,'内存占用过高',f'整机内存已用 {mem_p:.1f}%' if mem_p is not None else '')
        self._threshold('disk',disk_p,90,'服务器磁盘空间不足',f'可用 {size(data["disk_free"])}（磁盘为所有用户共享）')
        swap_used=data['swap_total']-data['swap_free']
        vis=data.get('process_visibility',{})
        self.host_rows['hostname'].set(data['hostname'])
        self.host_rows['uptime'].set(duration(data['uptime_seconds']))
        self.host_rows['load'].set(' / '.join(f'{x:.2f}' for x in load))
        self.host_rows['swap'].set(f'{size(swap_used)} / {size(data["swap_total"])}')
        self.host_rows['procs'].set(f'{vis.get("visible_count","—")}')
        try:
            server=dt.datetime.fromisoformat(data['timestamp_utc']).astimezone()
            self.host_rows['clock'].set(server.strftime('%m-%d %H:%M:%S'))
        except (KeyError,ValueError):
            pass
        self.show_gpu(data.get('gpu',{}))
        self.show_processes(data)
        self.show_license(data.get('license'))
        self.show_jobs(data['jobs'])
        self.show_running(data['jobs'],data.get('cad_sessions',[]))
        self.show_users(data)
        running=sum(j['state']=='运行中' for j in data['jobs'])
        solvers=collections.Counter(j.get('solver') or '?' for j in data['jobs'] if j['state']=='运行中')
        mix_text='（'+'，'.join(f'{k} {v}' for k,v in solvers.items())+'）' if solvers else ''
        self.activity.set(f'已更新 · {data["hostname"]} · 最近 14 天 {len(data["jobs"])} 个任务，{running} 个运行中{mix_text}')
        if not self.offline and not self.file_table.rows and 'files' not in self.busy:
            self.load_files(self.current_path)

    def _show_disk(self,data,percent):
        m=self.metrics['disk']
        fs=data.get('filesystem')
        if not fs:
            self._metric('disk',percent,f'可用 {size(data["disk_free"])} / {size(data["disk_total"])}',size(data['disk_total']))
            return
        total=fs['total'] or 1
        m['title'].set(f'磁盘 {fs["mount"]}（所有用户共享）')
        m['value'].set(pct(percent))
        m['chip'].set(size(fs['total']))
        m['bar'].set(100*fs['used']/total,level_color(percent,m['color']),extra=(100*fs['reserved']/total,C['toggle']))
        project=data.get('project_size') or {}
        mine=('' if project.get('complete',True) else '≥ ')+size(project.get('bytes')) if project else '—'
        m['detail'].set(f'可用 {size(fs["available"])} · 已用 {size(fs["used"])} · 系统保留 {size(fs["reserved"])}\n'
                        f'其中我的项目目录 {mine}')

    def _metric(self,key,percent,detail,chip=None):
        m=self.metrics[key]
        m['value'].set(pct(percent))
        m['detail'].set(detail)
        if chip is not None:
            m['chip'].set(chip)
        m['bar'].set(percent or 0,level_color(percent,m['color']))
        m['spark'].set(list(self.history[key]))

    def filter_processes(self):
        if self.snapshot:
            self.show_processes(self.snapshot)
            self.show_gpu(self.snapshot.get('gpu',{}),record=False)
            self.show_users(self.snapshot)

    def _filter_proc(self,query):
        self.proc_table.filter(query)

    def show_processes(self,data):
        rows=data.get('all_processes',[])
        visibility=data.get('process_visibility',{})
        if self.mine_only.get():
            rows=[p for p in rows if p.get('mine')]
        table=[]
        for p in rows:
            now=p.get('cpu_percent')
            table.append({'key':p['pid'],'data':p,'tags':('mine',) if p.get('mine') else (),
                          'values':(self._who(p),p['pid'],p['name'],pct(now),pct(p['cpu_average_percent']),
                                    size(p['rss_bytes']),p['threads'],duration(p['elapsed_seconds'])),
                          'sort':(p.get('user',''),p['pid'],p['name'].lower(),now,p['cpu_average_percent'],p['rss_bytes'],
                                  p['threads'],p['elapsed_seconds'])})
        self.proc_table.set_rows(table)
        scope='我的进程' if self.mine_only.get() else '进程'
        self.process_heading.set(f'{scope}  {len(rows)} / {visibility.get("visible_count",len(rows))}')
        note='实时 CPU 为 0.5 秒采样，平均为启动以来；100% = 1 个逻辑核 · 加粗为我的进程'
        if visibility.get('truncated'):
            note+=' · 仅列出 CPU 最高 300 个'
        if visibility.get('unreadable'):
            note+=f' · {visibility["unreadable"]} 个不可读/已退出'
        self.process_note.set(note)

    def show_gpu(self,gpu,record=True):
        m=self.metrics['gpu']
        devices=gpu.get('devices',[]) if gpu.get('available') else []
        if not gpu.get('available'):
            if record:
                self.history['gpu'].append(None)
            m['value'].set('—')
            m['detail'].set('GPU 状态不可用 · 详见 GPU 页')
            m['bar'].set(0)
            m['chip'].set('')
            self.gpu_summary.set('GPU 状态不可用：'+gpu.get('error','尚未获取 GPU 数据'))
            self.gpu_process_note.set('GPU 数据不可用，不能判断是否存在计算进程。')
            self.gpu_process_table.set_rows([])
            self._ensure_gpu_cards(0)
            return
        utilization=[g['utilization_percent'] for g in devices]
        peak=max(utilization) if utilization and all(v is not None for v in utilization) else None
        if record:
            self.history['gpu'].append(peak)
            for g in devices:
                self.gpu_history[g['uuid']].append(g['utilization_percent'])
        details=[]
        for g in devices:
            used,total=g['memory_used_bytes'],g['memory_total_bytes']
            details.append(f'GPU{g["index"]}  {pct(g["utilization_percent"],0)} · 显存 {pct(100*used/total if used is not None and total else None,0)}')
        names=collections.Counter(g['name'].replace('NVIDIA ','') for g in devices)
        self._metric('gpu',peak,'\n'.join(details) if devices else '未检测到 NVIDIA 显卡',
                     ' + '.join(f'{n} × {k}' for k,n in names.items()))
        self.gpu_summary.set(f'检测到 {len(devices)} 张 NVIDIA 显卡 · 随服务器状态一起刷新 · 曲线为最近 {HISTORY} 次采样'
                             if devices else '未检测到 NVIDIA 显卡')
        self._ensure_gpu_cards(len(devices))
        for g,card in zip(devices,self.gpu_cards):
            used,total=g['memory_used_bytes'],g['memory_total_bytes']
            mem_p=100*used/total if used is not None and total else None
            power,limit=g['power_watts'],g['power_limit_watts']
            power_p=100*power/limit if power is not None and limit else None
            card['title'].set(f'GPU {g["index"]}  ·  {g["name"]}')
            temp=g['temperature_c']
            card['temp'].configure(text='—' if temp is None else f'{temp:.0f} °C',
                                   fg=C['red'] if (temp or 0)>=85 else C['amber'] if (temp or 0)>=75 else C['sub'])
            card['util'].set(pct(g['utilization_percent'],0))
            tasks=[j['name'] for j in self._runs_by_pid().values() if g['index'] in (j.get('resources') or {}).get('gpus',[])]
            card['task'].set(('运行：'+'、'.join(dict.fromkeys(tasks))) if tasks else '没有我的 Lumerical 任务')
            card['spark'].set(list(self.gpu_history[g['uuid']]))
            for key,percent,text in [('util',g['utilization_percent'],pct(g['utilization_percent'])),
                                     ('mem',mem_p,f'{size(used)} / {size(total)}'),
                                     ('power',power_p,'—' if power is None else f'{power:.0f} W / {"—" if limit is None else f"{limit:.0f} W"}')]:
                var,bar,color=card['rows'][key]
                var.set(text)
                bar.set(percent or 0,level_color(percent,color))
            if record:
                self._threshold(f'gpu-temp-{g["uuid"]}',temp,85,f'GPU {g["index"]} 温度偏高',f'{temp:.0f} °C' if temp else '')
        indices={g['uuid']:g['index'] for g in devices}
        processes=gpu.get('processes',[])
        if self.mine_only.get():
            processes=[p for p in processes if p.get('mine')]
        owner=self._runs_by_pid()
        self.gpu_process_table.set_rows([{'key':(p['pid'],p['uuid']),'data':p,'tags':('mine',) if p.get('mine') else (),
            'values':(indices.get(p['uuid'],'?'),self._who(p),p['pid'],p['name'],owner.get(p['pid'],{}).get('path','—'),size(p['memory_bytes'])),
            'sort':(indices.get(p['uuid'],-1),p.get('user',''),p['pid'],p['name'],owner.get(p['pid'],{}).get('path',''),p['memory_bytes'])}
            for p in processes])
        self.gpu_process_heading.set(f'GPU 计算进程  {len(processes)}')
        if gpu.get('process_error'):
            self.gpu_process_note.set('计算进程查询失败：'+gpu['process_error'])
        else:
            self.gpu_process_note.set(('我的进程' if self.mine_only.get() else '各用户可见进程')+' · 用户不可读时标为未知')

    def _ensure_gpu_cards(self,count):
        if len(self.gpu_cards)==count:
            return
        for card in self.gpu_cards:
            card['card'].destroy()
        self.gpu_cards=[]
        columns=min(max(count,1),2) if count<=4 else 4
        for i in range(columns):
            self.gpu_grid.columnconfigure(i,weight=1,uniform='gpu')
        for i in range(count):
            card=self._gpu_card(self.gpu_grid)
            r,c=divmod(i,columns)
            card['card'].grid(row=r,column=c,sticky='nsew',padx=(0,self.theme.px(14)) if c<columns-1 else 0,
                              pady=(0,self.theme.px(14)) if r<(count-1)//columns else 0)
            self.gpu_cards.append(card)

    # ------------------------------------------------------------------ jobs
    def show_jobs(self,jobs):
        self._diff_jobs(jobs)
        counts=collections.Counter(j['state'] for j in jobs)
        for state,chip in self.chips.items():
            n=len(jobs) if state=='全部' else counts.get(state,0)
            chip.set_text(f'{state}  {n}')
        self._style_chips()
        running=counts.get('运行中',0)
        self.nav['tasks']['badge'].configure(text=f'{running}' if running else '')
        self.jobs=jobs
        self._build_solver_chips(jobs)
        self._render_jobs()

    def _build_solver_chips(self,jobs):
        counts=collections.Counter(j.get('solver') or '其他' for j in jobs)
        wanted=['全部',*sorted(counts)] if len(counts)>1 else []
        if self.solver_filter not in wanted:
            self.solver_filter='全部'
        if list(self.solver_chips)!=wanted:
            for chip in self.solver_chips.values():
                chip.destroy()
            self.solver_chips={}
            for solver in wanted:
                chip=Chip(self.solver_bar,self.theme,solver,lambda s=solver:self._set_solver_filter(s))
                chip.pack(side='left',padx=(self.theme.px(6),0))
                self.solver_chips[solver]=chip
        for solver,chip in self.solver_chips.items():
            chip.set_text(f'{solver}  {len(jobs) if solver=="全部" else counts[solver]}')
            chip.set_active(solver==self.solver_filter)

    def _set_solver_filter(self,solver):
        self.solver_filter=solver
        for name,chip in self.solver_chips.items():
            chip.set_active(name==solver)
        self._render_jobs()

    def _render_jobs(self):
        jobs=self.jobs
        if self.task_filter!='全部':
            jobs=[j for j in jobs if j['state']==self.task_filter]
        if self.solver_filter!='全部':
            jobs=[j for j in jobs if (j.get('solver') or '其他')==self.solver_filter]
        rows=[]
        # Generic stems such as "model" repeat across folders: prefix those with their folder name.
        repeated={n for n,c in collections.Counter(j.get('name') for j in self.jobs).items() if c>1}
        for j in jobs:
            p=j.get('progress')
            res=j.get('resources') or {}
            tag='amber' if j.get('stalled') else STATE_TAG.get(j['state'])
            name,where=j.get('name') or j['path'],self._where(j)
            if name in repeated and j.get('kind')=='run' and j.get('dir'):
                folder=PurePosixPath(j['dir'])
                name,where=f'{folder.name}/{name}',short_folder(str(folder.parent)) or '项目根目录'
            rows.append({'key':j['path'],'data':j,'tags':(tag,) if tag else (),
                         'values':(j['state']+(' · 无更新' if j.get('stalled') else ''),self._solver_label(j),name,
                                   where,pct(p),j.get('shutoff') or '—',self._eta(j),self._resources(j),stamp(j['mtime'])[5:]),
                         'sort':(STATE_ORDER.index(j['state']) if j['state'] in STATE_ORDER else 9,self._solver_label(j),
                                 (j.get('name') or '').lower(),j['path'],p,
                                 self._float(j.get('shutoff')),self._seconds(j.get('remaining')),
                                 (res.get('gpu_memory') or 0)+(res.get('cpu_percent') or 0),j['mtime'])})
        n=self.task_table.set_rows(rows)
        scope=' · '.join(x for x in (self.task_filter,self.solver_filter) if x!='全部')
        self.task_heading.set(f'任务列表  {n}' if not scope else f'任务列表 · {scope}  {n}')
        children=self.task_table.tree.get_children()
        if children and not self.task_table.tree.selection():
            self.task_table.tree.selection_set(children[0])  # show the newest/running task instead of an empty panel
        self._show_job_detail(self.task_table.selected())

    @staticmethod
    def _where(job):
        if job.get('kind')=='pipeline':
            return short_folder(str(PurePosixPath(job['path']).parent)) or '项目根目录'
        if job.get('dir') is None:
            return '项目根目录之外'
        return short_folder(job['dir']) or '项目根目录'

    @staticmethod
    def _solver_label(job):
        res=job.get('resources') or {}
        extra=[f'GPU {",".join(map(str,res["gpus"]))}'] if res.get('gpus') else [f for f in job.get('flags',[]) if f!='GPU']
        return ' · '.join([job.get('solver') or '—',*extra])

    @staticmethod
    def _resources(job):
        res=job.get('resources') or {}
        if not job.get('pids'):
            return '—'
        cores=f'{(res.get("cpu_percent") or 0)/100:.1f} 核'
        if res.get('gpu_memory'):
            return f'显存 {size(res["gpu_memory"])} · {cores}'
        return f'{cores} · {size(res.get("rss_bytes"))}'

    def _runs_by_pid(self):
        return {pid:j for j in (self.snapshot or {}).get('jobs',[]) for pid in j.get('pids',[])}

    @classmethod
    def _series_scale(cls,title,values):
        """Shutoff uses a fixed 1e-6..1 log axis; other positive series spanning a decade use their own log range."""
        values=[v for v in values if v is not None]
        if 'shutoff' in (title or '').lower():
            return [cls._shutoff_scale(v) for v in values],(cls._shutoff_scale(1e-5),C['faint']),'对数轴，虚线 = 1e-5'
        if values and min(values)>0 and max(values)/min(values)>=10:
            lo,hi=math.log10(min(values)),math.log10(max(values))
            return [(math.log10(v)-lo)/(hi-lo)*100 for v in values],None,'对数轴'
        lo,hi=(min(values),max(values)) if values else (0,1)
        return [50 if hi==lo else (v-lo)/(hi-lo)*100 for v in values],None,'线性'

    @classmethod
    def _eta(cls,job):
        seconds=cls._seconds(job.get('remaining'))
        return '—' if seconds is None else duration(seconds)

    @staticmethod
    def _shutoff_scale(value):
        """Map an auto-shutoff level onto 0..100 over 1e-6..1 (log scale)."""
        if value is None or value<=0:
            return None
        return max(0.,min(100.,(math.log10(value)+6)/6*100))

    @staticmethod
    def _seconds(text):
        if not text:
            return None
        total=0
        for n,unit in re.findall(r'(\d+)\s*(hr|min|sec|day)',text):
            total+=int(n)*{'day':86400,'hr':3600,'min':60,'sec':1}[unit]
        return total

    @staticmethod
    def _who(row):
        return row.get('user','未知/不可见')  # own rows are set in medium weight via the 'mine' tag

    @staticmethod
    def _float(text):
        try:
            return float(text)
        except (TypeError,ValueError):
            return None

    def _set_task_filter(self,state):
        self.task_filter=state
        self._style_chips()
        self._render_jobs()

    def _style_chips(self):
        for state,chip in self.chips.items():
            chip.set_active(state==self.task_filter)

    def _diff_jobs(self,jobs):
        current={j['path']:j['state'] for j in jobs}
        if self.known_jobs is not None:
            for j in jobs:
                path,state=j['path'],j['state']
                old=self.known_jobs.get(path)
                name=PurePosixPath(path).name
                if old is None and state=='运行中':
                    self.notify(f'{j.get("solver") or "仿真"} 开始运行',name,'info')
                elif old is not None and old!=state:
                    kind={'已完成':'ok','失败':'error','需检查结果':'warn'}.get(state,'info')
                    self.notify(f'{j.get("solver") or ""} 任务{state}'.strip() if old=='运行中' else f'任务状态 {old} → {state}',
                                name,kind,system=kind in ('ok','error','warn'))
        for j in jobs:
            if j.get('stalled') and j['path'] not in self.stall_alerted:
                self.stall_alerted.add(j['path'])
                self.notify('仿真可能卡住',f'{PurePosixPath(j["path"]).name} 的日志超过 20 分钟没有更新','warn',system=True)
            elif not j.get('stalled'):
                self.stall_alerted.discard(j['path'])
        self.known_jobs=current

    def show_running(self,jobs,sessions):
        t=self.theme
        for w in self.run_box.winfo_children():
            w.destroy()
        running=[j for j in jobs if j['state']=='运行中']
        self.run_heading.set(f'正在运行  {len(running)}')
        if not running:
            tk.Label(self.run_box,text='当前没有运行中的 Lumerical 任务',bg=C['surface'],fg=C['muted'],font=t.font(9)).pack(anchor='w')
        for j in running[:5]:
            item=tk.Frame(self.run_box,bg=C['surface'],cursor='hand2')
            item.pack(fill='x',pady=(0,t.px(10)))
            top=tk.Frame(item,bg=C['surface'])
            top.pack(fill='x')
            name=j['name'] if len(j['name'])<=26 else j['name'][:25]+'…'
            tk.Label(top,text=name,bg=C['surface'],fg=C['text'],font=t.font(9,'bold')).pack(side='left')
            tk.Label(top,text=self._solver_label(j),bg=C['surface'],fg=C['muted'],font=t.font(8)).pack(side='right')
            bar=Bar(item,t,height=5,color=C['amber'] if j.get('stalled') else C['accent'])
            bar.pack(fill='x',pady=(t.px(4),t.px(3)))
            bar.set(j.get('progress') or 0)
            note=f'{pct(j.get("progress"))}   剩余 {self._eta(j)}'+('   · 日志无更新' if j.get('stalled') else '')
            tk.Label(item,text=note,bg=C['surface'],fg=C['amber'] if j.get('stalled') else C['muted'],font=t.font(8)).pack(anchor='w')
            for w in (item,top,*top.winfo_children(),*item.winfo_children()):
                w.bind('<Button-1>',lambda e,k=j['path']:self._focus_job(k))
        if len(running)>5:
            tk.Label(self.run_box,text=f'另有 {len(running)-5} 个，见任务页',bg=C['surface'],fg=C['muted'],font=t.font(8)).pack(anchor='w')
        footer=[]
        if sessions:
            footer.append(f'CAD / lumapi 会话 {len(sessions)} 个（{"、".join(sorted({s["product"] for s in sessions}))}）')
        if self._license_line():
            footer.append(self._license_line())
        for text in footer:
            tk.Label(self.run_box,text=text,bg=C['surface'],fg=C['faint'],font=t.font(8)).pack(anchor='w',pady=(t.px(2),0))

    def _focus_job(self,key):
        self.show_page('tasks')
        if self.task_filter!='全部':
            self._set_task_filter('全部')
        for iid,row in self.task_table.items.items():
            if row.get('key')==key:
                self.task_table.tree.selection_set(iid)
                self.task_table.tree.see(iid)

    def _show_job_detail(self,row):
        if not row:
            self.job_name.set('选择一个任务查看详情')
            self.job_state_label.configure(text='',bg=C['surface'])
            self.job_progress.set('')
            self.job_bar.set(0)
            self.shutoff_spark.set([])
            self.job_alert.set('')
            return
        j=row['data']
        if j.get('dir') is not None and (self.page=='tasks' or not self.preview_target):
            self._select_preview(j['path'],running=j.get('state')=='运行中')
        color=C['amber'] if j.get('stalled') else C.get(STATE_TAG.get(j['state'],''),C['sub'])
        self.job_name.set(j['path'])
        self.job_state_label.configure(text=j['state'],fg=color,bg=mix(C['surface'],color,.18))
        self.job_bar.set(j.get('progress') or 0,color if j['state']!='未知/未完成' else C['accent'])
        seconds=self._seconds(j.get('remaining'))
        if seconds is not None:
            finish=dt.datetime.now()+dt.timedelta(seconds=seconds)
            self.job_progress.set(f'{pct(j.get("progress"))}   ·   剩余 {duration(seconds)}   ·   约 {finish:%m-%d %H:%M} 完成')
        elif j['state']=='已完成' and (j.get('progress') or 100)<99.5:
            self.job_progress.set(f'已完成   ·   Auto Shutoff 在 {pct(j.get("progress"))} 处提前收敛')
        else:
            self.job_progress.set(pct(j.get('progress')))
        title=j.get('series_title') or 'Auto Shutoff'
        values,marker,axis=self._series_scale(title,j.get('shutoff_history',[]))
        self.series_label.set(f'{title}（{axis}）' if values else '没有收敛曲线数据')
        self.shutoff_spark.marker=marker
        self.shutoff_spark.set(values)
        res=j.get('resources') or {}
        first=[f'求解器 {j.get("solver") or "—"}'+(f' ({j["engine"]})' if j.get('engine') else '')]
        if j.get('pids'):
            first+=[self._resources(j),f'已运行 {duration(res.get("elapsed_seconds"))}','PID '+', '.join(map(str,j['pids']))]
            if res.get('gpus'):
                first.append('GPU '+', '.join(map(str,res['gpus'])))
            first+=[f for f in j.get('flags',[]) if f!='GPU']
        if j.get('stage'):
            first.append('阶段 '+j['stage'])
        if j.get('licenses'):
            first.append('许可证 '+'、'.join(f'{l["feature"]}×{l["count"]}' for l in j['licenses']))
        second=[]
        for label,key in (('网格点',"grid"),('内存估计','memory_estimate')):
            if j.get(key):
                second.append(f'{label} {j[key]}')
        if j.get('speed'):
            second.append(f'速度 {j["speed"]:.0f} Mnodes/s')
        T,loss=j.get('total_transmission'),j.get('loss_db')
        if j.get('mesh_accuracy'):
            second.append(f'网格精度 {j["mesh_accuracy"]}')
        if T is not None:
            second.append(f'总透射率 {T*100:.3f}%')
        if loss is not None:
            second.append(f'损耗 {loss:.5f} dB')
        for name,value in (j.get('metrics') or {}).items():
            if name not in ('Max time remaining','Autoshutoff level'):
                second.append(f'{name} {value}')
        if j.get('driver'):
            second.append('启动脚本 '+j['driver'])
        if j.get('log') or j.get('engine_log'):
            second.append('日志 '+PurePosixPath(j.get('log') or j.get('engine_log')).name)
        second.append(f'更新 {stamp(j["mtime"])}')
        self.job_detail.set('   ·   '.join(first)+'\n'+'   ·   '.join(second))
        alerts=list(j.get('errors') or [])
        if j.get('stalled'):
            alerts.insert(0,'日志超过 20 分钟没有更新，进程仍在：可能卡住、等待许可证或在写大文件。')
        if j.get('dir') is None and j.get('kind')=='run':
            alerts.append('该项目文件在项目根目录之外：只显示进程信息，不读取其日志。')
        self.job_alert.set('\n'.join(alerts[:4]))

    def open_job(self):
        row=self.task_table.selected()
        if row:
            folder=row['data'].get('dir',row['data']['path'])
            if folder is None:
                self.activity.set('该运行的项目文件在项目根目录之外，无法浏览。')
                return
            self.show_page('files')
            self.load_files(folder)

    def open_job_log(self):
        row=self.task_table.selected()
        if not row:
            self.activity.set('请先选择一个任务。')
            return
        j=row['data']
        folder=j.get('dir',j['path'])
        if folder is None:
            self.activity.set('该运行的项目文件在项目根目录之外，不读取其日志。')
            return
        self.show_page('files')
        self.load_files(folder)
        log=j.get('log') or j.get('engine_log')
        if log:
            self.follow.set(j['state']=='运行中')
            self.open_log(log)
        else:
            self.activity.set('该任务没有找到 *_p0.log / *_engine.log，已打开任务目录。')

    # ----------------------------------------------------------------- users
    def show_users(self,data):
        users=data.get('users')
        if users is None:  # older probe: aggregate the bounded list
            agg={}
            for p in data.get('all_processes',[]):
                u=agg.setdefault(p.get('user','?'),{'user':p.get('user','?'),'mine':p.get('mine'),'processes':0,
                                                     'cpu_percent':0.,'rss_bytes':0})
                u['processes']+=1
                u['cpu_percent']+=p.get('cpu_percent') or 0
                u['rss_bytes']+=p['rss_bytes']
            users=list(agg.values())
        gpu={}
        for p in data.get('gpu',{}).get('processes',[]):
            g=gpu.setdefault(p.get('user','未知/不可见'),[0,0])
            g[0]+=1
            g[1]+=p['memory_bytes'] or 0
        total_mem=data['memory_total'] or 1
        rows=[]
        for u in users:
            if self.mine_only.get() and not u.get('mine'):
                continue
            gp,gm=gpu.get(u['user'],(0,0))
            rows.append({'key':u['user'],'data':u,'tags':('mine',) if u.get('mine') else (),
                         'values':(self._who(u),u['processes'],pct(u['cpu_percent']),f'{u["cpu_percent"]/100:.2f}',size(u['rss_bytes']),
                                   pct(100*u['rss_bytes']/total_mem),gp or '—',size(gm) if gp else '—'),
                         'sort':(u['user'],u['processes'],u['cpu_percent'],u['cpu_percent'],u['rss_bytes'],u['rss_bytes'],gp,gm)})
        self.user_table.set_rows(rows)
        self.users_heading.set(f'各用户资源占用  {len(rows)} 个用户')
        self.user_rows=[r['data']|{'gpu_mem':gpu.get(r['data']['user'],(0,0))[1]} for r in rows]
        self.user_total_mem=total_mem
        self.user_cores=data.get('cpu_count') or 1
        self._draw_user_chart()

    def _draw_user_chart(self):
        c=self.user_chart
        c.delete('all')
        t=self.theme
        w,h=c.winfo_width(),c.winfo_height()
        if w<50 or not self.user_rows:
            if w>50:
                c.create_text(w/2,h/2,text='等待服务器数据',fill=C['muted'],font=t.font(9))
            return
        sections=[('实时 CPU（逻辑核）',lambda u:u['cpu_percent']/100,lambda v:f'{v:.2f}',C['accent']),
                  ('驻留内存',lambda u:u['rss_bytes'],size,C['blue'])]
        if any(u['gpu_mem'] for u in self.user_rows):
            sections.append(('GPU 显存',lambda u:u['gpu_mem'],size,C['purple']))
        y=t.px(4)
        name_w,value_w=t.px(110),t.px(80)
        per=min(6,len(self.user_rows))
        block=(h-t.px(4))/len(sections)
        row_h=max(t.px(16),min(t.px(26),(block-t.px(34))/max(per,1)))
        for title,get,fmt,color in sections:
            c.create_text(0,y,text=title,anchor='nw',fill=C['sub'],font=t.font(9,'bold'))
            y+=t.px(26)
            top=sorted(self.user_rows,key=get,reverse=True)[:per]
            peak=max([get(u) for u in top]+[1e-9])
            for u in top:
                v=get(u)
                cy=y+row_h/2
                c.create_text(0,cy,text=u['user'][:14],anchor='w',fill=C['accent'] if u.get('mine') else C['text'],font=t.font(9))
                x0,x1=name_w,w-value_w
                bh=max(4,min(t.px(8),row_h*.4))
                c.create_line(x0+bh/2,cy,x1-bh/2,cy,width=bh,capstyle='round',fill=C['track'])
                if v>0:
                    c.create_line(x0+bh/2,cy,max(x0+bh/2+.6,x0+bh/2+(x1-x0-bh)*v/peak),cy,width=bh,capstyle='round',fill=color)
                c.create_text(w,cy,text=fmt(v),anchor='e',fill=C['sub'],font=t.font(9))
                y+=row_h
            y=y+t.px(14)

    # ----------------------------------------------------------------- files
    def _run_pending(self,key):
        path=self.pending.pop(key,None)
        if path is not None:
            (self.load_files if key=='files' else self._request_tail)(path)

    def load_files(self,path):
        path=path.strip().strip('/') or '.'
        if 'files' in self.busy:
            self.pending['files']=path
            return
        self.activity.set('正在读取目录…')
        def done(data):
            if 'files' not in self.pending:
                self.show_files(data)
            self._run_pending('files')
        self.submit('files',lambda:self.client.request('list',path),done)

    def show_files(self,data):
        self.current_path=data['path']
        self.path_var.set(self.current_path)
        rows=[]
        for e in data['entries']:
            d=e['directory']
            kind=('目录' if d else (Path(e['name']).suffix.lstrip('.').upper() or '文件'))+(' ↗' if e['symlink'] else '')
            rows.append({'key':e['path'],'data':e,'tags':('strong',) if d else (),
                         'values':(e['name']+('/' if d else ''),kind,'—' if d else size(e['size']),stamp(e['mtime'])),
                         'sort':((not d,e['name'].lower()),(not d,kind),-1 if d else e['size'],e['mtime'])})
        self.file_table.set_rows(rows)
        self._count_files(len(self.file_table.visible()),data['limit_reached'])
        self.activity.set(f'目录：{remote_join(self.client.profile.root,self.current_path)}')

    def _count_files(self,shown,limit=False):
        total=len(self.file_table.rows)
        name='项目根目录' if self.current_path in ('.','') else PurePosixPath(self.current_path).name
        self.files_heading.set(f'{name}  {shown}'+(f' / {total}' if shown!=total else '')+('（达到 2000 项上限）' if limit else ''))

    def up_directory(self):
        self.load_files(str(PurePosixPath(self.current_path).parent))

    def selected_file(self):
        row=self.file_table.selected()
        return row['data'] if row else None

    def open_selected(self,row=None):
        entry=self.selected_file()
        if entry and entry['directory']:
            self.load_files(entry['path'])
        elif entry:
            self.view_selected()

    def view_selected(self):
        entry=self.selected_file()
        if not entry or entry['directory']:
            self.activity.set('请先选中一个文件。')
            return
        if Path(entry['path']).suffix.lower() in {'.fsp','.lms'}:
            self._select_preview(entry['path'],open_page=True)
        else:
            self.open_log(entry['path'])

    def open_log(self,path):
        if Path(path).suffix.lower() not in TEXT_SUFFIXES:
            self.activity.set('该文件可能是二进制模型，请使用“下载…”。')
            return
        self.log_path=path
        self._request_tail(path)

    def _request_tail(self,path):
        self.log_loaded_at=time.monotonic()
        if 'tail' in self.busy:
            self.pending['tail']=path
            return
        def done(data):
            if 'tail' not in self.pending:
                self.show_text(data)
            self._run_pending('tail')
        self.submit('tail',lambda:self.client.request('tail',path),done)

    def _toggle_follow(self):
        if self.follow.get() and self.log_path:
            self._request_tail(self.log_path)
        elif self.follow.get():
            self.activity.set('先打开一个日志文件，跟踪会每 5 秒读取一次尾部。')

    _last_text=None

    def show_text(self,data):
        self._last_text=data
        engine=bool(re.search(r'(_engine\.log|solve\.log)$',data['path'])) or data['text'].count('<update>')>3
        if engine and self.pretty.get():
            data={**data,'text':pretty_engine_log(data['text'])}
        self.log_loaded_at=time.monotonic()
        same=data['path']==getattr(self,'_shown_log',None)
        at_end=self.log.yview()[1]>=.999
        view=self.log.yview()[0]
        self._shown_log=data['path']
        self.log_title.set(data['path']+(' · 仅显示最后 500 行 / 256 KiB' if data['truncated'] else '')+
                           (f' · {size(data["size"])}' if 'size' in data else ''))
        self.log.configure(state='normal')
        self.log.delete('1.0','end')
        self.log.insert('1.0',data['text'])
        for i,line in enumerate(data['text'].splitlines(),1):
            low=line.lower()
            tag=('err' if re.search(r'error|fail|traceback|exception|killed|abort|nan\b',low) else
                 'warn' if 'warn' in low else
                 'ok' if 'completed successfully' in low or re.search(r'\d% complete',low) else None)
            if tag:
                self.log.tag_add(tag,f'{i}.0',f'{i}.end')
        self.log.configure(state='disabled')
        self._search_log(self.log_search.var.get(),jump=False)
        if not same or at_end or self.follow.get():
            self.log.see('end')
        else:
            self.log.yview_moveto(view)
        stamp_=dt.datetime.now().strftime('%H:%M:%S')
        mode=' · 已整理引擎协议' if engine and self.pretty.get() else ' · 以纯文本显示'
        self.activity.set(f'日志已更新 {stamp_}' + (' · 跟踪中' if self.follow.get() else '')+mode)

    def _search_log(self,query,jump=True):
        self.log.tag_remove('match','1.0','end')
        self.log.tag_remove('current','1.0','end')
        if not query:
            self.match_text.set('')
            return
        count=0
        start='1.0'
        n=tk.IntVar()
        while True:
            pos=self.log.search(query,start,'end',nocase=True,count=n)
            if not pos or not n.get():
                break
            end=f'{pos}+{n.get()}c'
            self.log.tag_add('match',pos,end)
            start=end
            count+=1
            if count>=5000:
                break
        self.match_text.set(f'{count} 处匹配' if count else '无匹配')
        if jump and count:
            self._next_match(from_start=True)

    def _next_match(self,from_start=False):
        ranges=self.log.tag_ranges('match')
        if not ranges:
            return
        cur=self.log.tag_ranges('current')
        self.log.tag_remove('current','1.0','end')
        start=None
        if cur and not from_start:
            nxt=self.log.tag_nextrange('match',cur[1])
            start=nxt if nxt else None
        if not start:
            start=(ranges[0],ranges[1])
        self.log.tag_add('current',start[0],start[1])
        self.log.see(start[0])

    def download_selected(self):
        entry=self.selected_file()
        if not entry or entry['directory']:
            self.activity.set('请选择一个文件进行下载。')
            return
        if 'download' in self.busy:
            self.activity.set('当前下载尚未完成。')
            return
        dest=filedialog.asksaveasfilename(parent=self,title='保存远程文件到 Windows',initialfile=entry['name'])
        if not dest:
            return
        self.cancel_download.clear()
        self.cancel_button.set_enabled(True)
        self.download_text.set('连接中…')
        self.download_bar.set(0)
        self.download_bar.pack(side='left',padx=(self.theme.px(12),0),before=self.download_label)
        def progress(n,total):
            self.events.put(('progress','download',None,(n,total)))
        def done(n):
            self.download_text.set(f'已完成 {size(n)}')
            self.download_bar.pack_forget()
            self.notify('下载完成',f'{entry["name"]} → {dest}','ok')
        self.submit('download',lambda:self.client.download(entry['path'],dest,progress,self.cancel_download),done)

    # -------------------------------------------------------------- settings
    def open_settings(self):
        t=self.theme
        if 'download' in self.busy:
            messagebox.showinfo('请稍候','下载进行中，完成或取消后再修改连接。',parent=self)
            return
        win=tk.Toplevel(self,bg=C['bg'])
        win.title('连接与刷新设置')
        win.transient(self)
        win.resizable(False,False)
        body=tk.Frame(win,bg=C['bg'])
        body.pack(fill='both',expand=True,padx=t.px(24),pady=t.px(20))
        dark_title_bar(win,self.mode=='dark')
        tk.Label(body,text='设置',bg=C['bg'],fg=C['text'],font=t.serif_font(18)).grid(row=0,column=0,columnspan=3,sticky='w')
        tk.Label(body,text='使用本机 Windows OpenSSH 与已有密钥；主机指纹须已在系统 SSH 中验证。保存后立即重新连接。',
                 bg=C['bg'],fg=C['muted'],font=t.font(9),wraplength=t.px(460),justify='left').grid(row=1,column=0,columnspan=3,sticky='w',pady=(t.px(4),t.px(14)))
        p=self.client.profile
        fields=[('host','服务器地址',p.host),('user','用户名',p.user),('port','端口',str(p.port)),('key','私钥文件',p.key),
                ('root','项目根目录',p.root),('refresh_seconds','自动刷新间隔（秒，5–600）',str(self.refresh_seconds))]
        vars_={}
        for i,(key,name,value) in enumerate(fields,2):
            tk.Label(body,text=name,bg=C['bg'],fg=C['sub'],font=t.font(9)).grid(row=i,column=0,sticky='w',pady=t.px(5),padx=(0,t.px(14)))
            var=tk.StringVar(value=value)
            Field(body,t,var,width=44,mono=True).grid(row=i,column=1,sticky='ew',pady=t.px(4))
            vars_[key]=var
            if key=='key':
                def browse(v=var):
                    path=filedialog.askopenfilename(parent=win,title='选择 SSH 私钥',initialdir=str(Path.home()/'.ssh'))
                    if path:
                        v.set(str(Path(path)))
                RoundButton(body,t,'浏览…',browse,size=9).grid(row=i,column=2,padx=(t.px(8),0))
        row=len(fields)+2
        tk.Label(body,text='外观',bg=C['bg'],fg=C['sub'],font=t.font(9)).grid(row=row,column=0,sticky='w',pady=(t.px(10),0))
        looks=tk.Frame(body,bg=C['bg'])
        looks.grid(row=row,column=1,columnspan=2,sticky='w',pady=(t.px(10),0))
        appearance=tk.StringVar(value=self.appearance)
        chips={}
        def pick(mode):
            appearance.set(mode)
            for m,c in chips.items():
                c.set_active(m==mode)
        for mode,name in (('system','跟随系统'),('light','浅色'),('dark','深色')):
            chips[mode]=Chip(looks,t,name,lambda m=mode:pick(m))
            chips[mode].pack(side='left',padx=(0,t.px(8)))
        pick(self.appearance)
        row+=1
        tk.Label(body,text='系统通知',bg=C['bg'],fg=C['sub'],font=t.font(9)).grid(row=row,column=0,sticky='w',pady=(t.px(10),0))
        toast_box=tk.Frame(body,bg=C['bg'])
        toast_box.grid(row=row,column=1,columnspan=2,sticky='w',pady=(t.px(10),0))
        toasts=tk.BooleanVar(value=self.toasts)
        toast_chips={}
        def pick_toast(value):
            toasts.set(value)
            for v,c in toast_chips.items():
                c.set_active(v==value)
        for value,name in ((True,'窗口不在前台时弹出'),(False,'关闭')):
            toast_chips[value]=Chip(toast_box,t,name,lambda v=value:pick_toast(v))
            toast_chips[value].pack(side='left',padx=(0,t.px(8)))
        pick_toast(self.toasts)
        row+=1
        tk.Label(body,text='许可证查询',bg=C['bg'],fg=C['sub'],font=t.font(9)).grid(row=row,column=0,sticky='w',pady=(t.px(10),0))
        lic_box=tk.Frame(body,bg=C['bg'])
        lic_box.grid(row=row,column=1,columnspan=2,sticky='w',pady=(t.px(10),0))
        license_query=tk.BooleanVar(value=self.license_query)
        lic_chips={}
        def pick_license(value):
            license_query.set(value)
            for v,c in lic_chips.items():
                c.set_active(v==value)
        for value,name in ((True,'每分钟查询 lmstat'),(False,'关闭')):
            lic_chips[value]=Chip(lic_box,t,name,lambda v=value:pick_license(v))
            lic_chips[value].pack(side='left',padx=(0,t.px(8)))
        pick_license(self.license_query)
        error=tk.StringVar()
        tk.Label(body,textvariable=error,bg=C['bg'],fg=C['red'],font=t.font(9),wraplength=t.px(460),justify='left').grid(
            row=row+1,column=0,columnspan=3,sticky='w',pady=(t.px(8),0))
        buttons=tk.Frame(body,bg=C['bg'])
        buttons.grid(row=row+2,column=0,columnspan=3,sticky='e',pady=(t.px(14),0))
        def save():
            try:
                profile=Profile(host=vars_['host'].get().strip(),user=vars_['user'].get().strip(),key=vars_['key'].get().strip(),
                                port=int(vars_['port'].get()),root=vars_['root'].get().strip().rstrip('/') or '/')
                interval=int(vars_['refresh_seconds'].get())
                if not 5<=interval<=600:
                    raise ValueError('刷新间隔需在 5–600 秒之间')
                if not profile.root.startswith('/'):
                    raise ValueError('项目根目录必须是服务器上的绝对路径')
                save_settings(profile,refresh_seconds=interval,theme=appearance.get(),toasts=toasts.get(),
                              license_query=license_query.get())
                self.toasts=toasts.get()
                self.license_query=license_query.get()
            except (ValueError,OSError) as e:
                error.set(str(e) if 'invalid literal' not in str(e) else '端口和刷新间隔必须是整数')
                return
            win.destroy()
            self.apply_profile(profile,interval)
            if appearance.get()!=self.appearance:
                self.appearance=appearance.get()
                if messagebox.askyesno('外观','外观将在重新打开后生效。现在重新打开监控窗口吗？',parent=self):
                    self.restart()
        tk.Label(buttons,text=f'Lumerical Monitor {VERSION} · 只读 · 不在服务器安装任何程序',bg=C['bg'],fg=C['faint'],
                 font=t.font(8)).pack(side='left',padx=(0,t.px(40)))
        RoundButton(buttons,t,'取消',win.destroy,kind='ghost').pack(side='right')
        RoundButton(buttons,t,'保存',save,kind='primary').pack(side='right',padx=(0,t.px(8)))
        win.bind('<Escape>',lambda e:win.destroy())
        win.update_idletasks()
        x=self.winfo_rootx()+(self.winfo_width()-win.winfo_width())//2
        y=self.winfo_rooty()+(self.winfo_height()-win.winfo_height())//3
        win.geometry(f'+{x}+{y}')
        win.grab_set()

    def apply_profile(self,profile,interval):
        changed=profile!=self.client.profile
        self.refresh_seconds=interval
        self.auto_switch.text.configure(text=f'自动刷新 · {interval}s')
        if self.next_refresh is not None:
            self.next_refresh=min(self.next_refresh,time.monotonic()+interval)
        if changed:
            self.preview_cancel.set()
            self.preview_generation+=1
            self.preview_path=self.preview_target=''
            self.preview_pending=None
            self.preview_running=False
            for panel in (self.task_preview,self.preview_view):
                panel.set_running(False)
                panel.set_document({'available':False,'project':'','projects':[], 'message':'连接已切换，请重新选择工程文件'})
            threading.Thread(target=self.client.close,daemon=True).start()
            self.client=Client(profile)
            self._update_host_text()
            self.root_label.configure(text=profile.root.rstrip('/')+'/')
            self.snapshot=None
            self.known_jobs=None
            self.last_success=None
            self.alerted.clear()
            for h in self.history.values():
                h.clear()
            self.gpu_history.clear()
            self.current_path='.'
            self.file_table.set_rows([])
            self.log_path=None
            self.follow.set(False)
            self._feed('info',f'连接已切换到 {profile.user}@{profile.host}')
            self.refresh()
        self.activity.set('设置已保存到 profile.json。')

    def restart(self):
        import subprocess
        args=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve())]
        subprocess.Popen(args,cwd=str(HERE))
        self.close()

    # ----------------------------------------------------------------- close
    def close(self):
        if self.closing:
            return
        self.closing=True
        self.auto.set(False)
        self.cancel_download.set()
        if getattr(self,'preview_cancel',None) is not None:
            self.preview_cancel.set()
        self.activity.set('正在取消下载并清理本地临时文件，请稍候…')
        self._finish_close()

    def _finish_close(self):
        if 'download' in self.busy:
            self.after(100,self._finish_close)
            return
        self.closed=True
        self._save_window()
        self.client.close()  # ends the remote session process with the window
        self.destroy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check',action='store_true',help='Print one real SSH snapshot and exit')
    parser.add_argument('--ui-smoke',action='store_true',help='Render a saved snapshot, check widgets and exit')
    args=parser.parse_args()
    logging.basicConfig(filename=HERE/'monitor.log',level=logging.INFO,encoding='utf-8',
                        format='%(asctime)s %(levelname)s %(message)s')
    if args.check:
        data=Client().request('snapshot')
        (HERE/'last-check.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(data,indent=2,ensure_ascii=True))
        return
    app=Monitor(auto_connect=not args.ui_smoke)
    if args.ui_smoke:
        app.auto.set(False)
        data=json.loads((HERE/'last-check.json').read_text(encoding='utf-8'))
        app.show_snapshot(data)
        if (HERE/'last-files.json').exists():
            app.show_files(json.loads((HERE/'last-files.json').read_text(encoding='utf-8')))
        if (HERE/'last-tail.json').exists():
            app.show_text(json.loads((HERE/'last-tail.json').read_text(encoding='utf-8')))
        for key,_,_ in PAGES:
            app.show_page(key)
            app.update()
        assert len(app.task_tree.get_children())==len(data['jobs'])
        assert app.metrics['cpu']['value'].get()!='—'
        assert len(app.gpu_cards)==len(data.get('gpu',{}).get('devices',[]))
        assert len(app.proc_table.tree.get_children())==len(data.get('all_processes',[]))
        app.mine_only.set(True)
        app.filter_processes()
        assert len(app.proc_table.tree.get_children())==sum(bool(p.get('mine')) for p in data.get('all_processes',[]))
        assert len(app.gpu_process_tree.get_children())==sum(bool(p.get('mine')) for p in data.get('gpu',{}).get('processes',[]))
        app.mine_only.set(False)
        app.filter_processes()
        app.show_snapshot(data)  # second sample exercises history and job diffing
        app.close()
        print('UI smoke test passed')
    else:
        app.mainloop()


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        logging.exception('Monitor startup failed')
        if '--check' in sys.argv or '--ui-smoke' in sys.argv:
            raise
        messagebox.showerror('远程监控启动失败',str(e))
