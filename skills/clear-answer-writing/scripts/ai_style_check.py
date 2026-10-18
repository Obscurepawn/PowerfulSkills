#!/usr/bin/env python3
"""对中文 Markdown 长文做 AI 写作痕迹的剂量检查。

只统计正文：跳过 front matter、代码块、$$ 公式、表格、图片、HTML 锚点和链接定义。
输出每项指标、阈值和命中行号，供改稿时逐条处理。指标是线索，不是判决：
超阈值说明“密度可疑”，具体是否要改由写作者按 SKILL.md 判断。

用法：
    python3 ai_style_check.py article.md            # 人读报告
    python3 ai_style_check.py article.md --json     # 机器读
    python3 ai_style_check.py article.md --max-hits 20
退出码：0 = 无超标项；1 = 有超标项；2 = 输入错误。
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

# ---- 模式 ----------------------------------------------------------------

NEGATION_CAVEAT = re.compile(
    r"(?<!能)不能(?!不)|不代表|不等于|不意味着|并不|未必|不必然|不自动|不一定|无法据此|不足以|"
    r"不证明|不应据此|不宜"
)
HEDGE = re.compile(r"可能|通常|往往|一般来说|一般会|某些|在一定程度上|某种程度上|视情况")
DIRECTIVE = re.compile(r"应当|应该|(?<![对反适响供相])应(?![用答对该当])|必须|需要|要先|务必")
DISCLAIMER = re.compile(
    r"(示例|假设|示意|演示|说明用|举例)[^。；\n]{0,30}(不是|并非|不代表|而非|不属于)[^。；\n]{0,20}"
    r"(实测|测量|测得|目标|结果|基准|硬件)|"
    r"(不是|并非)[^。；\n]{0,12}(实测|测量结果|性能目标)|尚未[^。；\n]{0,10}(实机|实测|验证)"
)
DISTINGUISH = re.compile(r"分清|分开|区分|两个问题|不同的问题|几个独立问题|三个独立问题|两种能力")
META = re.compile(
    r"本文|本章|本节|前面已经|前文已经|上文|接下来|下面(先|再|来)?(介绍|讲|看|说明)|"
    r"回到开头|现在可以回到"
)
NOT_A_BUT_B = re.compile(r"不是[^。；，\n]{1,25}，?而是|不仅[^。；\n]{1,25}(更|还|也)")
SUMMARY_TAIL = re.compile(
    r"^(因此|所以|总之|总的来说|综上|这样|也就是说|换句话说|可见|由此)|"
    r"就不会|才(能|有|足以)|取决于[^。]*不取决于|这也解释了"
)
FIRST_PERSON = re.compile(r"我(?!们)")
WE = re.compile(r"我们")
HEADING = re.compile(r"^(#{2,4})\s+(.*)$")
HEADING_CONCLUSION = re.compile(r"不等于|不必然|无法|并不|未必|决定了|还要|需要|要先|^先|是两个问题")
HEADING_QUESTION = re.compile(r"为什么|如何|怎么|怎样|什么|哪|？|\?")


def is_conclusion_heading(title):
    """逗号断开的长标题算结论式；纯问句标题不算（问句标题是推荐写法）。"""
    if "，" in title:
        return True
    return not HEADING_QUESTION.search(title) and bool(HEADING_CONCLUSION.search(title))
HEADING_NUM_PREFIX = re.compile(r"^[\d.]+\s*")

SENT_SPLIT = re.compile(r"(?<=[。！？；])")

# ---- 阈值（每千个非空白正文字符） -------------------------------------------
# 用一篇典型“AI 技术长文”校准：该文否定限定 3.2/千字、指令 5.7/千字、
# 平均 335 字一个标题。阈值取明显低于它、又不至于误伤正常技术文的位置。
THRESHOLDS = {
    "negation_per_k": 1.5,
    "hedge_per_k": 1.8,
    "directive_per_k": 3.5,
    "caveat_tail_ratio": 0.20,     # 以否定/限定句收尾的段落占比
    "disclaimer_count": 1,         # “这是示例不是实测”类声明，全文最多 1 次
    "distinguish_count": 4,
    "meta_count": 3,
    "not_a_but_b_count": 3,
    "chars_per_heading_min": 600,  # 平均每个标题覆盖的字数下限
    "heading_conclusion_ratio": 0.35,
    "heading_same_prefix": 3,      # 同一起首字的标题数上限
    "section_summary_ratio": 0.30, # 以总结句收尾的小节占比
}


MIN_CHARS_FOR_DENSITY = 1500


def strip_non_prose(lines):
    """返回 [(行号, 文本, 类型)]，类型为 prose / heading；其余行丢弃。"""
    out = []
    in_code = in_math = False
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    for idx in range(start, len(lines)):
        raw = lines[idx]
        s = raw.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if s == "$$":
            in_math = not in_math
            continue
        if in_code or in_math:
            continue
        if s.startswith("$$") and s.endswith("$$") and len(s) > 4:
            continue
        if not s or s.startswith("|") or s.startswith("![") or s.startswith("<a ") \
                or re.match(r"^\[[^\]]+\]:\s*\S+", s) or s in ("---", "***"):
            out.append((idx + 1, "", "blank"))
            continue
        m = HEADING.match(s)
        if m:
            out.append((idx + 1, m.group(2).strip(), "heading"))
            continue
        if s.startswith("# "):
            continue  # 文章大标题
        text = re.sub(r"`[^`]*`", "X", s)            # 行内代码
        text = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", text)  # 引用式链接
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"\$[^$]+\$", "X", text)
        out.append((idx + 1, text, "prose"))
    return out


def paragraphs(items):
    """把连续 prose 行合并成段落：[(起始行号, 段落文本)]。"""
    paras, buf, first = [], [], None
    for ln, text, kind in items:
        if kind == "prose":
            if first is None:
                first = ln
            buf.append(text)
        else:
            if buf:
                paras.append((first, "".join(buf)))
            buf, first = [], None
    if buf:
        paras.append((first, "".join(buf)))
    return paras


def sentences(text):
    return [x for x in SENT_SPLIT.split(text) if x.strip()]


def hits(items, pattern):
    res = []
    for ln, text, kind in items:
        if kind != "prose":
            continue
        n = len(pattern.findall(text))
        if n:
            res.append((ln, n, text))
    return res


def analyze(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    # 参考资料之后不计入
    for i, l in enumerate(lines):
        if re.match(r"^#{1,3}\s*(参考资料|参考文献|References)", l.strip()):
            lines = lines[:i]
            break
    items = strip_non_prose(lines)
    prose = "".join(t for _, t, k in items if k == "prose")
    chars = len(re.sub(r"\s", "", prose))
    k = max(chars / 1000, 0.001)
    paras = paragraphs(items)
    headings = [(ln, t) for ln, t, kind in items if kind == "heading"]

    def per_k(pat):
        return round(len(pat.findall(prose)) / k, 2)

    # 段尾限定
    tail_hits = []
    for ln, p in paras:
        ss = sentences(p)
        if len(p) >= 40 and ss and (NEGATION_CAVEAT.search(ss[-1]) or HEDGE.search(ss[-1])):
            tail_hits.append((ln, ss[-1].strip()))
    long_paras = [p for p in paras if len(p[1]) >= 40]
    tail_ratio = round(len(tail_hits) / max(len(long_paras), 1), 2)

    # 小节末段总结句
    section_ends = []
    cur_last = None
    for ln, text, kind in items + [(10**9, "", "heading")]:
        if kind == "heading":
            if cur_last:
                section_ends.append(cur_last)
            cur_last = None
        elif kind == "prose":
            cur_last = (ln, text)
    summary_hits = []
    for ln, text in section_ends:
        ss = sentences(text)
        last = ss[-1].strip() if ss else ""
        if last and SUMMARY_TAIL.search(last):
            summary_hits.append((ln, last))
    summary_ratio = round(len(summary_hits) / max(len(section_ends), 1), 2)

    # 标题
    titles = [HEADING_NUM_PREFIX.sub("", t) for _, t in headings]
    concl = [(ln, t) for (ln, t), tt in zip(headings, titles) if is_conclusion_heading(tt)]
    prefix_count = {}
    for (ln, t), tt in zip(headings, titles):
        if tt:
            prefix_count.setdefault(tt[0], []).append((ln, t))
    worst_prefix = max(prefix_count.items(), key=lambda kv: len(kv[1]), default=("", []))

    para_lens = [len(p) for _, p in long_paras]
    cv = round(statistics.pstdev(para_lens) / statistics.mean(para_lens), 2) if len(para_lens) > 2 else None

    disclaimer = hits(items, DISCLAIMER)

    m = {
        "chars": chars,
        "negation_per_k": per_k(NEGATION_CAVEAT),
        "hedge_per_k": per_k(HEDGE),
        "directive_per_k": per_k(DIRECTIVE),
        "caveat_tail_ratio": tail_ratio,
        "disclaimer_count": len(disclaimer),
        "distinguish_count": len(DISTINGUISH.findall(prose)),
        "meta_count": len(META.findall(prose)),
        "not_a_but_b_count": len(NOT_A_BUT_B.findall(prose)),
        "headings": len(headings),
        "chars_per_heading": round(chars / max(len(headings), 1)),
        "heading_conclusion_ratio": round(len(concl) / max(len(headings), 1), 2),
        "heading_same_prefix": len(worst_prefix[1]),
        "section_summary_ratio": summary_ratio,
        "first_person_count": len(FIRST_PERSON.findall(prose)),
        "we_count": len(WE.findall(prose)),
        "paragraph_length_cv": cv,
    }

    flags = []
    density_keys = {"negation_per_k", "hedge_per_k", "directive_per_k", "caveat_tail_ratio",
                    "chars_per_heading", "heading_conclusion_ratio", "section_summary_ratio"}
    short = chars < MIN_CHARS_FOR_DENSITY

    def over(key, value, limit, msg, evidence):
        if short and key in density_keys:
            return  # 短文本一两处命中就会让密度失真，只看计数类指标
        flags.append({"metric": key, "value": value, "limit": limit, "advice": msg, "evidence": evidence})

    T = THRESHOLDS
    if m["negation_per_k"] > T["negation_per_k"]:
        over("negation_per_k", m["negation_per_k"], T["negation_per_k"],
             "否定式限定过密：只留读者真会踩的坑，其余删除或并入一处“常见误区”。",
             [(ln, t) for ln, _, t in hits(items, NEGATION_CAVEAT)])
    if m["hedge_per_k"] > T["hedge_per_k"]:
        over("hedge_per_k", m["hedge_per_k"], T["hedge_per_k"],
             "模糊情态过密：有依据就直接下判断；真正的条件写成“在 X 时”，不要用“可能/通常”兜底。",
             [(ln, t) for ln, _, t in hits(items, HEDGE)])
    if m["directive_per_k"] > T["directive_per_k"]:
        over("directive_per_k", m["directive_per_k"], T["directive_per_k"],
             "指令口吻过密：把一部分“应/需要/必须”改写成“否则会……”，讲后果而不是下命令。",
             [(ln, t) for ln, _, t in hits(items, DIRECTIVE)])
    if m["caveat_tail_ratio"] > T["caveat_tail_ratio"]:
        over("caveat_tail_ratio", m["caveat_tail_ratio"], T["caveat_tail_ratio"],
             "太多段落以限定句收尾：让段落停在事实、结论或具体后果上。", tail_hits)
    if m["disclaimer_count"] > T["disclaimer_count"]:
        over("disclaimer_count", m["disclaimer_count"], T["disclaimer_count"],
             "“这是示例/假设，不是实测”重复声明：全文开头统一说一次，正文删掉。",
             [(ln, t) for ln, _, t in disclaimer])
    if m["distinguish_count"] > T["distinguish_count"]:
        over("distinguish_count", m["distinguish_count"], T["distinguish_count"],
             "反复表演“要分清 X 和 Y”：直接写出两者差在哪里，不预告“这是两个问题”。",
             [(ln, t) for ln, _, t in hits(items, DISTINGUISH)])
    if m["meta_count"] > T["meta_count"]:
        over("meta_count", m["meta_count"], T["meta_count"],
             "元叙述过多（本文/前面已经/接下来）：删掉预告和回顾，直接进入内容。",
             [(ln, t) for ln, _, t in hits(items, META)])
    if m["not_a_but_b_count"] > T["not_a_but_b_count"]:
        over("not_a_but_b_count", m["not_a_but_b_count"], T["not_a_but_b_count"],
             "“不是 A 而是 B / 不仅…更…”过多：只在纠正真实误解时用。",
             [(ln, t) for ln, _, t in hits(items, NOT_A_BUT_B)])
    if m["headings"] >= 4 and m["chars_per_heading"] < T["chars_per_heading_min"]:
        over("chars_per_heading", m["chars_per_heading"], T["chars_per_heading_min"],
             "标题过密：合并相邻小节，长文控制在每 600–1200 字一个标题。", headings)
    if m["headings"] >= 4 and m["heading_conclusion_ratio"] > T["heading_conclusion_ratio"]:
        over("heading_conclusion_ratio", m["heading_conclusion_ratio"], T["heading_conclusion_ratio"],
             "结论句式标题过多：标题写对象或问题，结论留给正文。", concl)
    if m["heading_same_prefix"] > T["heading_same_prefix"]:
        over("heading_same_prefix", m["heading_same_prefix"], T["heading_same_prefix"],
             f"{m['heading_same_prefix']} 个标题以“{worst_prefix[0]}”开头：句式重复，换掉多数。",
             worst_prefix[1])
    if m["section_summary_ratio"] > T["section_summary_ratio"]:
        over("section_summary_ratio", m["section_summary_ratio"], T["section_summary_ratio"],
             "小节结尾总结句过多：读者已懂的复述直接删；要留就换成一个具体的坑或可执行建议。",
             summary_hits)
    notes = []
    if short:
        notes.append(f"正文仅 {chars} 字（< {MIN_CHARS_FOR_DENSITY}），密度和比例类指标不判定，只检查计数类指标。")
    if chars > 5000 and m["first_person_count"] == 0:
        notes.append("全文没有“我”：看不出作者。若有真实经历/实测，可在关键处用第一人称写两三句；没有就不要编。")
    if cv is not None and cv < 0.35 and len(para_lens) > 15:
        notes.append(f"段落长度变异系数 {cv}，段落长短过于均匀：重要处展开，次要处一两句带过。")
    return m, flags, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-hits", type=int, default=8, help="每项最多列出的命中行数")
    a = ap.parse_args()
    if not Path(a.file).is_file():
        print(f"找不到文件：{a.file}", file=sys.stderr)
        return 2
    m, flags, notes = analyze(a.file)
    if a.json:
        print(json.dumps({"metrics": m, "thresholds": THRESHOLDS, "flags": flags, "notes": notes},
                         ensure_ascii=False, indent=2))
        return 1 if flags else 0
    print(f"# AI 写作痕迹检查：{a.file}")
    print(f"正文 {m['chars']} 字，标题 {m['headings']} 个，“我” {m['first_person_count']} 次，“我们” {m['we_count']} 次\n")
    print("| 指标 | 数值 | 阈值 |\n|---|---:|---:|")
    labels = {
        "negation_per_k": "否定式限定/千字", "hedge_per_k": "模糊情态/千字", "directive_per_k": "指令口吻/千字",
        "caveat_tail_ratio": "以限定句收尾的段落占比", "disclaimer_count": "示例/未实测声明次数",
        "distinguish_count": "“要分清”类表述", "meta_count": "元叙述", "not_a_but_b_count": "不是A而是B",
        "chars_per_heading": "平均每标题字数(下限)", "heading_conclusion_ratio": "结论式标题占比",
        "heading_same_prefix": "同起首字标题数", "section_summary_ratio": "小节总结句收尾占比",
    }
    lim = dict(THRESHOLDS, chars_per_heading=THRESHOLDS["chars_per_heading_min"])
    flagged = {f["metric"] for f in flags}
    for key, label in labels.items():
        mark = " ⚠" if key in flagged else ""
        print(f"| {label} | {m[key]}{mark} | {lim[key]} |")
    if not flags:
        print("\n未发现超阈值项。阈值只覆盖可计数的模式，仍需按 SKILL.md 人工通读。")
    for f in flags:
        print(f"\n## ⚠ {labels.get(f['metric'], f['metric'])}：{f['value']}（阈值 {f['limit']}）")
        print(f["advice"])
        for ln, t in f["evidence"][: a.max_hits]:
            t = t if len(t) <= 70 else t[:68] + "…"
            print(f"  - L{ln}: {t}")
        if len(f["evidence"]) > a.max_hits:
            print(f"  - ……另有 {len(f['evidence']) - a.max_hits} 处")
    for n in notes:
        print(f"\n- 提示：{n}")
    return 1 if flags else 0


if __name__ == "__main__":
    raise SystemExit(main())
