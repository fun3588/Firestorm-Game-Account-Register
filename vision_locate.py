"""
vision_locate.py —— 在浏览器截图里视觉定位 Turnstile 勾选框。

为什么需要这个：
Cloudflare 有时不给 iframe 也不给坐标（invisible 模式、或容器结构变了），
DOM 里查不到任何可点元素。但勾选框**在屏幕上确实画出来了**。
那就直接看图 —— 找到那个方框，返回它的屏幕坐标。

实现：PIL 取图 + numpy 做积分图，**不用 cv2**
（本机 cv2 与 numpy 2.x 不兼容，import 就崩）。

性能要点（第一版纯 Python 像素循环全屏要几十秒，实用不了）：
- 用**积分图**（cumsum）把"一条边上有几个暗像素"从 O(side) 降到 O(1)
- 一张 1400x800 全屏图的构建约 16ms，之后每个候选框 4 次查询
- 只在 CF 容器区域（512x70）内搜索时更快

思路：
勾选框是"浅色圆角方框"，边框比内部暗、比背景浅。
找四条边都足够暗、内部偏亮的区域，打分最高的就是它。
"""
import io
import time

import numpy as np
from PIL import Image


def grab(page):
    """抓当前可视区域的 PNG 字节（视口截图，不是整页）。"""
    try:
        import base64
        res = page.run_cdp("Page.captureScreenshot", format="png")
        return base64.b64decode(res["data"])
    except Exception:
        try:
            return page.get_screenshot(as_bytes=True, as_base64=False)
        except Exception:
            return None


def _to_array(png_bytes):
    """PNG 字节 -> 灰度 numpy 数组（uint8）。"""
    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    return np.asarray(img, dtype=np.uint8)


# 勾选框的典型边长（Turnstile 常态 24~40px）
MIN_SIDE = 16
MAX_SIDE = 56

# 边框比背景至少暗这么多，才认定"这里有个框"
MIN_CONTRAST = 18


