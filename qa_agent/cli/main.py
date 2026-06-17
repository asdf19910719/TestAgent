"""
CLI 入口：命令行解析和用户交互

架构定位（v3.0-rev2）：
本 CLI 既是用户直接入口（终端运行 `qa ...`），
也是 Claude Code subagent 通过 Bash 调用的工具接口。

子命令分两类：
1. 用户面向：init / feature / bugfix / module / release / retry / status / resume
2. Subagent 面向：prepare / scaffold / execute / resolve-bugfix / l0
"""

import json
import sys
import click
from pathlib import Path

# Windows GBK 终端兼容：强制 stdout 用 UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

from ..core.types import Mode
from ..core.engine import Engine
from ..core.init_wizard import InitWizard


@click.group()
@click.version_option(version='0.2.0', prog_name='qa')
def cli():
    """
    AI Test Engineer Agent v3.0 Solo Edition

    产品级质量 + 个人级流程
    Claude Code 扩展（不需要 API key）
    """
    pass


# ============== 用户面向命令 ==============

@cli.command()
@click.option('--type', 'project_type', help='项目类型（web/backend/generic）')
@click.option('--generic', is_flag=True, help='使用 Generic Adapter')
def init(project_type, generic):
    """
    引导式初始化：自动扫描项目、生成配置草稿
    """
    if generic:
        project_type = 'generic'

    wizard = InitWizard()
    result = wizard.run(project_type=project_type)

    if result['status'] == 'success':
        click.echo("\n✅ 初始化完成")
    else:
        click.echo("\n❌ 初始化取消")


@cli.command()
@click.argument('scope')
@click.option('--impact', type=click.Choice(['gitnexus', 'local']), help='影响面模式')
def feature(scope, impact):
    """
    L1 Feature 模式：一个功能开发完
    """
    _run_mode(Mode.L1, scope, f"/qa feature {scope}", impact)


@cli.command()
@click.argument('scope')
@click.option('--impact', type=click.Choice(['gitnexus', 'local']), help='影响面模式')
def module(scope, impact):
    """
    L2 Module 模式：模块/迭代完成
    """
    _run_mode(Mode.L2, scope, f"/qa module {scope}", impact)


@cli.command()
@click.option('--with-dynamic-security', is_flag=True, help='开启动态安全扫描')
@click.option('--with-performance', is_flag=True, help='开启性能压测')
@click.option('--with-compatibility', is_flag=True, help='开启兼容性矩阵')
@click.option('--with-all-nonfunctional', is_flag=True, help='开启所有非功能测试')
@click.option('--skip', multiple=True, help='跳过指定维度（performance/security_scan/compatibility_matrix）')
def release(with_dynamic_security, with_performance, with_compatibility, with_all_nonfunctional, skip):
    """
    L3 Release 模式：发版前完整质量门
    """
    _run_mode(Mode.L3, 'release', '/qa release')


@cli.command()
@click.argument('reference')
def bugfix(reference):
    """
    L4 Bugfix 模式：修复缺陷后验证

    支持多种引用形式：
        qa bugfix BUG-008           # Bug ID
        qa bugfix TC-LOGIN-003      # 用例 ID
        qa bugfix #123              # Issue 编号
        qa bugfix "登录后昵称"       # 关键词
        qa bugfix "用户登录后首页没显示昵称"  # 完整描述
    """
    # 先解析引用得到 bug_id
    from ..core.bug_resolver import resolve_bugfix_target, create_bug_from_description
    target = resolve_bugfix_target(reference)
    if target is None:
        # 自然语言描述 → 创建新 bug
        target = create_bug_from_description(reference)

    _run_mode(Mode.L4, target.id, f"/qa bugfix {reference}")


@cli.command(name='l0')
@click.argument('scope', required=False, default='spot')
def l0_cmd(scope):
    """
    L0 Spot check：快速 sanity，10-30 秒级
    """
    _run_mode(Mode.L0, scope, f"/qa L0 {scope}")


@cli.command()
def retry():
    """
    重跑上次的 selection（修复后再验证）
    """
    from ..core.state_manager import StateManager
    sm = StateManager()
    last_run = sm.load_last_run()

    if not last_run:
        click.echo("⚠️  未找到上次运行记录")
        return

    mode_str = last_run['mode']
    scope = last_run['scope']
    click.echo(f"🔄 重跑上次 {mode_str} 模式：{scope}")

    _run_mode(Mode(mode_str), scope, f"/qa retry")


