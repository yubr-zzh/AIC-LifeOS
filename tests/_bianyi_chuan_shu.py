"""任务 1 变异验证：把承重代码真改坏，确认测试转红。

规则：判据必须落在会分岔的量上；红数预测另算，不照抄。
用法：`python tests/_bianyi_chuan_shu.py <编号>` —— 打补丁、跑测试、还原。

不手改文件：手改容易漏还原，而漏还原的下一次运行会得到「莫名其妙的红」，
比假绿更难查。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ZHEN = Path(__file__).resolve().parent.parent
YUAN = ZHEN / "lifeos" / "bridge" / "adapters" / "chuan_shu.py"

# (编号, 补丁, 预测转红的用例名片段)
# ⚠ **红数是预测值，逐一实测后才算数**。
BIAN_YI: list[tuple[str, tuple[str, str], list[str]]] = [
    # 1. 回合 Future 的 key 从递增序号改回指令原文
    #    ⚠ **实测不转红，而且这是对的**。查过原因：
    #    ① `_jie_shu_kao_ben` 遍历全部待决 Future，撞 key 照样被唤醒 → 不会挂死；
    #    ② `HuiHua.paichu` 是**串行**的，前一回合的 Future
    #       已在 `finally` 里 pop 干净 → 连发也不会撞上。
    #    要它撞上必须两条指令并发 fasong，而架构里不存在这种调用。
    #    所以序号 key 是**防御性写法**（让「这个 Future 属于哪一回合」可追溯），
    #    不是承重项——留着用，但别把它算进验收的承重清单。
    ("1", ("        men = self._xu_hao\n", "        men = a1\n"),
     []),
    # 2. 基类加回 gai_moshi（毁掉「方法不存在」这个信号）
    ("2", ("    # ---------- 子进程 ----------\n",
           "    async def gai_moshi(self, a1: str) -> None:\n"
           "        raise NotImplementedError\n\n"
           "    # ---------- 子进程 ----------\n"),
     ["test_gai_moshi_que_xi_ji_wei_xin_hao"]),
    # 3. stderr 不再读（取消起读任务）
    ("3", ("        self._cuo_wei_ting_du = asyncio.create_task(self._shou_cuo_wei())\n", ""),
     ["test_cuo_wei_bing_bie_kan_zhua_bu_liu_diao"]),
    # 4. pid 从 returncode 猜（模拟 claude_code 读不到 pid 的形态）
    ("4", ('        pid = getattr(self.jin, "pid", None)\n',
           '        pid = getattr(self.jin, "returncode", None)\n'),
     ["test_pid_neng_qu_dao"]),
    # 5. 去掉「回合已结束」的幂等保护
    ("5", ("            if not fu.done():\n                self._jie_shu_kao_ben_guo = True\n"
           "                fu.set_result(a1)\n",
           "            self._jie_shu_kao_ben_guo = True\n            fu.set_result(a1)\n"),
     ["test_jie_shu_kao_ben_shou_lian_chuan_wu_hai"]),
    # 6. 环境变量改成整份替换（丢掉继承）
    ("6", ("        return zeng or None\n", "        return zeng\n"),
     ["test_huan_jing_zeng_liang_bu_mo_di_bie_de"]),
    # 7. 进程退出时不唤醒挂起的回合（这是真机踩出来的 bug）
    ("7", ('        self._jie_shu_kao_ben(None)\n', ""),
     ["test_cuo_wei_bing_bie_kan_zhua_bu_liu_diao"]),
    # 8. 关进程时不杀（靠 wait 超时兜底）
    #    预测：**不转红**。理由：`tests/test_chuan_shu.py` 不经过 http，
    #    而真实调用方 `http._guan_yong` 给 `guan_bi` 只有 5 秒预算，
    #    超了也只是 `except: pass` —— 没有任何单测覆盖这条预算。
    #    **这是本任务留下的已知覆盖缺口，记在方案第十一节，不假装它被验过。**
    ("8", ("        with contextlib.suppress(ProcessLookupError, OSError):\n            jin.kill()\n", ""),
     []),
]


def _yan_chu(bian_hao: str) -> tuple[str, tuple[str, str], list[str]] | None:
    for b in BIAN_YI:
        if b[0] == bian_hao:
            return b
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tests/_bianyi_chuan_shu.py <编号> | all")
        return 2
    yao = sys.argv[1] if sys.argv[1] != "all" else None
    yuan_wen = YUAN.read_text(encoding="utf-8")
    shi = BIAN_YI if yao is None else [b for b in BIAN_YI if b[0] == yao]
    if not shi:
        print(f"没有编号 {yao} 的变异")
        return 2
    for bian_hao, (lao, xin), yu_ce in shi:
        if lao not in yuan_wen:
            print(f"[{bian_hao}] 跳过：锚点不在当前源码里（可能已改过）")
            continue
        YUAN.write_text(yuan_wen.replace(lao, xin, 1), encoding="utf-8")
        try:
            chu = subprocess.run(
                [str(ZHEN / ".venv" / "Scripts" / "python.exe"), "-m", "pytest",
                 "tests/test_chuan_shu.py", "-q", "--no-header", "-p", "no:cacheprovider"],
                cwd=str(ZHEN), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
            hong = [ln for ln in (chu.stdout or "").splitlines()
                    if ln.startswith("FAILED") or " passed" in ln or " failed" in ln]
            zheng = [ln.split("::")[-1].split()[0] for ln in (chu.stdout or "").splitlines()
                     if ln.startswith("FAILED")]
            dui = "对" if zheng else ("假红" if "passed" in (chu.stdout or "") else "?")
            print(f"[{bian_hao}] {dui}  预测红：{yu_ce}")
            print(f"      实际红：{zheng}")
        except subprocess.TimeoutExpired:
            print(f"[{bian_hao}] **超时**（挂死）——这本身可能就是该变异的正确表现")
        finally:
            YUAN.write_text(yuan_wen, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())