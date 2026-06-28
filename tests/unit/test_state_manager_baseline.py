"""
StateManager 基线刷新判定逻辑单元测试

验证三层判定（时间 / 内容 / 质量），修复前只看时间的缺陷。
"""

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from qa_agent.core.state_manager import StateManager


@pytest.fixture
def sm(tmp_path):
    """临时 StateManager，隔离 qa 目录"""
    qa_dir = str(tmp_path / "qa")
    return StateManager(qa_dir=qa_dir)


def _make_baseline(established_days_ago=0, pass_rate="40/40 (100%)",
                   docs_hash=None, history=None):
    """构造测试用基线"""
    return {
        'established_at': (datetime.now() - timedelta(days=established_days_ago)).isoformat(),
        'established_by': 'test-run',
        'updated_at': datetime.now().isoformat(),
        'updated_by': 'test-run',
        'total_cases': 40,
        'pass_rate': pass_rate,
        'completeness': 'full',
        'docs_hash': docs_hash or {},
        'history': history or [],
    }


# ── 第一层：时间维度 ──────────────────────────────────────────────

class TestTimeDimension:
    def test_baseline_not_exist_triggers_refresh(self, sm):
        """基线不存在 → 刷新"""
        assert sm.needs_baseline_refresh() is True

    def test_fresh_baseline_no_refresh(self, sm, tmp_path):
        """4 天前的基线，无文档变更 → 不刷新（本次事故的场景）"""
        sm.save_baseline(_make_baseline(established_days_ago=4))
        assert sm.needs_baseline_refresh() is False

    def test_baseline_over_30_days_triggers_refresh(self, sm):
        """超过 30 天 → 刷新"""
        sm.save_baseline(_make_baseline(established_days_ago=31))
        assert sm.needs_baseline_refresh() is True


# ── 第二层：内容维度 ──────────────────────────────────────────────

class TestContentDimension:
    def test_docs_hash_mismatch_triggers_refresh(self, sm, tmp_path):
        """需求文档内容 hash 变化 → 刷新（即使时间没到 30 天）"""
        doc = tmp_path / "req.md"
        doc.write_text("原始需求", encoding='utf-8')

        # 基线记录的是旧 hash
        old_hash = "deadbeef00000000"
        sm.save_baseline(_make_baseline(
            established_days_ago=4,
            docs_hash={str(doc): old_hash}
        ))

        # 当前文档内容已变（hash 必然不同）
        assert sm.needs_baseline_refresh(docs_paths=[str(doc)]) is True

    def test_docs_hash_match_no_refresh(self, sm, tmp_path):
        """需求文档未变 → 内容维度不触发"""
        doc = tmp_path / "req.md"
        doc.write_text("稳定需求", encoding='utf-8')

        # 基线记录正确 hash
        current_hash = sm._compute_file_hash(doc)
        sm.save_baseline(_make_baseline(
            established_days_ago=4,
            docs_hash={str(doc): current_hash}
        ))

        assert sm.needs_baseline_refresh(docs_paths=[str(doc)]) is False


# ── 第三层：质量维度（治本维度）──────────────────────────────────

class TestQualityDimension:
    def test_low_pass_rate_triggers_refresh(self, sm):
        """上次 pass_rate < 70% → 刷新（治本：捕获 spec 过时）"""
        sm.save_baseline(_make_baseline(
            established_days_ago=4,
            pass_rate="25/40 (62%)"  # 本次事故场景：大量失败
        ))
        assert sm.needs_baseline_refresh(sample_check=True) is True

    def test_high_pass_rate_no_refresh(self, sm):
        """上次 pass_rate 健康 → 质量维度不触发"""
        sm.save_baseline(_make_baseline(
            established_days_ago=4,
            pass_rate="40/40 (100%)"
        ))
        assert sm.needs_baseline_refresh(sample_check=True) is False

    def test_last_verdict_fail_triggers_refresh(self, sm):
        """上次 gatekeeper 判定 FAIL → 刷新（覆盖高通过率但 P0 失败的场景）"""
        sm.save_baseline(_make_baseline(
            established_days_ago=4,
            pass_rate="38/40 (95%)"  # 通过率不低，但有 P0 失败导致 FAIL
        ))
        # 构造 last.json 记录上次判定 FAIL（真实数据来自 last.json，非 baseline history）
        sm._atomic_write_json(sm.run_dir / 'last.json', {
            'run_id': 'prev-run',
            'gatekeeper_verdict': {'verdict': 'FAIL', 'reason': 'P0 失败'},
        })
        assert sm.needs_baseline_refresh(sample_check=True) is True

    def test_sample_check_off_by_default(self, sm):
        """sample_check 默认关闭，质量维度不生效（向后兼容）"""
        sm.save_baseline(_make_baseline(
            established_days_ago=4,
            pass_rate="25/40 (62%)"  # 低通过率
        ))
        # 不传 sample_check → 即使质量差也不触发（保持旧行为）
        assert sm.needs_baseline_refresh() is False


# ── 三层组合 ─────────────────────────────────────────────────────

class TestCombinedDimensions:
    def test_time_overrides_everything(self, sm):
        """时间维度触发后，其他维度无需检查"""
        sm.save_baseline(_make_baseline(established_days_ago=31))
        assert sm.needs_baseline_refresh(
            docs_paths=[], sample_check=True
        ) is True

    def test_regression_this_incident(self, sm, tmp_path):
        """
        回归测试：本次事故场景
        - 基线 4 天前建立（时间维度不触发）
        - 需求文档未变（内容维度不触发）
        - 但上次执行有 23 个失败（质量维度触发）
        → 应该刷新，而非"基线有效"
        """
        sm.save_baseline(_make_baseline(
            established_days_ago=4,
            pass_rate="24/47 (51%)",  # 23 个失败，本次事故的静态+E2E失败
        ))
        # 修复前：只看时间 → False（错误，未检测到 spec 过时）
        # 修复后：开启质量维度 → True（正确）
        assert sm.needs_baseline_refresh(sample_check=True) is True
