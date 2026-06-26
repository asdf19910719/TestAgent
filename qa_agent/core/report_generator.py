"""
测试报告生成器（第一阶段任务3，借鉴 oec build_test_report.py 的确定性计算原则）

核心原则（来自 oec 的设计教训）：
- 所有数字（计数/占比/趋势）在代码里**确定性计算**，禁止 LLM 拍脑袋
  （避免"汇报说通过 3 条但实际 5 条"的翻车）
- 只读 last.json / history.jsonl，只写报告产物，不联网、仅 stdlib

输出三种格式：
- markdown: 人读报告（摘要 + 明细 + 历史趋势）
- json: 机器可读元数据（供 CI 解析）
- html: 可视化报告（摘要卡片 + 用例表 + 趋势）
"""

import json
import html as _html
from pathlib import Path
from typing import Dict, Any, List, Optional


class ReportGenerator:
    """从 last.json + history.jsonl 生成结构化报告"""

    def __init__(self, last_run: Dict[str, Any], history: Optional[List[Dict[str, Any]]] = None):
        self.last_run = last_run
        self.history = history or []

    # ---------- 确定性计算（核心：数字只在这里算） ----------

    def compute_stats(self) -> Dict[str, Any]:
        """从 last_run 确定性计算统计数字"""
        execution = self.last_run.get('execution', {}) or {}
        totals = execution.get('totals', {}) or {}

        # 优先用 totals，回退到逐项统计
        total = totals.get('total', 0)
        passed = totals.get('passed', 0)
        failed = totals.get('failed', 0)
        blocked = totals.get('blocked', 0)
        skipped = totals.get('skipped', 0)

        # 回退：从 selection + failures 推算
        if total == 0:
            selection = self.last_run.get('selection', {}) or {}
            total = selection.get('total', selection.get('total_cases', 0))
            failures = execution.get('failures', []) or []
            failed = failed or len(failures)

        executed = passed + failed
        pass_rate = round(passed / executed * 100, 1) if executed > 0 else 0.0
        exec_rate = round(executed / total * 100, 1) if total > 0 else 0.0

        return {
            'total': total,
            'passed': passed,
            'failed': failed,
            'blocked': blocked,
            'skipped': skipped,
            'executed': executed,
            'pass_rate': pass_rate,
            'exec_rate': exec_rate,
        }

    def compute_trend(self) -> Dict[str, Any]:
        """对比上一次执行，计算趋势"""
        if len(self.history) < 2:
            return {'available': False}

        # history 按时间追加，最后一条是本次，倒数第二条是上次
        prev = self.history[-2]
        cur = self.history[-1]

        def _rate(entry):
            pr = entry.get('pass_rate', '')
            if isinstance(pr, str) and '%' in pr:
                try:
                    return float(pr.split('(')[-1].rstrip('%)').strip())
                except (ValueError, IndexError):
                    return None
            return None

        prev_rate = _rate(prev)
        cur_rate = _rate(cur)
        delta = None
        if prev_rate is not None and cur_rate is not None:
            delta = round(cur_rate - prev_rate, 1)

        return {
            'available': True,
            'prev_run_id': prev.get('run_id', '?'),
            'prev_verdict': prev.get('verdict', '?'),
            'cur_verdict': cur.get('verdict', '?'),
            'prev_pass_rate': prev_rate,
            'cur_pass_rate': cur_rate,
            'pass_rate_delta': delta,
        }

    # ---------- 三种格式输出 ----------

    def to_json(self) -> Dict[str, Any]:
        """机器可读元数据（供 CI 解析）"""
        verdict = self.last_run.get('gatekeeper_verdict', {}) or {}
        return {
            'run_id': self.last_run.get('run_id'),
            'mode': self.last_run.get('mode'),
            'scope': self.last_run.get('scope'),
            'verdict': verdict.get('verdict'),
            'stats': self.compute_stats(),
            'trend': self.compute_trend(),
            'failures': (self.last_run.get('execution', {}) or {}).get('failures', []),
        }

    def to_markdown(self) -> str:
        """人读 markdown 报告"""
        s = self.compute_stats()
        t = self.compute_trend()
        verdict = self.last_run.get('gatekeeper_verdict', {}) or {}
        v = verdict.get('verdict', '未判定')

        lines = [
            f"# 测试报告 — {self.last_run.get('scope', '')}",
            "",
            f"- 运行 ID: `{self.last_run.get('run_id', '')}`",
            f"- 模式: {self.last_run.get('mode', '')}",
            f"- 判定: **{v}**",
            "",
            "## 执行统计",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 总用例 | {s['total']} |",
            f"| 已执行 | {s['executed']} ({s['exec_rate']}%) |",
            f"| 通过 | {s['passed']} |",
            f"| 失败 | {s['failed']} |",
            f"| 阻塞 | {s['blocked']} |",
            f"| 通过率 | {s['pass_rate']}% |",
            "",
        ]

        # 历史趋势
        if t.get('available'):
            lines += [
                "## 历史趋势",
                "",
                f"- 上次判定: {t['prev_verdict']} → 本次: {t['cur_verdict']}",
            ]
            if t.get('pass_rate_delta') is not None:
                arrow = '↑' if t['pass_rate_delta'] > 0 else ('↓' if t['pass_rate_delta'] < 0 else '→')
                lines.append(f"- 通过率变化: {t['prev_pass_rate']}% → {t['cur_pass_rate']}% ({arrow} {abs(t['pass_rate_delta'])}%)")
            lines.append("")

        # 失败明细
        failures = (self.last_run.get('execution', {}) or {}).get('failures', [])
        if failures:
            lines += ["## 失败用例", ""]
            for f in failures:
                cid = f.get('case_id', '?')
                msg = f.get('message', '')[:80]
                lines.append(f"- `{cid}`: {msg}")
            lines.append("")

        return '\n'.join(lines)

    def to_html(self) -> str:
        """可视化 HTML 报告"""
        s = self.compute_stats()
        t = self.compute_trend()
        verdict = self.last_run.get('gatekeeper_verdict', {}) or {}
        v = _html.escape(str(verdict.get('verdict', '未判定')))
        scope = _html.escape(str(self.last_run.get('scope', '')))
        run_id = _html.escape(str(self.last_run.get('run_id', '')))

        verdict_color = {
            'PASS': '#22c55e', 'CONDITIONAL PASS': '#eab308',
            'FAIL': '#ef4444', 'BLOCKED': '#f97316',
        }.get(verdict.get('verdict', ''), '#6b7280')

        trend_html = ''
        if t.get('available') and t.get('pass_rate_delta') is not None:
            d = t['pass_rate_delta']
            arrow = '▲' if d > 0 else ('▼' if d < 0 else '—')
            color = '#22c55e' if d > 0 else ('#ef4444' if d < 0 else '#6b7280')
            trend_html = (
                f'<p>通过率趋势: {t["prev_pass_rate"]}% → {t["cur_pass_rate"]}% '
                f'<span style="color:{color}">{arrow} {abs(d)}%</span></p>'
            )

        failures = (self.last_run.get('execution', {}) or {}).get('failures', [])
        fail_rows = ''.join(
            f'<tr><td>{_html.escape(str(f.get("case_id","?")))}</td>'
            f'<td>{_html.escape(str(f.get("message",""))[:120])}</td></tr>'
            for f in failures
        )
        fail_section = (
            f'<h2>失败用例 ({len(failures)})</h2>'
            f'<table><tr><th>用例</th><th>错误</th></tr>{fail_rows}</table>'
        ) if failures else ''

        return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>测试报告 - {scope}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1f2937}}
