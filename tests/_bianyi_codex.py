"""任务 3（codex 适配器）的变异验证脚本。`python tests/_bianyi_codex.py all`

**为什么要有这个**：单测全绿不等于守住了。
每条变异删掉或改坏一处真实承重代码，看**有没有用例真的转红**。
零转红不自动等于失败——必须逐条查清原因并写进附录。

变异 1 与变异 3 最初零转红，各挖出一个覆盖缺口，见下面的记录。

⚠ **默认只跑 L-B（golden）**：`--lc` 才加上 L-C 真机用例。
理由是 L-C 每条要真打一回合（花模型额度、几十秒），不该在日常变异
循环里跑十几遍。要验真机那条自己显式加 `--lc`。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GEN = Path(__file__).resolve().parent.parent
CODEX = GEN / "lifeos" / "bridge" / "adapters" / "codex.py"
PY = str(GEN / ".venv" / "Scripts" / "python.exe")

L_B = "tests/test_codex_fan_yi.py"
L_C = "tests/test_codex_lc_ji_cheng.py"


def _xuan_ze_qi(ceng: str, ti_yao_lc: bool) -> list[str]:
    """该跑哪些测试文件/用例。

    ⚠ **L-C 那条变异必须单独跑那一个用例**，不能写成
    `"a.py b.py::SomeTest::test_x"`：pytest 收到「目录 + ::选择器」的
    组合时**一条都不收集**，报 `no tests ran in 0.00s`——而我的判据把
    「没跑用例」算作「没守住」，于是那条变异明明转红了却被报成失败。
    """
    if not (ti_yao_lc or "c" in ceng):
        return [L_B]
    # 先把 L-B 全跑，再单跑那条真正需要真机的用例
    return [L_B, f"{L_C}::Zhen_Shou_Tests::test_zhong_duan_de_hui_shou_cheng_bi_yong_await"]


def _bei_fen(wen: Path) -> Path:
    """备份一份，返回备份路径。**每条变异自己备份**（见 `_bianyi_neng_li.py`
    里同一个坑的记录：第一版共用一份备份 + `shutil.move` 还原，
    同文件的第二条变异就没有备份可还原，变异永久留在磁盘上）。"""
    bak = wen.parent / f"{wen.name}.bianyi_bak"
    shutil.copy2(str(wen), str(bak))
    return bak


def _tihuan(wen: Path, lao: str, xin: str) -> bool:
    s = wen.read_text(encoding="utf-8")
    if lao not in s:
        return False
    wen.write_text(s.replace(lao, xin, 1), encoding="utf-8")
    return True


def _pao_ce_shi(ke: list[str]) -> tuple[bool, str, bool]:
    """跑测试。返回 (是否全绿, 摘要行, 收集期是否废了)。

    ⚠ **`ke` 是列表，不能先 join 再当一个参数传。** 第一版 `shlex`-free 地
    写了 `subprocess.run([PY, "-m", "pytest", ke, ...])`，于是 pytest 收到
    的是一整个「a.py b.py::X」字符串，当成**一个路径**，一条都不收集，
    报 `no tests ran`——而我的判据把「没跑用例」算「没守住」，
    于是每条需要多个选择器的变异都被报成失败。L-C 那条查了两轮才发现。
    """
    chu = subprocess.run(
        [PY, "-m", "pytest", *ke, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
        cwd=str(GEN), capture_output=True, text=True, timeout=1800,
        encoding="utf-8", errors="replace",
    )
    zhuan = (chu.stdout or "") + (chu.stderr or "")
    gui = (chu.stdout or "").strip().splitlines()[-1] if (chu.stdout or "").strip() else ""
    # **error / no tests ran 都不算转红**：
    # 变异把文件改成语法错时 pytest 在收集阶段就 error，报出来也是红的，
    # 但生产代码一行都没执行。实测踩到过两种形态：`1 error` 与
    # `no tests ran`（变异让整个模块 import 失败时）。
    if ("error" in gui or "no tests ran" in gui) and "failed" not in gui:
        return False, gui, True
    m = re.findall(r"(\d+) failed", zhuan)
    if not m and "no tests ran" in zhuan:
        return False, gui, True
    return (not m and chu.returncode == 0), gui, False


# (编号, 说明, 旧串, 新串, 需要哪几层)
BIAN_YI = [
    ("1", "把 `turn/completed` 判据放宽成任何 `turn/` 通知（turn/started 就收回合）",
     'if a1.get("method") != "turn/completed":',
     'if not str(a1.get("method", "")).startswith("turn/"):', "b"),

    ("2", "`--listen stdio://` 改成 `stdio`（0.152+ 会让 stdio 失去响应）",
     'ZHI_LING = ["codex", "app-server", "--listen", "stdio://"]',
     'ZHI_LING = ["codex", "app-server", "--listen", "stdio"]', "b"),

    ("3", "`approvalPolicy` 从 on-request 改成 never（codex 自己批，LifeOS 审批卡永远空着）",
     '"approvalPolicy": "on-request", "sandbox": "read-only"',
     '"approvalPolicy": "never", "sandbox": "read-only"', "b"),

    ("4", "`JUECAO` 改成方案第 4.2 节的 approved/abort（本机 schema 里不存在）",
     'JUECAO = {"allow": "accept", "deny": "decline"}',
     'JUECAO = {"allow": "approved", "deny": "abort"}', "b"),

    ("5", "`thread/status/changed{idle}` 也发事件（界面先显示「空闲」再显示「已完成」）",
     '            # 先显示「空闲」再显示「已完成」，顺序是反的。\n            return',
     '            # 先显示「空闲」再显示「已完成」，顺序是反的。\n'
     '            self._fa("state", {"state": "idle", "lastEvent": "thread_idle"})\n'
     '            return', "b"),

    ("6", "`item/completed{agentMessage}` 的 text 非空判断删掉（空正文也落一条空消息）",
     '            if wen:\n                self._fa("text", {"messageId": self.xiang_id, "text": wen})',
     '            self._fa("text", {"messageId": self.xiang_id, "text": wen})', "b"),

    ("7", "挂起任务里把决定直接回成 allow（跳过 Bridge 的闸门 2 deny 基线）",
     '            self._hui_yi(a4, a3(zhao))',
     '            self._hui_yi(a4, {"decision": "accept"})', "b"),

    ("8", "不认识的 Server 请求不回 -32601（codex 一直等 id，回合卡到超时）",
     'self._hui_yi(a1.get("id"), error_code=-32601)',
     'pass', "b"),

    ("9", "`sandboxPolicy` 的形状写错（`{mode:...}` 而不是 `{type:...}`，静默失效）",
     '"sandboxPolicy": {"type": shen, "networkAccess": False}',
     '"sandboxPolicy": {"mode": shen}', "b"),

    ("10", "`resultText` 改成只读 turn.items（推理型回合返回空，决策回路收不到）",
     'wen = "".join(self._zhuan_wen)',
     'wen = ""', "b"),

    ("11", "`guan_bi` 不收挂起任务（协程还握着已拆掉的 stdin）",
     'for t in list(self._dai_dai):\n            t.cancel()',
     'pass', "b"),

    ("12", "`sandboxPolicy` 对 acceptEdits 也给 readOnly（切了模式但没生效）",
     'shen = "workspaceWrite" if self.moshi == "acceptEdits" else "readOnly"',
     'shen = "readOnly"', "b"),

    ("13", "`zhong_duan` 的 kill 兜底漏掉 await（L-C 挖出来的真缺陷）",
     'await self._zhong_zhi_chi_cheng()',
     'self._zhong_zhi_chi_cheng()', "bc"),
]


def pao_yi_条(bian: tuple, ti_yao_lc: bool) -> tuple[bool, str]:
    num, shuo_ming, lao, xin, ceng = bian
    print(f"\n[{num}] {shuo_ming}")
    bak = _bei_fen(CODEX)
    try:
        if not _tihuan(CODEX, lao, xin):
            print(f"  ⚠ 变异未生效：找不到待替换的代码块（源已漂移，需更新脚本）")
            return False
        ke = _xuan_ze_qi(ceng, ti_yao_lc)
        lv, gui, shou_le = _pao_ce_shi(ke)
    finally:
        shutil.copy2(str(bak), str(CODEX))
        bak.unlink(missing_ok=True)
    if shou_le:
        print(f"  ❌ 收集期就废了（变异没跑起来，不算守住）：{gui}")
        return False
    if lv:
        print(f"  ✅ 全绿（**没守住**）：{gui}")
        return False
    print(f"  ✅ 转红：{gui}")
    return True


def pao_quan_bu() -> int:
    ti_yao_lc = "--lc" in sys.argv
    hao = [x for x in sys.argv[1:] if not x.startswith("-")]
    # ⚠ **"all" 不是编号**。第一版把它当编号去匹配，结果一条都选不出来，
    # 脚本「全绿」退出——一个什么都没跑的脚本比失败的脚本更危险。
    xuan = BIAN_YI if (not hao or "all" in hao) else [b for b in BIAN_YI if b[0] in hao]
    if not xuan:
        print(f"没有匹配的变异：{hao}（可选 1-{len(BIAN_YI)} 或 all）")
        return 1
    if not ti_yao_lc:
        print("（默认只跑 L-B。要连 L-C 真机一起验，加 --lc）")
    cheng = []
    try:
        for b in xuan:
            cheng.append((b[0], pao_yi_条(b, ti_yao_lc)))
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