@cli.command()
def status():
    """查看当前测试覆盖状态"""
    from ..core.yaml_serializer import CaseSerializer, BugSerializer
    from ..core.state_manager import StateManager
    from .ui import bold, green, yellow, red, cyan, dim

    cases = CaseSerializer.load_all(Path('qa'))
    bugs = BugSerializer.load_all(Path('qa'), state_filter='open')

    sm = StateManager()
    last_run = sm.load_last_run()

    click.echo(f"\n{bold('📊 QA Agent 状态')}")
    click.echo(f"\n{bold('用例库')}:")
    click.echo(f"  总数: {green(str(len(cases)))}")

    by_level = {}
    by_priority = {}
    for c in cases:
        by_level[c.level.value] = by_level.get(c.level.value, 0) + 1
        by_priority[c.priority.value] = by_priority.get(c.priority.value, 0) + 1

    click.echo(f"  按层级: {dict(by_level)}")
    click.echo(f"  按优先级: {dict(by_priority)}")

    color_fn = red if bugs else green
    click.echo(f"\n{bold('Open Bugs')}: {color_fn(str(len(bugs)))}")
    for bug in bugs[:5]:
        sev_color = red if bug.severity in ('blocker', 'high') else yellow
        click.echo(f"  - {sev_color(bug.id)}: {bug.title} ({dim('severity=')}{bug.severity})")

    if last_run:
        click.echo(f"\n{bold('最近运行')}:")
        click.echo(f"  模式: {cyan(last_run['mode'])}")
        click.echo(f"  范围: {last_run['scope']}")
        click.echo(f"  状态: {last_run.get('status', 'unknown')}")
    else:
        click.echo(f"\n{dim('暂无运行记录，运行')} {cyan('qa feature <name>')} {dim('开始')}")


@cli.command()
def resume():
    """恢复中断的 L3 运行（检查点恢复）"""
    from ..core.state_manager import StateManager
    sm = StateManager()
    last_run = sm.load_last_run()

    if not last_run:
        click.echo("⚠️  未找到运行记录")
        return

    if last_run.get('status') not in ('paused', 'running'):
        click.echo(f"⚠️  上次运行状态: {last_run.get('status')}（无需恢复）")
        return

    checkpoint = last_run.get('checkpoint', {})
    click.echo(f"⏯️  恢复 L3 运行：{last_run['run_id']}")
    click.echo(f"  当前 Phase: {checkpoint.get('current_phase', 1)}")
    click.echo(f"  已完成: {len(checkpoint.get('completed_phases', []))} 个阶段")
    click.echo(f"\n请用 /qa resume slash command 在 Claude Code 中继续")


# ============== Subagent 面向命令 ==============

