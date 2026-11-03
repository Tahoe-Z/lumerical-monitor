"""Claude-desktop-inspired light/dark theme and custom Tk widgets; standard library only."""
import math
import tkinter as tk
from tkinter import ttk, font as tkfont

# Warm neutrals and the clay accent, following the Claude desktop palette.
LIGHT = {
    'bg': '#FAF9F5', 'side': '#F5F4ED', 'surface': '#FFFFFF', 'field': '#FAF9F5',
    'raised': '#F0EEE6', 'border': '#E8E6DC', 'line': '#F0EEE6', 'select': '#F6E9E2',
    'text': '#141413', 'sub': '#3D3D3A', 'muted': '#73726C', 'faint': '#A3A29B',
    'accent': '#C6613F', 'accent_hover': '#B4532F', 'on_accent': '#FFFFFF',
    'green': '#4C7D3F', 'amber': '#B7791F', 'red': '#B5432F', 'blue': '#3F6FA0', 'purple': '#7A63B8',
    'track': '#EEECE4', 'toggle': '#D9D7CD', 'stripe': '#FCFBF8', 'log': '#FAF9F5', 'log_text': '#3D3D3A',
    'tooltip': '#141413', 'tooltip_text': '#FAF9F5',
}
DARK = {
    'bg': '#262624', 'side': '#1F1E1D', 'surface': '#30302E', 'field': '#262624',
    'raised': '#3A3A37', 'border': '#3E3D39', 'line': '#3A3A37', 'select': '#4A3830',
    'text': '#FAF9F5', 'sub': '#C2C0B6', 'muted': '#9C9A92', 'faint': '#6E6C66',
    'accent': '#D97757', 'accent_hover': '#E38B6E', 'on_accent': '#FFFFFF',
    'green': '#8DBF7F', 'amber': '#E0A64B', 'red': '#E5735F', 'blue': '#80A8D6', 'purple': '#A894E0',
    'track': '#45443F', 'toggle': '#55534E', 'stripe': '#333331', 'log': '#262624', 'log_text': '#D6D4CB',
    'tooltip': '#FAF9F5', 'tooltip_text': '#141413',
}
C = dict(LIGHT)

ICON = {'overview': '', 'tasks': '', 'files': '', 'gpu': '', 'users': '',
        'settings': '', 'refresh': '', 'download': '', 'search': '',
        'up': '', 'home': '', 'folder': '', 'file': '', 'temp': '',
        'open': '', 'close': '', 'check': '', 'warn': '', 'info': ''}

ICON['license'] = chr(0xE72E)  # Segoe Fluent 'Lock'

def system_prefers_dark():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except (ImportError, OSError):
        return False


def use_palette(mode='system'):
    """Select the palette before any widget is created; returns 'light' or 'dark'."""
    dark = mode == 'dark' or (mode not in ('light', 'dark') and system_prefers_dark())
    C.clear()
    C.update(DARK if dark else LIGHT)
    return 'dark' if dark else 'light'


def mix(a, b, t):
    """Blend colour a toward b by t (0..1); Tk canvases have no alpha."""
    pa = [int(a[i:i+2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i+2], 16) for i in (1, 3, 5)]
    return '#'+''.join(f'{round(x+(y-x)*t):02x}' for x, y in zip(pa, pb))


def level_color(percent, base):
    if percent is None:
        return C['faint']
    return C['red'] if percent >= 90 else C['amber'] if percent >= 75 else base


