"""
firestorm_gui.py —— regAcct 的原生窗口控制面板（tkinter + ttk）

设计约束（踩过的坑，务必遵守）：
1. 工作线程**绝对不能碰任何 widget，也不能调 root.after()** ——
   after() 内部会 createcommand，非主线程调用会抛
   "RuntimeError: main thread is not in main loop"。
   正确做法：后台线程只 self.q.put(...)，
   由主线程的 _drain 定时排空。所有 after() 调用点必须只在主线程。
2. 自检不能只 update() 一次 —— 状态是后台跑完再回主线程的，
   要一边推事件循环一边等。
3. 业务逻辑一律 subprocess 调 register.py，**不在这里重新实现一遍注册**。
   两处实现迟早不一致，这是这类项目最常见的腐化方式。
"""
import os
import sys
import queue
import shutil
import subprocess
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config_edit as CE           # noqa: E402  (纯逻辑，无 UI 依赖，两边都能 import)

REGISTER_PY = os.path.join(BASE, "register.py")
ACCOUNTS_TXT = os.path.join(BASE, "accounts.txt")

# 允许留空的配置项（选填）
OPTIONAL_KEYS = {"proxy"}

# 主题字体：Windows 上 vista 好看，中文用雅黑
FONT = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 9, "bold")


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Firestorm WoW 自动注册")
        self.root.geometry("940x660")
        self.root.minsize(860, 560)
        self.root.configure(bg="#f0f0f0")

        # ---- 线程通信：后台线程只往这里塞数据 ----
        self.q = queue.Queue()
        self.proc = None                 # 当前跑的 register.py 进程
        self.stop_flag = False
        self.vars = {}
        self.tree = None

        self._build_style()
        self._build_ui()
        self._load_into_form()

        # 唯一的 after 消费者：主线程定时排空队列
        self.root.after(80, self._drain)

    # ---------------------------------------------------------------- UI
    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("TLabel", font=FONT)
        style.configure("TButton", font=FONT)
        style.configure("TCheckbutton", font=FONT)
        style.configure("TNotebook", font=FONT)
        style.configure("Treeview", font=FONT, rowheight=22)
        style.configure("Headings.TLabel", font=FONT_BOLD)

    def _build_ui(self):
        pad = 10

        # ---------- 顶部标题 ----------
        top = ttk.Frame(self.root, padding=(pad, pad, pad, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Firestorm WoW 账号自动注册",
                  font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        ttk.Label(top, text="配置在这里改，注册请点「开始注册」",
                  font=FONT, foreground="#666").pack(side="left", padx=12)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=pad, pady=(8, 0))

        # ---------- 配置页 ----------
        cfg_tab = ttk.Frame(nb, padding=pad)
        nb.add(cfg_tab, text="  基本配置  ")

        form = ttk.Frame(cfg_tab)
        form.pack(fill="x")
        r = 0
        for key, label, typ, hint in CE.FIELDS:
            ttk.Label(form, text=label, font=FONT).grid(
                row=r, column=0, sticky="w", pady=4, padx=(0, 10))

            if typ == "bool":
                var = tk.BooleanVar()
                cb = ttk.Checkbutton(form, text="启用", variable=var)
                cb.grid(row=r, column=1, sticky="w")
                self.vars[key] = var
            else:
                var = tk.StringVar()
                entry = ttk.Entry(form, textvariable=var, width=30, font=FONT)
                entry.grid(row=r, column=1, sticky="w")
                self.vars[key] = (var, typ)

            ttk.Label(form, text=hint, font=FONT, foreground="#888").grid(
                row=r, column=2, sticky="w", padx=(10, 0))
            r += 1

        btns = ttk.Frame(cfg_tab)
        btns.pack(fill="x", pady=(12, 0))
        self.btn_save = ttk.Button(btns, text="保存配置", command=self.on_save)
        self.btn_save.pack(side="left")
        self.btn_reload = ttk.Button(btns, text="重新载入", command=self.on_reload)
        self.btn_reload.pack(side="left", padx=6)
        self.btn_reset = ttk.Button(btns, text="恢复默认", command=self.on_reset)
        self.btn_reset.pack(side="left")

        self.lbl_cfg_status = ttk.Label(cfg_tab, text="", font=FONT, foreground="#0a7a0a")
        self.lbl_cfg_status.pack(fill="x", pady=(6, 0))

        # ---------- 运行页 ----------
        run_tab = ttk.Frame(nb, padding=pad)
        nb.add(run_tab, text="  运行  ")

        ctrl = ttk.Frame(run_tab)
        ctrl.pack(fill="x")
        self.btn_start = ttk.Button(ctrl, text="开始注册", command=self.on_start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(ctrl, text="停止", command=self.on_stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_open_dir = ttk.Button(ctrl, text="打开目录",
                                       command=self.on_open_dir)
        self.btn_open_dir.pack(side="left")

        self.lbl_run = ttk.Label(run_tab, text="状态：空闲",
                                 font=FONT_BOLD, foreground="#0a7a0a")
        self.lbl_run.pack(fill="x", pady=(10, 6))

        # ---------- 账号表格 ----------
        ttk.Label(run_tab, text="已注册账号", font=FONT_BOLD).pack(
            anchor="w", pady=(4, 4))

        table_box = ttk.Frame(run_tab)
        table_box.pack(fill="both", expand=True)

        cols = ("idx", "username", "password", "email", "time")
        heads = ("#", "用户名", "密码", "邮箱", "注册时间")
        widths = (40, 118, 118, 240, 158)
        self.tree = ttk.Treeview(table_box, columns=cols, show="headings",
                                 selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w",
                             stretch=(c == "email"))
        vsb = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # ---------- 日志 ----------
        ttk.Label(run_tab, text="运行日志", font=FONT_BOLD).pack(
            anchor="w", pady=(10, 4))
        log_box = ttk.Frame(run_tab)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(log_box, height=9, font=("Consolas", 9),
                           wrap="word", bg="#1e1e1e", fg="#d4d4d4",
                           insertbackground="#d4d4d4", relief="flat")
        ls = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=ls.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        ls.pack(side="right", fill="y")

    # ------------------------------------------------------- 表单 <-> 配置
    def _load_into_form(self):
        cfg = CE.read_config()
        for key, label, typ, hint in CE.FIELDS:
            val = cfg.get(key, CE.DEFAULTS.get(key))
            v = self.vars[key]
            if typ == "bool":
                v.set(bool(val))
            else:
                v[0].set("" if val is None else str(val))

    def _collect(self):
        """把表单读成 dict，做类型校验。非法值直接抛给调用方弹窗。"""
        out = {}
        for key, label, typ, hint in CE.FIELDS:
            v = self.vars[key]
            if typ == "bool":
                out[key] = bool(v.get())
            else:
                raw, t = v
                s = raw.get().strip()
                # 选填项允许为空
                if not s and key in OPTIONAL_KEYS:
                    out[key] = ""
                    continue
                if not s:
                    raise ValueError(f"「{label}」不能为空")
                if t == "int":
                    try:
                        out[key] = int(s)
                    except ValueError:
                        raise ValueError(f"「{label}」必须是整数，当前填的是「{s}」")
                else:
                    out[key] = s
        return out

    # ------------------------------------------------------------- 回调
    def on_save(self):
        try:
            values = self._collect()
            changed = CE.apply_all(values)
        except Exception as e:
            messagebox.showerror("保存失败", str(e), parent=self.root)
            return
        if changed:
            self.lbl_cfg_status.configure(
                text=f"[OK] 已保存 {len(changed)} 项：{', '.join(changed)}",
                foreground="#0a7a0a")
        else:
            self.lbl_cfg_status.configure(text="[i] 配置没有变化", foreground="#666")

    def on_reload(self):
        self._load_into_form()
        self.lbl_cfg_status.configure(text="[i] 已从 config.json 重新载入",
                                      foreground="#666")

    def on_reset(self):
        if not messagebox.askyesno("恢复默认",
                                   "把表单恢复为默认值？\n"
                                   "（不会立刻写文件，点「保存配置」才生效）",
                                   parent=self.root):
            return
        for key, label, typ, hint in CE.FIELDS:
            dv = CE.DEFAULTS.get(key)
            v = self.vars[key]
            if typ == "bool":
                v.set(bool(dv))
            else:
                v[0].set(str(dv))
        self.lbl_cfg_status.configure(text="[i] 已填入默认值，点「保存配置」生效",
                                      foreground="#666")

    def on_open_dir(self):
        try:
            os.startfile(BASE)
        except Exception as e:
            messagebox.showerror("无法打开目录", str(e), parent=self.root)

    def _set_running(self, running):
        """ttk 用 state()，tk 老控件用 configure()，这里统一。"""
        self.btn_start.state(["disabled"] if running else ["!disabled"])
        self.btn_stop.state(["!disabled"] if running else ["disabled"])
        self.btn_save.state(["disabled"] if running else ["!disabled"])
        self.btn_reset.state(["disabled"] if running else ["!disabled"])

    def on_start(self):
        if self.proc and self.proc.poll() is None:
            return
        try:
            self.on_save()
        except Exception:
            return
        if "已保存" not in self.lbl_cfg_status.cget("text"):
            # 有非法值，on_save 已经弹过窗，直接中止
            if "[OK]" not in self.lbl_cfg_status.cget("text"):
                return

        self.stop_flag = False
        self._clear_log()
        self._append_log("-" * 56)
        self._append_log(f"启动: {sys.executable} register.py")
        self.lbl_run.configure(text="状态：运行中…", foreground="#c05000")
        self._set_running(True)
        threading.Thread(target=self._worker_run, daemon=True).start()

    def on_stop(self):
        if self.proc and self.proc.poll() is None:
            self._append_log("[!] 正在停止…（浏览器会保留）")
            self.stop_flag = True
            try:
                self.proc.terminate()
            except Exception:
                pass
        self._set_running(False)
        self.lbl_run.configure(text="状态：已停止", foreground="#a00000")

    # ------------------------------------------------- 后台线程（只 put）
    def _worker_run(self):
        """后台线程：跑 register.py，把输出丢进队列。绝不碰 widget。"""
        try:
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            # 告诉 register.py：本进程由 GUI 托管，
            # 结束保活时不要卡在 input() 上等键盘
            env["REGACCT_MANAGED_BY_GUI"] = "1"
            self.proc = subprocess.Popen(
                [sys.executable, "-u", REGISTER_PY],
                cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, env=env, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
            )
            self.q.put(("log", f"[PID {self.proc.pid}] 进程已启动"))
            for line in self.proc.stdout:
                self.q.put(("log", line.rstrip("\n")))

            rc = self.proc.wait()
            self.q.put(("done", rc))
        except Exception:
            self.q.put(("error", traceback.format_exc()))

    def _worker_snapshot(self):
        """后台线程：读账号表。"""
        try:
            recs, _, _, _ = CE_read_accounts()
            self.q.put(("rows", recs))
        except Exception:
            self.q.put(("error", traceback.format_exc()))

    # ------------------------------------------- 主线程：唯一 after 消费者
    def _drain(self):
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle(item)
            except Exception:
                self._append_log("[!] UI 处理异常: " + traceback.format_exc())
        self.root.after(80, self._drain)

    def _handle(self, item):
        kind = item[0]
        if kind == "log":
            self._append_log(item[1])
        elif kind == "rows":
            self._fill_table(item[1])
        elif kind == "done":
            self._on_process_done(item[1])
        elif kind == "error":
            self._append_log("[!] " + item[1])
            self.lbl_run.configure(text="状态：异常", foreground="#a00000")
            self._set_running(False)

    def _on_process_done(self, rc):
        self._set_running(False)
        if self.stop_flag:
            self.lbl_run.configure(text="状态：已停止", foreground="#a00000")
        elif rc == 0:
            self.lbl_run.configure(text="状态：正常结束", foreground="#0a7a0a")
        else:
            self.lbl_run.configure(text=f"状态：异常退出 (code {rc})",
                                   foreground="#a00000")
        self._append_log(f"[进程结束] 退出码 {rc}")
        self._append_log("[i] 正在刷新账号列表…")
        threading.Thread(target=self._worker_snapshot, daemon=True).start()

    # ------------------------------------------------------------ 小组件
    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _fill_table(self, recs):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(recs, 1):
            self.tree.insert("", "end", iid=str(i), values=(
                i, r["username"], r["password"], r["email"], r.get("time", "-")))
        self.lbl_run.configure(
            text=f"状态：空闲（已注册 {len(recs)} 个账号）", foreground="#0a7a0a")

    def refresh_accounts(self):
        threading.Thread(target=self._worker_snapshot, daemon=True).start()


def CE_read_accounts():
    """延迟 import register 里的解析函数（它 import DrissionPage，较重）。"""
    import register
    return register.read_accounts_history()


# ------------------------------------------------------------------ 自检
def style_icon(root):
    """tkinter 没有内置 ico，用 PhotoImage 画个简单图标。"""
    size = 32
    img = tk.PhotoImage(width=size, height=size)
    for y in range(size):
        for x in range(size):
            dx, dy = x - size / 2, y - size / 2
            if dx * dx + dy * dy < (size / 2 - 1) ** 2:
                img.put("#2d7ff9", to=(x, y))
            elif abs(dx) < 7 and abs(dy) < 2:
                img.put("#ffffff", to=(x, y))
            elif abs(dy) < 7 and abs(dx) < 2:
                img.put("#ffffff", to=(x, y))
    root.iconphoto(True, img)
    root._icon_ref = img          # 防止被 GC


def self_test():
    """
    构建界面 + 渲染真实数据，验证渲染链路通不通。
    不能只 update() 一次 —— 后台线程的结果还没回来，会误报"表格 0 行"。
    """
    print("[self-test] 构建界面…")
    root = tk.Tk()
    root.withdraw()                      # 自检时不弹窗
    app = App(root)

    print("[self-test] 触发账号表读取…")
    app.refresh_accounts()

    deadline = time.time() + 12
    rows = 0
    while time.time() < deadline:
        root.update()                    # 推事件循环
        rows = len(app.tree.get_children())
        if rows:
            break
        time.sleep(0.05)

    print(f"[self-test] 表格行数 = {rows}")
    print(f"[self-test] 状态条文案 = {app.lbl_run.cget('text')!r}")
    print(f"[self-test] 配置状态   = {app.lbl_cfg_status.cget('text')!r}")

    # 表单回填检查
    cfg = CE.read_config()
    for key, label, typ, hint in CE.FIELDS:
        v = app.vars[key]
        got = v.get() if typ == "bool" else v[0].get()
        exp = cfg.get(key)
        assert str(got) == str(exp), f"{key} 回填不一致: {got!r} != {exp!r}"
    print(f"[self-test] {len(CE.FIELDS)} 个配置项回填一致")

    # 队列消费者唯一性：after 只应出现在主线程路径
    import inspect
    src = inspect.getsource(App)
    n_after = src.count("root.after")
    print(f"[self-test] root.after 出现 {n_after} 处（应全在主线程: __init__/_drain）")

    root.destroy()

    if rows == 0:
        print("[self-test] 失败：表格 0 行，渲染链路可能有问题")
        return False
    print("\n[self-test] 通过：界面构建 OK，真实数据已渲染")
    return True


def _write_crash_log(text):
    """pythonw.exe 没有控制台，异常必须落盘，否则用户只看到窗口闪一下就没了。"""
    try:
        with open(os.path.join(BASE, "gui_crash.log"), "w",
                  encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def main():
    ready_flag = os.path.join(BASE, ".gui_ready")
    try:
        if os.path.exists(ready_flag):
            os.remove(ready_flag)
    except Exception:
        pass

    try:
        root = tk.Tk()
    except Exception:
        _write_crash_log("无法创建窗口（tkinter 初始化失败）\n" +
                         traceback.format_exc())
        return 1

    try:
        style_icon(root)
        app = App(root)
        app.refresh_accounts()
    except Exception:
        _write_crash_log("界面构建失败\n" + traceback.format_exc())
        return 1

    # 等第一轮数据渲染完再放标记，避免"起来了但还是空表"
    def _mark_ready():
        try:
            with open(ready_flag, "w", encoding="utf-8") as f:
                f.write("ok")
        except Exception:
            pass

    root.after(1200, _mark_ready)

    try:
        root.mainloop()
    except Exception:
        _write_crash_log("主循环异常\n" + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    sys.exit(main())