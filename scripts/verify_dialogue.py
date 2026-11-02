#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台词零遗漏核验（对应《剧本 → 分镜 解析规范》§18）。

把原始剧本里的每一句台词 / OS / VO 抽出来，逐句检查是否 100% 出现在产出的
分镜文件里。长台词被拆成多句、分落多个镜头是允许的——只要拆分后的片段在
文件里相邻出现、拼接后能还原原文即可。

用法
----
    python verify_dialogue.py 原剧本.docx 第1集分镜脚本.md 第1集分镜故事板.md
    python verify_dialogue.py 原剧本.docx 第7集*.md --ep 7
    python verify_dialogue.py 原剧本.md   产出.md --quiet

退出码
------
    0  全部命中
    1  存在缺失或仅部分命中

依赖：仅标准库。
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

# 归一化时剔除的字符：空白 + 中英文标点
NOISE = re.compile(r'[\s，。！？、：；…“”‘’"\'`【】（）()\[\]「」『』\-—–·．,\.!\?;:]')

# 剧本里不作为台词的行首标记
SKIP_PREFIX = ("△", "▲", "人物", "场景", "时间", "备注", "画外音说明")

# 场景行：7-1 / 12-3 之类
SCENE_LINE = re.compile(r'^\s*\d+\s*-\s*\d+')
# 集标题：第7集 / 第七集
EP_TITLE = re.compile(r'^\s*第\s*([0-9]+|[一二三四五六七八九十百零]+)\s*集')

CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}


def cn_to_int(s: str) -> int | None:
    """把「七」「十二」「二十三」这类中文数字转成 int；阿拉伯数字直接转。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if not s:
        return None
    if s == "十":
        return 10
    if "十" in s:
        head, _, tail = s.partition("十")
        h = CN_NUM.get(head, 1) if head else 1
        t = CN_NUM.get(tail, 0) if tail else 0
        return h * 10 + t
    return CN_NUM.get(s)


def read_docx(path: Path) -> list[str]:
    """按段落抽出 .docx 的全部文本（只读，不改原文件）。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    out = []
    for p in paras:
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        out.append(text.strip())
    return out


def read_text(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]


def load_lines(path: Path) -> list[str]:
    if path.suffix.lower() == ".docx":
        return read_docx(path)
    return read_text(path)


def slice_episode(lines: list[str], ep: int) -> list[str]:
    """截取第 ep 集到下一集之间的段落。"""
    start = end = None
    for i, ln in enumerate(lines):
        m = EP_TITLE.match(ln)
        if not m:
            continue
        n = cn_to_int(m.group(1))
        if n == ep and start is None:
            start = i
        elif n is not None and n > ep and start is not None:
            end = i
            break
    if start is None:
        raise SystemExit(f"未找到第 {ep} 集标题，请检查剧本格式或去掉 --ep 参数")
    return lines[start:end if end is not None else len(lines)]


def extract_baseline(lines: list[str]) -> list[str]:
    """从剧本行里抽台词：跳过舞台提示与场景行，取首个「：」之后的文本。"""
    out = []
    for ln in lines:
        if not ln or ln.startswith(SKIP_PREFIX) or SCENE_LINE.match(ln) or EP_TITLE.match(ln):
            continue
        if "：" not in ln:
            continue
        dialogue = ln.split("：", 1)[1].strip()
        if dialogue:
            out.append(dialogue)
    return out


QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”')


def extract_quoted(text: str) -> list[str]:
    """抽文件中所有引号包裹的台词。"""
    out = []
    for m in QUOTE.finditer(text):
        s = m.group(1) or m.group(2)
        if s and s.strip():
            out.append(s.strip())
    return out


def norm(s: str) -> str:
    return NOISE.sub("", s)


def is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def verify(baseline: list[str], haystack: str) -> tuple[list[str], list[str]]:
    """返回 (缺失, 仅部分命中)。"""
    missing, partial = [], []
    for raw in baseline:
        key = norm(raw)
        if not key:
            continue
        if key in haystack:
            continue
        if is_subsequence(key, haystack):
            partial.append(raw)      # 字都在，但不相邻 → 拆分落点被打断
        else:
            missing.append(raw)
    return missing, partial


def main() -> int:
    ap = argparse.ArgumentParser(
        description="台词零遗漏核验：检查产出文件是否覆盖剧本全部台词/OS/VO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("baseline", type=Path, help="原始剧本（.docx 或 .txt/.md）")
    ap.add_argument("targets", nargs="+", type=Path, help="待核验的分镜文件（可多个）")
    ap.add_argument("--ep", type=int, default=None,
                    help="只核验该集（剧本为整本合集时必填）")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总，不列明细")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not args.baseline.exists():
        raise SystemExit(f"找不到剧本文件：{args.baseline}")

    lines = load_lines(args.baseline)
    if args.ep is not None:
        lines = slice_episode(lines, args.ep)

    baseline = extract_baseline(lines)
    if not baseline:
        raise SystemExit("未从剧本中抽到任何台词，请检查「角色（动作）：台词」格式")

    print(f"基准台词：{len(baseline)} 条"
          + (f"（第 {args.ep} 集）" if args.ep is not None else ""))

    failed = False
    for tgt in args.targets:
        if not tgt.exists():
            print(f"\n[{tgt.name}] 文件不存在，跳过")
            failed = True
            continue

        quotes = extract_quoted(tgt.read_text(encoding="utf-8"))
        haystack = "".join(norm(q) for q in quotes)
        missing, partial = verify(baseline, haystack)

        status = "通过" if not missing and not partial else "不合格"
        print(f"\n[{tgt.name}] 引号台词 {len(quotes)} 句 · "
              f"命中 {len(baseline) - len(missing) - len(partial)}/{len(baseline)} · {status}")

        if missing:
            print(f"  缺失 {len(missing)} 条：")
            for s in ([] if args.quiet else missing):
                print(f"    - {s}")
        if partial:
            print(f"  仅部分命中 {len(partial)} 条（字都在但未相邻，多为拆分落点被其他镜头打断）：")
            for s in ([] if args.quiet else partial):
                print(f"    ~ {s}")

        if missing or partial:
            failed = True

    print("\n结论：" + ("不合格，禁止交付" if failed else "全部命中，可交付"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
