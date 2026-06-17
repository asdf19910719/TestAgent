"""
CLI 入口：命令行解析和用户交互
"""

import click
from pathlib import Path

from ..core.types import Mode
from ..core.engine import Engine
from ..core.init_wizard import InitWizard


@click.group()
@click.version_option(version='0.1.0', prog_name='qa')
def cli():
    """
    AI Test Engineer Agent v3.0 Solo Edition

    产品级质量 + 个人级流程
    """
    pass


@cli.command()
@click.option('--type', 'project_type', help='项目类型（web/backend/generic）')
@click.option('--generic', is_flag=True, help='使用 Generic Adapter')
def init(project_type, generic):
    """
    引导式初始化：自动扫描项目、生成配置草稿

    示例：
        qa init
        qa init --type web
        qa init --generic
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

    示例：
        qa feature 用户登录
        qa feature 订单支付 --impact=local
    """
    _run_mode(Mode.L1, scope, f"/qa feature {scope}", impact)


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
    _run_mode(Mode.L4, reference, f"/qa bugfix {reference}")


@cli.command()
def retry():
    """
    重跑上次的 selection（修复后再验证）

    示例：
        # 修复代码后
        qa retry
    """
    click.echo("🔄 重跑上次执行范围...")
    # Phase 3 实现
    click.echo("⚠️ retry 在 Phase 3 实现")


@cli.command()
def status():
    """
    查看当前测试覆盖状态

    示例：
        qa status
    """
    click.echo("📊 测试覆盖状态...")
    # Phase 3 实现
    click.echo("⚠️ status 在 Phase 3 实现")


@cli.command()
def resume():
    """
    恢复中断的 L3 运行（检查点恢复）

    示例：
        # Ctrl+C 中断后
        qa resume
    """
    click.echo("⏯️  恢复中断的运行...")
    # Phase 6 实现
    click.echo("⚠️ resume 在 Phase 6（L3）实现")


def _run_mode(mode: Mode, scope: str, command: str, impact: str = None):
    """
    执行指定模式
    """
    try:
        # 加载或生成配置
        config_path = Path('.qa-agent.yml')
        if not config_path.exists():
            click.echo("⚠️  未找到 .qa-agent.yml，请先运行：qa init")
            click.echo("或者继续使用默认配置？(yes/no): ", nl=False)
            if not click.confirm('', default=False):
                return

        # 创建引擎
        engine = Engine(str(config_path) if config_path.exists() else '.qa-agent.yml')

        # 覆盖影响面模式
        if impact:
            engine.config['impact_analysis'] = impact

        # 执行
        click.echo(f"\n🚀 启动 {mode.value} 模式...")
        result = engine.run(mode=mode, scope=scope, command=command)

        # 输出结果
        if result.get('status') == 'stub':
            click.echo(f"\n⚠️  {result.get('message', 'Phase 1: 核心骨架已就绪')}")
            click.echo(f"✅ 已生成 qa/run/last.json 和 qa/run/selection.md")
            click.echo(f"\n完整执行在 Phase 2/3 实现")
        elif result.get('status') == 'cancelled':
            click.echo(f"\n❌ {result.get('message', '用户取消')}")
        else:
            click.echo(f"\n✅ {mode.value} 完成")

    except Exception as e:
        click.echo(f"\n❌ 错误: {e}", err=True)
        raise


if __name__ == '__main__':
    cli()
