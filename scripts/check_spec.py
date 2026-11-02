#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交付前自检（对应《剧本 → 分镜 解析规范》§16）。

§16 的自检清单是给人看的勾选框，勾的时候最容易发生的事是「眼睛过一遍就
打了勾」。本脚本把其中**可机器判定**的部分变成 26 个检查点，跑一遍就知道
哪条真的成立、哪条只是以为成立。

设计原则
--------
- **不假报通过**：判不了的检查点直接标 SKIP 并说明缺什么参数，绝不默认 OK。
- **只报可定位的问题**：每条问题带行号或组号，能直接跳过去改。
- **ERROR / WARN 分离**：ERROR 违反即为不合格；WARN 是需要人看一眼的可疑项
  （如剧情动词、非 30 秒标注），不一定错，`--strict` 时一并计入失败。

用法
----
    # 只查故事板
    python check_spec.py 第1集分镜故事板.md

    # 双文件 + 台词核验
    python check_spec.py 第1集分镜故事板.md --script 第1集分镜脚本.md \\
        --baseline 原剧本.docx --ep 1

    # 展开全部问题（默认每条只列前 3 个）
    python check_spec.py 第1集分镜故事板.md -v

退出码
------
    0  无 ERROR（`--strict` 下无 ERROR 且无 WARN）
    1  存在 ERROR（或 `--strict` 下存在 WARN）

依赖：仅标准库。台词核验复用同目录 `verify_dialogue.py`。
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- 结构正则

# 分镜组标题（宽松，用于结构解析）
GROUP_LINE = re.compile(r'^##\s*分镜组\s*0*(\d+)\s*(?:（\s*(\d+)\s*秒\s*）)?\s*$')
# 分镜组标题（严格，用于体例检查）
GROUP_STRICT = re.compile(r'^## 分镜组 \d{1,2}（30秒）$')
# 镜头标题
SHOT_LINE = re.compile(r'^【镜头\s*0*(\d+)\s*】')
# 一致性控制块起始
IC_LINE = re.compile(r'^【一致性控制】')
# 组内「场景：」字段
SCENE_FIELD = re.compile(r'^场景[：:]\s*(.+?)\s*$')
# 引用行（兼容顿号/逗号/与/和 的几种写法）
REF_LINE = re.compile(r'^\*\*角色\s*[、,，与和]\s*场景\s*[、,，与和]\s*道具引用\*\*')
# 「（30秒）」时长标注
DURATION = re.compile(r'（\s*(\d+)\s*秒\s*）')
# 集号
EP_NO = re.compile(r'第\s*(?:\d+|[一二三四五六七八九十百零]+)\s*集')
# cm 量化
CM_RE = re.compile(r'\d+(?:\.\d+)?\s*cm')
# 任意级别标题（故事板用「## 分镜组」，脚本用「###【分镜组号】」）
HEADING = re.compile(r'^#{1,6}')


# ---------------------------------------------------------------- 词表

#: 必须带左右的身体部位（含复合词，长的排前面避免只匹配到后半截）
#: 「指 / 眼 / 耳 / 怀内 / 衣袋」与指节、眼神、耳畔、入怀等常用词冲突太大，
#: 误报率高，不进自动检查，交人工核验（见 CHK11 的 note）。
BODY_PARTS = ["腰侧", "鬓角", "手臂", "大腿", "小腿", "大臂", "小臂",
              "臂", "腕", "肘", "腿", "脚", "肩", "膝", "手"]

#: 含部位字但非身体义（或本身就是完整名词）的固定词，命中即豁免
BODY_EXEMPT = {
    "凶手", "手段", "手法", "手续", "手工", "手艺", "高手", "新手",
    "老手", "助手", "帮手", "对手", "能手", "面手", "拿手", "得手",
    "手持", "巴掌", "脚步", "手帕", "手册", "手札", "手稿", "手笔", "手机",
    "随手", "顺手", "擦肩", "脱手", "失手",
    "手下", "打手", "水手", "好手", "熟手", "杀手", "枪手", "舵手", "骑手",
    "提手", "刹脚", "住脚", "手背", "手心", "手掌", "手指", "手腕", "手臂",
}

