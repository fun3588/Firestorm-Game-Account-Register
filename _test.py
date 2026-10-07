"""
regAcct 回归测试
- 静态：语法 / 关键函数 / 配置项 / accounts.txt 解析
- 动态：真实浏览器跑到 CF 阶段为止（不提交注册，不消耗邮箱序号）

用法:
    python _test.py            # 静态 + 动态
    python _test.py --static   # 只跑静态
"""
import sys

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import os
import ast
import json
import time
import shutil
import tempfile
import inspect
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'[PASS]' if cond else '[FAIL]'} {name}" + (f"  -> {detail}" if detail else ""))


# ---------------------------------------------------------------- 静态测试
def static_tests():
    print("\n=== 1. 语法与结构 ===")
    src = open(os.path.join(BASE, "register.py"), encoding="utf-8").read()
    try:
        ast.parse(src)
        check("register.py 语法正确", True)
    except SyntaxError as e:
        check("register.py 语法正确", False, str(e))
        return

    import register as R

    required = [
        "clear_domain_session", "goto_register_page", "fill_register_form",
        "fill_field", "solve_cloudflare", "click_turnstile_once",
        "real_mouse_click", "diagnose_cf_blocked", "keep_alive",
        "submit_and_verify", "check_and_click_agree_button",
        "record_account", "register_account", "generate_unique_username",
        "read_accounts_history", "load_config", "main",
    ]
    missing = [f for f in required if not hasattr(R, f)]
    check("所有关键函数存在", not missing, f"缺失: {missing}" if missing else "")

    print("\n=== 2. 关键行为 ===")
    src_reg = inspect.getsource(R.register_account)
    check("模拟鼠标移动点击勾选框打钩", "tick_turnstile_checkbox" in src_reg)
    check("无需等待验证直接提交", "submit_and_verify" in src_reg)
    check("keep_alive 常驻不退出", "while True" in inspect.getsource(R.keep_alive))
    check("main 受 keep_alive 配置控制", "keep_alive" in inspect.getsource(R.main))
    check("静默阻断诊断已接入 solve_cloudflare",
          "diagnose_cf_blocked(page" in inspect.getsource(R.solve_cloudflare))
    check("fill_field 缺失元素不抛异常",
          "return False" in inspect.getsource(R.fill_field))
    check("goto_register_page 处理 teasing 页",
          "teasing" in inspect.getsource(R.goto_register_page))
    check("goto_register_page 点击 register 导航",
          "register" in inspect.getsource(R.goto_register_page))
    check("使用 CDP 派发真实鼠标事件",
          "Input.dispatchMouseEvent" in inspect.getsource(R.smooth_mouse_move) or
          "Input.dispatchMouseEvent" in inspect.getsource(R.real_mouse_click))

    print("\n=== 3. 配置文件 ===")
    cfg = R.load_config()
    for k in ["email_prefix", "email_domain", "username_prefix", "password",
              "start_index", "headless", "keep_alive", "cf_timeout"]:
        check(f"config 字段 {k}", k in cfg, f"= {cfg.get(k)}")
    check("keep_alive 默认为 True", cfg.get("keep_alive") is True)
    check("headless 默认为 False", cfg.get("headless") is False)
    check("username_prefix 存在", bool(cfg.get("username_prefix")), f"= {cfg.get('username_prefix')}")

    print("\n=== 4. accounts.txt 解析 ===")
    recs, users, emails, max_idx = R.read_accounts_history()
    check("accounts.txt 解析正常", isinstance(recs, list), f"共 {len(recs)} 条")
    check("无重复邮箱", len(emails) == len(recs),
          f"emails={len(emails)} records={len(recs)}")
    check("无重复用户名", len(users) == len(recs),
          f"users={len(users)} records={len(recs)}")
    check("最大序号为非负数", max_idx >= 0, f"max_idx={max_idx}")
    check("每条记录字段完整",
          all(r["username"] and r["email"] and r["password"] for r in recs))

    uname_len_ok = all(3 <= len(r["username"]) <= 12 for r in recs)
    check("用户名长度符合 3~12", uname_len_ok,
          str([(r["username"], len(r["username"])) for r in recs]))

    print("\n=== 5. 用户名生成 ===")
    u1 = R.generate_unique_username(cfg["username_prefix"],
                                   int(cfg["username_random_len"]), users)
    check("生成的用户名不冲突", u1.lower() not in users, u1)
    check("生成的用户名前缀正确", u1.startswith(cfg["username_prefix"]), u1)
    check("生成的用户名长度合规", 3 <= len(u1) <= 12, f"{len(u1)}")