.verdict{{display:inline-block;padding:.3rem .8rem;border-radius:.4rem;color:#fff;background:{verdict_color};font-weight:600}}
.cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1rem 0}}
.card{{flex:1;min-width:120px;border:1px solid #e5e7eb;border-radius:.5rem;padding:1rem;text-align:center}}
.card .n{{font-size:2rem;font-weight:700}}
.card .l{{color:#6b7280;font-size:.85rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}
th,td{{border:1px solid #e5e7eb;padding:.5rem;text-align:left}}
th{{background:#f9fafb}}
</style></head><body>
<h1>测试报告 — {scope}</h1>
<p>运行 ID: <code>{run_id}</code> | 模式: {_html.escape(str(self.last_run.get('mode','')))} | 判定: <span class="verdict">{v}</span></p>
<div class="cards">
  <div class="card"><div class="n">{s['total']}</div><div class="l">总用例</div></div>
  <div class="card"><div class="n">{s['passed']}</div><div class="l">通过</div></div>
  <div class="card"><div class="n">{s['failed']}</div><div class="l">失败</div></div>
  <div class="card"><div class="n">{s['blocked']}</div><div class="l">阻塞</div></div>
  <div class="card"><div class="n">{s['pass_rate']}%</div><div class="l">通过率</div></div>
</div>
{trend_html}
{fail_section}
</body></html>"""


def generate_report(last_run: Dict[str, Any], history: Optional[List[Dict]] = None,
                    fmt: str = 'markdown') -> str:
    """便捷入口：生成指定格式报告"""
    gen = ReportGenerator(last_run, history)
    if fmt == 'json':
        return json.dumps(gen.to_json(), ensure_ascii=False, indent=2)
    elif fmt == 'html':
        return gen.to_html()
    else:
        return gen.to_markdown()
