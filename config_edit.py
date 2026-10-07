"""
config_edit.py —— config.json 的按键级增删改，保留注释与格式。

设计要点（踩过的坑）：
- 手写注释是资产，不能 json.load -> json.dump 洗掉。
- 只改指定 key 的那一行文本，其余字节原样保留。
- 新 key 追加到 "}" 之前。
- 连续改同一个 key 必须字节还原（靠"注释锚点"定位，见 _find_key）。
"""
import io
import json
import os
import re

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# 默认值（与 register.py 的 DEFAULT_CONFIG 保持一致）
DEFAULTS = {
    "email_prefix": "user",
    "email_domain": "@example.com",
    "username_prefix": "myuser",
    "username_random_len": 4,
    "password": "CHANGE_ME",
    "start_index": 1,
    "headless": False,
    "keep_alive": True,
    "cf_timeout": 60,
    "proxy": "",
}

# 允许留空的选填项
OPTIONAL_KEYS = {"proxy"}

# GUI 里展示的元信息：(标签, 类型, 提示)
#   类型: str / int / bool
FIELDS = [
    ("email_prefix",         "邮箱前缀",       "str",  "邮箱形如 前缀1@域名，前缀+序号"),
    ("email_domain",         "邮箱域名",       "str",  "含 @，例如 @example.com"),
    ("username_prefix",      "用户名前缀",     "str",  "例如 myuser"),
    ("username_random_len",  "用户名随机位数", "int",  "前缀后追加的随机字符个数"),
    ("password",             "固定密码",       "str",  "所有账号同一密码"),
    ("start_index",          "起始序号",       "int",  "已被占用时脚本会自动推荐下一个"),
    ("headless",             "无头模式",       "bool", "建议关闭，无头环境更容易被 CF 拦"),
    ("keep_alive",           "完成后保持运行", "bool", "注册完不退出，浏览器也不关"),
    ("cf_timeout",           "CF验证超时(秒)", "int",  "单个账号等验证的最长时间"),
    ("proxy",                "代理",           "str",  "留空=直连；http://ip:端口 或 socks5://ip:端口"),
]


def ensure_config(path=CONFIG_PATH):
    """文件不存在时用默认值建一个。"""
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("{\n")
            items = list(DEFAULTS.items())
            for i, (k, v) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""
                f.write(f"    {json.dumps(k)}: {json.dumps(v)}{comma}\n")
            f.write("}\n")
    return path


def load_raw(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _strip_comment(line):
    """去掉行尾 // 注释（不做字符串感知的完整解析，够本文件用）。"""
    out, in_str, esc = [], False, False
    i = 0
    while i < len(line):
        c = line[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
                out.append(c)
            elif c == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break
            else:
                out.append(c)
        i += 1
    return "".join(out)


def read_config(path=CONFIG_PATH):
    """读配置，缺失键用默认值补上（只读，不写）。"""
    ensure_config(path)
    try:
        data = json.loads(load_raw(path))
    except Exception:
        data = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in data.items() if k in DEFAULTS})
    return out


def _find_key_span(text, key):
    """
    定位顶层 "key": value 所在的完整区间（含前导缩进，不含行尾注释）。

    返回 (start, end) 字符下标；找不到返回 None。
    只匹配行首缩进后紧跟 "key"，避免误中嵌套同名 key。
    """
    pat = re.compile(r'^([ \t]*)"' + re.escape(key) + r'"\s*:', re.M)
    m = pat.search(text)
    if not m:
        return None
    start = m.start()
    line_start = start
    i = m.end()
    n = len(text)
    in_str, esc, depth = False, False, 0
    while i < n:
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c in "[{":
                depth += 1
            elif c in "]}":
                if depth == 0:
                    return start, i          # 结束在 } 或 ] 之前
                depth -= 1
            elif c == "," and depth == 0:
                return start, i + 1
        i += 1
    return start, i


