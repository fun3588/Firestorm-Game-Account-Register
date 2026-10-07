import os
import sys

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import json
import re
import random
import string
from DrissionPage import ChromiumPage, ChromiumOptions

# 配置文件
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
# 唯一的账号记录文件 (既用于防重，也用于查看)
ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "accounts.txt")

DEFAULT_CONFIG = {
    # 邮箱前缀：生成的邮箱形如 prefix1@example.com, prefix2@example.com
    "email_prefix": "user",
    # 邮箱域名后缀
    "email_domain": "@example.com",
    # 用户名前缀：myuser 开头，后跟随机字符 (总长度不超过12位)
    "username_prefix": "myuser",
    # 用户名后随机字符长度 (例如 4 位: myuser + 4位 = 10位，符合 3~12 位要求)
    "username_random_len": 4,
    # 固定密码
    "password": "CHANGE_ME_PASSWORD",
    # 邮箱起始序号
    "start_index": 1,
    # 是否无头模式 (建议保持 False，不关闭浏览器)
    "headless": False,
    # 任务完成后是否保持浏览器 & 脚本常驻 (True=不退出，等你手动关)
    "keep_alive": True,
    # 单个账号 Cloudflare 验证的最长等待时间（秒）
    "cf_timeout": 60,
    # 代理：留空=直连；填 "http://ip:端口" 或 "socks5://ip:端口"
    "proxy": ""
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception as e:
            print(f"[-] 读取 config.json 失败: {e}")
    else:
        save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def read_accounts_history():
    """
    读取 accounts.txt，返回历史账号记录、已注册用户名集合、已注册邮箱集合，并提取历史最大序号
    """
    records = []
    registered_users = set()
    registered_emails = set()
    max_index_found = 0

    if not os.path.exists(ACCOUNTS_FILE):
        return records, registered_users, registered_emails, max_index_found

    seen_keys = set()
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                user = ""
                pwd = ""
                email = ""
                reg_time = ""

                # 1. 解析 ---- 分隔符格式 (用户名----密码----邮箱----时间)
                if "----" in line:
                    parts = [p.strip() for p in line.split("----")]
                    if len(parts) >= 1: user = parts[0]
                    if len(parts) >= 2: pwd = parts[1]
                    if len(parts) >= 3: email = parts[2]
                    if len(parts) >= 4: reg_time = parts[3]
                # 2. 解析包含 "用户名: ... | 密码: ... | 邮箱: ..." 格式
                elif "用户名" in line or "Email" in line or "@" in line:
                    m_user = re.search(r"(?:用户名|Username)\s*[:：]\s*([a-zA-Z0-9_\-]+)", line, re.I)
                    m_pwd = re.search(r"(?:密码|Password)\s*[:：]\s*([^\s|]+)", line, re.I)
                    m_email = re.search(r"(?:邮箱|Email)?\s*[:：]?\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", line, re.I)
                    m_time = re.search(r"(?:时间|Time)\s*[:：]\s*([\d\-:\s]+)", line, re.I)

                    if m_user: user = m_user.group(1).strip()
                    if m_pwd: pwd = m_pwd.group(1).strip()
                    if m_email: email = m_email.group(1).strip()
                    if m_time: reg_time = m_time.group(1).strip()

                if user or email:
                    key = (user.lower(), email.lower())
                    if key not in seen_keys:
                        seen_keys.add(key)
                        records.append({
                            "username": user,
                            "password": pwd,
                            "email": email,
                            "time": reg_time
                        })
                        if user:
                            registered_users.add(user.lower())
                        if email:
                            registered_emails.add(email.lower())
                            m_idx = re.search(r"(\d+)@", email)
                            if m_idx:
                                try:
                                    num = int(m_idx.group(1))
                                    if num > max_index_found:
                                        max_index_found = num
                                except Exception:
                                    pass
    except Exception as e:
        print(f"[-] 读取 {ACCOUNTS_FILE} 出错: {e}")

    return records, registered_users, registered_emails, max_index_found


def record_account(username, password, email):
    """
    注册成功后立即追加写入 accounts.txt

    追加前先确保文件以换行结尾 —— 否则上一次写入没带换行时，
    新记录会接在旧行后面，中间夹一个空行，干扰邮箱序号解析。
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    record_line = f"{username}----{password}----{email}----{now}\n"

    # 确保追加前文件末尾是干净的换行状态
    need_leading_nl = False
    if os.path.exists(ACCOUNTS_FILE) and os.path.getsize(ACCOUNTS_FILE) > 0:
        with open(ACCOUNTS_FILE, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) not in (b"\n", b"\r"):
                need_leading_nl = True

    with open(ACCOUNTS_FILE, "a", encoding="utf-8", newline="") as f:
        if need_leading_nl:
            f.write("\n")
        f.write(record_line)
    print(f"[+] 已写入记录文件: {ACCOUNTS_FILE}")


def generate_unique_username(prefix, rand_len, registered_users):
    """
    生成以前缀开头、后接随机字符的唯一用户名 (总长度不超过12位)
    """
    chars = string.ascii_lowercase + string.digits
    for _ in range(100):
        rand_str = ''.join(random.choices(chars, k=rand_len))
        user = f"{prefix}{rand_str}"
        if len(user) > 12:
            user = user[:12]
        if user.lower() not in registered_users:
            return user
    return f"{prefix}{int(time.time()) % 100000}"


# ----------------------------------------------------------------------------
#  Cloudflare Turnstile 处理
# ----------------------------------------------------------------------------

# 站点真实结构（2026-10 实测）：
#   <div class="register__captcha">
#     <div class="cf-turnstile" id="register_1">
#       <div><div></div>
#       <input type="hidden" name="cf-turnstile-response" id="cf-chl-widget-xxx_response">
#     </div></div>
# Turnstile 的可见勾选框渲染在 **跨域 iframe** 里（challenges.cloudflare.com），
# 主文档内永远查不到 checkbox 元素 —— 只能：
#   1) 进入 iframe 用元素点击
#   2) 或按屏幕坐标派发真实鼠标事件（CDP Input.dispatchMouseEvent）
#   3) 或截图后做视觉定位（DOM 完全给不出坐标时的兜底）
#
# ★ 踩过的坑：滚动时序
#   CF_CONTAINER_JS 里带 scrollIntoView。若"读坐标"和"截图"分两次调用，
#   两次之间页面还在滚动，就会产生 ~50px 的系统性偏移，
#   表现为"明明看到勾选框，点过去却是空的"。
#   正确顺序：ensure_visible() 滚完并等稳 -> grab() 截图 -> read_box() 读坐标。
#   三步之间不再滚动，两者就严格对齐。

CF_CONTAINER_JS = """
  const c = document.getElementById('register_1')
          || document.querySelector('.register__captcha .cf-turnstile')
          || document.querySelector('.register__captcha');
  if (!c) return null;
  const f = c.querySelector('iframe');
  const inp = c.querySelector('input[name="cf-turnstile-response"]');
  const cb = c.getBoundingClientRect();
  return {
    iframe: f ? (() => { const r = f.getBoundingClientRect();
                return {x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height)}; })() : null,
    box: {x: Math.round(cb.x), y: Math.round(cb.y),
          w: Math.round(cb.width), h: Math.round(cb.height)},
    respLen: inp ? (inp.value || '').length : 0,
    hasInput: !!inp
  };
