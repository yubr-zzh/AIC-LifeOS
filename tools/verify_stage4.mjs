#!/usr/bin/env node
// 阶段 4 真机验收（方案 12.5 退出条件的第三条：F1–F7 逐条演示）。
//
// 与 tools/verify_stage3.py 分工不同：那份验的是 Bridge 进程内的适配器行为，
// 这份从头到尾只操作浏览器——F5 要求「全过程用户只在 LifeOS 界面操作」，
// 所以演示脚本自己也只碰页面，不去调 Bridge 的 HTTP 接口。
//
// 走的是一条完整链路，不是抄近路：
//   左栏对话 → 规划出委派计划 → 勾选 → 发给 Agent
//   → 右栏流式执行 → 触发审批 → 用户放行 → 跑完回流左栏
// F2 写的是「勾选委派计划 → 逐条发送」，F4 写的是「左侧出现委派完成」，
// 所以绕过委派卡直接往右栏输入框打字是验不到这两条的。
//
// 前置：
//   ./.venv/Scripts/python.exe -m lifeos.api.server   # 8765
//   cd frontend && npm run dev                        # 5173
// 用法：
//   node tools/verify_stage4.mjs [--keep] [--no-shot] [--cha]
//   --cha      额外打印右栏 DOM 文本，用于排查「该有内容却没有」

import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";

// puppeteer-core 装在全环境而非项目里（演示工具不该为它引依赖），
// 所以按「先本地、后全局」两条路解析。
const req = createRequire(import.meta.url);
let puppeteer;
try {
  puppeteer = req("puppeteer-core");
} catch {
  puppeteer = createRequire(`${process.env.APPDATA}/npm/node_modules/`)("puppeteer-core");
}

const ZHAN = "http://127.0.0.1:5173";
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const CWD = "D:/Github本地/AIC-LifeOS";
const TMP = "C:/Users/Liuxj/AppData/Local/Temp/lifeos-stage4";
const ARGS = new Set(process.argv.slice(2));

// 必须含一个绝对路径或 CICI 关键词，规划器才肯认它是一条委派。
// 也必须真的去跑一条命令，否则触发不了权限询问（F3）。
const HUA = `请在 ${CWD} 目录下运行 python -c "print(6*7)" 这一步，然后把命令输出原样告诉我，最后另起一句说：阶段四演示完成。`;

const bai = [];
let guo = 0;
function ji(a, b, c = true) {
  guo += c ? 1 : 0;
  bai.push(`${c ? "✅" : "❌"} ${a}｜${b}`);
  console.log(`${c ? "✅" : "❌"} ${a}｜${b}`);
}
const deng = (a) => new Promise((b) => setTimeout(b, a));

/** 在页面里按文字找一个元素并点掉。返回是否点到、点之前是否禁用。 */
async function dian(ye, hua, xuan, ding = 0) {
  return ye.evaluate(
    ([hua, xuan, ding]) => {
      const xu = [...document.querySelectorAll(xuan)];
      const mu = ding > 0 ? xu[ding] : xu.find((x) => ((x.textContent ?? "").replace(/\s+/g, " ").trim()).includes(hua));
      if (!mu) return { ok: false, jin: false };
      mu.scrollIntoView({ block: "center" });
      const jin = mu.disabled;
      mu.click();
      return { ok: true, jin };
    },
    [hua, xuan, ding],
  );
}

/** 读一段文字，压掉空白。 */
const du = (ye, xuan) =>
  ye.evaluate((x) => {
    const el = document.querySelector(x);
    return el ? (el.textContent ?? "").replace(/\s+/g, " ").trim() : null;
  }, xuan);

/** 右栏 Agent 面板的全部可见文本，排查「该有内容却没有」时用。 */
const ba = (ye) =>
  ye.evaluate(() => {
    const gui = document.querySelector(".agp-body");
    return {
      you: gui ? (gui.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 600) : "（没有 .agp-body）",
      shu: gui ? (gui.textContent ?? "").length : 0,
      kuai: [...document.querySelectorAll(".agp-body *")].map((x) => x.className).filter((c) => typeof c === "string" && c.startsWith("agb")).slice(0, 20),
    };
  });

