const REMINDERS = [
  { text: "真正重要的不是把每件事都做好，而是知道此刻什么值得被做好。", note: "把注意力留给今天最重要的一件事。" },
  { text: "慢一点没关系，方向对就好。", note: "稳定的小步，比偶尔的冲刺更接近长期目标。" },
  { text: "先完成，再完美。", note: "一个可以继续修改的版本，永远胜过停在脑海里的方案。" },
  { text: "你不需要一直有答案，先带着问题往前走。", note: "很多清晰，是在行动之后才出现的。" },
  { text: "把复杂的事拆小，今天只推进第一块。", note: "让下一步足够具体，行动就会变轻。" },
  { text: "休息不是中断，是下一次专注的准备。", note: "允许自己停一会儿，再回来。" },
  { text: "记录会让经验变成资产。", note: "今天留下的一点痕迹，未来会替你省下很多路。" },
  { text: "不必和所有人比较，只和昨天的自己对齐。", note: "你的节奏只属于你。" },
  { text: "情绪也是信息，不是需要立刻消灭的故障。", note: "先看见它，再决定怎么回应。" },
  { text: "把‘应该做’换成‘我选择做’。", note: "主动选择会让同一件事拥有不同的重量。" },
  { text: "今天做一点，明天就少一点阻力。", note: "开始本身就在降低未来的启动成本。" },
  { text: "不被打断的半小时，也是一种奢侈。", note: "为重要的事留出一段安静时间。" },
  { text: "先照顾睡眠，再谈效率。", note: "身体状态是所有计划的地基。" },
  { text: "你可以同时感到疲惫和期待。", note: "复杂感受不需要被简化成一句结论。" },
  { text: "给重要的人留一点真实的时间。", note: "关系也需要被放进日程，而不是只靠有空。" },
  { text: "完成清单不是目的，过好今天才是。", note: "别让工具反过来定义你的价值。" },
  { text: "不确定的时候，先做可逆的那一步。", note: "降低试错成本，就能更快获得信息。" },
  { text: "允许今天只完成一件像样的事。", note: "专注比忙碌更值得被记住。" },
  { text: "把注意力放回你能控制的部分。", note: "焦虑常常来自试图同时管理太多不可控变量。" },
  { text: "你现在做的积累，会在某个普通的日子突然连成线。", note: "继续留下你的那一笔。" },
] as const;

export function reminderIndex(date: Date): number {
  const day = Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
  const start = Date.UTC(date.getFullYear(), 0, 1);
  return Math.floor((day - start) / 86_400_000) % REMINDERS.length;
}

export function DailyReminderCard({ date = new Date() }: { date?: Date }) {
  const index = reminderIndex(date);
  const reminder = REMINDERS[index];
  return <section className="content-card quote-card daily-reminder-card">
    <div className="card-heading">
      <div><span className="card-kicker">今日提醒</span><h2>给今天的一句话</h2></div>
      <span className="soft-count">第 {index + 1} / {REMINDERS.length} 组</span>
    </div>
    <span className="quote-mark" aria-hidden="true">“</span>
    <p>{reminder.text}</p>
    <span className="quote-source">{reminder.note} · 每日自动轮换</span>
  </section>;
}