#: 左右前缀：左 / 右 / 双 / 两，后可带「侧 / 边 / 只」
SIDE_PREFIX = re.compile(r'[左右双两][侧边只]?$')

LEFT_RE = re.compile(r'左(?:手|掌|臂|腕|拳)')
RIGHT_RE = re.compile(r'右(?:手|掌|臂|腕|拳)')
STANCE_RE = re.compile(r'立|坐|跪|卧|蹲|倚|伏|站|趴|仰躺|侧卧')
#: 非人角色（灵兽/妖兽）没有左右手概念，CHK13 跳过
ANIMAL_HINT = ("幼崽", "灵兽", "妖兽", "兽", "蟒", "虎", "狼", "鸟", "蛇", "猪", "犬", "猫", "鹰", "蛛", "蟾")

#: §16 量化无歧义条明列的模糊量词
VAGUE_WORDS = ["些许", "若干", "数缕", "微促", "半尺", "1步", "1 步",
               "1尺", "1 尺", "旁边", "附近", "较多", "少许"]

#: §16 服饰禁令：服装名称与服饰部位词
DRESS_RE = re.compile(r'[袍衫裙褂袄]|衣袖|袖口|衣摆|衣襟|衣裳|衣服|衣物|前襟|下摆|披风|斗篷|劲装')

#: §17 去剧情铁律：剧情动词
PLOT_WORDS = ["转入", "转念", "准备", "打算", "将要", "欲", "开始",
              "随即", "随后", "接着", "于是", "届时", "决意"]
#: §17 去剧情铁律：主观情绪判词
EMOTION_WORDS = ["笃定", "期待", "果断", "惊恐", "愤怒", "悲伤", "喜悦",
                 "紧张", "犹豫", "决心", "气势", "心中", "心里"]

#: §17 第 9 条：视轴与机位五项
AXIS_ITEMS = [
    ("机位方位与距离", re.compile(r'机位\s*[=＝≈]\s*\S+')),
    ("机位高度", re.compile(r'距地|机位高度|高度\s*[=＝≈]')),
    ("俯仰角", re.compile(r'俯仰角|[+＋\-−]\s*\d+\s*°')),
    ("视轴靶点", re.compile(r'视轴\s*(?:→|指向)')),
    # 常规体位写「眼高」，悬空/卧姿无标准眼高时写「身中心距地 + 高差」，两者皆可
    ("眼高或高差", re.compile(r'(?:眼高|高差)[^0-9]{0,8}\d')),
]

#: §16 角色标注正例 / 反例（正例实际写法为「（21岁，178cm，……）」，岁可省）
ROLE_TAG_OK = re.compile(r'（\s*\d{1,3}\s*岁?\s*[，,]\s*\d{2,3}\s*cm')
ROLE_TAG_BAD = re.compile(r'（\s*\d{1,3}\s*岁\s*[，,]\s*\d{2,3}\s*(?:[，,）)])')

#: 系统面板镜头内不得附带的字幕声明；面板类关键词
SUB_NOTICE = "画面上不要有任何的字幕内容"
PANEL_WORDS = ("系统面板", "光幕", "属性面板", "面板文字")


# ---------------------------------------------------------------- 解析


def parse_groups(lines: list[str]) -> list[dict]:
    """切出每个分镜组：标题行号、组号、时长、组体行。"""
    heads = [(i, GROUP_LINE.match(ln)) for i, ln in enumerate(lines) if GROUP_LINE.match(ln.strip())]
    groups = []
    for k, (i, m) in enumerate(heads):
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if HEADING.match(lines[j]) and not GROUP_LINE.match(lines[j].strip()):
                end = j
                break
        if k + 1 < len(heads):
            end = min(end, heads[k + 1][0])
        groups.append({
            "lineno": i,                 # 0-based
            "num": int(m.group(1)),
            "dur": m.group(2),
            "head": lines[i],
            "body": lines[i + 1:end],
        })
    return groups


