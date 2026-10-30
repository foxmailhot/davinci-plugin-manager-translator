from __future__ import annotations
import csv
import os
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from core import DATA, SEED, default_roots, scan, read_json, write_json, disable, restore, records, validate_dictionary
from version import VERSION, APP_NAME, REPOSITORY
import translation
import updater

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME + ' ' + VERSION)
        self.geometry('1180x790')
        self.minsize(1000, 700)
        self.configure(bg='#202124')
        self.settings = read_json(DATA / 'settings.json', {})
        if not isinstance(self.settings, dict): self.settings = {}
        self.roots = self.settings.get('roots', default_roots())
        if not isinstance(self.roots, list) or not all(isinstance(r, str) and r.strip() for r in self.roots): self.roots = default_roots()
        self.dictionary = read_json(DATA / 'dictionary.json', SEED.copy())
        try: validate_dictionary(self.dictionary)
        except ValueError: self.dictionary = SEED.copy()
        self.rows, self.visible = [], {}
        self.events = queue.Queue()
        self.busy = False
        self.catalog = None
        self.translation_result = None
        self.translation_row = None
        self.cancel_translation = threading.Event()
        self.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10), background='#252629', foreground='#d7d9dd')
        style.configure('TFrame', background='#252629')
        style.configure('TLabel', background='#252629', foreground='#d7d9dd')
        style.configure('TButton', padding=(12, 7), background='#3b3d42', foreground='#e6e6e6', bordercolor='#505258')
        style.map('TButton',background=[('active','#51545b'),('pressed','#32353a')])
        style.configure('Accent.TButton',background='#ae5d28',foreground='white')
        style.map('Accent.TButton',background=[('active','#c67539')])
        style.configure('TEntry', fieldbackground='#1c1d20', foreground='#eeeeee', insertcolor='white')
        style.configure('TCombobox', fieldbackground='#1c1d20', foreground='#eeeeee', arrowcolor='#cccccc')
        style.map('TCombobox',fieldbackground=[('readonly','#303237')],foreground=[('readonly','#eeeeee')],selectbackground=[('readonly','#303237')])
        style.configure('TNotebook', background='#252629',borderwidth=0)
        style.configure('TNotebook.Tab', background='#303237', foreground='#b7b9bd',padding=(10,8))
        style.map('TNotebook.Tab', background=[('selected','#45474d')],foreground=[('selected','#ffffff')])
        style.configure('Treeview', rowheight=32, background='#202124', fieldbackground='#202124',foreground='#d7d9dd',bordercolor='#44464b')
        style.map('Treeview',background=[('selected','#61503c')],foreground=[('selected','#ffffff')])
        style.configure('Treeview.Heading', background='#34363b',foreground='#dddddd', padding=8, font=('Microsoft YaHei UI', 10, 'bold'))
        self.option_add('*TCombobox*Listbox.background','#303237'); self.option_add('*TCombobox*Listbox.foreground','#eeeeee')
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill='both', expand=True)
        heading=ttk.Frame(outer); heading.pack(fill='x')
        ttk.Label(heading, text=APP_NAME, font=('Microsoft YaHei UI', 22, 'bold')).pack(side='left')
        ttk.Button(heading,text='检查更新',command=self.check_update).pack(side='right')
        ttk.Label(outer, text=f'OFX 插件管理  /  一键翻译  /  手动更新     v{VERSION}', foreground='#a5a8ae').pack(anchor='w', pady=(5, 16))
        self.summary = tk.StringVar(value='准备扫描…')
        ttk.Label(outer, textvariable=self.summary, font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w', pady=(0, 12))
        tabs = ttk.Notebook(outer)
        self.tabs = tabs
        tabs.pack(fill='both', expand=True)
        plugins, dictionary, backups = (ttk.Frame(tabs, padding=14) for _ in range(3))
        tabs.add(plugins, text='  插件清单  ')
        self.translation_tab=ttk.Frame(tabs,padding=14)
        tabs.add(self.translation_tab,text='  插件翻译  ')
        tabs.add(dictionary, text='  汉化词库  ')
        tabs.add(backups, text='  备份与恢复  ')
        bar = ttk.Frame(plugins); bar.pack(fill='x', pady=(0, 10))
        self.query = tk.StringVar()
        ttk.Label(bar, text='搜索').pack(side='left', padx=(0, 8))
        ttk.Entry(bar, textvariable=self.query, width=27).pack(side='left')
        self.query.trace_add('write', lambda *_: self.render())
        self.filter = tk.StringVar(value='全部状态')
        combo = ttk.Combobox(bar, textvariable=self.filter, values=['全部状态', '已启用', '已禁用'], state='readonly', width=10)
        combo.pack(side='left', padx=8); combo.bind('<<ComboboxSelected>>', lambda _: self.render())
        for label, command in [('扫描', self.reload), ('扫描目录', self.root_dialog), ('导出清单', self.export)]:
            ttk.Button(bar, text=label, command=command).pack(side='left', padx=3)
        self.tree = self.make_tree(plugins, [('name','OFX 模块',210), ('vendor','厂商 / 目录',110), ('status','状态',80), ('size','大小',90), ('path','文件位置',380)])
        self.tree.bind('<<TreeviewSelect>>', self.selection)
        self.detail = tk.StringVar(value='选择一个模块查看详情。一个 OFX 模块可能包含多个效果。')
        ttk.Label(plugins, textvariable=self.detail, wraplength=1040).pack(anchor='w', pady=12)
        actions = ttk.Frame(plugins); actions.pack(fill='x')
        ttk.Button(actions, text='打开所在目录', command=self.open_folder).pack(side='left')
        ttk.Button(actions, text='一键翻译所选插件',style='Accent.TButton',command=self.translate_selected).pack(side='left',padx=8)
        ttk.Button(actions, text='备份并禁用所选模块', command=self.disable_selected).pack(side='left', padx=8)
        ttk.Label(plugins, text='禁用或应用翻译影响所有加载此 OFX 的软件；操作前请先退出相关宿主，重启后生效。', foreground='#c5a478', wraplength=1040).pack(anchor='w', pady=(12,0))
        ttk.Label(dictionary, text='中文词库工作台', font=('Microsoft YaHei UI', 14, 'bold')).pack(anchor='w')
        ttk.Label(dictionary, text='手动校对的译文优先于机器翻译。编辑后，在插件翻译页重新翻译并应用，以更新界面译文。', wraplength=1030).pack(anchor='w', pady=8)
        db = ttk.Frame(dictionary); db.pack(fill='x', pady=6)
        self.en, self.zh = tk.StringVar(), tk.StringVar()
        ttk.Label(db, text='英文').pack(side='left'); ttk.Entry(db, textvariable=self.en, width=32).pack(side='left', padx=6)
        ttk.Label(db, text='中文').pack(side='left'); ttk.Entry(db, textvariable=self.zh, width=30).pack(side='left', padx=6)
        ttk.Button(db, text='保存词条', command=self.save_word).pack(side='left', padx=4)
        self.words = self.make_tree(dictionary, [('en','英文原文',400), ('zh','中文译文',480)])
        self.words.bind('<<TreeviewSelect>>', self.pick_word)
        db2 = ttk.Frame(dictionary); db2.pack(fill='x', pady=10)
        for label, command in [('导入 JSON 词库', self.import_words), ('导出词库', self.export_words), ('删除所选词条', self.delete_word)]:
            ttk.Button(db2, text=label, command=command).pack(side='left', padx=(0,8))
        ttk.Label(backups, text='禁用前自动复制模块并校验 SHA-256。恢复时拒绝覆盖已有或发生变化的文件。', wraplength=1030).pack(anchor='w', pady=(0,10))
        self.backups = self.make_tree(backups, [('created','备份时间',165), ('state','记录状态',95), ('original','原始文件',630)])
        bb = ttk.Frame(backups); bb.pack(fill='x', pady=10)
        ttk.Button(bb, text='恢复所选备份', command=self.restore_selected).pack(side='left')
        ttk.Button(bb, text='打开本地数据目录', command=lambda: self.open_path(DATA)).pack(side='left', padx=8)
        self.status = tk.StringVar(value=f'数据保存在 {DATA}')
        ttk.Label(outer, textvariable=self.status, wraplength=1100, foreground='#a5a8ae').pack(anchor='w', pady=(12,0))
        self.build_translation_tab()
        self.render_words(); self.render_backups()
        self.poll_task=self.after(100, self.poll)
        self.reload()

    def destroy(self):
        task=getattr(self,'poll_task',None)
        if task:
            try: self.after_cancel(task)
            except tk.TclError: pass
        super().destroy()

    def close(self):
        if self.busy:
            messagebox.showinfo('正在处理', '正在扫描或处理插件，请等待完成后退出。')
            return
        self.destroy()

    def make_tree(self, parent, columns):
        frame = ttk.Frame(parent); frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', selectmode='browse', height=8)
        for key, title, width in columns:
            tree.heading(key, text=title); tree.column(key, width=width, minwidth=60)
        vs = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        hs = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0,column=0,sticky='nsew'); vs.grid(row=0,column=1,sticky='ns'); hs.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1); frame.columnconfigure(0,weight=1)
        return tree

    def run_job(self, fn, callback):
        if self.busy:
            messagebox.showinfo('正在处理', '请等待当前操作完成。'); return
        self.busy = True; self.status.set('正在处理，请稍候…')
        def work():
            try: self.events.put((callback, fn(), None))
            except Exception as e: self.events.put((callback, None, e))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                callback, value, error = self.events.get_nowait()
                self.busy = False
                if error:
                    text = str(error)
                    if isinstance(error, PermissionError): text += '\n系统目录需要写入权限，请退出后右键本程序，以管理员身份运行。'
                    self.status.set('操作未完成'); messagebox.showerror('操作未完成', text)
                elif callback is None:
                    self.busy=True; self.status.set(value); self.translation_status.set(value)
                else: callback(value)
        except queue.Empty: pass
        self.poll_task=self.after(100, self.poll)

    def reload(self):
        roots = list(self.roots)
        self.run_job(lambda: scan(roots), self.scanned)

    def scanned(self, result):
        self.rows, errors = result
        self.render(); self.render_backups()
        self.status.set('扫描完成。' + (' 部分目录未扫描：' + '；'.join(errors) if errors else '未加载或执行插件代码。'))

    def render(self):
        self.tree.delete(*self.tree.get_children()); self.visible = {}
        query = self.query.get().casefold()
        for i, row in enumerate(self.rows):
            if query not in (row['name'] + row['vendor'] + row['path']).casefold(): continue
            status = '已禁用' if row['disabled'] else '已启用'
            if self.filter.get() not in ('全部状态', status): continue
            key = str(i); self.visible[key] = row
            self.tree.insert('', 'end', iid=key, values=(row['name'], row['vendor'], status, f"{row['size']/1048576:.1f} MB", row['path']))
        disabled = sum(r['disabled'] for r in self.rows)
        self.summary.set(f'共 {len(self.rows)} 个模块    已启用 {len(self.rows)-disabled}    已禁用 {disabled}    当前显示 {len(self.visible)}    词库 {len(self.dictionary)} 条')

    def selected(self):
        selection = self.tree.selection()
        return self.visible.get(selection[0]) if selection else None

    def selection(self, *_):
        row = self.selected()
        if row:
            state=read_json(Path(row['path']+translation.STATE),{})
            text=f"已安装实验适配层，{state.get('translated',0)} 条译文；宿主显示需验证" if state else '未安装翻译适配层'
            self.detail.set(f"模块：{row['name']}  |  修改时间：{row['modified']}\n插件包：{row['bundle']}\n翻译状态：{text}")

    def open_path(self, path):
        try:
            Path(path).mkdir(parents=True, exist_ok=True) if Path(path) == DATA else None
            os.startfile(str(path))
        except OSError as e: messagebox.showerror('无法打开', str(e))

    def open_folder(self):
        row = self.selected()
        if row: self.open_path(Path(row['path']).parent)

    def disable_selected(self):
        row = self.selected()
        if not row: messagebox.showinfo('选择模块', '请先选择一个模块。'); return
        if row['disabled']: messagebox.showinfo('已禁用', '请到“备份与恢复”中恢复此模块。'); return
        if not messagebox.askyesno('禁用模块', f"将备份并禁用 {row['name']}。\n此模块包含的所有效果将不可用，其他 OFX 宿主也会受到影响。\n请先关闭使用该插件的软件。是否继续？"): return
        self.run_job(lambda: disable(row), lambda _: self.reload())

    def render_backups(self):
        self.backups.delete(*self.backups.get_children()); self.backup_map = {}
        for i, (path, rec) in enumerate(records()):
            if not rec: continue
            key = str(i); self.backup_map[key] = path
            state = {'prepared':'待核对', 'disabled':'已禁用', 'restored':'已恢复'}.get(rec.get('state'), '未知')
            self.backups.insert('', 'end', iid=key, values=(rec.get('created'), state, rec.get('original')))

    def restore_selected(self):
        selected = self.backups.selection()
        if not selected: messagebox.showinfo('选择备份', '请选择一条备份记录。'); return
        path = self.backup_map[selected[0]]
        if messagebox.askyesno('恢复模块', '请先关闭使用该插件的软件。现在恢复所选模块？'):
            self.run_job(lambda: restore(path), lambda _: self.reload())

    def root_dialog(self):
        win = tk.Toplevel(self); win.title('扫描目录'); win.geometry('800x330'); win.transient(self)
        ttk.Label(win, text='管理扫描目录（支持 OFX_PLUGIN_PATH；可手动添加自定义位置）', padding=12).pack(anchor='w')
        listing = tk.Listbox(win, font=('Microsoft YaHei UI',10),bg='#202124',fg='#dddddd',selectbackground='#61503c'); listing.pack(fill='both',expand=True,padx=12)
        for root in self.roots: listing.insert('end',root)
        bar = ttk.Frame(win,padding=12); bar.pack(fill='x')
        def add():
            root = filedialog.askdirectory(parent=win)
            if root and root not in listing.get(0,'end'): listing.insert('end',root)
        def remove():
            for i in reversed(listing.curselection()): listing.delete(i)
        def save():
            if self.busy: messagebox.showinfo('正在处理','请等待当前操作完成。',parent=win); return
            self.roots = list(listing.get(0,'end')); self.settings['roots'] = self.roots
            try: write_json(DATA/'settings.json',self.settings)
            except OSError as e: messagebox.showerror('无法保存',str(e),parent=win); return
            win.destroy(); self.reload()
        for text, command in [('添加目录',add),('移除所选',remove),('保存并扫描',save)]: ttk.Button(bar,text=text,command=command).pack(side='left',padx=4)

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv',initialfile='达芬奇OFX插件清单.csv',filetypes=[('CSV','*.csv')])
        if not path: return
        try:
            with open(path,'w',newline='',encoding='utf-8-sig') as f:
                writer = csv.writer(f); writer.writerow(['模块','厂商/目录','状态','字节','文件位置','修改时间'])
                for r in self.visible.values(): writer.writerow([r['name'],r['vendor'],'已禁用' if r['disabled'] else '已启用',r['size'],r['path'],r['modified']])
            self.status.set(f'已导出 {len(self.visible)} 个模块：{path}')
        except OSError as e: messagebox.showerror('导出失败',str(e))

    def render_words(self):
        self.words.delete(*self.words.get_children())
        for en, zh in sorted(self.dictionary.items()): self.words.insert('','end',values=(en,zh))
        self.render()

    def pick_word(self,*_):
        selected = self.words.selection()
        if selected:
            en, zh = self.words.item(selected[0],'values'); self.en.set(en); self.zh.set(zh)

    def persist_words(self, value):
        try:
            validate_dictionary(value); write_json(DATA/'dictionary.json',value)
            self.dictionary = value; self.render_words(); self.status.set(f'词库已保存，共 {len(value)} 条；重新翻译并应用后更新插件。')
        except (ValueError,OSError) as e: messagebox.showerror('保存失败',str(e))

    def save_word(self):
        value = dict(self.dictionary); value[self.en.get().strip()] = self.zh.get().strip(); self.persist_words(value)

    def delete_word(self):
        selected = self.words.selection()
        if selected:
            value = dict(self.dictionary); value.pop(self.words.item(selected[0],'values')[0],None); self.persist_words(value)

    def import_words(self):
        path = filedialog.askopenfilename(filetypes=[('JSON 词库','*.json')])
        if not path: return
        try:
            import json
            incoming = validate_dictionary(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            conflicts = sum(k in self.dictionary and self.dictionary[k] != v for k,v in incoming.items())
            if conflicts and not messagebox.askyesno('覆盖词条',f'有 {conflicts} 条已有译文将被替换。继续导入？'): return
            value = dict(self.dictionary); value.update(incoming); self.persist_words(value)
        except (ValueError,OSError) as e: messagebox.showerror('导入失败',str(e))

    def export_words(self):
        path = filedialog.asksaveasfilename(defaultextension='.json',initialfile='插件汉化词库.json',filetypes=[('JSON','*.json')])
        if path:
            try: write_json(path,self.dictionary); self.status.set('词库已导出。')
            except OSError as e: messagebox.showerror('导出失败',str(e))

    def build_translation_tab(self):
        frame=self.translation_tab
        self.translation_title=tk.StringVar(value='先在插件清单选择模块，点击“一键翻译所选插件”')
        ttk.Label(frame,textvariable=self.translation_title,font=('Microsoft YaHei UI',13,'bold'),wraplength=1020).pack(anchor='w')
        ttk.Label(frame,text='每包 1000 条，按接口限制拆分请求；发送下一包的同时核对上一包。异常按编号定位并重试，候选数不等于界面覆盖率。',wraplength=1020,foreground='#a5a8ae').pack(anchor='w',pady=7)
        row=ttk.Frame(frame); row.pack(fill='x',pady=5)
        ttk.Label(row,text='翻译服务').pack(side='left')
        self.provider=tk.StringVar(value=self.settings.get('provider',translation.PROVIDERS[0]))
        ttk.Combobox(row,textvariable=self.provider,values=translation.PROVIDERS,state='readonly',width=38).pack(side='left',padx=8)
        ttk.Label(row,text='密钥（仅本次会话）').pack(side='left')
        self.api_key=tk.StringVar(); ttk.Entry(row,textvariable=self.api_key,show='•',width=23).pack(side='left',padx=8)
        row2=ttk.Frame(frame); row2.pack(fill='x',pady=(0,7))
        ttk.Label(row2,text='LibreTranslate 地址').pack(side='left')
        self.endpoint=tk.StringVar(value=self.settings.get('endpoint','http://127.0.0.1:5000'))
        ttk.Entry(row2,textvariable=self.endpoint,width=39).pack(side='left',padx=8)
        ttk.Button(row2,text='测试接口',command=self.test_provider).pack(side='left',padx=5)
        ttk.Button(row2,text='停止翻译',command=self.cancel_translation.set).pack(side='left',padx=5)
        ttk.Label(frame,text='在线翻译仅发送候选英文文字。MyMemory 免密钥、限额；Google 网页接口非官方、可能失效；Google Cloud 需自备密钥并自行管理账单。',wraplength=1020,foreground='#c5a478').pack(anchor='w',pady=(0,8))
        self.translation_status=tk.StringVar(value='等待选择插件')
        ttk.Label(frame,textvariable=self.translation_status,wraplength=1030).pack(anchor='w',pady=(0,7))
        self.preview=self.make_tree(frame,[('en','提取的英文候选文字',370),('zh','中文译文',370),('check','核对结果 / 原文行号',200)])
        self.preview.configure(height=4)
        buttons=ttk.Frame(frame); buttons.pack(fill='x',pady=(10,0))
        for text,cmd in [('继续 / 重新翻译',self.translate_current),('应用至插件（实验）',self.apply_translation),('恢复原版插件',self.restore_translation),('导出译文',self.export_translation),('打开批次报告',self.open_batch_report)]:
            ttk.Button(buttons,text=text,command=cmd).pack(side='left',padx=(0,7))

    def progress(self,text):
        self.events.put((None,text,None))

    def provider_config(self):
        provider=self.provider.get(); endpoint=self.endpoint.get().strip()
        if provider not in translation.PROVIDERS: raise ValueError('请选择翻译服务。')
        self.settings.update(provider=provider,endpoint=endpoint)
        write_json(DATA/'settings.json',self.settings)
        return provider,self.api_key.get(),endpoint

    def test_provider(self):
        if self.busy: return
        try: provider,key,endpoint=self.provider_config()
        except (ValueError,OSError) as e: messagebox.showerror('设置错误',str(e)); return
        if provider==translation.PROVIDERS[-1]: messagebox.showinfo('本地词库','本地模式无需网络，优先使用内置和自定义词库。'); return
        self.run_job(lambda:translation.translate_one('Brightness',provider,key,endpoint),lambda value:messagebox.showinfo('接口可用','Brightness → '+value))

    def translate_selected(self):
        if self.busy: return
        row=self.selected()
        if not row: messagebox.showinfo('选择插件','请先在插件清单中选择模块。'); return
        self.translation_row=dict(row); self.catalog=None; self.translation_result=None
        self.tabs.select(self.translation_tab)
        self.translation_title.set('翻译模块：'+row['name'])
        self.preview.delete(*self.preview.get_children())
        self.translation_status.set('正在读取模块及关联资源，提取英文候选文字…')
        self.run_job(lambda:translation.extract(row),self.extracted)

    def extracted(self,catalog):
        self.catalog=catalog
        self.translate_current()

    def translate_current(self):
        if self.busy: return
        if not self.catalog: messagebox.showinfo('选择插件','请从插件清单选择模块并点击一键翻译。'); return
        try: provider,key,endpoint=self.provider_config()
        except (ValueError,OSError) as e: messagebox.showerror('设置错误',str(e)); return
        self.cancel_translation.clear()
        catalog=self.catalog; dictionary=dict(self.dictionary)
        self.run_job(lambda:translation.translate_catalog(catalog,dictionary,provider,DATA,key,endpoint,self.progress,self.cancel_translation),self.translated)

    def translated(self,result):
        self.translation_result=result
        self.preview.delete(*self.preview.get_children())
        problems={r['source']:r for r in result.get('unmatched_records',[])}
        from batch_translation import ISSUE_LABELS
        for index,text in enumerate(result['texts'],1):
            problem=problems.get(text,{})
            reason=ISSUE_LABELS.get(problem.get('reason'),'待核对')
            state=f'已匹配 / 行 {index}' if text in result['translations'] else f'{reason} / 行 {problem.get("line",index)}'
            self.preview.insert('','end',values=(text,result['translations'].get(text,'待翻译'),state))
        count=len(result['translations']); total=len(result['texts'])
        text=f'候选译文 {count}/{total}；待翻译 {result["remaining"]}；核对 {result.get("verified_packages",0)} 包。异常位置与返回原文已存入批次报告。'
        if result.get('error'): text+=' '+result['error']
        self.translation_status.set(text); self.status.set(text)

    def open_batch_report(self):
        if self.translation_result and self.translation_result.get('job_folder'):
            self.open_path(Path(self.translation_result['job_folder']))
        else:
            self.open_path(DATA/'batch-jobs') if (DATA/'batch-jobs').exists() else messagebox.showinfo('批次报告','完成一次翻译后可在此查看打包文件、返回原文及核对报告。')

    def apply_translation(self):
        if self.busy: return
        if not self.translation_result or not self.translation_result['translations']: messagebox.showinfo('没有译文','请先完成提取和翻译。'); return
        if not messagebox.askyesno('应用实验翻译适配层',f"模块：{self.translation_row['name']}\n将应用 {len(self.translation_result['translations'])} 条候选译文。\n\n适配层尚未完成真实 BCC 的达芬奇兼容性验证，可能导致插件无法加载。会备份原版，可恢复。它影响所有加载此模块的 OFX 宿主，不翻译独立编辑器。\n\n请退出所有相关宿主后继续，应用后重启达芬奇。现在应用？"): return
        row=dict(self.translation_row); result=self.translation_result
        self.run_job(lambda:translation.apply_adapter(row,result,DATA),lambda _:self.applied())

    def applied(self):
        messagebox.showinfo('已应用适配层','适配层已安装。请重新打开达芬奇验证文字及效果是否正常；有异常可在此页恢复原版。')
        self.reload()

    def restore_translation(self):
        if self.busy: return
        row=self.translation_row or self.selected()
        if not row: messagebox.showinfo('选择插件','请先选择插件。'); return
        if messagebox.askyesno('恢复原版','请先退出所有相关宿主。现在移除翻译适配层并恢复原版模块？'):
            self.run_job(lambda:translation.restore_adapter(row),lambda _:self.reload())

    def export_translation(self):
        if not self.translation_result: return
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='插件译文.json',filetypes=[('JSON','*.json')])
        if path:
            try: write_json(path,self.translation_result['translations']); self.status.set('插件译文已导出。')
            except OSError as e: messagebox.showerror('导出失败',str(e))

    def check_update(self):
        self.run_job(updater.check_latest,self.update_checked)

    def update_checked(self,release):
        if not release:
            self.status.set('当前已是最新正式版本。'); messagebox.showinfo('检查更新',f'当前版本 {VERSION} 已是最新正式版本。'); return
        if messagebox.askyesno('发现新版本',f"发现 {release['version']}，当前 {VERSION}。\n\n{release.get('notes','')[:700]}\n\n下载并校验后打开新版本？旧版会保留，本地词库与备份继续共用。"):
            self.run_job(lambda:updater.stage_update(release,DATA),self.update_downloaded)

    def update_downloaded(self,executable):
        try: updater.launch_update(executable)
        except OSError as e: messagebox.showerror('启动失败',f'新版本已下载至 {executable}\n{e}'); return
        self.destroy()

if __name__ == '__main__':
    App().mainloop()