@cli.command(name='prepare')
@click.option('--mode', required=True, type=click.Choice(['L0', 'L1', 'L2', 'L3', 'L4']))
@click.option('--scope', required=True)
@click.option('--impact', type=click.Choice(['gitnexus', 'local']), default=None)
@click.option('--docs-path', multiple=True, help='用户动态指定文档目录（可多次）')
def prepare(mode, scope, impact, docs_path):
    """
    [Subagent 用] 影响面分析 + 生成 selection.md，不实际执行

    输出 qa/run/selection.md 和 qa/run/last.json（status=prepared）

    支持动态文档路径：
      --docs-path doc/v2026-06-17-当前版本文档/
      --docs-path ai-docs/prd/
    """
    config_path = '.qa-agent.yml'
    engine = Engine(config_path)

    if impact:
        engine.config['impact_analysis'] = impact

    # 动态文档发现
    docs_info = None
    if docs_path:
        from ..core.requirement_discovery import discover_from_directory, merge_discovery_results
        from ..core.requirement_discovery import discover_requirements

        # 自动发现
        auto = discover_requirements(engine.config)

        # 动态目录发现
        all_dynamic = []
        for path in docs_path:
            result = discover_from_directory(path)
            all_dynamic.append(result)

        # 合并：取第一个动态结果作为主，其他文档合并入 all_docs
        primary_dynamic = all_dynamic[0] if all_dynamic else None
        for d in all_dynamic[1:]:
            primary_dynamic['all_docs'].extend(d.get('all_docs', []))

        docs_info = merge_discovery_results(auto, primary_dynamic)
    else:
        # 仅自动发现
        from ..core.requirement_discovery import discover_requirements
        docs_info = discover_requirements(engine.config)

    # 加载用例
    all_cases = engine._load_all_cases()

    # 影响面分析
    impact_result = engine.impact_analyzer.analyze(Mode(mode), all_cases)

    # 生成 run_id 和 selection.md
    run_id = engine._generate_run_id()
    selection = {
        'total': len(impact_result['selected_cases']),
        'by_level': engine._group_by_level(impact_result['selected_cases']),
        'by_priority': engine._group_by_priority(impact_result['selected_cases']),
        'case_ids': [c.id for c in impact_result['selected_cases']]
    }

    engine.state_manager.save_last_run(
        run_id=run_id,
        mode=Mode(mode),
        scope=scope,
        selection=selection,
        impact_analysis={
            'mode': impact_result['mode'],
            'diff_files': impact_result['diff_files'],
            'affected_symbols': impact_result['affected_symbols']
        },
        command=f"/qa {mode.lower()} {scope}"
    )

    engine.state_manager.save_selection_md(
        mode=Mode(mode),
        scope=scope,
        selection=impact_result['selected_cases'],
        diff_files=impact_result['diff_files'],
        affected_symbols=impact_result['affected_symbols'],
        impact_mode=impact_result['mode']
    )

    # 输出 JSON 给 subagent 解析
    result = {
        'run_id': run_id,
        'mode': mode,
        'scope': scope,
        'total_selected': selection['total'],
        'by_level': selection['by_level'],
        'by_priority': selection['by_priority'],
        'impact_mode': impact_result['mode'],
        'selection_md_path': 'qa/run/selection.md',
        'last_json_path': 'qa/run/last.json',
        'docs': {
            'source': docs_info.get('source', 'unknown'),
            'primary': docs_info.get('primary'),
            'design': docs_info.get('design'),
            'api': docs_info.get('api'),
            'acceptance': docs_info.get('acceptance'),
            'all_docs_count': len(docs_info.get('all_docs', [])),
            'unclassified_count': len(docs_info.get('unclassified', [])),
            'directory': docs_info.get('directory')
        }
    }
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@cli.command(name='discover-docs')
@click.option('--path', required=True, help='文档目录路径')
def discover_docs(path):
    """
    [Subagent 用] 扫描指定目录，按文件名分类文档

    示例：
      qa discover-docs --path doc/v2026-06-17-当前版本文档/

    Subagent 用此命令在用户提供路径后获取文档分类
    """
    from ..core.requirement_discovery import discover_from_directory

    result = discover_from_directory(path)
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@cli.command(name='scaffold')
@click.option('--case', 'case_id', required=True, help='用例 ID')
def scaffold(case_id):
    """
    [Subagent 用] 调用 Adapter 生成测试脚本骨架
    """
    from ..core.yaml_serializer import CaseSerializer
    from ..adapters.loader import auto_detect_adapter

    case = CaseSerializer.load_by_id(case_id, Path('qa'))
    if not case:
        click.echo(f"❌ 未找到用例: {case_id}", err=True)
        sys.exit(1)

    try:
        adapter = auto_detect_adapter()
        script_path = adapter.generate(case)
        click.echo(json.dumps({
            'case_id': case_id,
            'script_path': script_path,
            'status': 'scaffolded'
        }, ensure_ascii=False))
    except NotImplementedError:
        click.echo(json.dumps({
            'case_id': case_id,
            'status': 'manual',
            'note': 'Adapter 不支持自动生成，请手动编写测试'
        }, ensure_ascii=False))


@cli.command(name='execute')
@click.option('--selection', 'selection_path', default='qa/run/selection.md',
              help='selection.md 路径')