def _fmt_value(value):
    """按值的类型序列化成 JSON 字面量。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(str(value) if isinstance(value, str) else value)


def key_order(path=CONFIG_PATH):
    """当前文件里顶层键的出现顺序（只读）。"""
    text = load_raw(path)
    return [m.group(2) for m in re.finditer(r'^([ \t]*)"([^"]+)"\s*:', text, re.M)]


def set_key(key, value, path=CONFIG_PATH):
    """
    把某个 key 改成新值，保留其余文本与注释。返回是否真的改了。

    键不存在时退化为 insert_key（追加到末尾）。
    """
    if key not in DEFAULTS:
        raise KeyError(f"未知配置项: {key}")
    if (isinstance(value, str) and value.strip() == ""
            and key not in OPTIONAL_KEYS):
        raise ValueError(f"{key} 不能为空")

    text = load_raw(path)
    span = _find_key_span(text, key)
    if not span:
        return insert_key(key, value, path=path)

    # 值没变就不动文件，避免无意义的 mtime 抖动
    current = _strip_comment(text[span[0]:span[1]]).strip().rstrip(",").strip()
    if current == _fmt_value(value):
        return False

    start, end = span
    old = text[start:end]
    indent = re.match(r"^[ \t]*", old).group(0)
    # 区间可能已包含结尾逗号，也可能只到值末尾（末项），两种都要处理
    stripped_old = old.rstrip()
    lead_comma = stripped_old.endswith(",")
    cut = len(stripped_old)
    tail_comment = old[cut:]                     # 保留行尾注释

    new = f"{indent}{json.dumps(key)}: {_fmt_value(value)}"
    if lead_comma:
        new += ","

    new_text = text[:start] + new + tail_comment + text[end:]
    json.loads(new_text)                          # 写盘前先校验结构
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return True


def _anchor_after(text, key):
    """
    找 key **前面**最后一个顶层键名，作为"插回原位"的锚点。

    语义要想清楚：要把删掉的键放回原位，就该插到它**前一个键之后**。
    所以这里返回的是前驱，不是后继。

    删除再重建时靠它定位，才能保证字节还原（否则新键会被追加到文件末尾，
    顺序变了，diff 就脏了）。key 已在文件中时，返回它自己的前驱。
    """
    order = [m.group(2) for m in re.finditer(r'^([ \t]*)"([^"]+)"\s*:', text, re.M)]
    if key in order:
        idx = order.index(key)
        if idx > 0:
            return order[idx - 1]
    return None


def insert_key(key, value, after=None, path=CONFIG_PATH):
    """
    在指定键之后插入新键。after=None 时追加到末尾。
    返回是否真的改了文件。
    """
    if key not in DEFAULTS:
        raise KeyError(f"未知配置项: {key}")
    if (isinstance(value, str) and value.strip() == ""
            and key not in OPTIONAL_KEYS):
        raise ValueError(f"{key} 不能为空")

    text = load_raw(path)
    if _find_key_span(text, key):
        return set_key(key, value, path=path)

    block = f"    {json.dumps(key)}: {_fmt_value(value)}"

    if after:
        span = _find_key_span(text, after)
        if span:
            seg = text[span[0]:span[1]]
            end = span[1]
            # 同样不能看"自己后面有没有逗号"，只能看它是不是末项
            # （末项区间里也可能带着给下一个键用的逗号）
            is_last = text[end:].lstrip().startswith("}")
            stripped = seg.rstrip()
            if is_last:
                # 锚点是末项：给它补逗号，新键成为新的末项（不带逗号）
                # 末项区间里已经含行尾换行，rebuilt 必须把它去掉，
                # 否则会多出一个空行
                tail_comment = seg[len(seg.rstrip()):].strip()
                rebuilt = stripped.rstrip(",") + "," + (
                    ("  " + tail_comment) if tail_comment else ""
                )
                new_text = text[:span[0]] + rebuilt + "\n" + block + "\n" + text[end:]
            else:
                # 锚点是中间项：直接在新行之后插入
                new_text = text[:end] + "\n" + block + "," + text[end:]
            json.loads(new_text)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new_text)
            return True

    # 追加到末尾
    idx = text.rstrip().rfind("}")
    if idx == -1:
        raise ValueError("config.json 结构异常：找不到结尾 }")
    head = text[:idx].rstrip("\n")
    tail = text[idx:]

    # 空对象（"{}" 或 "{\n}"）—— 插入第一个键，不能带前导逗号
    if _strip_comment(head).strip() in ("{", ""):
        new_text = head.rstrip() + "\n" + block + "\n" + tail
        json.loads(new_text)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        return True

    stripped = _strip_comment(head.rstrip())
    if stripped and not stripped.rstrip().endswith(","):
        head = head.rstrip() + ",\n"
    elif not head.endswith("\n"):
        head = head + "\n"
    new_text = head + block + "\n" + tail
    json.loads(new_text)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return True


def delete_key(key, path=CONFIG_PATH):
    """
    删除某个键，保留其余文本与注释。返回 (是否删除, 原位锚点=前驱键名)。

    要处理两种位置：
      - 中间项（后面有逗号）：整行删掉
      - 末项  （后面没逗号）：删掉之后**必须把前一项补上逗号**，
        否则 JSON 会因为尾逗号而非法

    返回的前驱键用于后续 insert_key(after=...) 插回原位。
    """
    text = load_raw(path)
    span = _find_key_span(text, key)
    if not span:
        return False, None

    anchor = _anchor_after(text, key)
    start, end = span
    line_start = text.rfind("\n", 0, start) + 1

    # 是不是末项？不能看"自己后面有没有逗号"——末项的区间里也可能带着
    # 给下一个键用的逗号（末项被删后它就成了尾逗号）。
    # 判据是：区间之后是否直接就是结尾的 }。
    is_last = text[end:].lstrip().startswith("}")

    # 整行删掉。
    # _find_key_span 对末项会把行尾换行符一起纳入区间，对中间项则停在逗号后，
    # 所以只在"逗号之后紧跟换行"时才额外吃掉那个换行，避免多删一行。
    if not is_last and end < len(text) and text[end] == "\n":
        end += 1
    new_text = text[:line_start] + text[end:]

    if is_last:
        # 末项被删后，它原来的逗号会变成尾逗号 —— 必须把逗号撤掉，
        # 而不是给前一项补逗号。
        brace = new_text.rstrip().rfind("}")
        if brace != -1:
            head = new_text[:brace].rstrip()
            if head.endswith(","):
                new_text = head[:-1] + "\n" + new_text[brace:]

    data = json.loads(new_text)
    if key in data:
        raise ValueError(f"删除 {key} 后 key 仍存在")

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return True, anchor


def apply_all(values, path=CONFIG_PATH):
    """批量写入，返回实际发生变更的 key 列表。"""
    changed = []
    for key, value in values.items():
        try:
            if set_key(key, value, path=path):
                changed.append(key)
        except Exception as e:
            print(f"[config_edit] 写入 {key} 失败: {e}")
    return changed


def _key_of_seg(seg):
    m = re.search(r'"([^"]+)"\s*:', seg)
    return m.group(1) if m else ""


def _prev_key_span(text, before):
    """找 before 之前最近的一个顶层键区间。"""
    pat = re.compile(r'^([ \t]*)"([^"]+)"\s*:', re.M)
    last = None
    for m in pat.finditer(text):
        if m.start() >= before:
            break
        s = m.start()
        e = _find_key_span(text, m.group(2))
        if e:
            last = (s, e[1])
    return last


def self_test():
    """
    字节还原自检：增 -> 改 -> 删 -> 还原，断言文件字节与原始完全一致。
    """
    import shutil
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="cfgtest_")
    p = os.path.join(tmpdir, "config.json")
    try:
        ensure_config(p)
        original = load_raw(p)
        print(f"[self-test] 初始 {len(original)} 字节, {len(original.splitlines())} 行")

        # 1. 改已有键 -> 还原
        set_key("username_random_len", 6, path=p)
        assert json.loads(load_raw(p))["username_random_len"] == 6, "改已有键失败"
        set_key("username_random_len", 4, path=p)
        assert load_raw(p) == original, "改回原值未字节还原"
        print("[self-test] 改 -> 还原 OK")

        # 2. 删中间项 -> 按原位插回 -> 字节还原
        _, anchor = delete_key("username_random_len", path=p)
        assert "username_random_len" not in json.loads(load_raw(p)), "删中间项失败"
        insert_key("username_random_len", 4, after=anchor, path=p)
        assert load_raw(p) == original, f"删除后重建(中间项)未字节还原\n{load_raw(p)!r}"
        print("[self-test] 删中间项 -> 原位插回 OK")

        # 3. 删末项 -> 按原位插回 -> 字节还原（末项补逗号，最易出错）
        _, anchor = delete_key("cf_timeout", path=p)
        assert "cf_timeout" not in json.loads(load_raw(p)), "删末项失败"
        insert_key("cf_timeout", 60, after=anchor, path=p)
        assert load_raw(p) == original, f"删除后重建(末项)未字节还原\n{load_raw(p)!r}"
        print("[self-test] 删末项 -> 原位插回 OK")

        # 4. 同值写入不应改动文件
        set_key("email_domain", "@example.com", path=p)
        assert load_raw(p) == original
        print("[self-test] 同值写入不改动文件 OK")

        # 5. 删到空对象，途中每次都必须是合法 JSON
        for k in ["username_random_len", "cf_timeout", "keep_alive"]:
            delete_key(k, path=p)
            json.loads(load_raw(p))
        print("[self-test] 批量删除后仍是合法 JSON OK")

        # 6. 全部删光再全部加回 -> 字节还原
        for k in list(DEFAULTS.keys()):
            if k in json.loads(load_raw(p)):
                delete_key(k, path=p)
        json.loads(load_raw(p))
        assert json.loads(load_raw(p)) == {}, "应删成空对象"
        order = [k for k in DEFAULTS if k in original]
        for i, k in enumerate(order):
            insert_key(k, DEFAULTS[k],
                       after=order[i - 1] if i else None, path=p)
        assert load_raw(p) == original, "全删后重建未字节还原"
        print("[self-test] 全删 -> 全建 -> 字节还原 OK")

        print("\n[self-test] 全部通过：增删改均可字节还原")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    self_test()