def parse_ic(lines: list[str]) -> list[dict]:
    """切出每个【一致性控制】块：起始行号与块体行。"""
    blocks = []
    i = 0
    while i < len(lines):
        if IC_LINE.match(lines[i].strip()):
            j = i + 1
            while j < len(lines):
                s = lines[j].strip()
                if HEADING.match(s) or SHOT_LINE.match(s) or IC_LINE.match(s) or s == "---":
                    break
                j += 1
            blocks.append({"lineno": i, "body": lines[i + 1:j]})
            i = j
        else:
            i += 1
    return blocks


def shot_blocks(groups: list[dict]) -> list[dict]:
    """切出镜头块：{num, lineno, lines}，遇到分隔线或下一块即止。"""
    out = []
    for g in groups:
        cur = None
        for i, ln in enumerate(g["body"]):
            s = ln.strip()
            m = SHOT_LINE.match(s)
            if m:
                if cur:
                    out.append(cur)
                cur = {"num": m.group(1), "lineno": g["lineno"] + i + 2, "lines": []}
            elif cur is not None:
                if s == "---" or IC_LINE.match(s) or HEADING.match(s):
                    out.append(cur)
                    cur = None
                else:
                    cur["lines"].append(s)
        if cur:
            out.append(cur)
    return out


def norm_ws(lines: list[str]) -> str:
    """归一化：去掉全部空白，用于双文件逐字比对。"""
    return "".join("".join(lines).split())


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------- 检查点

CHECKS: list[dict] = []


def check(num: str, title: str, level: str, ref: str):
    def deco(fn):
        CHECKS.append({"num": num, "title": title, "level": level, "ref": ref, "fn": fn})
        return fn
    return deco


# ---- A 结构 ---------------------------------------------------------------

@check("01", "故事板文件存在且非空", "ERROR", "§16-1")
def chk01(c):
    if not c.lines:
        return ["文件为空"], ""
    return [], f"{len(c.lines)} 行 · {len(c.groups)} 组"


@check("02", "双文件【一致性控制】逐字一致", "ERROR", "§16-14 / §17-5")
def chk02(c):
    if c.script_lines is None:
        return None, "未提供 --script"
    a = [norm_ws(b["body"]) for b in c.ic]
    b = [norm_ws(x["body"]) for x in parse_ic(c.script_lines)]
    probs = []
    if len(a) != len(b):
        probs.append(f"块数不一致：故事板 {len(a)} 块 / 脚本 {len(b)} 块")
    for k, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            probs.append(f"第 {k} 块内容不一致（空白差异不计）")
    return probs, f"{len(a)} 块比对"


@check("03", "组标题为「## 分镜组 NN（30秒）」", "ERROR", "§16-4")
def chk03(c):
    if not c.groups:
        return ["未找到任何「## 分镜组」标题"], ""
    probs = []
    for g in c.groups:
        if GROUP_STRICT.match(g["head"]):
            continue
        if g["dur"] is None:
            probs.append(f"第 {g['lineno'] + 1} 行：缺「（30秒）」→ {g['head']}")
        elif g["dur"] != "30":
            probs.append(f"第 {g['lineno'] + 1} 行：标注 {g['dur']} 秒 → {g['head']}")
        else:
            probs.append(f"第 {g['lineno'] + 1} 行：写法不规范（全角括号/空格/位宽）→ {g['head']}")
    return probs, f"{len(c.groups)} 组"


@check("04", "每组内容镜头 8~11 个", "ERROR", "§16-2")
def chk04(c):
    probs = []
    for g in c.groups:
        n = sum(1 for ln in g["body"] if SHOT_LINE.match(ln.strip()))
        if n == 0:
            probs.append(f"组{g['num']:02d}：0 个镜头")
        elif not 8 <= n <= 11:
            tag = "" if g["dur"] in (None, "30") else f"（{g['dur']} 秒短组）"
            probs.append(f"组{g['num']:02d}：{n} 个镜头{tag}")
    return probs, ""


