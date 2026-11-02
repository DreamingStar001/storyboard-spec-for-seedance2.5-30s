# Script → Storyboard Spec

**Built for Seedance 2.5 · 30-second shot groups**

[中文](README.md) | **English**

> A specification for turning a novel chapter or screenplay into two production-ready files:
> a **shot script** (generation-unit level) and a **storyboard** (shot level).
> Not theory — hard rules distilled from dozens of real episodes that kept breaking.

The numbers are calibrated to Seedance 2.5's single-pass capability: **one group = one generation = 30 seconds**, 8–11 content shots inside, one scene per group, no cuts within a group. Swapping models or aspect ratios means editing §1 / §2 / §10 only; the rest of the spec is platform-agnostic.

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)

---

## The problem it solves

When you turn a novel into an AI-generated series, image quality is rarely what kills you. **Consistency** is.

- The protagonist's scar moves from the left cheek to the right between episodes
- A character stands by the table in one shot, then teleports to the doorway in the next
- A long line of dialogue gets split in two, and the second half silently disappears — found on the fifth manual read-through
- Every shot is written like prose, so the model interprets it differently each run and you end up rolling dice

This spec turns those into **machine-checkable constraints**: positions quantified in cm against a named anchor, left/right handedness written out hand by hand, the first group of every episode forced to read back the last shot of the previous episode, and dialogue completeness verified by script instead of by eyeball.

---

## Six core rules (all learned the hard way)

**1. One group carries exactly one scene. Never cut inside a group.**
Transitions happen only between groups. If a scene is shorter than 30 seconds and the next scene needs to start — **let the group run short** rather than packing two scenes into one. Scene integrity outranks duration integrity.

**2. Positions are always "anchor + relative offset". No adjectives.**
Not "standing by the table" but "anchor = east side of the square table, standing ~30cm from the east edge". The file header must declare `## Scene Coordinate Basis` first (origin / axes / fixed-object dimensions and long-edge orientation / measurement convention); groups reference it, never redefine it.

**3. Left and right are written per hand. The idle hand counts too.**
"Hand hanging down" is missing information — the model will not infer what the other hand is doing, and an omission becomes drift. Held objects need all four parts: which hand + grip + orientation or height + whether both hands cooperate.

**4. The opening group of an episode must read back the previous episode's final group and final shot.**
Do not infer it from the screenplay. Verify five attributes entity by entity: posture / position / facing / held objects / physiological signals. Any mismatch fails. If the previous episode's deliverable lands later, backfill it.

**5. Every abstract word becomes a visible signal.**
"Despair" becomes "tears falling, slumping to sit"; "shock" becomes "eyes wide, lips slightly parted". Run a full-text check; no bare abstractions.

**6. Dialogue completeness is verified by machine, not by eye.**
Every line, OS and VO must appear. Split long lines must reassemble to 100% of the original. Run a normalized-substring comparison as a hard delivery gate — "the split dropped the second half" is the single most common failure, and it slips past manual review almost every time.

---

## Quick start

**Just reading?** Go to [`references/storyboard-spec.md`](references/storyboard-spec.md) — 18 chapters, ~15k characters, Simplified Chinese.

**Using it inside an agent?** Drop this repo into your skills directory, or copy `SKILL.md` and `references/` together.

**Here for the scripts?** Both are pure standard library, zero dependencies, exit code 1 on any violation — ready to hang in a pipeline as a gate.

```bash
# Dialogue completeness check (.docx and .txt screenplays supported)
python scripts/verify_dialogue.py screenplay.docx ep01-shot-script.md ep01-storyboard.md

# 26-point pre-delivery self-check (structure / layout / handedness / continuity / tagging / dialogue)
python scripts/check_spec.py ep01-storyboard.md \
    --script ep01-shot-script.md --baseline screenplay.docx --ep 1
```

`check_spec.py` prints 26 lines of `OK / WARN / FAIL / SKIP`, each violation carrying a line or group number. Checks that cannot be decided are marked `SKIP` with the missing argument named — it never passes by default. Without `--script` it will not diff the two files; without `--baseline` it will not check dialogue.

> First run on an older draft will usually flag a batch of CHK11 hits (bare body-part words without left/right).
> That rule was added later and old drafts were never retrofitted — expected. New episodes should hit zero.

---

## Structure

```
storyboard-spec-for-seedance2.5-30s/
├── SKILL.md                        # Agent entry point (frontmatter included)
├── references/
│   └── storyboard-spec.md          # The spec itself · 18 chapters
├── scripts/
│   ├── check_spec.py               # §16 · 26 pre-delivery checks
│   └── verify_dialogue.py          # §18 · dialogue completeness
├── CHANGELOG.md
├── LICENSE                         # CC BY 4.0 (documentation)
└── LICENSE-MIT                     # MIT (scripts)
```

---

## Chapters

| Ch. | Content |
|---|---|
| §0–1 | Dual-file delivery, per-episode sizing |
| §2–2.1 | Group duration and shot-count rules, one-scene principle |
| §3–4.1 | Script / storyboard file structure, layout consistency |
| §5 | Six-field action block (the core format) |
| §6 | Sparse "key frame" strategy (A / B / C) |
| §7–9 | Fidelity to screenplay, abstractions → visible signals, jump-cut avoidance |
| §10–12.1 | Fixed 30s, long-line splitting, character tagging, left/right handedness |
| §13–14.1 | Art style and negative prompts, asset library, prop dimensions |
| §15 | Six bridging methods for action continuity |
| §16 | Pre-delivery checklist (26 items, automated by `scripts/check_spec.py`) |
| §17 | Inter-group continuity control (incl. sight axis, camera, coordinate basis) |
| §18 | Dialogue completeness rule and verification procedure |

---

## Scope

- **Fits**: vertical-format AI series, AI video storyboards, any continuous narrative that needs strong cross-shot consistency.
- **Does not fit**: single-image prompts, non-continuous short clips, live-action scripts that need free camera work.
- The "30 s / 9:16 / 8–11 shots" figures assume current mainstream AI video models (≤30 s per generation, portrait). Change the model or the frame and you edit §1, §2, §10; everything else stays.

---

## Disclaimer

This is a **personal practice write-up**, not official documentation from any AI video platform, and it is not affiliated with any of them. Product names appear only to describe fit.

Example characters (Character A, Character B, …) are placeholders for format demonstration and refer to no specific work.

---

## License

- Documentation (`references/`, `README.md`, `README.en.md`, `CHANGELOG.md`, `SKILL.md`): [CC BY 4.0](LICENSE) — free to redistribute, use commercially, adapt, **with attribution**.
- Code (`scripts/`): [MIT](LICENSE-MIT).

Attribution line:

> Source: *Script → Storyboard Spec*, https://github.com/DreamingStar001/storyboard-spec-for-seedance2.5-30s

---

## Contributing

If a rule does not hold up in practice, or you have a more machine-checkable formulation, open an issue. This spec is the product of being repeatedly rejected by real deliverables — it will keep changing.
