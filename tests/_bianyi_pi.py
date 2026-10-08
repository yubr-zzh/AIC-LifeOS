"""pi 适配器的变异验证脚本。`python tests/_bianyi_pi.py all`

**为什么要有这个**：单测全绿不等于守住了。
每条变异删掉或改坏一处真实承重代码，看**有没有用例真的转红**。
零转红不自动等于失败——必须逐条查清原因并写清。

## 判定逻辑（踩过三次）

判定必须是「**要求转红**」与「**实际是否全绿**」取反：

- 真全绿 ⇒ 没守住（**不是**「守住」）
- 收集期就废了（`error` / `no tests ran`）⇒ 不算守住，
  因为生产代码一行都没执行
- ANSI 转义：pytest 摘要是 `ESC[2mESC[1m9 failedESC[22m`，
  `(\\d+) failed` 匹配不上 ⇒ **每次变异都判成全绿**。
  本项目踩过一次，所以 `_pao_ce_shi` 里先剥 `chr(27)`。

## 条数从简

方案要求 3-5 条而不是 codex 的 13 条（本轮 §6.1：允许削覆盖率换开发速度，
但**判据的真实性不能削**）。挑的 5 条都是「读错了就静默错」的地方，
其中 1、2 两条是这类适配器最常见的假绿。

⚠ **默认只跑 L-B（golden）**：`--lc` 才加上 L-C 真机用例。
理由是 L-C 每条要真打一回合（花模型额度、几十秒）。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GEN = Path(__file__).resolve().parent.parent
PI = GEN / "lifeos" / "bridge" / "adapters" / "pi.py"
PY = str(GEN / ".venv" / "Scripts" / "python.exe")

L_B = "tests/test_pi_fan_yi.py"
L_C = "tests/test_pi_lc_ji_cheng.py"


def _xuan_ze_qi(ceng: str, ti_yao_lc: bool) -> list[str]:
    """该跑哪些测试文件/用例。

    ⚠ **L-C 那条变异必须单独跑那一个用例**，不能写成
    `"a.py b.py::SomeTest::test_x"`：pytest 收到「文件 + ::选择器」的
    组合时**一条都不收集**，报 `no tests ran`——而判据把「没跑用例」
    算作「没守住」，于是那条变异明明转红了却被报成失败。
    """
    if not (ti_yao_lc or "c" in ceng):
        return [L_B]
    return [L_B, f"{L_C}::Zhen_Shou_Tests::"
                  "test_sha_chan_jin_cheng_shou_wan_biao_di_pai_de_yang_cheng_guo_cheng"]


def _bei_fen(wen: Path) -> Path:
    """备份一份，返回备份路径。**每条变异自己备份**：共用一份备份时，
    同文件的第二条变异就没有备份可还原，变异永久留在磁盘上。"""
    bak = wen.parent / f"{wen.name}.bianyi_bak"
    shutil.copy2(str(wen), str(bak))
    return bak


def _tihuan(wen: Path, lao: str, xin: str) -> bool:
    """单行锚点替换。

    ⚠ **锚点必须用读文件时看到的那个换行**：文件是 CRLF 时
    搜索串里的 `\\n` 匹配不上，报出来是「源已漂移」，而真相通常是锚点写错。
    这里 `read_text` 已经把 CRLF 归一化成 `\\n`（Python 默认universal newlines），
    所以锚点写 `\\n` 是对的——但**报「源已漂移」时要先 `repr()` 核那一段**。
    """
    s = wen.read_text(encoding="utf-8")
    if lao not in s:
        return False
    wen.write_text(s.replace(lao, xin, 1), encoding="utf-8")
    return True


def _pao_ce_shi(ke: list[str]) -> tuple[bool, str, bool]:
    """跑测试。返回 (是否全绿, 摘要行, 收集期是否废了)。

    ⚠ **`ke` 是列表，不能先 join 再当一个参数传。** 写成
    `subprocess.run([PY, "-m", "pytest", ke, ...])` 时 pytest 收到的是
    一整个「a.py b.py::X」字符串，当成**一个路径**，一条都不收集。
    """
    chu = subprocess.run(
        [PY, "-m", "pytest", *ke, "-q", "--no-header", "-x", "-p", "no:cacheprovider"],
        cwd=str(GEN), capture_output=True, text=True, timeout=1800,
        encoding="utf-8", errors="replace",
    )
    # ⚠ **先剥 ANSI 转义**：`ESC[2mESC[1m9 failedESC[22m` 里 `(\d+) failed`
    # 匹配不上，每次变异都会被判成全绿（记着这个坑）。
    zhan = (chu.stdout or "") + (chu.stderr or "")
    zhuan = re.sub(f"{chr(27)}\\[[0-9;]*m", "", zhan)
    gui = (zhuan or "").strip().splitlines()[-1] if (zhuan or "").strip() else ""
    # **error / no tests ran 都不算转红**：
    # 变异把文件改成语法错时 pytest 在收集阶段就 error，报出来也是红的，
    # 但生产代码一行都没执行。
    if ("error" in gui or "no tests ran" in gui) and "failed" not in gui:
        return False, gui, True
    m = re.findall(r"(\d+) failed", zhuan)
    if not m and "no tests ran" in zhuan:
        return False, gui, True
    return (not m and chu.returncode == 0), gui, False


# (编号, 说明, 旧串, 新串, 需要哪几层)
BIAN_YI = [
    # ⚠ **1 与 2 是这类适配器最常见的两处假绿**：事件全翻译对、单测全绿，
    # 真机上 `fasong()` 挂死到看门狗。所以这两条各配一条专门的判据。
    ("1", "回合边界从 `agent_settled` 放宽成 `agent_end`（重试场景把回合提前收走，结果是空的）",
     'if a1.get("type") != "agent_settled":',
     'if a1.get("type") not in ("agent_settled", "agent_end"):', "b"),

    ("2", "回合边界放宽成「任何 `*_end`」（`turn_end` 更早，一个 run 里能有多次）",
     'if a1.get("type") != "agent_settled":',
     'if not str(a1.get("type") or "").endswith("_end"):', "b"),

    ("3", "`resultText` 只读 delta 累加器（provider 不吐增量时正文为空，决策回路收不到）",
     'wen = self._wen_zheng or "".join(self._zhuan_wen)',
     'wen = "".join(self._zhuan_wen)', "b"),

    ("4", "挂起任务里把决定直接回成 allow（跳过 Bridge 闸门 2 的 deny 基线）",
     'self._hui_dao_ui(a4, a3(zhao))',
     'self._hui_dao_ui(a4, {"cancelled": False})', "b"),

    ("5", "`guan_bi` 不收挂起任务（协程还握着已拆掉的 stdin）",
     'for t in list(self._dai_dai):\n            t.cancel()\n        self._dai_dai.clear()',
     'pass', "bc"),
]


def pao_yi_tiao(bian: tuple, ti_yao_lc: bool) -> tuple[bool, str]:
    num, shuo_ming, lao, xin, ceng = bian
    print(f"\n[{num}] {shuo_ming}")
    bak = _bei_fen(PI)
    try:
        if not _tihuan(PI, lao, xin):
            print("  ⚠ 变异未生效：找不到待替换的代码块"
                  "（先 repr() 核那一段，多半是锚点写错而不是源漂移）")
            return False
        ke = _xuan_ze_qi(ceng, ti_yao_lc)
        lv, gui, shou_le = _pao_ce_shi(ke)
    finally:
        shutil.copy2(str(bak), str(PI))
        bak.unlink(missing_ok=True)
    if shou_le:
        print(f"  ❌ 收集期就废了（变异没跑起来，不算守住）：{gui}")
        return False
    if lv:
        print(f"  ❌ 全绿（**没守住**）：{gui}")
        return False
    print(f"  ✅ 转红：{gui}")
    return True


def pao_quan_bu() -> int:
    ti_yao_lc = "--lc" in sys.argv
    hao = [x for x in sys.argv[1:] if not x.startswith("-")]
    # ⚠ **"all" 不是编号**：把它当编号去匹配会一条都选不出来，脚本「全绿」
    # 退出——一个什么都没跑的脚本比失败的脚本更危险。
    xuan = BIAN_YI if (not hao or "all" in hao) else [b for b in BIAN_YI if b[0] in hao]
    if not xuan:
        print(f"没有匹配的变异：{hao}（可选 1-{len(BIAN_YI)} 或 all）")
        return 1
    if not ti_yao_lc:
        print("（默认只跑 L-B。要连 L-C 真机一起验，加 --lc）")
    cheng = []
    try:
        for b in xuan:
            cheng.append((b[0], pao_yi_tiao(b, ti_yao_lc)))
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