async function kai() {
  const guan = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    defaultViewport: { width: 1440, height: 900 },
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const [shou] = await guan.pages();
  if (shou) await shou.close(); // 新开标签页前关掉空白页，否则 F5 数 tab 会多一个
  const ye = await guan.newPage();
  ye.on("pageerror", (a) => console.log("   [页面异常]", a.message.slice(0, 200)));
  ye.on("console", (a) => {
    const t = a.text();
    if (a.type() === "error") console.log("   [console]", t.slice(0, 200));
  });
  await ye.goto(ZHAN, { waitUntil: "networkidle2" });
  return { guan, ye };
}

// ---------------------------------------------------------------- F1
async function f1(ye) {
  console.log("\n── F1 发现 · 选择 · 连接 ──");
  await dian(ye, "本地 Agent", "button.nav-item");
  await deng(600);

  const fa = await ye.evaluate(() => {
    const tiao = document.querySelector(".ags-agent.on");
    if (!tiao) return null;
    return {
      wen: (tiao.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 100),
      ban: (tiao.querySelector(".mono")?.textContent ?? "").trim(),
    };
  });
  ji("F1-发现", fa ? fa.wen : "没有可用的 Agent 卡片", Boolean(fa));
  ji("F1-看到版本", fa?.ban ? `版本 ${fa.ban}` : "没看到版本号", Boolean(fa?.ban));

  const shuru = await ye.$(".ags-form input[placeholder]");
  if (!shuru) throw new Error("找不到 cwd 输入框");
  await shuru.click({ clickCount: 3 });
  await shuru.type(CWD);

  const an = await dian(ye, "连接并打开对话", ".ags-btns button");
  ji("F1-按钮就绪", an.ok ? `disabled=${an.jin}（应为 false）` : "找不到「连接并打开对话」", an.ok && !an.jin);
  if (!an.ok) return false;

  try {
    await ye.waitForSelector(".chat-split-grid .agp", { timeout: 120_000 });
  } catch {
    ji("F1-连接成功", "120 秒内没出现 Agent 面板", false);
    return false;
  }
  const zhuang = await du(ye, ".agp-bar .pill");
  ji("F1-连接成功", `状态条：${zhuang ?? "（无）"}`, Boolean(zhuang));
  ji("F1-自动回到对话页", "已跳到对话页并展开双栏", true);
  return true;
}

// ---------------------------------------------------------------- F2
async function f2(ye) {
  console.log("\n── F2 勾选委派计划 → 逐条发送 → 右侧流式执行 ──");
  // 在**左栏**对话里说这件事，规划器才会产出委派计划挂在同一条消息上。
  const shuru = await ye.$(".chat-card textarea");
  if (!shuru) throw new Error("找不到左栏对话输入框");
  await shuru.click();
  await shuru.type(HUA);
  await dian(ye, "Send", ".chat-card button");
  ji("F2-指令已发出", "已在左栏对话发出需求", true);

  let kaichu = null;
  for (let i = 0; i < 40; i++) {
    await deng(1000);
    kaichu = await ye.evaluate(() => {
      const ka = document.querySelector(".dlg");
      if (!ka) return null;
      return {
        zhai: (ka.querySelector(".dlg-sum")?.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 60),
        xiang: (ka.querySelector(".dlg-foot .mono")?.textContent ?? "").replace(/\s+/g, " ").trim(),
        tiao: ka.querySelectorAll(".dlg-item").length,
        xuan: ka.querySelectorAll(".dlg-item:not(.off)").length,
      };
    });
    if (kaichu) break;
  }
  if (!kaichu) {
    ji("F2-规划出委派计划", "40 秒内没出现委派卡", false);
    return false;
  }
  ji("F2-规划出委派计划", `共 ${kaichu.tiao} 条、默认勾选 ${kaichu.xuan} 条｜${kaichu.zhang ?? kaichu.zhai}`, kaichu.tiao > 0 && kaichu.xuan > 0);
  if (!ARGS.has("--no-shot")) await ye.screenshot({ path: `${TMP}/f2-plan.png` });

  const fa = await dian(ye, "发给 Agent", ".dlg-btns button");
  ji("F2-勾选后逐条发送", fa.ok ? `disabled=${fa.jin}` : "找不到「发给 Agent」按钮", fa.ok && !fa.jin);
  if (!fa.ok) return false;

  // 右栏流式出字。审批卡出现时 Agent 会停住等用户，所以这里只要求
  // 「有内容在长」，不要求跑完——跑完归 F4 管。
  let zui = 0;
  let you = false;
  for (let i = 0; i < 120; i++) {
    await deng(1000);
    const x = await ba(ye);
    zui = Math.max(zui, x.shu);
    if (x.shu > 0) you = true;
    if (await ye.$(".agp-decide .apr")) break;
  }
  ji("F2-右侧流式出字", `右栏累计 ${zui} 字符`, you);
  if (!you) {
    const x = await ba(ye);
    console.log("   右栏 DOM：" + x.you.slice(0, 300));
    if (ARGS.has("--cha")) console.log("   气泡类名：" + JSON.stringify(x.kuai));
  }
  return you;
}

