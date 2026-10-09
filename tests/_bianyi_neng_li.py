"""任务 2（能力契约）的变异验证脚本。`python tests/_bianyi_neng_li.py all`

**为什么要有这个**：单测全绿不等于守住了。
每条变异删掉/改坏一处真实承重代码，然后看**有没有用例真的转红**。
零转红不自动等于失败——但必须逐条查清原因并写进附录，不能放过。

变异 5 与 7 最初也是零转红，各挖出一个覆盖缺口，见下面的记录。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GEN = Path(__file__).resolve().parent.parent
BAO = GEN / "lifeos" / "bridge"
WEN = GEN / "tests"
PY = str(GEN / ".venv" / "Scripts" / "python.exe")


def _bei_fen(wen: Path) -> Path:
    """把文件内容备份到磁盘，返回备份路径。

    **第一版把备份写成 `<文件>.bianyi_bak`、还原用 `shutil.move`**，
    结果同一个文件的第二条变异开始时备份已经不在了——「还原」变成
    「跳过」，于是**前一条变异永久留在磁盘上**。实测就是这么把
    `planner_guard.fang` 的早退分支、`http._agents` 的交集收敛、
    `http._gai_moshi` 的第二级、`base.dui_hui_id` 四处生产代码改坏的，
    后面 4 条变异于是全部报「源已漂移」。

    ⇒ **备份必须是每条变异自己的**：备份文件在每条变异自己的 finally 里
    产生并被 copy 回去（copy 而不是 move——move 会把原件搬走）。
    """
    bak = wen.parent / f"{wen.name}.bianyi_bak"
    shutil.copy2(str(wen), str(bak))
    return bak


def _tihuan(wen: Path, old: str, new: str) -> bool:
    """把 `old` 换成 `new`。找不到就返回 False——**别静默跳过**。"""
    s = wen.read_text(encoding="utf-8")
    if old not in s:
        return False
    wen.write_text(s.replace(old, new, 1), encoding="utf-8")
    return True


def _pao_ce_shi(ke: str) -> tuple[bool, str]:
    chu = subprocess.run(
        [PY, "-m", "pytest", ke, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
        cwd=str(GEN), capture_output=True, text=True, timeout=900,
        encoding="utf-8", errors="replace",
    )
    zhuan = (chu.stdout or "") + (chu.stderr or "")
    gui = (chu.stdout or "").strip().splitlines()[-1] if (chu.stdout or "").strip() else ""
    # **error 不算转红**（形态级假绿）。
    # 变异把文件改成语法错 / NameError 时，pytest 在**收集阶段**就 error，
    # 报出来也是红的，但**生产代码一行都没被执行**——那不是「守住了」，
    # 是「根本没跑起来」。这条判据是本脚本自身的第一道保险。
    if "error" in gui and "failed" not in gui:
        print(f"  ❌ 收集期报错（变异没跑起来，不算守住）：{gui}")
        print(f"     {zhuan.strip().splitlines()[-1][:160] if zhuan.strip() else ''}")
        return False, gui
    m = re.findall(r"(\d+) failed", zhuan)
    return (not m and chu.returncode == 0), gui


# ---- 每条变异：(编号, 说明, 要改的文件, 旧串, 新串, 该转红的测试选择器) ----
BIAN_YI = [
    ("1", "base.py：MOSHI_ZI 默认从空集改成全部（契约失去意义）",
     BAO / "adapters" / "base.py",
     "MOSHI_ZI: frozenset[str] = frozenset()",
     "MOSHI_ZI: frozenset[str] = frozenset({'manual', 'acceptEdits', 'plan', 'auto', 'dontAsk'})",
     "tests/test_neng_li_qian_yue.py"),

    ("2", "planner_guard：删掉子集检查的 `zi and`（空集变成全拒，回退方向反了）",
     BAO / "planner_guard.py",
     "if zi and a1 not in zi:",
     "if a1 not in zi:",
     "tests/test_neng_li_qian_yue.py"),

    ("3", "planner_guard：`None` 又变成早退（缺省值绕过能力子集）",
     BAO / "planner_guard.py",
     "        zi = getattr(a2, \"MOSHI_ZI\", frozenset()) if a2 is not None else frozenset()\n"
     "        if a1 is None:\n"
     "            a1 = \"manual\"\n"
     "        elif a1 not in MOSHI:",
     "        if a1 is None:\n"
     "            return \"manual\"\n"
     "        zi = getattr(a2, \"MOSHI_ZI\", frozenset()) if a2 is not None else frozenset()\n"
     "        if a1 not in MOSHI:",
     "tests/test_neng_li_qian_yue.py"),

    ("4", "http._jian_hui：不把适配器传给闸门（接线断掉）",
     BAO / "http.py",
     "mode = self.shen.fang(body.get(\"permissionMode\"), cls)       # 闸门 1",
     "mode = self.shen.fang(body.get(\"permissionMode\"))       # 闸门 1",
     "tests/test_neng_li_qian_yue.py"),

    ("5", "http._agents：moshi 上报改成用 MOSHI_ZI 原样（不做交集收敛）",
     BAO / "http.py",
     "xian[\"moshi\"] = sorted((zi or MOSHI) & MOSHI)",
     "xian[\"moshi\"] = sorted(zi or MOSHI)",
     "tests/test_neng_li_qian_yue.py"),

    ("6", "http._gai_moshi：切换路径不查能力子集（能绕进去）",
     BAO / "http.py",
     "mo = self.shen.fang(mo, ZHU_CE_QI.get(hui.agentId))",
     "mo = mo",
     "tests/test_neng_li_qian_yue.py"),

    ("7", "chuan_shu：一次性进程默认值从 True 改成 False",
     BAO / "adapters" / "chuan_shu.py",
     "    yi_ci_xing = True\n\n    #: **能不能切换权限模式",
     "    yi_ci_xing = False\n\n    #: **能不能切换权限模式",
     "tests/test_neng_li_qian_yue.py"),

    ("8", "base.py：dui_hui_id 默认改成 agentSessionId（claude-code 的 resume 会静默失效）",
     BAO / "adapters" / "base.py",
     '    dui_hui_id = "claudeSessionId"',
     '    dui_hui_id = "agentSessionId"',
     "tests/test_neng_li_qian_yue.py"),
]


def pao_yi_条(bian: tuple, gan: bool) -> tuple[bool, str, str]:
    num, shuo_ming, wen, lao, xin, xuan_ze_qi = bian
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
        lv, gui = _pao_ce_shi(xuan_ze_qi)
    finally:
        # 还原放在 finally 里：变异生效但测试超时/崩了也必须还原，
        # 否则生产代码就带着变异留在磁盘上下次跑更糟。
        shutil.copy2(str(bak), str(wen))
        bak.unlink(missing_ok=True)
    if gan and not lv:
        print(f"  ✅ 转红：{gui}")
        return True, num, shuo_ming
    if not gan and not lv:
        print(f"  ⚠ 预期转红却全绿（{gui}）——**要么变异没落在承重处，要么测试没守住**")
        return False, num, shuo_ming
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
        # 兜底：任何一条变异若因故没走到自己的 finally，把残留备份清掉。
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