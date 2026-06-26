"""测试前端静态分析器（W1，迁移自 oec web-uitest-frontend-analyzer）"""
import json
import pytest
from pathlib import Path

from qa_agent.webui.analyzer.analyze import build_knowledge
from qa_agent.webui.analyzer.parsers.vue_router_parser import parse_vue_router


@pytest.fixture
def vue_project(tmp_path):
    """造一个解析器约定结构的最小 Vue2 项目"""
    proj = tmp_path / 'vueproj'
    (proj / 'src' / 'router').mkdir(parents=True)
    (proj / 'src' / 'views').mkdir(parents=True)

    (proj / 'package.json').write_text(
        '{"name":"demo","dependencies":{"vue":"^2.6.0","vue-router":"^3.0.0"}}',
        encoding='utf-8')

    (proj / 'src' / 'router' / 'index.js').write_text(
        "import Vue from 'vue'\n"
        "import Router from 'vue-router'\n"
        "const routes = [\n"
        "  { path: '/login', component: () => import('@/views/Login.vue') },\n"
        "  { path: '/orders', component: () => import('@/views/Orders.vue') },\n"
        "]\n"
        "export default new Router({ routes })\n",
        encoding='utf-8')

    (proj / 'src' / 'views' / 'Login.vue').write_text(
        "<template>\n"
        "  <div>\n"
        '    <el-input v-model="username" placeholder="用户名" />\n'
        '    <el-button @click="doLogin">登录</el-button>\n'
        "  </div>\n"
        "</template>\n"
        "<script>\n"
        "export default { data() { return { username: '' } }, methods: { doLogin() {} } }\n"
        "</script>\n",
        encoding='utf-8')

    return proj


def test_detect_and_parse_routes(vue_project):
    """框架检测 + 路由解析"""
    knowledge = build_knowledge(
        repo=vue_project, test_urls=['/login'], base_prefix='', max_depth=3)

    assert knowledge['framework'] == 'vue2'
    assert knowledge['total_routes'] == 2
    assert knowledge['relevant_route_count'] == 1  # /login 匹配


def test_knowledge_schema_fields(vue_project):
    """产出 JSON 含约定 schema 字段"""
    knowledge = build_knowledge(
        repo=vue_project, test_urls=['/login'], base_prefix='', max_depth=3)

    for field in ('schema_version', 'framework', 'frontend_repo',
                  'test_urls', 'total_routes', 'relevant_route_count'):
        assert field in knowledge, f"缺字段: {field}"


def test_routes_only_mode(vue_project):
    """routes_only 模式只解析路由不深挖组件"""
    knowledge = build_knowledge(
        repo=vue_project, test_urls=['/login'], base_prefix='',
        max_depth=3, routes_only=True)

    assert knowledge['total_routes'] == 2


def test_parse_vue_router_direct(vue_project):
    """直接调路由解析器（返回 Route dataclass，完整路径在 .url 字段）"""
    routes = parse_vue_router(vue_project)
    urls = {r.url for r in routes}
    assert '/login' in urls
    assert '/orders' in urls


def test_nonexistent_repo():
    """非 Vue/不存在的项目走 error 早返回（不崩溃）"""
    knowledge = build_knowledge(
        repo=Path('/nonexistent/proj'), test_urls=['/x'],
        base_prefix='', max_depth=3)
    # 非 Vue 项目返回 error 字段而非 total_routes，关键是不抛异常
    assert 'error' in knowledge or knowledge.get('total_routes') == 0
    assert knowledge['framework'] not in ('vue2', 'vue3')