class Theme:
    def __init__(self, root):
        self.scale = max(1.0, root.winfo_fpixels('1i')/96)
        families = set(tkfont.families(root))
        pick = lambda *names: next((n for n in names if n in families), names[-1])
        self.ui = pick('Noto Sans SC', 'Microsoft YaHei UI', 'Segoe UI')
        self.ui_medium = pick('Noto Sans SC Medium', '')
        self.serif = pick('Noto Serif SC', 'Source Han Serif SC', 'Georgia', self.ui)
        self.serif_medium = pick('Noto Serif SC Medium', 'Noto Serif SC SemiBold', '')
        self.num = self.serif
        self.mono = pick('Cascadia Mono', 'Consolas', 'Courier New')
        self.icons = pick('Segoe Fluent Icons', 'Segoe MDL2 Assets', self.ui)

    def px(self, value):
        return max(1, int(round(value*self.scale)))

    def font(self, size, weight='normal', family=None):
        # Claude uses medium weights rather than heavy bold.
        if weight == 'bold' and family is None and self.ui_medium:
            return (self.ui_medium, size, 'normal')
        return (family or self.ui, size, weight)

    def serif_font(self, size, weight='normal'):
        if weight == 'bold' and self.serif_medium:
            return (self.serif_medium, size, 'normal')
        return (self.serif, size, weight)

    def icon(self, size=12):
        return (self.icons, size)

    def apply(self, root):
        s = ttk.Style(root)
        s.theme_use('clam')
        s.configure('.', font=self.font(10), background=C['bg'], foreground=C['text'], bordercolor=C['border'],
                    lightcolor=C['surface'], darkcolor=C['surface'], troughcolor=C['surface'],
                    focuscolor=C['accent'], selectbackground=C['select'], selectforeground=C['text'],
                    fieldbackground=C['field'], insertcolor=C['text'])
        s.configure('TFrame', background=C['bg'])
        s.configure('Treeview', background=C['surface'], fieldbackground=C['surface'], foreground=C['text'],
                    bordercolor=C['surface'], lightcolor=C['surface'], darkcolor=C['surface'],
                    rowheight=self.px(32), font=self.font(9))
        s.map('Treeview', background=[('selected', C['select'])], foreground=[('selected', C['text'])])
        s.configure('Treeview.Heading', background=C['surface'], foreground=C['muted'], relief='flat',
                    bordercolor=C['border'], lightcolor=C['surface'], darkcolor=C['border'],
                    font=self.font(9, 'bold'), padding=(self.px(8), self.px(7)))
        s.map('Treeview.Heading', background=[('active', C['raised'])], foreground=[('active', C['text'])])
        s.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        # Slim, arrowless scrollbars like the desktop app.
        for orient, side in (('Vertical', 'ns'), ('Horizontal', 'ew')):
            s.layout(f'{orient}.TScrollbar', [(f'{orient}.Scrollbar.trough', {'sticky': side, 'children': [
                (f'{orient}.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})]})])
            s.configure(f'{orient}.TScrollbar', background=C['toggle'], troughcolor=C['surface'],
                        bordercolor=C['surface'], lightcolor=C['toggle'], darkcolor=C['toggle'],
                        arrowsize=self.px(7), gripcount=0, relief='flat')
            s.map(f'{orient}.TScrollbar', background=[('active', C['faint'])],
                  lightcolor=[('active', C['faint'])], darkcolor=[('active', C['faint'])])
        s.configure('Sash', sashthickness=self.px(10), background=C['bg'], gripcount=0)
        s.configure('TPanedwindow', background=C['bg'])
        root.option_add('*Menu.background', C['surface'])
        root.option_add('*Menu.foreground', C['text'])


def dark_title_bar(window, dark):
    """Ask DWM for a dark caption so the native title bar matches the dark palette."""
    if not dark:
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old builds)
            if not ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)):
                break
    except (AttributeError, OSError):
        pass


# ----------------------------------------------------------------- rounded shapes


def _rgb(color):
    return [int(color[i:i+2], 16) for i in (1, 3, 5)]


def _corner_images(master, r, fill, border, outer, bw):
    """Anti-aliased quarter-circle corner images (4x4 supersampled), cached per Tk root and colour set."""
    root = master._root()
    cache = root.__dict__.setdefault('_corner_cache', {})  # images die with their interpreter
    key = (r, fill, border, outer, bw)
    if key in cache:
        return cache[key]
    F, B, O = _rgb(fill), _rgb(border), _rgb(outer)
    samples = [(i+.5)/4 for i in range(4)]
    images = {}
    for name, (cx, cy) in {'tl': (r, r), 'tr': (0, r), 'bl': (r, 0), 'br': (0, 0)}.items():
        rows = []
        for y in range(r):
            row = []
            for x in range(r):
                fo = fb = ff = 0
                for sy in samples:
                    for sx in samples:
                        d = math.hypot(x+sx-cx, y+sy-cy)
                        if d > r:
                            fo += 1
                        elif d > r-bw:
                            fb += 1
                        else:
                            ff += 1
                row.append('#'+''.join(f'{round((o*fo+b*fb+f*ff)/16):02x}' for o, b, f in zip(O, B, F)))
            rows.append('{'+' '.join(row)+'}')
        image = tk.PhotoImage(master=master, width=r, height=r)
        image.put(' '.join(rows))
        images[name] = image
    cache[key] = images
    return images


class Rounded(tk.Frame):
    """Frame whose background is a rounded rectangle drawn on a canvas behind its children.

    Children are packed normally (so the frame still sizes to its content); keep them
    inset by roughly a third of the radius so they do not cover the curved corners.
    """
    def __init__(self, parent, theme, fill, border=None, radius=12, outer=None, **kw):
        if outer is None:
            try:
                outer = parent.cget('bg')
            except tk.TclError:  # ttk containers have no bg option
                outer = C['bg']
        self.outer = outer
        super().__init__(parent, bg=self.outer, **kw)
        self.theme, self.fill, self.border = theme, fill, border or fill
        self.radius = theme.px(radius)
        self.canvas = tk.Canvas(self, bg=self.outer, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas.bind('<Configure>', lambda e: self._draw())

    def _draw(self):
        c = self.canvas
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()
        if w < 4 or h < 4:
            return
        r = min(self.radius, w//2, h//2)
        bordered = self.border != self.fill
        c.create_rectangle(r, 0, w-r, h, fill=self.fill, width=0)
        c.create_rectangle(0, r, w, h-r, fill=self.fill, width=0)
        if bordered:
            for box in ((r, 0, w-r, 1), (r, h-1, w-r, h), (0, r, 1, h-r), (w-1, r, w, h-r)):
                c.create_rectangle(*box, fill=self.border, width=0)
        if r >= 1:
            images = _corner_images(self, r, self.fill, self.border, self.outer, 1 if bordered else 0)
            for name, x, y in (('tl', 0, 0), ('tr', w-r, 0), ('bl', 0, h-r), ('br', w-r, h-r)):
                c.create_image(x, y, anchor='nw', image=images[name])

    def recolor(self, fill, border=None):
        old, self.fill = self.fill, fill
        self.border = border or fill
        self._draw()
        stack = [w for w in self.winfo_children() if w is not self.canvas]
        while stack:
            w = stack.pop()
            try:
                if w.cget('bg') == old:
                    w.configure(bg=fill)
            except tk.TclError:
                pass
            if isinstance(w, Rounded):
                if w.outer == old:
                    w.outer = fill
                    w.configure(bg=fill)
                    w.canvas.configure(bg=fill)
                    w._draw()
                continue
            stack.extend(w.winfo_children())


class Card(Rounded):
    """White surface with a hairline border, rounded corners and an optional header row."""
    def __init__(self, parent, theme, title=None, pad=16, **kw):
        super().__init__(parent, theme, C['surface'], C['border'], radius=12, **kw)
        self.body = tk.Frame(self, bg=C['surface'])
        p = theme.px(pad)
        if title is not None:
            self.header = tk.Frame(self, bg=C['surface'])
            self.header.pack(fill='x', padx=p, pady=(p-theme.px(2), 0))
            self.title_var = tk.StringVar(value=title)
            tk.Label(self.header, textvariable=self.title_var, bg=C['surface'], fg=C['text'],
                     font=theme.font(10, 'bold')).pack(side='left')
            self.body.pack(fill='both', expand=True, padx=p, pady=(theme.px(8), p-theme.px(4)))
        else:
            self.body.pack(fill='both', expand=True, padx=p, pady=p)


class RoundButton(Rounded):
    """Pill button: 'primary' (clay), 'secondary' (outlined) or 'ghost'."""
    def __init__(self, parent, theme, text, command, kind='secondary', icon=None, radius=9, size=10):
        outer = parent.cget('bg')
        self.kind = kind
        fill, border, fg = self._colors(outer)
        super().__init__(parent, theme, fill, border, radius=radius, outer=outer, cursor='hand2')
        self.command, self.enabled = command, True
        self.fg = fg
        self.parts = []
        inner = tk.Frame(self, bg=fill, cursor='hand2')
        inner.pack(padx=theme.px(14), pady=theme.px(5))
        if icon:
            self.parts.append(tk.Label(inner, text=icon, font=theme.icon(size-1), bg=fill, fg=fg, cursor='hand2'))
            self.parts[-1].pack(side='left', padx=(0, theme.px(6) if text else 0))
        if text:
            self.parts.append(tk.Label(inner, text=text, font=theme.font(size, 'bold'), bg=fill, fg=fg, cursor='hand2'))
            self.parts[-1].pack(side='left')
        for w in (self, self.canvas, inner, *self.parts):
            w.bind('<Enter>', lambda e: self._hover(True))
            w.bind('<Leave>', lambda e: self._hover(False))
            w.bind('<Button-1>', lambda e: self._click())

    def _colors(self, outer):
        if self.kind == 'primary':
            return C['accent'], C['accent'], C['on_accent']
        if self.kind == 'ghost':
            return outer, outer, C['sub']
        return C['surface'], C['border'], C['text']

    def _hover(self, inside):
        if not self.enabled:
            return
        fill, border, _ = self._colors(self.outer)
        if inside:
            fill = C['accent_hover'] if self.kind == 'primary' else C['raised']
            border = fill if self.kind != 'secondary' else C['border']
        self.recolor(fill, border)

    def _click(self):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = enabled
        for p in self.parts:
            p.configure(fg=self.fg if enabled else C['faint'])
        self.configure(cursor='hand2' if enabled else 'arrow')
        fill, border, _ = self._colors(self.outer)
        self.recolor(fill, border)

    def set_text(self, text):
        self.parts[-1].configure(text=text)


class Chip(Rounded):
    """Clickable pill used as a filter toggle."""
    def __init__(self, parent, theme, text, command, color=None):
        outer = parent.cget('bg')
        super().__init__(parent, theme, C['surface'], C['border'], radius=40, outer=outer, cursor='hand2')
        self.theme, self.color, self.active = theme, color or C['accent'], False
        self.label = tk.Label(self, text=text, bg=C['surface'], fg=C['sub'], font=theme.font(9), cursor='hand2')
        self.label.pack(padx=theme.px(14), pady=theme.px(4))
        for w in (self, self.canvas, self.label):
            w.bind('<Button-1>', lambda e: command())
            w.bind('<Enter>', lambda e: self.active or self.recolor(C['raised'], C['border']))
            w.bind('<Leave>', lambda e: self.set_active(self.active))

    def set_active(self, active):
        self.active = active
        if active:
            self.recolor(mix(C['surface'], self.color, .12), mix(C['surface'], self.color, .45))
            self.label.configure(fg=C['text'], font=self.theme.font(9, 'bold'))
        else:
            self.recolor(C['surface'], C['border'])
            self.label.configure(fg=C['sub'], font=self.theme.font(9))

    def set_text(self, text):
        self.label.configure(text=text)


class Bar(tk.Canvas):
    def __init__(self, parent, theme, height=6, color=None, bg=None):
        bg = bg or parent.cget('bg')
        super().__init__(parent, height=theme.px(height), width=theme.px(40), bg=bg, highlightthickness=0, bd=0)
        self.percent, self.color = 0, color or C['accent']
        self.extra = None  # optional (percent, colour) segment drawn right after the main one
        self.track = C['track']
        self.bind('<Configure>', lambda e: self.draw())

    def set(self, percent, color=None, extra=None):
        self.percent = max(0, min(100, percent or 0))
        self.color = color or self.color
        self.extra = extra
        self.draw()

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), int(self.cget('height'))
        if w < 4:
            return
        r = h/2
        span = lambda p: max(r+.6, r+(w-2*r)*min(100, p)/100)
        self.create_line(r, h/2, w-r, h/2, width=h, capstyle='round', fill=self.track)
        if self.extra and self.extra[0] > 0:
            self.create_line(r, h/2, span(self.percent+self.extra[0]), h/2, width=h, capstyle='round', fill=self.extra[1])
        if self.percent > 0:
            self.create_line(r, h/2, span(self.percent), h/2, width=h, capstyle='round', fill=self.color)


class Sparkline(tk.Canvas):
    """Right-aligned history line with a soft filled area; fixed 0..maximum scale."""
    def __init__(self, parent, theme, color, height=44, capacity=120, maximum=100, bg=None, fit=False):
        bg = bg or parent.cget('bg')
        super().__init__(parent, height=theme.px(height), width=theme.px(40), bg=bg, highlightthickness=0, bd=0)
        self.theme, self.color, self.bgc = theme, color, bg
        self.capacity, self.maximum, self.values = capacity, maximum, []
        self.marker = None  # optional (value, colour) reference line
        self.fit = fit      # stretch the series across the full width instead of a fixed window
        self.bind('<Configure>', lambda e: self.draw())

    def set(self, values, color=None):
        self.values = [v for v in values][-self.capacity:]
        self.color = color or self.color
        self.draw()

    def draw(self):
        self.delete('all')
        w, h = self.winfo_width(), int(self.cget('height'))
        if w < 10:
            return
        grid = C['line']
        self.create_line(0, h/2, w, h/2, fill=grid, dash=(2, 4))
        self.create_line(0, h-1, w, h-1, fill=grid)
        if self.marker:
            my = h-2-(h-6)*self.marker[0]/self.maximum
            self.create_line(0, my, w, my, fill=self.marker[1], dash=(4, 3))
        if sum(v is not None for v in self.values) < 3:
            # Too few samples for a trend; a 2-point sliver at the right edge reads as a glitch.
            self.create_text(w/2, h/2, text='正在积累趋势数据…' if self.values else '暂无数据',
                             fill=C['faint'], font=self.theme.font(8))
            return
        slots = len(self.values) if self.fit else self.capacity
        pts, step = [], w/max(1, slots-1)
        n = len(self.values)
        for i, v in enumerate(self.values):
            if v is None:
                continue
            x = w-(n-1-i)*step
            y = h-2-(h-6)*max(0, min(self.maximum, v))/self.maximum
            pts.append((x, y))
        if len(pts) >= 2:
            flat = [c for p in pts for c in p]
            self.create_polygon(pts[0][0], h, *flat, pts[-1][0], h, fill=mix(self.bgc, self.color, .13), outline='')
            self.create_line(*flat, fill=self.color, width=self.theme.px(1.6), joinstyle='round', capstyle='round')
        if pts:
            x, y = pts[-1]
            r = self.theme.px(3)
            self.create_oval(x-r, y-r, x+r, y+r, fill=self.color, outline=self.bgc)


class Switch(tk.Frame):
    """Pill toggle bound to a BooleanVar."""
    def __init__(self, parent, theme, variable, text, command=None, bg=None):
        bg = bg or parent.cget('bg')
        super().__init__(parent, bg=bg, cursor='hand2')
        self.var, self.command, self.theme = variable, command, theme
        w, h = theme.px(30), theme.px(17)
        self.canvas = tk.Canvas(self, width=w, height=h, bg=bg, highlightthickness=0, bd=0, cursor='hand2')
        self.canvas.pack(side='left')
        self.text = tk.Label(self, text=text, bg=bg, fg=C['sub'], font=theme.font(9), cursor='hand2')
        self.text.pack(side='left', padx=(theme.px(7), 0))
        for widget in (self, self.canvas, self.text):
            widget.bind('<Button-1>', self.toggle)
        variable.trace_add('write', lambda *a: self.draw())
        self.draw()

    def toggle(self, event=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        c, on = self.canvas, self.var.get()
        c.delete('all')
        w, h = int(c.cget('width')), int(c.cget('height'))
        r = h/2
        c.create_line(r, r, w-r, r, width=h, capstyle='round', fill=C['accent'] if on else C['toggle'])
        k = r-self.theme.px(2.5)
        x = w-r if on else r
        c.create_oval(x-k, r-k, x+k, r+k, fill='#ffffff', outline='')
        self.text.configure(fg=C['text'] if on else C['sub'])


class IconButton(Rounded):
    def __init__(self, parent, theme, glyph, command, tip=None, size=12):
        outer = parent.cget('bg')
        super().__init__(parent, theme, outer, radius=8, outer=outer, cursor='hand2')
        self.label = tk.Label(self, text=glyph, font=theme.icon(size), bg=outer, fg=C['sub'], cursor='hand2')
        self.label.pack(padx=theme.px(8), pady=theme.px(6))
        for w in (self, self.canvas, self.label):
            w.bind('<Enter>', lambda e: (self.recolor(C['raised']), self.label.configure(fg=C['text'])))
            w.bind('<Leave>', lambda e: (self.recolor(self.outer), self.label.configure(fg=C['sub'])))
            w.bind('<Button-1>', lambda e: command())
        if tip:
            Tooltip(self, tip)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind('<Enter>', self.show, add='+')
        widget.bind('<Leave>', self.hide, add='+')

    def show(self, event=None):
        if self.tip:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        tk.Label(self.tip, text=self.text, bg=C['tooltip'], fg=C['tooltip_text'], padx=9, pady=4,
                 font=(tkfont.nametofont('TkDefaultFont').actual('family'), 9)).pack()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty()+self.widget.winfo_height()+6
        self.tip.wm_geometry(f'+{x}+{y}')

    def hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Table(tk.Frame):
    """Treeview with click-to-sort headers, text filtering, striping and stable selection.

    Rows are dicts: values (display), sort (optional per-column keys), key, data, tags.
    """
    def __init__(self, parent, theme, columns, height=None, on_open=None, on_select=None, empty='暂无数据'):
        super().__init__(parent, bg=C['surface'])
        self.theme, self.columns = theme, columns
        self.rows, self.query, self.sort_col, self.sort_rev = [], '', None, False
        self.items = {}
        self.empty_text = empty
        keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=keys, show='headings', selectmode='browse')
        if height:
            self.tree.configure(height=height)
        for i, (key, title, width, *rest) in enumerate(columns):
            anchor = rest[0] if rest else 'w'
            stretch = rest[1] if len(rest) > 1 else False
            self.tree.heading(key, text=title, anchor=anchor, command=lambda i=i: self.sort_by(i))
            self.tree.column(key, width=theme.px(width), minwidth=theme.px(36), anchor=anchor, stretch=stretch)
        y = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        y.grid(row=0, column=1, sticky='ns', padx=(theme.px(4), 0))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.tree.tag_configure('odd', background=C['stripe'])
        for tag in ('green', 'red', 'amber', 'muted', 'accent', 'purple', 'blue'):
            self.tree.tag_configure(tag, foreground=C['faint' if tag == 'muted' else tag])
        self.tree.tag_configure('mine', foreground=C['text'], font=theme.font(9, 'bold'))
        self.tree.tag_configure('strong', font=theme.font(9, 'bold'))
        self.widths = [theme.px(c[2]) for c in columns]
        self.tree.bind('<Configure>', self._fit)
        self.empty = tk.Label(self.tree, text=empty, bg=C['surface'], fg=C['muted'], font=theme.font(9))
        if on_open:
            self.tree.bind('<Double-1>', lambda e: self.selected() and on_open(self.selected()))
            self.tree.bind('<Return>', lambda e: self.selected() and on_open(self.selected()))
        if on_select:
            self.tree.bind('<<TreeviewSelect>>', lambda e: on_select(self.selected()))

    def _fit(self, event):
        """Scale columns down proportionally so every column stays visible."""
        factor = min(1, (event.width-2)/sum(self.widths))
        for (key, *_), width in zip(self.columns, self.widths):
            self.tree.column(key, width=max(self.theme.px(40), int(width*factor)))

    def set_rows(self, rows):
        self.rows = rows
        return self.render()

    def filter(self, query):
        self.query = query.strip().lower()
        return self.render()

    def sort_by(self, index):
        if self.sort_col == index:
            self.sort_rev = not self.sort_rev
        else:
            # Numbers start largest-first, text starts A→Z.
            sample = next(((r.get('sort') or r['values'])[index] for r in self.rows
                           if (r.get('sort') or r['values'])[index] is not None), '')
            self.sort_rev = isinstance(sample, (int, float))
        self.sort_col = index
        self.render()

    def selected(self):
        sel = self.tree.selection()
        return self.items.get(sel[0]) if sel else None

    def visible(self):
        rows = self.rows
        if self.query:
            rows = [r for r in rows if self.query in ' '.join(str(v) for v in r['values']).lower()]
        if self.sort_col is not None:
            i = self.sort_col
            def key(r):
                v = (r.get('sort') or r['values'])[i]
                return (v is not None, v if v is not None else 0)
            rows = sorted(rows, key=key, reverse=self.sort_rev)
        return rows

    def render(self):
        old = self.selected()
        old_key = old.get('key') if old else None
        top = self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        self.items = {}
        rows = self.visible()
        for n, r in enumerate(rows):
            tags = tuple(r.get('tags', ()))+(('odd',) if n % 2 else ())
            iid = self.tree.insert('', 'end', values=r['values'], tags=tags)
            self.items[iid] = r
            if old_key is not None and r.get('key') == old_key:
                self.tree.selection_set(iid)
        self.tree.yview_moveto(top)
        for i, (key, title, *_) in enumerate(self.columns):
            arrow = (' ↓' if self.sort_rev else ' ↑') if i == self.sort_col else ''
            self.tree.heading(key, text=title+arrow)
        if rows:
            self.empty.place_forget()
        else:
            self.empty.configure(text=self.empty_text if not self.query else '没有匹配的项目')
            self.empty.place(relx=.5, rely=.45, anchor='center')
        return len(rows)


class Field(Rounded):
    """Rounded text input; .entry is the tk.Entry, .var its StringVar."""
    def __init__(self, parent, theme, var=None, width=20, mono=False, icon=None, placeholder=''):
        super().__init__(parent, theme, C['field'], C['border'], radius=9)
        self.var = var or tk.StringVar()
        if icon:
            tk.Label(self, text=icon, font=theme.icon(10), bg=C['field'], fg=C['muted']).pack(side='left', padx=(theme.px(11), 0))
        self.entry = tk.Entry(self, textvariable=self.var, bg=C['field'], fg=C['text'], insertbackground=C['text'],
                              relief='flat', font=(theme.mono, 9) if mono else theme.font(9), width=width,
                              highlightthickness=0, bd=0, selectbackground=C['select'], selectforeground=C['text'])
        self.entry.pack(side='left', fill='x', expand=True, padx=theme.px(8) if icon else theme.px(11), pady=theme.px(6))
        self.hint = tk.Label(self, text=placeholder, bg=C['field'], fg=C['faint'], font=theme.font(9))
        self.hint_x = theme.px(34 if icon else 11)
        if placeholder:
            self.hint.bind('<Button-1>', lambda e: self.entry.focus_set())
            self.var.trace_add('write', lambda *a: self._hint())
            self._hint()
        self.entry.bind('<FocusIn>', lambda e: self.recolor(C['field'], C['accent']), add='+')
        self.entry.bind('<FocusOut>', lambda e: self.recolor(C['field'], C['border']), add='+')

    def _hint(self):
        if self.var.get():
            self.hint.place_forget()
        else:
            self.hint.place(x=self.hint_x, rely=.5, anchor='w')

    def focus(self):
        self.entry.focus_set()
        self.entry.select_range(0, 'end')


class SearchBox(Field):
    def __init__(self, parent, theme, command, placeholder='搜索…', width=22):
        super().__init__(parent, theme, width=width, icon=ICON['search'], placeholder=placeholder)
        self.var.trace_add('write', lambda *a: command(self.var.get()))
        self.entry.bind('<Escape>', lambda e: self.var.set(''))


class Toaster:
    """Stacked in-window notifications in the bottom-right corner."""
    KINDS = {'info': ('accent', ICON['info']), 'ok': ('green', ICON['check']),
             'warn': ('amber', ICON['warn']), 'error': ('red', ICON['warn'])}

    def __init__(self, root, theme):
        self.root, self.theme, self.items = root, theme, []

    def show(self, title, body='', kind='info', ms=7000):
        color_key, glyph = self.KINDS.get(kind, self.KINDS['info'])
        t = self.theme
        frame = Rounded(self.root, t, C['surface'], C['border'], radius=12, outer=C['bg'])
        tk.Label(frame, text=glyph, font=t.icon(13), bg=C['surface'], fg=C[color_key]).pack(
            side='left', anchor='n', padx=(t.px(16), 0), pady=t.px(14))
        inner = tk.Frame(frame, bg=C['surface'])
        inner.pack(side='left', fill='both', expand=True, padx=t.px(12), pady=t.px(12))
        tk.Label(inner, text=title, bg=C['surface'], fg=C['text'], font=t.font(10, 'bold'), anchor='w',
                 justify='left', wraplength=t.px(280)).pack(anchor='w')
        if body:
            tk.Label(inner, text=body, bg=C['surface'], fg=C['muted'], font=t.font(9), anchor='w',
                     justify='left', wraplength=t.px(280)).pack(anchor='w', pady=(t.px(2), 0))
        for w in [frame, frame.canvas, inner, *inner.winfo_children(), *frame.winfo_children()]:
            w.bind('<Button-1>', lambda e, f=frame: self.dismiss(f))
        self.items.append(frame)
        while len(self.items) > 4:
            self.items.pop(0).destroy()
        self.layout()
        self.root.after(ms, lambda: self.dismiss(frame))

    def dismiss(self, frame):
        if frame in self.items:
            self.items.remove(frame)
            frame.destroy()
            self.layout()

    def layout(self):
        y = -self.theme.px(44)
        for f in reversed(self.items):
            f.place(relx=1, rely=1, anchor='se', x=-self.theme.px(20), y=y, width=self.theme.px(350))
            f.update_idletasks()
            y -= f.winfo_reqheight()+self.theme.px(10)
            f.lift()