def find_checkbox(png_bytes, region=None, expect=None, verbose=False):
    """
    在截图里找 Turnstile 勾选框。

    返回 dict(x, y, side, score)：中心点屏幕坐标 + 边长 + 置信度；
    找不到返回 None。

    region: 可选 (x, y, w, h) 限定搜索范围（视口坐标），
            一般传 CF 容器的 rect —— 能大幅提速并避免误判。
            **强烈建议传**：全屏 1400x800 约 6s，容器区域约 0.4s。

    expect: 可选 (x, y) **期望位置**（勾选框中心的先验坐标，通常是
            容器左上 + (30, 高/2)）。给了之后会按距离给候选降权 ——
            这一条非常关键：页面里有很多"长得像方框"的东西
            （输入框底边、图标按钮），不加约束会锁定到它们身上。
    """
    t0 = time.time()
    try:
        gray = _to_array(png_bytes)
    except Exception:
        return None

    ox = oy = 0
    scale = 1
    if region:
        ox, oy, rw, rh = region
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(gray.shape[1], ox + rw), min(gray.shape[0], oy + rh)
        if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
            return None
        gray = gray[y0:y1, x0:x1]
    else:
        # 全屏搜索很慢。降采样后再找，最后把坐标放大回去 ——
        # 勾选框在原图里有几十像素，缩到 1/2 仍有 12~20px，够识别。
        step_ds = 2
        gray = gray[::step_ds, ::step_ds]
        scale = step_ds
    h, w = gray.shape
    if h < MIN_SIDE or w < MIN_SIDE:
        return None

    # ---- 自适应阈值 ----
    # 踩过的坑：不能假设"背景是亮的"。
    # Firestorm 注册页是**深色背景**，CF 勾选框是"白底浅灰边框"，
    # 周围是大片暗色 —— 用 percentile(95) 会把框内部的白色当成背景，
    # 于是阈值失效，匹配到页面里随便一个深色块（比如右下角徽标）。
    #
    # 正确做法：勾选框本身是**区域内最亮的一小块**。
    # 先按亮度分位找出"亮部"，再在亮部里找"比亮部稍暗的边框"。
    flat = gray.ravel().astype(np.float32)

    p50 = float(np.percentile(flat, 50))
    p90 = float(np.percentile(flat, 90))
    # 亮部基准：取 p90 与最大值的一半（框内白色通常接近 255）
    bright_level = min(250.0, max(p90, (p90 + 255.0) / 2.0))
    DARK = bright_level - MIN_CONTRAST

    if verbose:
        print(f"      [vision] 区域 {w}x{h} p50={p50:.0f} p90={p90:.0f} "
              f"亮部≈{bright_level:.0f} 边框阈值={DARK:.0f}")

    dark = (gray < DARK).astype(np.int32)

    # 积分图：dark 的二维前缀和，任意矩形内暗像素数可 O(1) 求出
    ii = dark.cumsum(axis=0).cumsum(axis=1)
    # 灰度积分图，用来算"边框平均亮度"
    gi = gray.astype(np.int32).cumsum(axis=0).cumsum(axis=1)

    def rect_sum(integ, x, y, ww, hh):
        """[y, y+hh) x [x, x+ww) 的和（前缀和 O(1)）。"""
        y2, x2 = y + hh, x + ww
        s = integ[y2 - 1, x2 - 1]
        if x > 0:
            s -= integ[y2 - 1, x - 1]
        if y > 0:
            s -= integ[y - 1, x2 - 1]
            if x > 0:
                s += integ[y - 1, x - 1]
        return s

    best = None
    best_total = 0.0
    need_ratio = 0.55
    edge_n = 6                       # 每条边至少 6 个采样点判暗
    # 全屏降采样后边长也缩小了，下限跟着降
    side_min = MIN_SIDE if region else max(12, MIN_SIDE // 2)
    side_max = MAX_SIDE if region else max(20, MAX_SIDE // 2)

    # 期望位置（换算到裁剪后的坐标系），用于距离降权
    exp_x = exp_y = None
    if expect:
        exp_x = (expect[0] - ox) / scale
        exp_y = (expect[1] - oy) / scale
        # 容差：允许偏离期望多少像素仍算候选
        tol_x = 90.0 / scale
        tol_y = 70.0 / scale

    for side in range(side_min, min(side_max, min(w, h)) + 1):
        # 四条边的取样步长：保证至少取到 edge_n 个点
        step = max(1, side // edge_n)
        offs = list(range(0, side, step))
        if not offs:
            continue
        need = max(3, int(len(offs) * need_ratio))

        # 候选位置步进：命中率高时可以粗扫，score 低再细化
        coarse = 2 if side > 28 else 1

        for y in range(0, h - side + 1, coarse):
            for x in range(0, w - side + 1, coarse):
                # --- 上边 / 下边：一行 ---
                top_dark = rect_sum(ii, x, y, side, 1)
                bot_dark = rect_sum(ii, x, y + side - 1, side, 1)
                if top_dark < need or bot_dark < need:
                    continue
                # --- 左边 / 右边：一列 ---
                left_dark = rect_sum(ii, x, y, 1, side)
                right_dark = rect_sum(ii, x + side - 1, y, 1, side)
                if left_dark < need or right_dark < need:
                    continue

                # 边框平均亮度（四条边）
                b_sum = (rect_sum(gi, x, y, side, 1)
                         + rect_sum(gi, x, y + side - 1, side, 1)
                         + rect_sum(gi, x, y, 1, side)
                         + rect_sum(gi, x + side - 1, y, 1, side))
                b_cnt = 2 * side + 2 * side - 4
                border_avg = b_sum / b_cnt

                # 内部：用中位数抗对勾干扰
                m = side // 4
                if m < 1:
                    m = 1
                inner = gray[y + m:y + side - m, x + m:x + side - m]
                if inner.size == 0:
                    continue
                inner_med = int(np.median(inner))

                # 内部整体太暗 -> 是深色背景/图片/色块，不是勾选框
                if inner_med < DARK:
                    continue
                # 内部必须明显比边框亮，否则"框"不成立
                if inner_med < border_avg + MIN_CONTRAST * 0.6:
                    continue

                contrast = inner_med - border_avg
                score = max(0.0, min(1.0, (contrast - MIN_CONTRAST * 0.5) / 26.0))
                if score < 0.30:
                    continue

                # 尺寸偏好：Turnstile 勾选框典型 24~40px（降采样后按比例缩）。
                # 对勾会打断边框，让小尺寸更容易"碰巧"满足四边条件，
                # 所以对明显偏小的框降权，避免锁定到对勾碎片上。
                real_min, real_max = 22 * scale, 46 * scale
                if side < real_min:
                    score *= 0.55
                elif side > real_max:
                    score *= 0.85

                # ---- 距离降权（关键）----
                # 页面里"长得像方框"的东西很多：输入框底边、图标按钮、
                # logo 边框……不加约束会锁定到最先扫到的那个。
                # Turnstile 勾选框的位置是**确定的**：容器左侧 30px、垂直居中，
                # 所以离期望位置越远，越不可能是它。
                total = score
                if exp_x is not None:
                    cx_local = x + side / 2.0
                    cy_local = y + side / 2.0
                    dx = abs(cx_local - exp_x) / tol_x
                    dy = abs(cy_local - exp_y) / tol_y
                    dist_pen = max(dx, dy)          # 0=正好，1=在容差边缘
                    if dist_pen >= 1.0:
                        continue                   # 超出容差，直接不是它
                    total *= (1.0 - 0.75 * dist_pen)   # 容差内线性降权

                if total > best_total:
                    best_total = total
                    cand = {
                        "x": int(ox + x * scale + (side * scale) // 2),
                        "y": int(oy + y * scale + (side * scale) // 2),
                        "side": side * scale,
                        "score": round(float(score), 3),
                        "match": round(float(total), 3),
                    }
                    best = cand

    if verbose and best:
        best["elapsed"] = round(time.time() - t0, 2)
    return best


def locate_and_click(page, container_box, tries=3, verbose=True):
    """
    视觉定位 + 点击勾选框。

    container_box: CF 容器的视口 rect (x, y, w, h)，限定搜索范围；
                   传 None 表示全屏搜索（慢，不推荐）。

    返回 (是否点到, 描述)。**点到不代表验证通过**，只代表"点下去了"，
    调用方要自己再读一次 token。
    """
    # 期望位置：勾选框在容器左侧约 30px、垂直居中。
    # 这个先验很重要 —— 页面上有很多"长得像方框"的东西。
    expect = None
    if container_box:
        cb_x, cb_y, cb_w, cb_h = container_box
        expect = (cb_x + 30, cb_y + cb_h // 2)

    for attempt in range(1, tries + 1):
        png = grab(page)
        if not png:
            if verbose:
                print("    · 截图失败，无法视觉定位")
            return False, "截图失败"

        t0 = time.time()
        hit = find_checkbox(png, region=container_box, expect=expect)
        dt = time.time() - t0

        if not hit:
            if verbose:
                print(f"    · 视觉定位第 {attempt} 次：未找到勾选框（{dt:.1f}s）")
            time.sleep(1.5)
            continue

        if verbose:
            print(f"    · 视觉定位命中: ({hit['x']}, {hit['y']}) "
                  f"边长={hit['side']}px 置信={hit['score']} "
                  f"匹配={hit.get('match')} 耗时={dt:.1f}s")

        from register import real_mouse_click
        real_mouse_click(page, hit["x"], hit["y"])
        time.sleep(2.5)
        return True, f"视觉定位点击 ({hit['x']}, {hit['y']})"

    return False, "视觉定位未找到勾选框"


if __name__ == "__main__":
    import time as _t
    from PIL import Image, ImageDraw

    def make(box, bg, border, width=2, check=True):
        """box = (x, y, w, h)"""
        x, y, w_, h_ = box
        img = Image.new("RGB", (x + w_ + 140, y + h_ + 90), bg)
        d = ImageDraw.Draw(img)
        d.rectangle([x, y, x + w_, y + h_], outline=border, width=width)
        if check:
            cx, cy = x + w_ // 2, y + h_ // 2
            d.line([cx - 7, cy, cx - 2, cy + 6], fill=border, width=2)
            d.line([cx - 2, cy + 6, cx + 7, cy - 6], fill=border, width=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), (x + w_ // 2, y + h_ // 2)

    cases = [
        ("浅灰边框/白底/空框", (60, 40, 25, 25), (250, 250, 250), (200, 200, 200), False),
        ("深灰边框/白底/空框", (60, 40, 28, 28), (252, 252, 252), (160, 160, 160), False),
        ("灰边框/白底/已勾选", (50, 30, 30, 30), (248, 248, 248), (170, 170, 170), True),
        ("小尺寸 20px", (80, 50, 20, 20), (255, 255, 255), (190, 190, 190), False),
        ("大尺寸 40px", (40, 25, 40, 40), (245, 245, 245), (175, 175, 175), False),
    ]

    ok = 0
    for name, box, bg, border, chk in cases:
        x, y, w_, h_ = box
        # 模拟真实用法：传 region + expect（勾选框在容器左侧 30px、垂直居中）
        cb_x, cb_y, cb_w, cb_h = x - 30, y, w_ + 60, h_
        region = (max(0, cb_x - 40), max(0, cb_y - 25), cb_w + 80, cb_h + 50)
        expect = (cb_x + 30, cb_y + cb_h // 2)
        png, expect2 = make(box, bg, border, check=chk)
        hit = find_checkbox(png, region=region, expect=expect)
        if not hit:
            print(f"[FAIL] {name}: 未找到")
            continue
        dx, dy = abs(hit["x"] - expect2[0]), abs(hit["y"] - expect2[1])
        good = dx <= 6 and dy <= 6
        print(f"[{'PASS' if good else 'FAIL'}] {name}: "
              f"找到({hit['x']},{hit['y']}) 期望({expect2[0]},{expect2[1]}) "
              f"偏差({dx},{dy}) 边长={hit['side']} 置信={hit['score']}")
        ok += 1 if good else 0

    # 干扰测试：搜索区域里放多个"像方框"的元素（复现真实页面的坑）
    # 真实页面有输入框底边、图标按钮等，不加 expect 会锁定到最先扫到的那个
    img = Image.new("RGB", (700, 300), (30, 40, 55))
    d = ImageDraw.Draw(img)
    d.rectangle([300, 60, 660, 100], fill=(250, 250, 250))          # 输入框
    d.rectangle([300, 110, 660, 150], fill=(250, 250, 250))         # 输入框
    d.rectangle([120, 120, 160, 160], fill=(250, 250, 250))         # 图标按钮
    d.rectangle([540, 120, 590, 170], outline=(200, 200, 200), width=2)  # 真勾选框
    cbx, cby, cbw, cbh = 510, 110, 100, 70
    bb = io.BytesIO(); img.save(bb, format="PNG")
    region = (cbx - 60, cby - 40, cbw + 120, cbh + 80)
    expect = (cbx + 30, cby + cbh // 2)
    hit = find_checkbox(bb.getvalue(), region=region, expect=expect)
    good = hit and abs(hit["x"] - expect[0]) <= 6 and abs(hit["y"] - expect[1]) <= 6
    print(f"[{'PASS' if good else 'FAIL'}] 多干扰框下仍锁定真勾选框: {hit}")
    if good:
        ok += 1

    # 负例：纯白图不该瞎报（同样走 region 路径）
    blank = Image.new("RGB", (300, 160), (250, 250, 250))
    b = io.BytesIO(); blank.save(b, format="PNG")
    no_hit = find_checkbox(b.getvalue(), region=(40, 30, 220, 100)) is None
    print(f"[{'PASS' if no_hit else 'FAIL'}] 纯白图不误报")
    if no_hit:
        ok += 1

    # 性能：模拟真实视口 1400x800，限定 CF 容器区域（实际走的路径）
    big = Image.new("RGB", (1400, 800), (250, 250, 250))
    ImageDraw.Draw(big).rectangle([420, 400, 450, 430],
                                   outline=(200, 200, 200), width=2)
    bb2 = io.BytesIO(); big.save(bb2, format="PNG")
    bp = bb2.getvalue()

    reg = (400, 380, 520, 70)
    exp = (430, 415)
    t = _t.time()
    r_region = find_checkbox(bp, region=reg, expect=exp)
    t_region = _t.time() - t
    print(f"[perf] 容器区域(520x70): {t_region:.2f}s -> {r_region}")

    t = _t.time(); r_full = find_checkbox(bp)
    t_full = _t.time() - t
    print(f"[perf] 全屏降采样(1400x800): {t_full:.2f}s -> {r_full}")

    perf_ok = t_region < 3.0 and t_full < 12.0
    print(f"[{'PASS' if perf_ok else 'FAIL'}] 性能达标（区域<3s 全屏<12s）")
    if perf_ok:
        ok += 1

    total = len(cases) + 3
    print(f"\n[self-test] {ok}/{total} 通过")