@check("05", "每组仅含单一场景、组内无转场", "ERROR", "§16-3")
def chk05(c):
    probs = []
    for g in c.groups:
        vals = []
        for ln in g["body"]:
            m = SCENE_FIELD.match(ln.strip())
            if not m:
                continue
            v = re.split(r'[（(]', m.group(1))[0].strip()
            if v and v not in vals:
                vals.append(v)
        if len(vals) > 1:
            probs.append(f"组{g['num']:02d}：出现 {len(vals)} 个场景 → {' / '.join(vals)}")
    return probs, ""


@check("06", "无高角全景衔接格", "ERROR", "§16-18")
def chk06(c):
    probs = []
    for i, ln in enumerate(c.lines):
        if "高角全景" in ln or ("高角" in ln and "全景" in ln):
            probs.append(f"第 {i + 1} 行：{ln.strip()[:40]}")
    return probs, ""


# ---- B 排版 ---------------------------------------------------------------

@check("07", "镜头标题为纯文本、无加粗/井号", "ERROR", "§16-20 / §4.1")
def chk07(c):
    probs = []
    for i, ln in enumerate(c.lines):
        s = ln.strip()
        if "【镜头" not in s:
            continue
        if s.startswith(("#", "*", "**")) or "**" in s:
            probs.append(f"第 {i + 1} 行：{s[:40]}")
    return probs, ""


@check("08", "镜头块内正文无加粗", "ERROR", "§16-20 / §4.1")
def chk08(c):
    probs = []
    for b in shot_blocks(c.groups):
        for ln in b["lines"]:
            if "**" in ln:
                probs.append(f"第 {b['lineno']} 行（镜头{b['num']}）块内：{ln[:40]}")
                break
    return probs, ""


@check("09", "分隔线「---」上下各有空行", "ERROR", "§16-20 / §4.1")
def chk09(c):
    probs = []
    for i, ln in enumerate(c.lines):
        if ln.strip() != "---":
            continue
        if i > 0 and c.lines[i - 1].strip() != "":
            probs.append(f"第 {i + 1} 行：上方紧贴正文 → {(c.lines[i - 1].strip())[:24]}")
        if i + 1 < len(c.lines) and c.lines[i + 1].strip() != "":
            probs.append(f"第 {i + 1} 行：下方无空行")
    return probs, f"{sum(1 for x in c.lines if x.strip() == '---')} 处"


@check("10", "时长标注统一为 30 秒", "WARN", "§16-4 / §10")
def chk10(c):
    probs = []
    for m in DURATION.finditer(c.text):
        if m.group(1) != "30":
            probs.append(f"第 {line_of(c.text, m.start())} 行：{m.group(0)}")
    return probs, ""


# ---- C 手性 ---------------------------------------------------------------

@check("11", "全文无裸写部位词（须带左右）", "ERROR", "§16-21 / §12.1")
def chk11(c):
    parts = "|".join(re.escape(p) for p in BODY_PARTS)
    pat = re.compile(r'(' + parts + r')')
    probs = []
    for i, ln in enumerate(c.lines):
        s0 = ln.strip()
        # 镜头标题是概括（「抬手聚爪」），运镜是机位描述（「手持跟摇」），
        # 二者不承载逐手信息，跳过以免噪声淹没真问题。
        if SHOT_LINE.match(s0) or s0.startswith(("运镜：", "运镜:", "- 跨集承接注记", "角色：")):
            continue
        last = -9
        for m in pat.finditer(ln):
            pos, word = m.start(), m.group(1)
            if SIDE_PREFIX.search(ln[max(0, pos - 3):pos]):
                continue                              # 左腰侧 / 两侧鬓角 / 右大腿
            if re.search(r'[左右双两]', ln[max(0, pos - 3):pos]):
                continue                              # 右大腿内侧 / 其右手手背
            if (ln[max(0, pos - 1): pos + 1] in BODY_EXEMPT
                    or ln[pos: pos + 2] in BODY_EXEMPT):
                continue                              # 手持 / 凶手 / 脚步
            if pos - last <= len(word):
                continue                              # 同一复合词内不重复报
            last = pos
            probs.append(f"第 {i + 1} 行：「{word}」缺左右 → {s0[:36]}")
    return probs, f"{len(probs)} 处；掌/指/眼/耳/怀内/衣袋 未自动查，须人工核"