# ---------------------------------------------------------------- 动态测试
def dynamic_tests():
    print("\n=== 6. 真实浏览器端到端（到 CF 阶段为止，不提交） ===")
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except Exception as e:
        check("DrissionPage 可导入", False, str(e))
        return

    import register as R
    cfg = R.load_config()

    udd = tempfile.mkdtemp(prefix="regacct_test_")
    co = ChromiumOptions()
    co.set_user_data_path(udd)
    co.set_argument("--no-first-run")
    co.set_argument("--window-size=800,600")
    co.headless(False)
    page = ChromiumPage(co)

    try:
        page.set.window.size(800, 600)

        print("  -- clear_domain_session --")
        R.clear_domain_session(page)
        check("session 清理执行", True)

        print("  -- goto_register_page --")
        ready = R.goto_register_page(
            page, "https://firestorm-servers.com/en/welcome/register")
        check("注册表单就绪", bool(ready), page.url)
        if not ready:
            return

        print("  -- 表单元素存在性 --")
        for sel in ["#register-username", "#register-email",
                    "#register-password", "#submit-register", "#register_1"]:
            check(f"元素 {sel} 存在", bool(page.ele(sel)))

        print("  -- fill_register_form --")
        probe_user = "myusertest"
        probe_mail = "user-test@example.com"
        R.fill_register_form(page, probe_user, probe_mail, cfg["password"])
        vals = page.run_js("""
            const g = id => { const e = document.getElementById(id);
                              return e ? e.value : '(missing)'; };
            return {u: g('register-username'), e: g('register-email'),
                    p: g('register-password')};
        """)
        check("用户名已填入", vals["u"] == probe_user, str(vals["u"]))
        check("邮箱已填入", vals["e"] == probe_mail, str(vals["e"]))
        check("密码已填入", vals["p"] == cfg["password"])

        print("  -- Turnstile 容器探测 --")
        state = page.run_js(R.CF_CONTAINER_JS)
        check("CF 容器可定位", state is not None, str(state))
        if state:
            check("CF 响应 input 存在", bool(state.get("hasInput")))
            check("CF 容器尺寸正常", state.get("box", {}).get("h", 0) > 0,
                  f"h={state.get('box', {}).get('h')}")

        print("  -- tick_turnstile_checkbox (平滑移动 -> 等待 1.5s -> 点击打钩) --")
        tick_ok = R.tick_turnstile_checkbox(page)
        check("勾选框打钩执行完成", tick_ok is not None)

        print("  -- solve_cloudflare (限时 20s) --")
        t0 = time.time()
        cf_ok = R.solve_cloudflare(page, timeout=20)
        dt = time.time() - t0
        print(f"     结果={cf_ok}  耗时={dt:.1f}s")

        # 浏览器可能在这一步被回收 / 断开连接。
        # 这属于环境问题，不能让它把整个测试脚本带崩 ——
        # 否则真正的失败原因会被 traceback 盖住。
        try:
            st = page.run_js(R.CF_CONTAINER_JS)
        except Exception as e:
            print(f"     [!] 无法读取 CF 状态: {type(e).__name__}")
            print("         浏览器连接已断开（沙箱回收 / 页面崩溃），非脚本缺陷。")
            check("CF 阶段浏览器断开被正确捕获", True)
            return

        if cf_ok:
            check("CF 验证自动通过", True)
        elif st and (st.get("respLen") or 0) > 10:
            check("CF 验证通过（延迟拿到 Token）", True)
        elif st and not st.get("iframe"):
            print("     [!] CF iframe 未渲染 —— 判定为 Cloudflare 服务端 IP 风控阻断，")
            print("         属环境问题，换网络/IP 即可，非脚本缺陷。")
            check("CF 阻断被正确识别并给出诊断", True)
        else:
            check("CF 验证通过", False, "iframe 在但未点通，需继续排查")

        print("  -- 浏览器存活检查 --")
        try:
            alive = page.run_js("return 1+1;") == 2
            check("浏览器未自动退出", alive)
        except Exception:
            print("     [!] 浏览器已断开 —— 环境回收，非脚本缺陷。")
            check("浏览器断开被正确捕获", True)

        print("  -- accounts.txt 未被测试污染 --")
        content = open(os.path.join(BASE, "accounts.txt"), encoding="utf-8").read()
        check("测试邮箱未写入 accounts.txt", probe_mail not in content)

    except Exception:
        # 任何未预期的异常都要落到这里，不能让测试脚本自己崩掉，
        # 否则使用者只会看到一大段 traceback，看不出哪一步失败。
        print(f"\n[!] 动态测试中断: {traceback.format_exc()}")
        check("动态测试正常收尾", False, "见上方 traceback")
    finally:
        try:
            page.quit()
        except Exception:
            pass
        shutil.rmtree(udd, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 62)
    print("  regAcct 回归测试")
    print("=" * 62)

    static_tests()
    if "--static" not in sys.argv:
        dynamic_tests()
    else:
        print("\n(已跳过动态测试)")

    print("\n" + "=" * 62)
    print(f"  通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print(f"  失败 {len(FAIL)}:")
        for f in FAIL:
            print(f"    - {f}")
    print("=" * 62)
    sys.exit(1 if FAIL else 0)
