"""给演示用的记忆库灌一批种子数据。

⚠️ 这些是**演示数据**，不是真实使用记录：数量、来源、引用次数都是构造出来的，
目的是让「42 条」「引用 12 次」这类数字在录屏时成立。

用法：
    python tools/seed_demo_memory.py <memory.json 路径>

它只写 user / project / feedback / reference 四组，不动 candidates / backups。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

NOW = datetime.now()

USER = [
    "界面用薄荷绿，不要大面积暖色",
    "回答要短，别客套",
    "代码里注释写「为什么」不写「做了什么」",
    "中英文之间加空格",
    "不要用感叹号",
    "先给结论，再给理由",
    "表格比段落更适合对比信息",
    "别用 emoji 当图标",
    "文件名和路径用反引号包起来",
    "改动前先说清楚要改什么",
    "Python 用 3.11",
    "提交信息用中文写",
    "测试跑 pytest，不要用 unittest",
    "前端用 Inter 和 Noto Sans SC",
    "写代码优先小函数",
    "别替我删注释",
    "调试日志用中文",
    "涉及删除的操作先确认",
]

PROJECT = [
    "LifeOS 的测试用 pytest -q tests/",
    "LifeOS 的前端在 frontend/，构建用 vite",
    "LifeOS 的桌面端打包走 tools/build_exe.ps1",
    "LifeOS 的数据存在本机 lifeOS 目录",
    "LifeOS 的桥接进程是 lifeos/bridge",
    "LifeOS 的 Agent 用 claude-code 适配器",
    "LifeOS 的记忆分 user/project/feedback/reference 四类",
    "LifeOS 的发布包是 dist/LifeOS",
    "LifeOS 的 dev server 走 vite",
    "LifeOS 的 UI 体系见 docs/agent-sidebar-p0a-corrected.md",
    "LifeOS 的登录态存在 Windows DPAPI 里",
    "LifeOS 的工作历是年度热力图",
]

FEEDBACK = [
    "上次计划页留白太多，编辑器应该占满",
    "审批框的倒计时要能一眼看到",
    "工具调用的展开默认折叠就好",
    "不要在正文里重复显示 LifeOS 署名",
    "输入框默认小一点，120px 够了",
    "复制按钮改成 hover 出现",
]

REFERENCE = [
    "Impeccable craft-floor：去 eyebrow、去卡片套卡片、去 Unicode 图标",
    "VSCode 聊天侧栏：轮次容器 + 工具一行 + hover 工具栏",
    "Koder 的记忆抽屉骨架：右滑、搜索、分类、逐条编辑",
    "Shape of AI 的记忆原则：捕获时要给反馈",
    "Agentic UX：记忆要有全局入口和内联提示",
    "GitHub contributions 的热力图配色",
]

SCOPE_GLOBAL = {"kind": "global", "scenario_type": None, "project_id": None, "user_id": None}


def scope_project(pid: str) -> dict:
    return {"kind": "project", "scenario_type": None, "project_id": pid, "user_id": None}


def entry(i: int, category: str, text: str, scope: dict, used: int, days_ago: int) -> dict:
    when = (NOW - timedelta(days=days_ago)).isoformat()
    return {
        "id": f"demo-{category}-{i:03d}",
        "source": "direct" if i % 3 else "candidate",
        "category": category,
        "scope": scope,
        "content": {"text": text},
        "occurred_at": when,
        "created_at": when,
        "status": "active",
        "used_count": used,
    }


def build() -> dict:
    out = []
    for i, t in enumerate(USER, 1):
        out.append(entry(i, "user", t, SCOPE_GLOBAL, (i * 7) % 13, 30 - i))
    for i, t in enumerate(PROJECT, 1):
        out.append(entry(i, "project", t, scope_project("lifeos"), (i * 5) % 9, 20 - i))
    for i, t in enumerate(FEEDBACK, 1):
        out.append(entry(i, "feedback", t, SCOPE_GLOBAL, i % 4, 14 - i))
    for i, t in enumerate(REFERENCE, 1):
        out.append(entry(i, "reference", t, SCOPE_GLOBAL, (i * 3) % 6, 40 - i * 2))
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tools/seed_demo_memory.py <memory.json>")
        return 1
    path = Path(sys.argv[1])
    store = {}
    if path.is_file():
        try:
            store = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            store = {}
    store.setdefault("schema_version", 1)
    for name in ("user", "project", "feedback", "reference"):
        store[name] = [e for e in build() if e["category"] == name]
    store.setdefault("candidates", [])
    store.setdefault("backups", [])
    store.setdefault("vector_index", {})
    store.setdefault("cache", {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(store[n]) for n in ("user", "project", "feedback", "reference"))
    print(f"已写入 {total} 条演示记忆 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
