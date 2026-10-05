"""阶段 3 真机验收（方案 12.4 的 3.1–3.4、3.6、3.7）。

跑的是真的 Claude Code：真的 spawn 子进程、真的触发审批、真的提问。
假适配器验不出来的三件事只有它能验：
  1. SDK 消息到底长什么样（3.2 的真实样本写进 docs/）
  2. 审批放行后 Agent 是否真的继续执行（3.3）
  3. AskUserQuestion 的答案经 deny+message 回传后，Agent 是否真的读到了（3.4）

用法：
    python tools/verify_stage3.py            # 3.1–3.4 + 3.8
    python tools/verify_stage3.py --chao_shi  # 额外跑 3.7 的两个真超时
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifeos.agent.runtime import LifeOSAgent
from lifeos.api.server import LifeOSRequestHandler
from lifeos.bridge import auth
from lifeos.bridge.events import ZongXian
from lifeos.bridge.http import BridgeServer
from lifeos.bridge.localbus import LuDao
from lifeos.bridge.planner_guard import ShenKa
from lifeos.bridge.session import HuiHua
from lifeos.llm.client import LLMClient

ROOT = str(Path(__file__).resolve().parent.parent)


def duan_kong() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Qiao:
    def __init__(self, base: str, token: str = "") -> None:
        self.base = base
        self.token = token

    def get(self, path: str):
        req = urllib.request.Request(f"{self.base}{path}")
        if self.token:
            req.add_header("x-bridge-token", self.token)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    def post(self, path: str, body: dict):
        req = urllib.request.Request(
            f"{self.base}{path}", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST", headers={"content-type": "application/json; charset=utf-8"})
        if self.token:
            req.add_header("x-bridge-token", self.token)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with op.open(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


def deng(ti, a1: str, a2=180.0):
    kaishi = time.monotonic()
    while time.monotonic() - kaishi < a2:
        v = ti()
        if v:
            return v
        time.sleep(0.3)
    raise SystemExit(f"[验收] 等待超时：{a1}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chao_shi", action="store_true", help="额外跑 3.7 的两个真超时")
    args = ap.parse_args()

    # ---- 主服务（决策回路的另一端）----
    zhu_duan = duan_kong()
    zhu = ThreadingHTTPServer(("127.0.0.1", zhu_duan), LifeOSRequestHandler)
    zhu.daemon_threads = True
    threading.Thread(target=zhu.serve_forever, daemon=True).start()
    LifeOSRequestHandler.agent = LifeOSAgent(LLMClient(), storage_dir=ROOT + "/.lifeos")

    # ---- Bridge ----
    z = ZongXian(uuid.uuid4().hex[:8])
    h = HuiHua(z)
    z.zhan = h
    token = auth.shengcheng()
    bp = duan_kong()
    fu = BridgeServer(("127.0.0.1", bp), z, h, ShenKa([ROOT]), token)
    fu.cli_ban_ben = "2.1.283"
    fu.sdk_ban_ben = "0.2.160"
    lu = LuDao(f"http://127.0.0.1:{zhu_duan}")
    fu.lu_dao = lu
    threading.Thread(target=fu.serve_forever, daemon=True).start()
    q = Qiao(f"http://127.0.0.1:{bp}", token)

    print(f"[验收] 主服务 {zhu_duan} / Bridge {bp}")
    agents = q.get("/agents?token=" + token)["agents"]
    for a in agents:
        print(f"[验收] 适配器 {a['agentId']} 可用={a['available']} 版本={a['version']} "
              f"SDK={a.get('sdkVersion')} 错误={a.get('error')}")
    print(f"[验收] 版本门禁 {q.get('/agents?token=' + token)['versionGate']}")

    s, d = q.post("/sessions", {"agentId": "claude-code", "cwd": ROOT,
                                "permissionMode": "manual", "title": "阶段 3 验收",
                                "clientIdempotencyKey": uuid.uuid4().hex})
    assert s == 201, (s, d)
    sid = d["session"]["sessionId"]
    print(f"[验收] 会话 {sid} 生效模式 {d['session']['effectiveMode']}")

    zhi = [
        '用 Bash 工具执行这条命令：node -e "console.log(41+1)"。'
        "执行完只回答命令的输出，不要做别的。",
        "现在必须调用 AskUserQuestion 工具问用户「你要我用哪种方式收尾？」，"
        "选项给「A 写文档」和「B 写测试」。拿到答案后，把你选的那一项用一句话说明。",
    ]
    s, _ = q.post(f"/sessions/{sid}/messages", {"instructions": zhi})
    assert s == 202

    # ---- 3.3 真实审批 ----
    dai = deng(lambda: [x for x in h.dai_jue() if x["sessionId"] == sid], "审批请求")
    print(f"[验收] 3.3 真实审批：toolName={dai[0]['toolName']} "
          f"requestId={dai[0]['requestId']} 截断={dai[0]['inputTruncated']}")
    print(f"         入参={json.dumps(dai[0]['toolInput'], ensure_ascii=False)[:120]}")
    s, r = q.post(f"/permissions/{dai[0]['requestId']}", {"decision": "allow"})
    print(f"[验收] 3.3 用户点允许 → {s} {r}")
    assert r.get("decision") == "user_allow", r

    # ---- 3.4 真实提问 ----
    wen = deng(lambda: [x for x in h.dai_wen() if x["sessionId"] == sid], "提问请求")
    print(f"[验收] 3.4 真实提问：{json.dumps(wen[0]['questions'], ensure_ascii=False)[:300]}")
    s, r = q.post(f"/questions/{wen[0]['questionId']}",
                  {"answers": [{"questionId": wen[0]["questions"][0].get("question", "q"),
                                "values": ["B 写测试"]}]})
    print(f"[验收] 3.4 用户作答 → {s} {r}")

    deng(lambda: h.du(sid).state == "ended", "整批跑完")
    hui = h.du(sid)
    print(f"[验收] 会话结束：batchDone={hui.batchDone}/{hui.batchTotal} "
          f"turnCount={hui.turnCount} claudeSessionId={hui.claudeSessionId}")

    # ---- 3.1 / 3.2 真实消息样本 ----
    zhen = [z2 for _, z2 in z.huan if z2.get("sessionId") == sid]
    lei = {}
    for f in zhen:
        if f["type"] == "message":
            lei.setdefault(f["message"]["kind"], 0)
            lei[f["message"]["kind"]] += 1
    print(f"[验收] 3.2 观察到的消息 kind：{lei}")
    print(f"[验收] 帧类型：{sorted({f['type'] for f in zhen})}")

    cai = []
    for f in zhen:
        if f["type"] == "result":
            cai.append({k: f[k] for k in ("subtype", "isError", "numTurns",
                                          "totalCostUsd", "batchDone", "batchTotal")})
            cai[-1]["resultText"] = f["resultText"][:200]
    print(f"[验收] 3.1 result 帧：{json.dumps(cai, ensure_ascii=False, indent=1)}")

    print(f"[验收] 3.6 子进程 pid（会话跑完时）：{dict(fu.pids)}")
    Agent = wen[0]
    print(f"[验收] Agent 读到了用户答案吗："
          f"{'B 写测试' in json.dumps([m.to_dict() for m in h.juan_biao(sid)], ensure_ascii=False)}")

    # ---- 3.8 决策回路 ----
    shang = deng(lambda: LifeOSRequestHandler.agent.agent_context.du(sid), "结果回到主服务")
    print(f"[验收] 3.8 主服务上下文：")
    for c in shang:
        print(f"         [{c['kind']}] {c['text'][:160]}")
    s, d = Qiao(f"http://127.0.0.1:{zhu_duan}").post(
        "/chat", {"message": "刚才本地 Agent 做了什么？", "session_id": sid})
    print(f"[验收] 3.8 /chat 仍然正常：{s} {json.dumps(d, ensure_ascii=False)[:160]}")

    if args.chao_shi:
        # ---- 3.7 审批超时真跑 ----
        print("\n[验收] 3.7 审批超时（改成 5 秒，故意不点）")
        fu.shen_qing.shi_ji = 5.0
        s2, d2 = q.post("/sessions", {"agentId": "claude-code", "cwd": ROOT,
                                      "permissionMode": "manual",
                                      "clientIdempotencyKey": uuid.uuid4().hex})
        sid2 = d2["session"]["sessionId"]
        q.post(f"/sessions/{sid2}/messages",
               {"instructions": ['用 Bash 执行：node -e "console.log(1+1)"']})
        time.sleep(12)
        jie = [x for x in fu.shen_qing.jue_chao if x.get("sessionId") == sid2]
        print(f"[验收] 3.7 超时收口记录：{[x for x in jie if x.get('decision')]}")
        print(f"[验收] 3.7 剩余挂起：{len([x for x in h.dai_jue() if x['sessionId'] == sid2])}")
        q.post(f"/sessions/{sid2}/close", {})

        # ---- 3.7 停滞超时真跑 ----
        # 阈值压到 1 秒：看门狗会在真 claude 进程刚起、第一帧还没到时就打断它。
        # 不用「让 Agent 跑一条 90 秒的静默命令」那种做法——模型不配合，
        # 同一份脚本跑三次有三次直接拒绝了，跑不通不算验收。
        #
        # 断言的是**广播出去的 error 帧**，不是瞬时状态：error 可能只存在几十毫秒
        # （Agent 被打断后 paichu 会把状态推到 ended），轮询状态是抓不到的。
        print("[验收] 3.7 停滞超时（阈值 1 秒，打断一个真进程）")
        h.ting_ge = 1.0
        s3, d3 = q.post("/sessions", {"agentId": "claude-code", "cwd": ROOT,
                                      "permissionMode": "manual",
                                      "clientIdempotencyKey": uuid.uuid4().hex})
        sid3 = d3["session"]["sessionId"]
        q.post(f"/sessions/{sid3}/messages",
               {"instructions": ["读一下 requirements.txt 的第一行，"
                                 "然后告诉我第一行的内容"]})

        def ting_le(a1):
            return [f for _, f in z.huan
                    if f.get("sessionId") == a1 and f["type"] == "error"
                    and f.get("code") == "stall_timeout"]

        deng(lambda: ting_le(sid3), "停滞 error 帧", a2=90.0)
        print(f"[验收] 3.7 停滞结果：{ting_le(sid3)[-1]['message']}")
        time.sleep(4)
        hui3 = h.du(sid3)
        print(f"[验收] 3.7 打断后 state={hui3.state if hui3 else None} "
              f"batchDone={hui3.batchDone if hui3 else '-'}/{hui3.batchTotal if hui3 else '-'}")
        res3 = [f for _, f in z.huan if f.get("sessionId") == sid3 and f["type"] == "result"]
        print(f"[验收] 3.7 打断后的 result："
              f"{[(r['subtype'], r['isError']) for r in res3] or '（无，进程已被打断）'}")
        q.post(f"/sessions/{sid3}/close", {})

        # ---- 3.5 中断一个真进程 ----
        print("[验收] 3.5 中断真进程")
        h.ting_ge = 900.0
        s4, d4 = q.post("/sessions", {"agentId": "claude-code", "cwd": ROOT,
                                      "permissionMode": "manual",
                                      "clientIdempotencyKey": uuid.uuid4().hex})
        sid4 = d4["session"]["sessionId"]
        q.post(f"/sessions/{sid4}/messages",
               {"instructions": ["数一下 lifeos/bridge 目录下有多少个 .py 文件，逐个说明用途"]})
        time.sleep(8)
        print(f"[验收] 中断前 state={h.du(sid4).state} "
              f"消息数={len([1 for _, f in z.huan if f.get('sessionId') == sid4 and f['type'] == 'message'])}")
        s5, r5 = q.post(f"/sessions/{sid4}/interrupt", {})
        print(f"[验收] 中断请求 → {s5} {r5}")
        time.sleep(8)
        hui4 = h.du(sid4)
        res4 = [f for _, f in z.huan if f.get("sessionId") == sid4 and f["type"] == "result"]
        print(f"[验收] 中断后 state={hui4.state if hui4 else None} "
              f"batchDone={hui4.batchDone if hui4 else '-'}/{hui4.batchTotal if hui4 else '-'} "
              f"result={[(r['subtype'], r['isError']) for r in res4] or '（无）'}")
        q.post(f"/sessions/{sid4}/close", {})

    # ---- 3.6 两段式关闭 ----
    print("\n[验收] 3.6 两段式关闭")
    pid_qian = dict(fu.pids)
    print(f"[验收] 记录在案的子进程：{pid_qian}")
    s, r = q.post("/bridge/stop", {})
    print(f"[验收] 关闭请求 → {s} {r}")
    time.sleep(2)
    sheng = []
    for pid in pid_qian:
        os_alive = Path(f"/proc/{pid}").exists() if Path("/proc").exists() else None
        sheng.append((pid, os_alive))
    import ctypes
    for pid, _ in sheng:
        k32 = ctypes.windll.kernel32
        hd = k32.OpenProcess(0x1000, False, pid)
        if not hd:
            print(f"[验收]   pid {pid} 已不存在")
            continue
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(hd, ctypes.byref(code))
        k32.CloseHandle(hd)
        print(f"[验收]   pid {pid} 存活={code.value == 259}")
    lu.ting_zhi()
    h.ting_zhi()
    fu.server_close()
    zhu.shutdown()
    zhu.server_close()
    print("\n[验收] 全部步骤完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