@check("12", "未用画面左右作身体定语", "ERROR", "§16-21 / §12.1")
def chk12(c):
    pat = re.compile(r'画面(?:的)?[左右](?:手|臂|腿|脚|肩|膝)')
    probs = []
    for i, ln in enumerate(c.lines):
        for m in pat.finditer(ln):
            probs.append(f"第 {i + 1} 行：{m.group(0)} → {ln.strip()[:36]}")
    return probs, ""


@check("13", "人物行左右手成对交代", "WARN", "§16-21 / §17-8")
def chk13(c):
    probs = []
    for b in c.ic:
        body = b["body"]
        start = None
        for k, ln in enumerate(body):
            if ln.strip().startswith("- 开场站位"):
                start = k
                break
        if start is None:
            continue
        for ln in body[start + 1:]:
            s = ln.strip()
            if s.startswith("- ") and not s.startswith("- 开场站位"):
                break
            if not s.startswith("·"):
                continue
            if any(w in s for w in ("画面落位", "体态", "视轴", "视线")):
                continue
            if "锚=" not in s or not STANCE_RE.search(s):
                continue
            if any(w in s for w in ANIMAL_HINT):
                continue                      # 灵兽/妖兽无左右手
            if "双手" in s or "双臂" in s:
                continue                      # 已交代两手协同
            has_l, has_r = bool(LEFT_RE.search(s)), bool(RIGHT_RE.search(s))
            if not (has_l and has_r):
                miss = "左手" if not has_l else "右手"
                probs.append(f"第 {b['lineno'] + 1} 行块：{miss}未交代 → {s[:34]}")
    return probs, ""


# ---- D 一致性控制 ---------------------------------------------------------

@check("14", "首组前设【一致性控制】开场设计", "ERROR", "§16-14")
def chk14(c):
    if not c.groups:
        return ["未找到分镜组"], ""
    g0 = c.groups[0]["lineno"]
    for b in c.ic:
        if b["lineno"] < g0:
            return [], f"开场设计在第 {b['lineno'] + 1} 行"
    return [f"首组（第 {g0 + 1} 行）之前没有【一致性控制】"], ""


@check("15", "相邻组之间均有【一致性控制】", "ERROR", "§16-14")
def chk15(c):
    probs = []
    for k in range(1, len(c.groups)):
        prev, cur = c.groups[k - 1]["lineno"], c.groups[k]["lineno"]
        if not any(prev < b["lineno"] < cur for b in c.ic):
            probs.append(f"组{c['groups'][k]['num']:02d}（第 {cur + 1} 行）之前缺块")
    return probs, f"{len(c.groups) - 1} 处交界"


@check("16", "【一致性控制】内不出现集号", "ERROR", "§16-16")
def chk16(c):
    probs = []
    for b in c.ic:
        for i, ln in enumerate(b["body"]):
            for m in EP_NO.finditer(ln):
                probs.append(f"第 {b['lineno'] + i + 2} 行：{m.group(0)}")
    return probs, ""


@check("17", "视轴与机位五项齐全", "ERROR", "§16-22 / §17-9")
def chk17(c):
    probs = []
    for b in c.ic:
        text = "\n".join(b["body"])
        line_no = b["lineno"] + 1
        if "视轴与机位" not in text:
            probs.append(f"第 {line_no} 行块：缺「视轴与机位」条")
            continue
        miss = [name for name, pat in AXIS_ITEMS if not pat.search(text)]
        if miss:
            probs.append(f"第 {line_no} 行块：缺 {'、'.join(miss)}")
    return probs, f"{len(c.ic)} 块"


@check("18", "【一致性控制】无模糊量词", "ERROR", "§16-17")
def chk18(c):
    probs = []
    for b in c.ic:
        for i, ln in enumerate(b["body"]):
            for w in VAGUE_WORDS:
                if w in ln:
                    probs.append(f"第 {b['lineno'] + i + 2} 行：「{w}」→ {ln.strip()[:34]}")
    return probs, ""