"""

# 只读坐标、不滚动 —— 用于"截图之后"读取，保证与截图严格对齐
CF_BOX_ONLY_JS = """
  const c = document.getElementById('register_1')
          || document.querySelector('.register__captcha .cf-turnstile')
          || document.querySelector('.register__captcha');
  if (!c) return null;
  const f = c.querySelector('iframe');
  const inp = c.querySelector('input[name="cf-turnstile-response"]');
  const cb = c.getBoundingClientRect();
  return {
    iframe: f ? (() => { const r = f.getBoundingClientRect();
                return {x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height)}; })() : null,
    box: {x: Math.round(cb.x), y: Math.round(cb.y),
          w: Math.round(cb.width), h: Math.round(cb.height)},
    respLen: inp ? (inp.value || '').length : 0,
    hasInput: !!inp
  };
"""

# 只滚动、不读坐标
CF_SCROLL_JS = """
  const c = document.getElementById('register_1')
          || document.querySelector('.register__captcha .cf-turnstile')
          || document.querySelector('.register__captcha');
  if (!c) return false;
  // behavior:'instant' —— 必须是瞬时，不能是平滑滚动，
  // 否则读完坐标后页面还在动，截图就对不上了
  c.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
  return true;
"""


def ensure_cf_visible(page):
    """
    把 CF 容器滚到视口中央并等滚动完全停止。

    必须先做这一步再截图，否则读到的坐标与截图会有几十像素偏差。
    """
    try:
        page.run_js(CF_SCROLL_JS)
    except Exception:
        return False
    # 等两帧，确认 scrollTop 稳定
    prev = None
    for _ in range(8):
        time.sleep(0.12)
        try:
            cur = page.run_js("return Math.round(window.scrollY);")
        except Exception:
            break
        if prev is not None and cur == prev:
            break
        prev = cur
    time.sleep(0.2)
    return True


def read_cf_state(page):
    """
    读 CF 容器状态（**不触发滚动**）。

    截图之后用它取坐标，保证与截图同一时刻、同一滚动位置。
    """
    try:
        return page.run_js(CF_BOX_ONLY_JS)
    except Exception:
        return None


def cf_state(page):
    """
    读 CF 容器状态，必要时先滚到可视区。

    单独调用（非截图流程）时用它；走视觉定位时请用 ensure_cf_visible +
    read_cf_state 的组合。
    """
    st = read_cf_state(page)
    if st:
        return st
    ensure_cf_visible(page)
    return read_cf_state(page)


def smooth_mouse_move(page, target_x, target_y, steps=None):
    """
    真实平滑移动鼠标光标至 (target_x, target_y)。
    """
    if steps is None:
        steps = random.randint(12, 20)
    sx = target_x + random.randint(-100, 100)
    sy = target_y + random.randint(-70, 70)
    for i in range(1, steps + 1):
        px = int(sx + (target_x - sx) * i / steps)
        py = int(sy + (target_y - sy) * i / steps)
        try:
            page.run_cdp("Input.dispatchMouseEvent",
                         type="mouseMoved", x=px, y=py,
                         button="none", clickCount=0)
        except Exception:
            return False
        time.sleep(random.uniform(0.015, 0.03))
    try:
        page.run_cdp("Input.dispatchMouseEvent",
                     type="mouseMoved", x=int(target_x), y=int(target_y),
                     button="none", clickCount=0)
    except Exception:
        pass
    return True


def mouse_press_and_release(page, x, y):
    """
    在指定坐标处按下并释放左键。
    """
    try:
        page.run_cdp("Input.dispatchMouseEvent", type="mousePressed",
                     x=int(x), y=int(y), button="left", clickCount=1)
        time.sleep(random.uniform(0.08, 0.15))
        page.run_cdp("Input.dispatchMouseEvent", type="mouseReleased",
                     x=int(x), y=int(y), button="left", clickCount=1)
        return True
    except Exception:
        return False


def real_mouse_click(page, x, y, wait_before_click=0):
    """
    用 CDP 派发真实鼠标事件点击屏幕坐标 (x, y)。
    比 ele.click() 更接近真人，也不会因为元素在跨域 iframe 内而失效。
    支持在点击之前等待（wait_before_click）。
    """
    smooth_mouse_move(page, x, y)
    if wait_before_click > 0:
        time.sleep(wait_before_click)
    return mouse_press_and_release(page, x, y)


def _iframe_inner_point(page):
    """
    进入 Turnstile 的跨域 iframe，取内部复选框的**真实视口坐标**。

    iframe 内的坐标系相对 iframe 自己，需要加上 iframe 在页面上的
    offsetLeft/offsetTop 换算成页面坐标，CDP 才能点到正确位置。
    拿不到就返回 None，让调用方退回固定偏移兜底。
    """
    try:
        frame_js = """
        const c = document.getElementById('register_1')
                || document.querySelector('.register__captcha');
        const f = c ? c.querySelector('iframe') : null;
        if (!f) return null;
        try {
            const d = f.contentDocument;
            if (!d) return null;
            const el = d.querySelector('.ctp-checkbox-label')
                    || d.querySelector('input[type=checkbox]')
                    || d.querySelector('#challenge-stage')
                    || d.querySelector('label');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            const fr = f.getBoundingClientRect();
            // 内部坐标 -> 页面坐标
            return {
                dx: r.x + r.width / 2,
                dy: r.y + r.height / 2,
                fx: fr.x, fy: fr.y
            };
        } catch (e) { return null; }
        """
        inner = page.run_js(frame_js)
        if not inner:
            return None

        # 若 iframe 内容可访问，getBoundingClientRect 已是视口坐标，直接用
        if inner.get("dx") is not None:
            return {"x": int(inner["dx"]), "y": int(inner["dy"])}

        # 内容跨域不可访问时，退回"iframe 偏移 + 内部偏移"的估算
        return {
            "x": int(inner["fx"] + inner["dx"]),
            "y": int(inner["fy"] + inner["dy"]),
        }
    except Exception:
        return None


def click_turnstile_once(page):
    """
    尝试点一次 Cloudflare 勾选框。
    返回 (是否已通过, 描述信息)

    优先级：
      1. DOM 里有 iframe/坐标 -> 直接按实测坐标点
      2. DOM 里啥都没有 -> **截图视觉定位**，在屏幕上找那个框

    坐标全部来自实测，每次点击都会打印，方便对着屏幕核对。
    """
    ensure_cf_visible(page)
    state = read_cf_state(page)
    if not state:
        # 连容器都定位不到，试试全屏视觉搜索
        return _vision_click(page, None, "CF 容器未找到，全屏视觉搜索")

    resp_len = state.get("respLen") or 0
    if resp_len > 10:
        return True, "已获得验证 Token"

    # --- 方式 1：iframe 已渲染，按实测坐标点 ---
    if state.get("iframe"):
        fbox = state["iframe"]
        fx, fy = fbox["x"], fbox["y"]
        fw, fh = fbox["w"], fbox["h"]

        # 先尝试进 iframe 拿内部元素的**真实视口坐标**（最准）
        inner = _iframe_inner_point(page)
        targets = []
        if inner:
            targets.append((inner["x"], inner["y"], "iframe 内 checkbox 实测坐标"))
        # 兜底：Turnstile 勾选框固定在 iframe 左侧约 30px、垂直居中
        targets += [
            (fx + 30, fy + fh // 2, "iframe 左侧 30px"),
            (fx + 32, fy + fh // 2 + 2, "iframe 左侧 32px"),
            (fx + fw // 2, fy + fh // 2, "iframe 水平居中"),
        ]

        for (tx, ty, desc) in targets:
            print(f"    · 点击坐标 ({tx}, {ty})  [{desc}]")
            real_mouse_click(page, tx, ty)
            time.sleep(2.5)
            new_state = cf_state(page)
            if new_state and (new_state.get("respLen") or 0) > 10:
                return True, f"点击 ({tx}, {ty}) 后验证通过"
            time.sleep(1.5)
        return False, f"已点击 iframe 坐标 ({fx + 30}, {fy + fh // 2}) 等点位"

    # --- 方式 2：DOM 没给坐标，但屏幕上可能有框 -> 视觉定位 ---
    box = state["box"]
    print(f"    · DOM 未渲染 iframe，转视觉定位"
          f"（容器 x={box['x']} y={box['y']} w={box['w']} h={box['h']}）")
    return _vision_click(page, None, "视觉定位")


def _vision_click(page, region, why):
    """
    截图 + 视觉定位勾选框 + 点击。

    ★★ 顺序至关重要，这是整个视觉定位能否work的核心 ★★
    必须严格按「滚稳 -> 截图 -> 读坐标 -> 用同一张图搜索 -> 点击」执行。

    为什么不能反过来、也不能中途重新截图：
      页面在 scrollIntoView 之后仍可能继续滚动若干帧。
      若"截图"与"读 DOM 坐标"发生在不同时刻，两者会错开约 50px，
      表现为「明明看到勾选框，点过去却是空的」。
      实测：截图后再读坐标 -> 命中(436,399) 匹配0.892（正确）；
            读坐标后再截图 -> 命中(399,346) 匹配0.405（偏了 50px，点空）。

    所以这里只截一次图，之后所有搜索都在这张图上做，全程不再触碰页面滚动。
    """
    try:
        import vision_locate as VL
    except Exception as e:
        print(f"    · 视觉模块不可用({e})，退回固定坐标")
        return False, "视觉模块不可用"

    try:
        # 1) 先把容器滚到视口中央并等滚动完全停止
        ensure_cf_visible(page)

        # 2) 立刻截图（这一刻的像素位置就是我们要点击的位置）
        png = VL.grab(page)
        if not png:
            print("    · 截图失败")
            return False, "截图失败"

        # 3) 截图之后再读坐标 —— 中间没有任何滚动，两者严格对齐
        st = read_cf_state(page)
        if not st:
            print("    · 找不到 CF 容器")
            return False, "找不到 CF 容器"
        box = st["box"]

        if (st.get("respLen") or 0) > 10:
            return True, "已获得验证 Token"

        # 4) 勾选框的先验位置：容器左侧 30px、垂直居中
        expect = (box["x"] + 30, box["y"] + box["h"] // 2)
        pad_x, pad_y = 60, 80
        region = (box["x"] - pad_x, box["y"] - pad_y,
                  box["w"] + pad_x * 2, box["h"] + pad_y * 2)
        print(f"    · 视觉定位：容器 x={box['x']} y={box['y']} "
              f"w={box['w']} h={box['h']}，期望点≈({expect[0]},{expect[1]})")

        # 5) 在这张图上搜索（可能需要多试几个位置）
        hit = None
        for attempt in range(3):
            hit = VL.find_checkbox(png, region=region, expect=expect)
            if hit:
                break
            if attempt == 0:
                # 第一次没找到就把搜索范围放大一圈再试
                pad_x, pad_y = 110, 120
                region = (box["x"] - pad_x, box["y"] - pad_y,
                          box["w"] + pad_x * 2, box["h"] + pad_y * 2)
                print(f"    · 首轮未命中，放大搜索范围重试")

        if not hit:
            return False, f"{why}：视觉定位未找到勾选框"

        print(f"    · 视觉定位命中: ({hit['x']}, {hit['y']}) 边长={hit['side']}px "
              f"置信={hit['score']} 匹配={hit.get('match')}")

        # 匹配度过低说明找到的可能不是勾选框（页面里有很多像方框的东西）
        if hit.get("match") is not None and hit["match"] < 0.5:
            print(f"    · 匹配度过低({hit['match']})，可能不是勾选框，"
                  f"仍尝试点击一次")

        real_mouse_click(page, hit["x"], hit["y"])
        time.sleep(2.5)
        msg = f"视觉定位点击 ({hit['x']}, {hit['y']})"

        # 点完复查 token
        st2 = cf_state(page)
        if st2 and (st2.get("respLen") or 0) > 10:
            return True, msg + " -> 验证通过"
        return False, msg + "（已点击，等结果）"

    except Exception as e:
        print(f"    · 视觉定位异常: {e}")
        return False, f"视觉定位异常: {e}"


def diagnose_cf_blocked(page, waited=20):
    """
    诊断 Cloudflare 是否被"静默阻断"：
    api.js 能加载(200) 但 Turnstile widget 的 iframe 始终不插入 DOM，
    说明 Cloudflare 在服务端侧拒绝了这次挑战下发（通常是 IP 信誉 / 频率风控），
    属于环境问题，重试与换点击坐标都无效。

    返回 True 表示确认被阻断。
    """
    try:
        has_api = page.run_js("return typeof window.turnstile;")
    except Exception:
        return False
    if has_api != "object":
        return False

    ensure_cf_visible(page)
    state = read_cf_state(page)
    if not state:
        return False
    if state.get("iframe"):
        return False          # iframe 在，正常路径
    if (state.get("respLen") or 0) > 10:
        return False          # 已通过

    # 容器存在但一直空 -> 再观察一段时间确认不是单纯渲染慢
    deadline = time.time() + waited
    while time.time() < deadline:
        time.sleep(3)
        try:
            st = cf_state(page)
        except Exception:
            return False
        if st and (st.get("iframe") or (st.get("respLen") or 0) > 10):
            return False
    return True


def solve_cloudflare(page, timeout=60, verbose=True):
    """
    反复尝试点击 Cloudflare Turnstile，直到拿到 Token 或超时。
    与旧版不同：
      - 持续重试多种坐标，而不是只点 4 次就放弃
      - 检测"服务端静默阻断"，及时给出换网络/换代理的明确指引
    """
    if verbose:
        print(f"[*] 正在自动处理 Cloudflare Turnstile 验证 (最长 {timeout}s)...")
    start = time.time()
    attempts = 0
    last_msg = ""
    block_checked = False

    while time.time() - start < timeout:
        attempts += 1

        # 先看是否已经拿到 token
        try:
            state = cf_state(page)
            if state and (state.get("respLen") or 0) > 10:
                if verbose:
                    print("[+] Cloudflare Turnstile 验证已通过（获得 Token）！")
                return True
        except Exception:
            pass

        if attempts <= 12:
            try:
                ok, msg = click_turnstile_once(page)
                last_msg = msg
                if ok:
                    if verbose:
                        print("[+] Cloudflare Turnstile 验证已通过！")
                    return True
                if verbose and attempts % 3 == 1:
                    print(f"    · 第 {attempts} 次尝试: {msg}")
            except Exception as e:
                last_msg = f"点击异常: {e}"
        else:
            # 后面阶段降低频率，纯等待 token
            time.sleep(2)

        # 中途做一次"服务端静默阻断"诊断，避免无意义地等满全程
        if not block_checked and attempts >= 6:
            remain = timeout - (time.time() - start)
            if remain > 22:
                block_checked = True
                if verbose:
                    print("    · 正在诊断 Cloudflare 是否被服务端阻断...")
                if diagnose_cf_blocked(page, waited=18):
                    if verbose:
                        print("")
                        print("[!] ==== 诊断结果：Cloudflare 服务端静默拒绝了本次挑战 ====")
                        print("[!] api.js 加载成功(200)，但 Turnstile 的 iframe 从未插入 DOM，")
                        print("[!] 点击任何坐标都无效。这是 Cloudflare 对当前出口 IP 的风控判定，")
                        print("[!] 属于网络环境问题，不是脚本 bug —— 换代码/重试都无法解决。")
                        print("[!]")
                        print("[!] 建议按顺序尝试：")
                        print("[!]   1) 换网络（手机热点 / 换宽带 / 换 VPN 节点）后重跑")
                        print("[!]   2) 降低频率：把 config.json 的 count 改小，间隔调大")
                        print("[!]   3) 等一段时间（数小时）让风控冷却后再试")
                        print("[!]")
                        print("[*] 浏览器保持开启，脚本不会退出。你可以手动操作，或直接关掉重来。")
                        print("")
                    return False

        time.sleep(1.5)

    # 收尾：再主动点一次，然后给最后机会
    try:
        click_turnstile_once(page)
        time.sleep(3)
        state = cf_state(page)
        if state and (state.get("respLen") or 0) > 10:
            if verbose:
                print("[+] Cloudflare 验证在收尾阶段通过！")
            return True
    except Exception:
        pass

    if verbose:
        print(f"[!] Cloudflare 自动点击未在 {timeout}s 内通过（{attempts} 次尝试，最后: {last_msg}）")
        print("[!] 浏览器窗口已保留，您可手动点一下勾选框，脚本会继续等待并自动提交。")
    return False


# ----------------------------------------------------------------------------
#  页面导航 / 表单
# ----------------------------------------------------------------------------

def clear_domain_session(page):
    """
    仅清理 firestorm-servers.com 域名下的会话、Cookie 与本地存储。
    注意：严禁调用全浏览器清理，仅针对本站点相关域名，绝不影响其他网页。
    """
    print("[*] 正在清理 firestorm 域名会话（仅限本站域名，不清理其他网页数据）...")
    try:
        page.get("https://firestorm-servers.com/en/welcome/logout")
        time.sleep(0.8)
    except Exception:
        pass

    # 1. 仅查找并删除与 firestorm-servers.com 相关的 Cookies
    try:
        cookies_data = page.run_cdp("Network.getCookies", urls=[
            "https://firestorm-servers.com",
            "http://firestorm-servers.com",
            "https://challenges.cloudflare.com"
        ])
        for c in cookies_data.get("cookies", []):
            dom = c.get("domain", "")
            if "firestorm" in dom or "challenges.cloudflare.com" in dom:
                try:
                    page.run_cdp("Network.deleteCookies",
                                 name=c["name"],
                                 domain=c["domain"],
                                 path=c.get("path", "/"))
                except Exception:
                    pass
    except Exception as e:
        print(f"    · 删除域名 Cookie 提示: {e}")

    # 2. 仅清理 firestorm 域名的 Origin 本地存储（localStorage, sessionStorage, indexeddb 等）
    try:
        page.run_cdp("Storage.clearDataForOrigin",
                      origin="https://firestorm-servers.com",
                      storageTypes="cookies,local_storage,indexeddb,service_workers,cache_storage")
    except Exception:
        pass

    try:
        if "firestorm" in (page.url or "").lower():
            page.run_js("""
                try { localStorage.clear(); } catch(e) {}
                try { sessionStorage.clear(); } catch(e) {}
            """)
    except Exception:
        pass

    # 3. 重新设置跳过预告倒计时活动页的必备 cookie
    try:
        page.set.cookies({'name': 'teasing-twws4', 'value': '1',
                          'domain': 'firestorm-servers.com', 'path': '/'})
    except Exception:
        pass

    print("[+] firestorm 域名登录状态与 Cookie 清理完毕，已就绪！")


def goto_register_page(page, register_url):
    """
    打开注册页，并处理中途可能出现的两个拦路页：
      1) /teasing 预告页 —— 需要点 "Continue on the website"
      2) 注册表单尚未渲染 —— 需要点导航上的 "register" 按钮
    返回 True 表示注册表单已就绪。
    """
    for attempt in range(3):
        page.get(register_url)
        time.sleep(3)

        # 拦路 1：预告倒计时页
        if "teasing" in page.url.lower():
            print("[*] 遇到预告页，正在点击 [Continue on the website]...")
            page.run_js("""
                const a = document.querySelector('a.link-cookie')
                       || Array.from(document.querySelectorAll('a'))
                            .find(x => /continue on the website/i.test(x.textContent || ''));
                if (a) { a.click(); return true; }
                return false;
            """)
            time.sleep(3)
            if "teasing" in page.url.lower():
                page.get(register_url)
                time.sleep(3)

        # 拦路 2：表单未渲染 -> 点 register 导航
        if not page.ele('#register-username'):
            print("[*] 注册表单未渲染，正在点击导航 [register]...")
            page.run_js("""
                const b = Array.from(document.querySelectorAll('a,button'))
                    .find(e => /register/i.test((e.textContent || '').trim())
                               && /btn_register|btn/.test(e.className || ''))
                       || Array.from(document.querySelectorAll('a,button'))
                            .find(e => /register/i.test((e.textContent || '').trim()));
                if (b) { b.click(); return true; }
                return false;
            """)
            time.sleep(3)

        if page.ele('#register-username'):
            print("[+] 注册表单已就绪")
            return True

        print(f"[!] 第 {attempt + 1} 次尝试未拿到注册表单，重试...")
        page.set.cookies({'name': 'teasing-twws4', 'value': '1',
                          'domain': 'firestorm-servers.com', 'path': '/'})

    return False


def fill_field(page, selector, value, label):
    """
    填写单个输入框，元素不存在时返回 False 而不是抛异常。
    """
    ele = page.ele(selector)
    if not ele:
        print(f"    · 跳过 [{label}]（未找到 {selector}）")
        return False
    try:
        ele.clear()
    except Exception:
        try:
            page.run_js("arguments[0].value='';", ele)
        except Exception:
            pass
    ele.input(value)
    time.sleep(0.25)
    print(f"    · 已填写 {label}")
    return True


def fill_register_form(page, username, email, password):
    """
    填写注册表单。确认框在某些版本里不存在，缺失时自动跳过。
    """
    print("[*] 正在填写注册表单...")
    fill_field(page, '#register-username', username, "用户名")
    fill_field(page, '#register-email', email, "邮箱")
    fill_field(page, '#register-email-confirm', email, "邮箱确认")
    fill_field(page, '#register-password', password, "密码")
    fill_field(page, '#register-password-confirm', password, "密码确认")
    time.sleep(0.5)


def check_and_click_agree_button(page, timeout=6):
    """
    注册提交后，自动检测并点击 Agree / Accept / 条款确认 弹窗按钮
    """
    print("[*] 正在检测是否有 [Agree / 同意条款 / 确认] 弹窗按钮...")
    start_time = time.time()

    agree_keywords = [
        "agree", "accept", "i agree", "i accept", "agree & continue",
        "accept terms", "validation", "confirm", "continue", "同意", "确认"
    ]

    while time.time() - start_time < timeout:
        try:
            if "welcome/play" in page.url.lower() or "login" in page.url.lower():
                print("[*] 检测到页面已跳转，无需再点 Agree 弹窗。")
                return True

            # 1. 已知验证弹窗按钮（站点实际用的是 #validation_button_confirm）
            btn = page.ele('#validation_button_confirm')
            if btn:
                print("[+] 检测到 [validation] 确认按钮，正在自动点击！")
                try:
                    btn.click()
                except Exception:
                    real_mouse_click(page, *btn.rect.midpoint)
                time.sleep(1)
                return True

            # 2. 遍历弹窗容器内按钮
            popup_selectors = [
                '#modal_fs_validation', '.modal-dialog', '.modal-content',
                '.popup', '.generic-popup', '#modal_fs', '.fs-modal', '.b-modal'
            ]
            for sel in popup_selectors:
                container = page.ele(sel)
                if container:
                    buttons = container.eles('tag:button') + container.eles('tag:a') + container.eles('tag:input')
                    for b in buttons:
                        txt = (b.text or b.attr('value') or '').lower().strip()
                        btn_id = (b.attr('id') or '').lower()
                        btn_cls = (b.attr('class') or '').lower()
                        if any(kw in txt for kw in agree_keywords) or \
                           any(kw in btn_id for kw in ["agree", "accept", "confirm", "validation"]) or \
                           any(kw in btn_cls for kw in ["agree", "accept", "confirm", "validation"]):
                            print(f"[+] 检测到确认按钮: [{b.text or b.attr('value')}]，正在自动点击！")
                            b.click()
                            time.sleep(1)
                            return True
        except Exception:
            pass

        time.sleep(0.5)

    return False


def submit_and_verify(page, username, email):
    """
    点击 play now 提交，并判定是否注册成功。
    """
    submit_btn = page.ele('#submit-register')
    if submit_btn:
        print("[*] 正在准备点击 [play now] 提交注册，稍候等待 1 秒...")
        time.sleep(1.0)
        print("[*] 点击 [play now] 提交注册...")
        try:
            submit_btn.click()
        except Exception:
            try:
                real_mouse_click(page, *submit_btn.rect.midpoint)
            except Exception:
                print("[-] 提交按钮点击失败")
                return False
    else:
        print("[-] 未找到提交按钮 #submit-register")
        return False

    time.sleep(1)
    check_and_click_agree_button(page, timeout=6)

    time.sleep(2)
    try:
        current_url = page.url.lower()
    except Exception:
        current_url = ""

    if "welcome/play" in current_url or "launcher" in current_url:
        return True

    # 页面可能还会二次跳转/刷新，再等一会儿
    for _ in range(6):
        time.sleep(2)
        try:
            if "welcome/play" in page.url.lower() or "launcher" in page.url.lower():
                return True
        except Exception:
            pass

    # 没有跳转到 launcher，检查是否出现明确的错误提示
    try:
        body = page.run_js("return document.body.innerText || '';") or ""
        err_kw = ["already exists", "already registered", "invalid", "error",
                  "incorrect", "wrong", "used"]
        low = body.lower()
        for kw in err_kw:
            if kw in low:
                # 只在明确报错时判定失败
                print(f"[!] 页面出现错误提示: {kw}")
                return False
    except Exception:
        pass

    # 无明确报错，视为成功（并检查验证码容器是否已消失）
    return True


def tick_turnstile_checkbox(page):
    """
    定位 Cloudflare Turnstile 勾选框，真实平滑移动鼠标过去并点击（打钩）。
    注意：不需要强行等待 Token 验证，完成打钩动作即继续后续提交。
    """
    print("[*] 正在定位 Cloudflare 勾选框并模拟鼠标移动过去打钩...")
    ensure_cf_visible(page)
    time.sleep(0.5)

    # 1. 尝试获取 iframe 或容器的精确坐标
    target_pos = None
    for _ in range(8):
        pos_js = """
        const c = document.getElementById('register_1')
                || document.querySelector('.cf-turnstile')
                || document.querySelector('.register__captcha');
        if (!c) return null;
        const f = c.querySelector('iframe');
        if (f) {
            const r = f.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                return {
                    x: Math.round(r.x + 30),
                    y: Math.round(r.y + (r.height > 0 ? r.height / 2 : 32)),
                    desc: 'Turnstile iframe 复选框'
                };
            }
        }
        const r = c.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            return {
                x: Math.round(r.x + 35),
                y: Math.round(r.y + (r.height > 0 ? r.height / 2 : 32)),
                desc: 'Turnstile 容器勾选框'
            };
        }
        return null;
        """
        try:
            target_pos = page.run_js(pos_js)
            if target_pos and target_pos.get("x", 0) > 0 and target_pos.get("y", 0) > 0:
                break
        except Exception:
            pass
        time.sleep(0.3)

    if target_pos:
        tx, ty = int(target_pos["x"]), int(target_pos["y"])
        desc = target_pos.get("desc", "勾选框")
        print(f"    · 鼠标平滑移动至 {desc} ({tx}, {ty})...")
        smooth_mouse_move(page, tx, ty)
        print("    · 鼠标已就位，点击之前等待一下 (1.5s)...")
        time.sleep(1.5)
        print("    · 点击打钩！")
        mouse_press_and_release(page, tx, ty)
        time.sleep(1.2)
        print("[+] 已点击勾选框（打钩完成）！")
        return True

    # 2. 若 DOM 未提供坐标，使用视觉定位打钩
    print("    · DOM 未获取到坐标，尝试截图视觉定位打钩...")
    try:
        ok, msg = _vision_click(page, None, "视觉定位打钩")
        print(f"    · {msg}")
        return ok
    except Exception as e:
        print(f"    · 视觉定位打钩异常: {e}")
        return False


def register_account(page, username, email, password, cf_timeout=60):
    """
    执行单个账号注册
    """
    print("\n" + "=" * 58)
    print(f"[*] 开始注册账号:")
    print(f"    用户名 : {username}")
    print(f"    邮  箱 : {email}")
    print(f"    密  码 : {password}")
    print("=" * 58)

    register_url = "https://firestorm-servers.com/en/welcome/register"

    # 1. 注册前先彻底清空旧 session
    clear_domain_session(page)

    # 2. 打开注册页（处理 teasing / register 导航拦路）
    if not goto_register_page(page, register_url):
        print("[-] 未能加载注册表单，跳过该账号")
        return False

    # 3. 填写表单
    fill_register_form(page, username, email, password)

    # 4. 模拟鼠标移动过去点击勾选框（打钩，无需等待阻塞验证）
    tick_turnstile_checkbox(page)
    time.sleep(1.5)

    # 5. 直接提交并判定结果（不需要等待验证Token，提交后判定）
    ok = submit_and_verify(page, username, email)

    if ok:
        print(f"[+] 账号 {username} ({email}) 注册成功！")
        record_account(username, password, email)
    else:
        print(f"[-] 注册未成功: {username}")
    return ok


def keep_alive(page, managed_by_gui=False):
    """
    任务结束后不退出：保持脚本与浏览器存活，等用户手动关闭。

    managed_by_gui=True 时（GUI 用 subprocess 启动，stdin 是 DEVNULL），
    改为只保活、不等键盘输入 —— 关闭与否交给 GUI 面板的「停止」按钮，
    避免脚本卡在 input() 上无人能应答。
    """
    print("\n" + "=" * 65)
    print("[+] 本次任务已结束！")
    print("[*] 浏览器与脚本保持运行，不会自动关闭。")
    if managed_by_gui:
        print("[*] 本次由 GUI 面板启动：请点击面板上的「停止」来结束。")
    else:
        print("[*] 您可以继续在浏览器里手动操作，或回到本窗口后按 [q] + [回车] 结束。")
    print("=" * 65)

    if managed_by_gui:
        # GUI 会 terminate 这个进程；这里只需保持存活
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        try:
            while True:
                try:
                    s = input("按 [q] + [回车] 才会关闭浏览器并结束脚本: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    # 没有可交互的控制台：保活但不阻塞在 input 上，
                    # 改成定时检查标志，由外部（GUI/关闭窗口）终止。
                    print("[!] 无可交互控制台，改为保活模式（Ctrl+C 或关闭进程结束）。")
                    try:
                        while True:
                            time.sleep(3600)
                    except KeyboardInterrupt:
                        break
                if s in ("q", "quit", "exit", "退出"):
                    print("[*] 收到退出指令，正在关闭浏览器...")
                    break
                print("[*] 浏览器仍然保持开启中。")
        finally:
            try:
                page.quit()
            except Exception:
                pass


def main():
    cfg = load_config()

    print("*" * 65)
    print("      Firestorm WoW 自动注册 (自动点 CF 验证)")
    print("*" * 65)

    print(f"[*] 正在读取历史注册记录文件 ({ACCOUNTS_FILE})...")
    history_records, reg_users, reg_emails, max_idx = read_accounts_history()
    print("-" * 65)
    print(f"[i] 当前已注册账号总数: {len(history_records)} 个")

    if history_records:
        print("[i] 最近注册的账号列表 (最新最多显示5个):")
        for idx, rec in enumerate(history_records[-5:], 1):
            print(f"    {idx}. 用户名: {rec['username']} | 邮箱: {rec['email']} | 时间: {rec.get('time', '-')}")
        print(f"[i] 分析发现: 邮箱历史最大序号已达 -> {max_idx}")
    else:
        print("[i] 历史记录为空，尚未注册过任何账号。")
    print("-" * 65)

    email_prefix = cfg["email_prefix"]
    email_domain = cfg["email_domain"]
    user_prefix = cfg.get("username_prefix", "myuser")
    rand_len = int(cfg.get("username_random_len", 4))
    pwd = cfg["password"]
    start_idx = int(cfg["start_index"])
    cf_timeout = int(cfg.get("cf_timeout", 60))

    # 智能识别起始序号
    if max_idx >= start_idx:
        suggest_idx = max_idx + 1
        print(f"[!] 提示: 配置的起始序号 {start_idx} 之前已被使用，已注册到序号 {max_idx}。")
        print(f"[+] 建议下一个起始序号为: {suggest_idx}")
        print(f"    即将从 {suggest_idx} 开始注册。")
        # 不阻塞等待输入 —— 序号判断是确定性的（历史最大序号 +1），
        # 直接用建议值继续，不需要人工确认。
        start_idx = suggest_idx

    print(f"\n[*] 本次注册配置:")
    print(f"    - 邮箱前缀   : {email_prefix}")
    print(f"    - 邮箱后缀   : {email_domain}")
    print(f"    - 起始序号   : {start_idx}")
    print(f"    - 用户名前缀 : {user_prefix} (后接 {rand_len} 位随机字符)")
    print(f"    - 固定密码   : {pwd}")
    print(f"    - CF 验证超时: {cf_timeout}s")
    print("*" * 65)

    # 启动原生 Chrome 浏览器
    co = ChromiumOptions()
    co.set_argument('--no-first-run')
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument('--window-size=800,600')
    if cfg.get("headless", False):
        co.headless(True)
    else:
        co.headless(False)

    # ---- 代理（可选）----
    # CF 对出口 IP 很敏感，换代理往往比改代码有效。
    # 支持 "http://ip:port" / "socks5://ip:port"，留空则直连。
    proxy = (cfg.get("proxy") or "").strip()
    if proxy:
        if "://" not in proxy:
            proxy = "http://" + proxy
        try:
            co.set_proxy(proxy)
            print(f"[*] 已启用代理: {proxy}")
        except Exception as e:
            print(f"[!] 代理设置失败({e})，改用直连")
    else:
        print("[*] 未配置代理，直连")

    print("\n[*] 正在启动浏览器环境...")
    page = ChromiumPage(co)
    try:
        page.set.window.size(800, 600)
    except Exception:
        pass

    # 开始之前完成本站域名会话清理（仅限 firestorm 域名，绝不影响其他网页）
    clear_domain_session(page)

    # 查找下一个可用的邮箱序号（防重复）
    current_idx = start_idx
    while f"{email_prefix}{current_idx}{email_domain}".lower() in reg_emails:
        print(f"[!] 邮箱 {email_prefix}{current_idx}{email_domain} 已存在于 accounts.txt，自动跳过...")
        current_idx += 1

    email = f"{email_prefix}{current_idx}{email_domain}"
    username = generate_unique_username(user_prefix, rand_len, reg_users)

    print(f"\n[*] 开始注册单个账号:")
    print(f"    - 用户名: {username}")
    print(f"    - 邮  箱: {email} (序号: {current_idx})")
    print(f"    - 密  码: {pwd}")
    print("*" * 65)

    reg_ok = False
    try:
        reg_ok = register_account(page, username, email, pwd, cf_timeout=cf_timeout)
        if reg_ok:
            reg_users.add(username.lower())
            reg_emails.add(email.lower())
            print(f"\n[+] 账号注册成功: {username} ({email})")
        else:
            print(f"\n[-] 账号注册未成功: {username} ({email})")
    except KeyboardInterrupt:
        print("\n[!] 用户中断了任务。")
    except Exception as e:
        print(f"\n[-] 运行提示: {e}")
    finally:
        print("\n" + "=" * 65)
        if reg_ok:
            print(f"[+] 注册任务结束，已成功注册账号: {username} ({email})")
        else:
            print(f"[-] 注册任务结束，本次未成功注册。")
        all_records, _, _, _ = read_accounts_history()
        print(f"[i] accounts.txt 当前累计有效总记录: {len(all_records)} 个账号")
        print(f"[*] 账号已保存至: {ACCOUNTS_FILE}")
        print("=" * 65)

        # 任务完成后是否保持浏览器 & 脚本常驻
        if cfg.get("keep_alive", True):
            managed = bool(os.environ.get("REGACCT_MANAGED_BY_GUI"))
            keep_alive(page, managed_by_gui=managed)
        else:
            print("[*] keep_alive=false，脚本将退出（浏览器仍保持开启）。")


if __name__ == "__main__":
    main()