@click.option('--mode', required=True, type=click.Choice(['L0', 'L1', 'L2', 'L3', 'L4']))
def execute(selection_path, mode):
    """
    [Subagent 用] 执行选中用例（真实调用 Adapter.run）
    """
    from ..core.state_manager import StateManager
    from ..core.yaml_serializer import CaseSerializer
    from ..core.designer_runner import DesignerRunner
    from ..adapters.loader import auto_detect_adapter
    from ..core.config import load_config

    sm = StateManager()
    last_run = sm.load_last_run()

    if not last_run:
        click.echo("❌ 未找到 last.json，请先运行 `qa prepare`", err=True)
        sys.exit(1)

    # 加载选中用例
    case_ids = last_run['selection']['case_ids']
    cases = []
    for cid in case_ids:
        c = CaseSerializer.load_by_id(cid, Path('qa'))
        if c:
            cases.append(c)

    if not cases:
        click.echo("⚠️  selection 中无用例", err=True)
        sys.exit(0)

    # 执行
    config = load_config('.qa-agent.yml')
    designer = DesignerRunner(config)

    try:
        adapter = auto_detect_adapter()
    except Exception as e:
        click.echo(f"⚠️  Adapter 加载失败: {e}", err=True)
        adapter = None

    execution_result = designer.execute_tests(cases, Mode(mode), adapter=adapter)

    # 收集失败 + 持久化
    bugs = designer.collect_failures(execution_result)
    if bugs:
        designer.save_bugs(bugs)

    # 更新 last.json
    failures = [
        {'case_id': c['case_id'], 'bug_id': bugs[i].id if i < len(bugs) else '',
         'failure_kind': c.get('failure_kind', 'test'),
         'message': c.get('error', '')}
        for i, c in enumerate(execution_result.get('cases', []))
        if c.get('status') == 'fail'
    ]

    sm.update_execution_result(
        run_id=last_run['run_id'],
        result=type('RunResult', (), {
            'fail': execution_result['fail'],
            'duration_seconds': execution_result.get('total', 0) * 0.1
        })(),
        failures=failures
    )

    # 输出结果
    click.echo(json.dumps({
        'run_id': last_run['run_id'],
        'total': execution_result['total'],
        'pass': execution_result['pass'],
        'fail': execution_result['fail'],
        'skip': execution_result['skip'],
        'bugs_created': [b.id for b in bugs]
    }, ensure_ascii=False, indent=2))


@cli.command(name='resolve-bugfix')
@click.option('--ref', required=True, help='Bug 引用')
def resolve_bugfix(ref):
    """
    [Subagent 用] 解析 bug 引用，返回 bug_id

    支持：BUG-XXX / TC-XXX / #issue / 关键词 / 自然语言
    """
    from ..core.bug_resolver import resolve_bugfix_target, create_bug_from_description

    target = resolve_bugfix_target(ref)

    if target is None:
        # 自然语言描述 → 创建新 bug
        target = create_bug_from_description(ref)
        result = {
            'bug_id': target.id,
            'title': target.title,
            'created': True,
            'note': '已根据自然语言描述创建新 bug'
        }
    else:
        result = {
            'bug_id': target.id,
            'title': target.title,
            'state': target.state,
            'severity': target.severity,
            'created': False
        }

    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@cli.command(name='judge')
@click.option('--mode', required=True, type=click.Choice(['L0', 'L1', 'L2', 'L3', 'L4']))
def judge(mode):
    """
    [Subagent 用] Gatekeeper 算法判定（仅 L0/L4 用此命令）

    L1/L2/L3 应使用 qa-gatekeeper subagent 完成深度判定
    """
    from ..core.state_manager import StateManager
    from ..core.gatekeeper import Gatekeeper
    from ..core.config import load_config

    sm = StateManager()
    last_run = sm.load_last_run()

    if not last_run:
        click.echo("❌ 未找到 last.json", err=True)
        sys.exit(1)

    config = load_config('.qa-agent.yml')
    gatekeeper = Gatekeeper(config)

    verdict = gatekeeper.judge(
        run_id=last_run['run_id'],
        mode=Mode(mode),
        last_run=last_run,
        requirements="",
        all_cases=[],
        waivers=None
    )

    # 写报告
    gatekeeper.write_report(verdict, Mode(mode), last_run, Path('qa/final_test_report.md'))

    click.echo(json.dumps(verdict, ensure_ascii=False, indent=2))


# ============== 内部工具 ==============

def _run_mode(mode: Mode, scope: str, command: str, impact: str = None):
    """
    执行指定模式（直接 Python 流程，不经 Claude Code）

    适用场景：
    - 用户在终端直接运行（无 LLM 推理，仅算法判定）
    - 测试 / 自动化脚本
    """
    try:
        config_path = Path('.qa-agent.yml')
        if not config_path.exists():
            click.echo("⚠️  未找到 .qa-agent.yml，请先运行：qa init")
            if not click.confirm('继续使用默认配置？', default=False):
                return

        engine = Engine(str(config_path) if config_path.exists() else '.qa-agent.yml')

        if impact:
            engine.config['impact_analysis'] = impact

        click.echo(f"\n🚀 启动 {mode.value} 模式...")
        click.echo(f"💡 提示：完整智能流程请在 Claude Code 中使用 /qa {scope}")

        result = engine.run(mode=mode, scope=scope, command=command)

        if result.get('status') == 'cancelled':
            click.echo(f"\n❌ {result.get('message', '用户取消')}")
        else:
            click.echo(f"\n✅ {mode.value} 完成: {result.get('verdict', 'N/A')}")

    except Exception as e:
        click.echo(f"\n❌ 错误: {e}", err=True)
        raise


if __name__ == '__main__':
    cli()