@check("19", "【一致性控制】不描述服饰", "ERROR", "§16-14 / §17-5")
def chk19(c):
    probs = []
    for b in c.ic:
        for i, ln in enumerate(b["body"]):
            m = DRESS_RE.search(ln)
            if m:
                probs.append(f"第 {b['lineno'] + i + 2} 行：「{m.group(0)}」→ {ln.strip()[:34]}")
    return probs, ""


@check("20", "【一致性控制】无剧情动词/情绪判词", "WARN", "§16-14 / §17-1")
def chk20(c):
    probs = []
    for b in c.ic:
        for i, ln in enumerate(b["body"]):
            hit = [w for w in PLOT_WORDS + EMOTION_WORDS if w in ln]
            if hit:
                probs.append(f"第 {b['lineno'] + i + 2} 行：「{'、'.join(hit)}」→ {ln.strip()[:34]}")
    return probs, ""


@check("21", "【一致性控制】锚点关系已量化到 cm", "WARN", "§16-17")
def chk21(c):
    probs = []
    for b in c.ic:
        n = len(CM_RE.findall("\n".join(b["body"])))
        if n < 3:
            probs.append(f"第 {b['lineno'] + 1} 行块：仅 {n} 处 cm 量化")
    return probs, ""


# ---- E 标注 ---------------------------------------------------------------

@check("22", "引用行只列名单，不带标注", "ERROR", "§16-10")
def chk22(c):
    probs = []
    for i, ln in enumerate(c.lines):
        s = ln.strip()
        if not REF_LINE.match(s):
            continue
        body = REF_LINE.sub("", s).strip(" 　:：")
        bad = []
        if "cm" in body.lower():
            bad.append("含尺寸")
        if re.search(r'[（(]', body):
            bad.append("含括号注记")
        if "岁" in body:
            bad.append("含年龄")
        if bad:
            probs.append(f"第 {i + 1} 行：{'、'.join(bad)} → {body[:36]}")
    return probs, ""


@check("23", "角色标注为「（年龄,身高cm）」", "WARN", "§16-10 / §12")
def chk23(c):
    probs = []
    for m in ROLE_TAG_BAD.finditer(c.text):
        probs.append(f"第 {line_of(c.text, m.start())} 行：{m.group(0)} 缺 cm")
    if not ROLE_TAG_OK.search(c.text):
        probs.append("全文未见「（年龄,身高cm）」标注")
    n = len(ROLE_TAG_OK.findall(c.text))
    return probs, f"{n} 处合法标注"


@check("24", "文件头有「## 场景坐标基准」", "WARN", "§16-23 / §17-10")
def chk24(c):
    if "## 场景坐标基准" in c.text:
        return [], "已定义"
    return ["缺「## 场景坐标基准」（原点 / 轴向 / 固定物尺寸与朝向 / 量距口径）"], ""


# ---- F 画面与台词 ---------------------------------------------------------

@check("25", "系统面板镜头不附带字幕声明", "ERROR", "§16 系统面板条")
def chk25(c):
    """只看系统面板/光幕所在的**行**：该行不得附带「画面上不要有任何的字幕内容」。

    人物台词、OS、VO 后附这句是规范要求的，不在此列。
    """
    probs = []
    for b in shot_blocks(c.groups):
        for ln in b["lines"]:
            if SUB_NOTICE in ln and any(w in ln for w in PANEL_WORDS):
                probs.append(f"第 {b['lineno']} 行（镜头{b['num']}）：面板文字附带了字幕声明")
    return probs, ""


@check("26", "台词零遗漏（调用 §18 核验）", "ERROR", "§16-5 / §18")
def chk26(c):
    if c.baseline is None:
        return None, "未提供 --baseline"
    if vd is None:
        return None, "未找到 verify_dialogue.py"
    lines = vd.load_lines(c.baseline)
    if c.ep is not None:
        lines = vd.slice_episode(lines, c.ep)
    base = vd.extract_baseline(lines)
    if not base:
        return ["未从剧本抽到任何台词（检查「角色（动作）：台词」格式）"], ""

    targets = [c.sb] + ([c.script] if c.script else [])
    probs = []
    for tgt in targets:
        quotes = vd.extract_quoted(tgt.read_text(encoding="utf-8"))
        hay = "".join(vd.norm(q) for q in quotes)
        missing, partial = vd.verify(base, hay)
        for s in missing:
            probs.append(f"{tgt.name} 缺失：{s[:30]}")
        for s in partial:
            probs.append(f"{tgt.name} 仅部分命中（拆分落点被打断）：{s[:30]}")
    return probs, f"基准 {len(base)} 条 × {len(targets)} 文件"