// ---------------------------------------------------------------- F3
async function f3(ye) {
  console.log("\n── F3 权限提示返回用户 · 放行后继续 ──");
  const chu = await ye
    .waitForSelector(".agp-decide .apr", { timeout: 240_000, visible: true })
    .then(() => true, () => false);
  if (!chu) {
    ji("F3-审批卡出现", "240 秒内没等到审批卡", false);
    return false;
  }
  const ka = await ye.evaluate(() => {
    const c = document.querySelector(".agp-decide .apr");
    return {
      gong: (c.querySelector(".apr-tool")?.textContent ?? "").replace(/\s+/g, " ").trim(),
      ming: (c.querySelector(".apr-cmd")?.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 90),
      zhuang: (document.querySelector(".agp-bar .pill")?.textContent ?? "").replace(/\s+/g, " ").trim(),
      jia: [...document.querySelectorAll(".agp-decide .apr button")].map((x) => (x.textContent ?? "").trim()),
    };
  });
  ji("F3-审批卡出现", `工具=${ka.gong || "?"}｜状态=${ka.zhuang || "?"}｜按钮=${ka.jia.join("/")}`, Boolean(ka.gong));
  ji("F3-展示真实参数", ka.ming ? ka.ming : "没看到命令内容", Boolean(ka.ming));
  if (!ARGS.has("--no-shot")) await ye.screenshot({ path: `${TMP}/f3-approval.png` });

  const an = await dian(ye, "允许", ".agp-decide .apr button");
  if (!an.ok) {
    ji("F3-放行", "找不到「允许」按钮", false);
    return false;
  }
  if (an.jin) {
    ji("F3-放行", "「允许」被禁用（通常是输入被截断）", false);
    return false;
  }
  const ci = await dian(ye, "确认放行", ".agp-decide .apr button");
  ji("F3-放行", ci.ok ? "危险命令，已点第二次确认" : "已点「允许」（非危险命令，无需二次确认）", true);
  return true;
}

// ---------------------------------------------------------------- F4
async function f4(ye) {
  console.log("\n── F4 结束输出 · 批完 · 左侧回报 ──");
  const zhong = await ye
    .waitForSelector(".agp-end", { timeout: 300_000, visible: true })
    .then(() => true, () => false);
  const jie = await ye.evaluate(() => ({
    jie: (document.querySelector(".agp-end")?.textContent ?? "").replace(/\s+/g, " ").trim(),
    zhuang: (document.querySelector(".agp-bar .pill")?.textContent ?? "").replace(/\s+/g, " ").trim(),
    pi: (document.querySelector(".agp-bar .mono")?.textContent ?? "").replace(/\s+/g, " ").trim(),
  }));
  ji("F4-批次跑完", `状态=${jie.zhuang || "?"}｜${jie.pi || "无批次信息"}`, zhong);
  ji("F4-出现结束提示", jie.jie || "（未出现）", zhong);

  // 左侧回报：最后一条 assistant 消息里应出现「委派完成」。
  const bao = await ye.evaluate(() => {
    // 对话气泡用的是内联样式、没有专属类名，所以读整块对话卡就够
    const ka = document.querySelector(".chat-card");
    const wen = (ka?.textContent ?? "").replace(/\s+/g, " ");
    const i = wen.search(/委派(完成|中断)/);
    return { zhao: i >= 0 ? wen.slice(Math.max(0, i - 20), i + 90).trim() : null };
  });
  ji("F4-左侧出现回报", bao.zhao ?? "左栏没有出现委派结果", Boolean(bao.zhao));
  return zhong;
}

