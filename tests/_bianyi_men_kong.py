"""任务 4（`/agents` 端点扩展 + 三态 UI）的变异验证脚本。

**为什么要有这个**：本任务新增的判据里，有三条特别容易假绿——
它们的断言都是「某个键存在」「某个类型对」，而这些在实现删掉之后**照样成立**：

- `ce_shi` 存在性：`assertIn("ce_shi", x)` 在 `ce_shi = {}`（空 dict）时也成立。
- `probeMs` 是数字：`assertIsInstance(..., (int, float))` 在恒 0 时也成立。
- `moshi` 收窄：断言 `notIn("auto")` 在 `moshi` **整个不存在**时也成立
  （`zi.includes` 走 undefined 分支 ⇒ 全支持 ⇒ 反而有 auto，所以这条会红，
  但前提是前端写了 `keYongMoShi` 这个函数；把它改成直接 `PERMISSION_MODES` 也一样红）。

⇒ 必须逐条真删代码，看有没有用例真的转红。零转红不自动等于失败，
但必须查清原因并写进附录。

前端那三条用 `vitest run` 判定，判据与后端一致：
**收集期报错不算守住**（生产代码一行都没执行）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GEN = Path(__file__).resolve().parent.parent
BAO = GEN / "lifeos" / "bridge"
QIAN = GEN / "frontend"
PY = str(GEN / ".venv" / "Scripts" / "python.exe")
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def _bei_fen(wen: Path) -> Path:
    """每条变异自己的备份，finally 里 copy 回去（见任务 2 脚本的记录）。"""
    bak = wen.parent / f"{wen.name}.bianyi_bak"
    shutil.copy2(str(wen), str(bak))
    return bak


def _tihuan(wen: Path, old: str, new: str) -> bool:
    s = wen.read_text(encoding="utf-8")
    if old not in s:
        return False
    wen.write_text(s.replace(old, new, 1), encoding="utf-8")
    return True


def _qu_ansi(s: str) -> str:
    return re.sub(chr(27) + r"\[[0-9;]*m", "", s)


def _gui_zi(chu) -> str:
    """摘要行。**优先抓 `N failed` 那一行**而不是 stdout 最后一行——
    vitest 最后一行是 `Duration …`，把它当摘要的话每条变异的输出都长得一样，
    看不出到底红了几条。后端 pytest 两种都能抓到，一起兼容。
    """
    all_lines = (chu.stdout or "").strip().splitlines()
    for x in all_lines:
        # vitest 的摘要是 ` Tests  9 failed | 6 passed (15)`，pytest 是 `9 failed`
        if re.search(r"\d+ failed", x):
            return re.sub(r"\x1b\[[0-9;]*m", "", x).strip()
    for x in all_lines:
        if re.search(r"\d+ passed", x):
            return re.sub(r"\x1b\[[0-9;]*m", "", x).strip()
    return re.sub(r"\x1b\[[0-9;]*m", "", all_lines[-1]).strip() if all_lines else ""


def _pao_hou_duan(xuan_ze_qi: str) -> tuple[bool, str]:
    chu = subprocess.run(
        [PY, "-m", "pytest", xuan_ze_qi, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(GEN), capture_output=True, text=True, timeout=900,
        encoding="utf-8", errors="replace",
    )
    zhuan = (chu.stdout or "") + (chu.stderr or "")
    gui = _gui_zi(chu)
    if "error" in gui and "failed" not in gui:
        print(f"  ❌ 收集期报错（变异没跑起来，不算守住）：{gui}")
        return False, gui
    # **先剥 ANSI 再数**：vitest 的摘要是 `[2m[1m9 failed[22m`,
    # 转义夹在数字与 failed 之间, 不剥的话 `(\d+) failed` 匹配不上 ⇒ 恒判全绿。
    m = re.findall(r"(\d+) failed", _qu_ansi(zhuan))
    return (not m and chu.returncode == 0), gui


def _pao_qian_duan(xuan_ze_qi: str) -> tuple[bool, str]:
    chu = subprocess.run(
        [NPM, "run", "test", "--", "--run", xuan_ze_qi],
        cwd=str(QIAN), capture_output=True, text=True, timeout=900,
        encoding="utf-8", errors="replace",
    )
    zhuan = (chu.stdout or "") + (chu.stderr or "")
    gui = _gui_zi(chu)
    # vitest 的收集期失败报 "Failed to load url"/"Cannot find"，同样不算守住。
    if re.search(r"Failed to resolve|Cannot find module|SyntaxError", zhuan):
        print(f"  ❌ 收集期报错（变异没跑起来，不算守住）：{gui}")
        return False, gui
    # **先剥 ANSI 再数**：vitest 的摘要是 `[2m[1m9 failed[22m`,
    # 转义夹在数字与 failed 之间, 不剥的话 `(\d+) failed` 匹配不上 ⇒ 恒判全绿。
    m = re.findall(r"(\d+) failed", _qu_ansi(zhuan))
    return (not m and chu.returncode == 0), gui


# ---- 每条变异：(编号, 说明, 文件, 旧串, 新串, 选择器, 前端还是后端) ----
BIAN_YI = [
    # ---- 后端 ----
    ("1", "http._agents：`ce_shi` 整个不上报（前端退回两态，无耗时无原因）",
     BAO / "http.py",
     '            xian["ce_shi"] = {\n'
     '                "ok": bool(xian.get("available")),',
     '            xian["ce_shi_unused"] = {\n'
     '                "ok": bool(xian.get("available")),',
     "tests/test_v3_agents_men_kong.py", "hou"),

    ("2", "http._agents：`ce_shi.ok` 另算一份（与 available 可以分叉，界面自相矛盾）",
     BAO / "http.py",
     '"ok": bool(xian.get("available")),',
     '"ok": bool(xian.get("version")),',
     "tests/test_v3_agents_men_kong.py", "hou"),

    ("3", "http._agents：`probeMs` 恒 0（类型对、数字假，界面显示的耗时永远是假的）",
     BAO / "http.py",
     "hao = int((time.perf_counter() - kai) * 1000)",
     "hao = 0",
     "tests/test_v3_agents_men_kong.py", "hou"),

    ("4", "http._agents：计时起点挪到 `hao` 计算**之前**（包不住探测本身 ⇒ 恒 0）",
     BAO / "http.py",
     "            hao = int((time.perf_counter() - kai) * 1000)",
     "            kai = time.perf_counter()\n"
     "            hao = int((time.perf_counter() - kai) * 1000)",
     "tests/test_v3_agents_men_kong.py", "hou"),

    ("5", "http._agents：失败时 `shuoming` 泛化成「探测失败」（用户什么也做不了）",
     BAO / "http.py",
     '                shuo = (str(xian.get("error") or "").strip()\n'
     '                        or f"{cls.label} 探测没通过")',
     '                shuo = "探测失败"',
     "tests/test_v3_agents_men_kong.py", "hou"),

    # ---- 前端 ----
    ("6", "AgentsSection：`keYongMoShi` 退化成「全支持」（moshi 收窄完全失效）",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     "  if (!zi || zi.length === 0) return PERMISSION_MODES;\n"
     "  return PERMISSION_MODES.filter((m) => zi.includes(m.value));",
     "  return PERMISSION_MODES;",
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("7", "AgentsSection：模式下拉框无视 `moShiLie`，直接用全局表",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     "              {moShiLie.map((m) => (",
     "              {PERMISSION_MODES.map((m) => (",
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("8", "AgentsSection：模式被收窄掉时不落回（留着兑现不了的模式，提交必 400）",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     "    if (moShiLie.length > 0 && !moShiLie.some((m) => m.value === mode)) {\n"
     "      setMode(moShiLie[0].value);\n"
     "    }",
     "    // 变异：删掉自动落回",
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("9", "AgentsSection：`nengGuanQuan` 删掉 `canUseTool` 那一级（旧 Bridge 满屏假警告）",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     "  return a.fangquan ?? a.canUseTool ?? true;",
     "  return a.fangquan ?? true;",
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("10", "AgentsSection：`keYongMoShi` 把空数组也当全拒（下拉框全空）",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     "  if (!zi || zi.length === 0) return PERMISSION_MODES;",
     "  if (!zi) return PERMISSION_MODES;\n"
     "  return PERMISSION_MODES.filter((m) => zi.includes(m.value));",
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("11", "AgentsSection：可用列表里不再标「由它自己管权限」（三态之二消失）",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     "              {nengGuanQuan(a) ? null : (",
     "              {false ? null : (",
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("12", "AgentsSection：`yuanYin` 退回只读 `error`（不再显示 `ce_shi.shuoming`）",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     '  const e = (a.ce_shi?.shuoming || a.error || "").trim();',
     '  const e = a.error ?? "";',
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("13", "AgentsSection：`nengGuanQuan` 兜底写成 `?? false`（「不知道」被判成没权限回路）",
     QIAN / "src" / "panels" / "AgentsSection.tsx",
     "  return a.fangquan ?? a.canUseTool ?? true;",
     "  return a.fangquan ?? a.canUseTool ?? false;",
     "src/panels/AgentsSection.v3.test.tsx", "qian"),

    ("14", "http._agents：`shuoming` 兜底按 `error` 分（失败却说「已确认可用」）",
     BAO / "http.py",
     '            if not xian.get("available"):\n'
     '                shuo = (str(xian.get("error") or "").strip()\n'
     '                        or f"{cls.label} 探测没通过")\n'
     '            else:\n'
     '                shuo = f"已确认 {cls.label} 可用（{hao} 毫秒）"',
     '            shuo = (str(xian.get("error") or "").strip()\n'
     '                    or f"已确认 {cls.label} 可用（{hao} 毫秒）")',
     "tests/test_v3_agents_men_kong.py", "hou"),
]


def pao_yi_条(bian: tuple, gan: bool) -> tuple[bool, str, str]:
    num, shuo_ming, wen, lao, xin, xuan_ze_qi, ce = bian
    print(f"\n[{num}] {shuo_ming}")
    if not wen.exists():
        print(f"  ⚠ 文件不存在：{wen}")
        return gan, num, shuo_ming
    bak = _bei_fen(wen)
    try:
        yi = _tihuan(wen, lao, xin)
        if not yi:
            print(f"  ⚠ 变异未生效：{wen.name} 里找不到待替换的代码块（源已漂移，需更新脚本）")
            return not gan, num, shuo_ming
        lv, gui = (_pao_hou_duan if ce == "hou" else _pao_qian_duan)(xuan_ze_qi)
    finally:
        shutil.copy2(str(bak), str(wen))
        bak.unlink(missing_ok=True)
    # **判据：`lv` = 「测试是否全绿」，而要求是「必须转红」。**
    # 两者取反才是守住。⚠ 这里原本写的是 `if gan and not lv: 转红` /
    # `if not gan and not lv: 预期转红却全绿` / 末尾无条件 `✅ 全绿`——
    # 在 `gan` 恒为 True 的实际用法下，**变异真的全绿时两个 if 都不命中**，
    # 于是落到末尾那条 `✅ 全绿（预期）` 并 `return True`：
    # **判反了还报「守住」**。实测抓到过（变异 8）。
    # 「全绿」这个结局只有当变异压根没生效（找不到待替换代码块）时才是预期的，
    # 那条在上面就 return 了，走不到这里。
    if gan:
        if lv:
            print(f"  ❌ 预期转红却全绿（{gui}）——**要么变异没落在承重处，要么测试没守住**")
            return False, num, shuo_ming
        print(f"  ✅ 转红：{gui}")
        return True, num, shuo_ming
    print(f"  ✅ 全绿（预期）：{gui}")
    return True, num, shuo_ming


def pao_quan_bu() -> int:
    bian = [b for b in BIAN_YI if len(sys.argv) < 2 or sys.argv[1] in ("all", b[0])]
    cheng = []
    try:
        for b in bian:
            ok, num, _ = pao_yi_条(b, gan=True)
            cheng.append((num, ok))
    finally:
        for bak in GEN.rglob("*.bianyi_bak"):
            bak.unlink()
            print(f"  ⚠ 清理残留备份：{bak.relative_to(GEN)}")
    print("\n===== 变异验证汇总 =====")
    for num, ok in cheng:
        print(f"  变异 {num}: {'✅ 转红（守住了）' if ok else '❌ 全绿（没守住）'}")
    bo = [n for n, ok in cheng if not ok]
    print(f"\n{len(cheng) - len(bo)}/{len(cheng)} 条转红"
          + (f"，未转红：{', '.join(bo)}" if bo else "，全部守住"))
    return 1 if bo else 0


if __name__ == "__main__":
    sys.exit(pao_quan_bu())