# ---------------------------------------------------------------- 运行


class Ctx:
    def __init__(self, sb: Path, script: Path | None, baseline: Path | None, ep: int | None):
        self.sb = sb
        self.lines = sb.read_text(encoding="utf-8").splitlines()
        self.text = "\n".join(self.lines)
        self.groups = parse_groups(self.lines)
        self.ic = parse_ic(self.lines)
        self.script = script
        self.script_lines = script.read_text(encoding="utf-8").splitlines() if script else None
        self.baseline = baseline
        self.ep = ep


def dwidth(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def pad(s: str, n: int) -> str:
    return s + " " * max(0, n - dwidth(s))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="交付前自检：§16 的 26 个可机检检查点",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("storyboard", type=Path, help="分镜故事板（.md）")
    ap.add_argument("--script", type=Path, default=None, help="分镜脚本（.md），用于双文件比对")
    ap.add_argument("--baseline", type=Path, default=None, help="原始剧本（.docx/.md），用于台词核验")
    ap.add_argument("--ep", type=int, default=None, help="剧本为整本合集时指定集号")
    ap.add_argument("--strict", action="store_true", help="WARN 也计为失败")
    ap.add_argument("-v", "--verbose", action="store_true", help="展开全部问题（默认每项最多 3 条）")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not args.storyboard.exists():
        raise SystemExit(f"找不到故事板文件：{args.storyboard}")
    for p, name in ((args.script, "--script"), (args.baseline, "--baseline")):
        if p is not None and not p.exists():
            raise SystemExit(f"{name} 指向的文件不存在：{p}")

    ctx = Ctx(args.storyboard, args.script, args.baseline, args.ep)

    print(f"交付前自检 · {args.storyboard.name}")
    print("=" * 66)

    tally = {"OK": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    details = []

    for spec in sorted(CHECKS, key=lambda x: x["num"]):
        try:
            problems, note = spec["fn"](ctx)
        except Exception as e:                       # 检查器自身出错不能静默
            problems, note = [f"检查器异常：{e}"], ""

        if problems is None:
            status = "SKIP"
            summary = note
        elif problems:
            status = "FAIL" if spec["level"] == "ERROR" else "WARN"
            summary = f"{len(problems)} 处" + (f" · {note}" if note else "")
        else:
            status = "OK"
            summary = note

        tally[status] += 1
        print(f"CHK{spec['num']}  {pad(spec['title'], 34)}{pad(status, 6)}{summary}")
        if problems:
            details.append((spec, status, problems))

    print("=" * 66)
    print(f"26 项：OK {tally['OK']} · WARN {tally['WARN']} · "
          f"FAIL {tally['FAIL']} · SKIP {tally['SKIP']}")

    if details:
        print()
        for spec, status, problems in details:
            print(f"[{status}] CHK{spec['num']} {spec['title']}  （{spec['ref']}）")
            shown = problems if args.verbose else problems[:3]
            for p in shown:
                print(f"    - {p}")
            if not args.verbose and len(problems) > 3:
                print(f"    … 另有 {len(problems) - 3} 处，用 -v 展开")
            print()

    failed = tally["FAIL"] > 0 or (args.strict and tally["WARN"] > 0)
    if failed:
        print("结论：不合格，禁止交付")
    elif tally["WARN"]:
        print("结论：无硬性违规；WARN 项须人工确认后交付")
    else:
        print("结论：全部通过，可交付")

    return 1 if failed else 0


# 台词核验复用同目录脚本（缺失时 CHK26 标 SKIP，不影响其余检查）
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import verify_dialogue as vd          # noqa: E402
except Exception:                          # pragma: no cover
    vd = None


if __name__ == "__main__":
    sys.exit(main())