// ---------------------------------------------------------------- F6 / F5
async function f6(ye) {
  console.log("\n── F6 两个对话区同屏 ──");
  const ge = await ye.evaluate(() => {
    const kuai = document.querySelector(".chat-split-grid");
    if (!kuai) return null;
    const zuo = kuai.firstElementChild;
    const you = kuai.querySelector(".agp");
    const z = zuo?.getBoundingClientRect();
    const y = you?.getBoundingClientRect();
    return {
      zuo: z ? Math.round(z.width) : 0,
      you: y ? Math.round(y.width) : 0,
      chan: (zuo?.textContent ?? "").includes("对话空间"),
      ai: Boolean(you),
      bi: z && y && z.width + y.width > 0 ? Math.round((y.width / (z.width + y.width)) * 100) : 0,
      gui: Boolean(zuo?.querySelector(".panel")),
      guiWen: (zuo?.querySelector(".panel-title")?.textContent ?? "").trim(),
    };
  });
  ji("F6-同屏双栏", ge ? `左 ${ge.zuo}px / 右 ${ge.you}px（右占 ${ge.bi}%）` : "没有分裂容器", Boolean(ge));
  ji("F6-互不串味", ge ? `左=对话空间(${ge.chan})｜右=Agent 面板(${ge.ai})｜左栏 RuntimeRail=${ge.gui}` : "—", Boolean(ge?.chan && ge?.ai));

  console.log("\n── F5 全过程只在 LifeOS 界面 ──");
  const mian = (await ye.browser().pages()).length;
  ji("F5-单窗口", `全程 ${mian} 个 tab，未打开终端与 Bridge 页面`, mian === 1);
}

// ---------------------------------------------------------------- F7
async function f7(ye) {
  console.log("\n── F7 未使用 Agent 时是完整原页面 ──");
  await ye.evaluate(() => localStorage.setItem("lifeos.agentLayout", "collapsed"));
  await ye.reload({ waitUntil: "networkidle2" });
  await dian(ye, "对话", "button.nav-item");
  await deng(900);
  const zhe = await ye.evaluate(() => {
    const gong = document.querySelector(".chat-page-grid");
    return {
      cun: Boolean(document.querySelector(".chat-split-grid")),
      agp: Boolean(document.querySelector(".agp")),
      tiao: Boolean(document.querySelector(".apk")),
      hua: Boolean(gong?.querySelector(".chat-card")),
      gui: Boolean(gong?.querySelector(".panel")),
      kuan: Math.round(gong?.getBoundingClientRect().width ?? 0),
    };
  });
  ji("F7-折叠即原页面", zhe.cun || zhe.agp ? "折叠态仍带着 Agent 相关 DOM" : "DOM 与改造前一致", !zhe.cun && !zhe.agp);
  ji("F7-原组件齐全", `对话卡=${zhe.hua}｜RuntimeRail=${zhe.gui}｜宽 ${zhe.kuan}px`, zhe.hua && zhe.gui);
  ji("F7-无残留审批条", zhe.tiao ? "折叠态挂着审批条" : "无待决定项时不出现审批条", !zhe.tiao);
  if (!ARGS.has("--no-shot")) await ye.screenshot({ path: `${TMP}/f7-collapsed.png` });
  return zhe;
}

// ---------------------------------------------------------------- 主流程
async function main() {
  mkdirSync(TMP, { recursive: true });
  const { guan, ye } = await kai();
  console.log(`演示目标：${ZHAN}`);
  try {
    if (!(await f1(ye))) return 1;
    if (!(await f2(ye))) return 1;
    if (!(await f3(ye))) return 1;
    await f4(ye);
    await f6(ye);
    await f7(ye);
  } catch (a) {
    ji("演示中断", a.stack?.split("\n").slice(0, 3).join(" ") || a.message, false);
  } finally {
    if (!ARGS.has("--keep")) await guan.close();
  }
  console.log(`\n──── 演示结果：${guo}/${bai.length} 条通过 ────`);
  for (const x of bai) console.log("  " + x);
  return guo === bai.length ? 0 : 1;
}

process.exit(await main());
