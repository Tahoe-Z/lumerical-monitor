"""Tk views for cached model, field, spectrum and parameter data."""
import io
import queue
import threading
import tkinter as tk
from tkinter import ttk

from ui_kit import C, RoundButton


class PreviewPanel(tk.Frame):
    def __init__(self, parent, theme, *, load, generate=None, open_full=None, compact=False):
        super().__init__(parent, bg=C['surface'])
        self.theme, self.load, self.generate, self.compact = theme, load, generate, compact
        self.info = None
        self.document = None
        self.running = False
        self._events = queue.Queue()
        self._generation = 0
        self._busy = False
        self._pending = False
        self._alive = True
        self._photos = {}
        self._rendered = {}
        self.project = tk.StringVar(value='')
        self.status = tk.StringVar(value='选择工程文件查看模型与结果')
        self.wavelength = tk.StringVar(value='1550')
        self.z = tk.StringVar(value='0')
        self.field = tk.StringVar()
        self.spectrum = tk.StringVar()
        self._canvases = {}
        if compact:
            canvas = tk.Canvas(self, bg=C['field'], highlightthickness=0, height=theme.px(136), width=theme.px(300))
            canvas.pack(fill='both', expand=True)
            self._canvases['model'] = canvas
            canvas.bind('<Configure>', lambda _: self._draw('model'))
            if open_full:
                canvas.configure(cursor='hand2')
                canvas.bind('<Button-1>', lambda _: open_full())
            tk.Label(self, textvariable=self.status, bg=C['surface'], fg=C['muted'], font=theme.font(8),
                     wraplength=theme.px(300), justify='left').pack(fill='x', pady=(theme.px(4), 0))
        else:
            header = tk.Frame(self, bg=C['surface'])
            header.pack(fill='x', padx=theme.px(14), pady=theme.px(12))
            self.project_picker = ttk.Combobox(header, textvariable=self.project, state='readonly', width=50)
            self.project_picker.pack(side='left', fill='x', expand=True)
            self.project_picker.bind('<<ComboboxSelected>>', lambda _: self.load(self.project.get()))
            RoundButton(header, theme, '读取缓存', lambda: self.load(self.project.get())).pack(side='left', padx=theme.px(8))
            self.generate_button = RoundButton(header, theme, '生成 / 更新预览', self._generate, kind='primary')
            self.generate_button.pack(side='left')
            options = tk.Frame(self, bg=C['surface'])
            options.pack(fill='x', padx=theme.px(14))
            for title, variable in [('目标波长 (nm)', self.wavelength), ('模型 XY 截面 z (µm)', self.z)]:
                tk.Label(options, text=title, bg=C['surface'], fg=C['muted'], font=theme.font(9)).pack(side='left')
                ttk.Entry(options, textvariable=variable, width=10).pack(side='left', padx=(theme.px(6), theme.px(18)))
            tk.Label(self, textvariable=self.status, bg=C['surface'], fg=C['muted'], font=theme.font(9),
                     anchor='w', justify='left', wraplength=theme.px(850)).pack(fill='x', padx=theme.px(14), pady=theme.px(10))
            self.tabs = ttk.Notebook(self)
            self.tabs.pack(fill='both', expand=True, padx=theme.px(10), pady=(0, theme.px(10)))
            for kind, title in [('model', '模型示意'), ('field', '模场 / 电场'), ('spectrum', '透射谱 T'), ('parameters', '参数与说明')]:
                frame = tk.Frame(self.tabs, bg=C['surface'])
                self.tabs.add(frame, text=title)
                if kind == 'parameters':
                    self.parameters = tk.Text(frame, wrap='word', relief='flat', bg=C['field'], fg=C['text'],
                        font=theme.font(10), padx=theme.px(16), pady=theme.px(14), state='disabled')
                    self.parameters.pack(fill='both', expand=True)
                    continue
                if kind in ('field', 'spectrum'):
                    variable = self.field if kind == 'field' else self.spectrum
                    picker = ttk.Combobox(frame, textvariable=variable, state='readonly', width=60)
                    picker.pack(fill='x', padx=theme.px(8), pady=theme.px(8))
                    picker.bind('<<ComboboxSelected>>', lambda _, k=kind: self._request_render())
                    setattr(self, kind + '_picker', picker)
                canvas = tk.Canvas(frame, bg=C['field'], highlightthickness=0, height=theme.px(320))
                canvas.pack(fill='both', expand=True)
                canvas.bind('<Configure>', lambda _, k=kind: self._draw(k))
                self._canvases[kind] = canvas
        self.after(80, self._drain)
        self._clear_images()

    def destroy(self):
        self._alive = False
        self._generation += 1
        super().destroy()

    def set_running(self, running):
        self.running = bool(running)
        if not self.compact:
            self.generate_button.set_enabled(not self.running)

    def loading(self, path, message='正在读取预览缓存…'):
        if path and path != self.project.get():
            self.project.set(path)
            self.document = None
            self._clear_images()
            if not self.compact:
                self._set_parameters('正在读取所选工程的预览…')
        self.status.set(message)

    def error(self, message):
        self.status.set('预览不可用：' + str(message))

    def set_document(self, info):
        self.info = info
        self.project.set(info.get('project', self.project.get()))
        self.status.set(info.get('message', '已读取预览缓存'))
        if self.running:
            self.status.set(self.status.get() + ' · 任务运行中，显示已保存缓存')
        if not self.compact:
            self.project_picker.configure(values=info.get('projects', []))
        self.document = info.get('document') if info.get('available') else None
        if not self.document:
            self._clear_images()
            if not self.compact:
                self._set_parameters(info.get('message', '没有保存的预览结果'))
            return
        if not self.compact:
            for kind in ('field', 'spectrum'):
                entries = self.document['fields' if kind == 'field' else 'spectra']
                names = [f'{index + 1}. {entry.get("name", "未命名")}' for index, entry in enumerate(entries)]
                picker = getattr(self, kind + '_picker')
                previous = picker.get()
                picker.configure(values=names)
                picker.set(previous if previous in names else names[0] if names else '')
            lines = [f"工程：{self.document['source']['path']}",
                     '缓存生成：' + str(self.document.get('generated_utc', '')), '',
                     '场图显示记录单位下的 |E|²；波长与截面以图中标注为准。',
                     'T 保留监视器的方向符号，不等同于某个模式的耦合效率。', '']
            for item in self.document.get('parameters', []):
                value = item.get('value', '—')
                if isinstance(value, (int, float)):
                    value = f'{value:.8g}'
                if item.get('imag'):
                    value = str(value) + f" {item['imag']:+.8g}j"
                suffix = f" · λ={item['wavelength_m'] * 1e9:.5g} nm" if item.get('wavelength_m') else ''
                lines.append(f"{item.get('name', '')}：{value} {item.get('unit', '')}{suffix}")
            lines += ['', *['• ' + str(item) for item in self.document.get('warnings', [])]]
            self._set_parameters('\n'.join(lines))
        self._request_render()

    def _set_parameters(self, text):
        self.parameters.configure(state='normal')
        self.parameters.delete('1.0', 'end')
        self.parameters.insert('1.0', text)
        self.parameters.configure(state='disabled')

    def _generate(self):
        if self.generate:
            try:
                wavelength = float(self.wavelength.get()) * 1e-9
                z_m = float(self.z.get()) * 1e-6
            except ValueError:
                self.error('波长和截面位置必须是数字')
                return
            self.generate(self.project.get(), wavelength, z_m)

    def _clear_images(self):
        self._generation += 1
        self._rendered.clear()
        self._photos.clear()
        for kind in self._canvases:
            self._draw(kind)

    def _request_render(self):
        self._generation += 1
        if not self.document:
            return
        if self._busy:
            self._pending = True
            return
        self._busy = True
        self._pending = False
        generation, document = self._generation, self.document
        choices = {}
        if not self.compact:
            for kind, variable in [('field', self.field), ('spectrum', self.spectrum)]:
                try:
                    choices[kind] = int(variable.get().split('.')[0]) - 1
                except ValueError:
                    choices[kind] = 0
        def render():
            try:
                from preview_plot import render_preview
                output = {'model': render_preview('model', document['model'], (700, 350) if self.compact else (1100, 650))}
                if not self.compact:
                    for kind, index in choices.items():
                        entries = document['fields' if kind == 'field' else 'spectra']
                        if entries:
                            output[kind] = render_preview(kind, entries[max(0, min(index, len(entries) - 1))])
                self._events.put((generation, output, None))
            except Exception as error:
                self._events.put((generation, {}, str(error)))
        threading.Thread(target=render, daemon=True).start()

    def _drain(self):
        if not self._alive:
            return
        try:
            while True:
                generation, output, error = self._events.get_nowait()
                self._busy = False
                if generation == self._generation:
                    self._rendered = output
                    if error:
                        self.status.set('绘图不可用：' + error + '；请检查预览绘图依赖')
                    for kind in self._canvases:
                        self._draw(kind)
                if self._pending:
                    self._request_render()
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _draw(self, kind):
        canvas = self._canvases[kind]
        canvas.delete('all')
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        image = self._rendered.get(kind)
        if image and width > 8 and height > 8:
            try:
                from PIL import Image, ImageTk
                decoded = Image.open(io.BytesIO(image))
                decoded.thumbnail((width - 4, height - 4), Image.Resampling.LANCZOS)
                self._photos[kind] = ImageTk.PhotoImage(decoded, master=canvas)
                canvas.create_image(width / 2, height / 2, image=self._photos[kind])
                return
            except Exception:
                pass
        message = {'model': '暂无模型截面预览', 'field': '未保存可显示的二维场结果', 'spectrum': '未保存 T 光谱'}.get(kind, '暂无预览')
        canvas.create_text(width / 2, height / 2, text=message, fill=C['muted'], font=self.theme.font(9),
                           width=max(100, width - 24), justify='center')
