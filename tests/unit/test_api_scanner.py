"""测试 Spring MVC 接口扫描器（backlog A1）"""
import json
import pytest
from pathlib import Path

from qa_agent.core.api_scanner import (
    scan_spring_apis, scan_java_file, _normalize_path,
)


SAMPLE_CONTROLLER = """package com.openclaw.api;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/contacts")
public class ContactController {

    @GetMapping("/list")
    public List<Contact> listContacts(@RequestParam String phone) {
        return service.list(phone);
    }

    @PostMapping
    public Contact addContact(@RequestBody ContactDto dto) {
        return service.add(dto);
    }

    @DeleteMapping("/{id}")
    public void deleteContact(@PathVariable Long id) {
        service.delete(id);
    }

    @RequestMapping(value = "/sync", method = RequestMethod.PUT)
    public void syncContacts() {
        service.sync();
    }
}
"""

NON_CONTROLLER = """package com.openclaw.service;

@Service
public class ContactService {
    public void doStuff() {}
}
"""


@pytest.fixture
def spring_src(tmp_path):
    src = tmp_path / 'src' / 'main' / 'java' / 'com' / 'openclaw'
    (src / 'api').mkdir(parents=True)
    (src / 'service').mkdir(parents=True)
    (src / 'api' / 'ContactController.java').write_text(SAMPLE_CONTROLLER, encoding='utf-8')
    (src / 'service' / 'ContactService.java').write_text(NON_CONTROLLER, encoding='utf-8')
    return tmp_path / 'src' / 'main' / 'java'


def test_normalize_path():
    assert _normalize_path('/api/contacts', '/list') == '/api/contacts/list'
    assert _normalize_path('/api/contacts', '') == '/api/contacts'
    assert _normalize_path('api/x/', '/y/') == '/api/x/y'
    assert _normalize_path('', '/login') == '/login'


def test_scan_extracts_all_methods(spring_src):
    """提取 GET/POST/DELETE/RequestMapping 全部接口"""
    result = scan_spring_apis(str(spring_src))

    assert result['controllers'] == 1  # 只有 ContactController
    apis = result['apis']
    by_path_method = {(a['path'], a['method']) for a in apis}

    assert ('/api/contacts/list', 'GET') in by_path_method
    assert ('/api/contacts', 'POST') in by_path_method
    assert ('/api/contacts/{id}', 'DELETE') in by_path_method
    assert ('/api/contacts/sync', 'PUT') in by_path_method


def test_scan_skips_non_controller(spring_src):
    """非控制器类不被扫描"""
    result = scan_spring_apis(str(spring_src))
    classes = {a['class'] for a in result['apis']}
    assert 'ContactService' not in classes
    assert classes == {'ContactController'}


def test_scan_captures_handler_names(spring_src):
    """提取 handler 方法名"""
    result = scan_spring_apis(str(spring_src))
    handlers = {a['handler'] for a in result['apis']}
    assert 'listContacts' in handlers
    assert 'addContact' in handlers
    assert 'deleteContact' in handlers


def test_output_structure_matches_consumer(spring_src):
    """输出 {'apis': [...]} 结构对齐消费端 enhanced_execute_with_auth"""
    result = scan_spring_apis(str(spring_src))
    assert 'apis' in result
    assert isinstance(result['apis'], list)
    # 消费端按 len(api_data.get('apis', [])) 算应测接口数
    assert result['total'] == len(result['apis'])
    # 每个 api 含 method + path（消费端 conftest 用 method/url）
    for a in result['apis']:
        assert 'method' in a and 'path' in a


def test_scan_nonexistent_dir():
    with pytest.raises(FileNotFoundError):
        scan_spring_apis('/nonexistent/src')


def test_scan_java_file_direct(spring_src):
    """直接扫单文件"""
    f = spring_src / 'com' / 'openclaw' / 'api' / 'ContactController.java'
    apis = scan_java_file(f, spring_src)
    assert len(apis) == 4
    assert all(a['class'] == 'ContactController' for a in apis)
