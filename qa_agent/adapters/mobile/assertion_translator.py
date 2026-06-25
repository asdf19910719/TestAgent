"""
Android 测试断言转译器
将 TestCase.assertions (声明式 YAML) 转译成可执行的 Kotlin/Java 测试代码

支持的断言类型:
- database: ContentProvider/ContentResolver 查询
- log: Logcat 读取 + 正则匹配
- ui: Espresso UI 断言
- return_value: 方法调用返回值断言
"""

from typing import Dict, List, Any
from pathlib import Path


class AssertionTranslator:
    """断言转译引擎"""

    def __init__(self, package_name: str, language: str = 'kotlin'):
        """
        Args:
            package_name: Android 项目包名(如 com.openclaw.agent)
            language: 'kotlin' 或 'java'
        """
        self.package = package_name
        self.lang = language

    def translate(self, assertions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        转译所有断言

        Args:
            assertions: 用例 yml 的 assertions 列表

        Returns:
            {
                'imports': ['import android.content.ContentResolver', ...],
                'setup_code': '// 准备代码',
                'assertion_code': '// 断言代码',
                'helpers': {'assertLogContains': '...'}  # 辅助方法
            }
        """
        imports = set()
        setup_lines = []
        assertion_lines = []
        helpers = {}

        for assertion in assertions:
            atype = assertion.get('type', 'unknown')

            if atype == 'database':
                result = self._translate_database(assertion)
            elif atype == 'log':
                result = self._translate_log(assertion)
            elif atype == 'ui':
                result = self._translate_ui(assertion)
            elif atype == 'return_value':
                result = self._translate_return_value(assertion)
            else:
                # 未知类型,生成 TODO
                result = {
                    'imports': [],
                    'setup': [],
                    'assertions': [f"// TODO: 实现 {atype} 断言: {assertion}"],
                    'helpers': {}
                }

            imports.update(result['imports'])
            # setup 去重(resolver 声明只保留一份,避免 Kotlin val 重复声明)
            for line in result['setup']:
                if line not in setup_lines:
                    setup_lines.append(line)
            assertion_lines.extend(result['assertions'])
            helpers.update(result['helpers'])

        return {
            'imports': sorted(imports),
            'setup_code': '\n'.join(setup_lines),
            'assertion_code': '\n'.join(assertion_lines),
            'helpers': helpers
        }

    def _translate_database(self, assertion: Dict[str, Any]) -> Dict[str, Any]:
        """
        转译 database 断言

        示例输入:
          type: database
          query: "SELECT COUNT(*) FROM RawContacts WHERE account_type='com.openclaw.agent'"
          equals: 3

        输出 Kotlin:
          val cursor = resolver.query(...)
          assertEquals(3, cursor.getInt(0))
        """
        query = assertion.get('query', '')
        equals = assertion.get('equals')
        contains = assertion.get('contains')

        imports = {
            'android.content.ContentResolver',
            'android.provider.ContactsContract',
            'androidx.test.platform.app.InstrumentationRegistry',
            'org.junit.Assert.assertEquals',
        }

        setup = []
        assertions = []

        if 'RawContacts' in query or 'Contacts' in query or 'Data' in query:
            # ContactsContract 查询
            setup.append('val resolver = InstrumentationRegistry.getInstrumentation().targetContext.contentResolver')

            # 解析 SQL 生成 ContentResolver 查询
            # 简化版:支持常见模式
            if 'COUNT(*)' in query.upper():
                table_uri = self._extract_contacts_uri(query)
                selection, selection_args = self._parse_where_clause(query)

                assertions.append(f'run {{')
                assertions.append(f'    val cursor = resolver.query(')
                assertions.append(f'        {table_uri},')
                assertions.append(f'        arrayOf("COUNT(*) AS cnt"),')
                assertions.append(f'        {selection},')
                assertions.append(f'        {selection_args},')
                assertions.append(f'        null')
                assertions.append(f'    )')
                assertions.append(f'    cursor?.use {{')
                assertions.append(f'        it.moveToFirst()')
                if equals is not None:
                    assertions.append(f'        assertEquals({equals}, it.getInt(it.getColumnIndex("cnt")))')
                assertions.append(f'    }}')
                assertions.append(f'}}')

            elif 'SELECT' in query.upper():
                # 普通字段查询
                fields = self._extract_select_fields(query)
                table_uri = self._extract_contacts_uri(query)
                selection, selection_args = self._parse_where_clause(query)

                fields_str = ", ".join([f'"{f}"' for f in fields])
                assertions.append(f'run {{')
                assertions.append(f'    val cursor = resolver.query(')
                assertions.append(f'        {table_uri},')
                assertions.append(f'        arrayOf({fields_str}),')
                assertions.append(f'        {selection},')
                assertions.append(f'        {selection_args},')
                assertions.append(f'        null')
                assertions.append(f'    )')
                assertions.append(f'    cursor?.use {{')
                assertions.append(f'        it.moveToFirst()')
                if equals is not None:
                    assertions.append(f'        assertEquals("{equals}", it.getString(0))')
                if contains is not None:
                    assertions.append(f'        assertTrue(it.getString(0).contains("{contains}"))')
                assertions.append(f'    }}')
                assertions.append(f'}}')

        return {
            'imports': imports,
            'setup': setup,
            'assertions': assertions,
            'helpers': {}
        }

    def _translate_log(self, assertion: Dict[str, Any]) -> Dict[str, Any]:
        """
        转译 log 断言

        示例输入:
          type: log
          pattern: "完全同步完成: 新增=2, 删除=1"

        输出 Kotlin:
          assertLogContains("完全同步完成: 新增=2, 删除=1")
        """
        pattern = assertion.get('pattern', '')

        imports = {
            'org.junit.Assert.assertTrue',
        }

        # 生成辅助方法(读 Logcat)
        helper_method = '''
    private fun assertLogContains(pattern: String, timeoutMs: Long = 5000) {
        val startTime = System.currentTimeMillis()
        val process = Runtime.getRuntime().exec(arrayOf("logcat", "-d", "-s", "TAG:*"))
        val reader = process.inputStream.bufferedReader()

        var found = false
        while (System.currentTimeMillis() - startTime < timeoutMs) {
            val line = reader.readLine() ?: break
            if (line.contains(pattern)) {
                found = true
                break
            }
        }
        reader.close()
        assertTrue("日志中未找到: $pattern", found)
    }
'''

        return {
            'imports': imports,
            'setup': [],
            'assertions': [f'assertLogContains("{pattern}")'],
            'helpers': {'assertLogContains': helper_method}
        }

    def _translate_ui(self, assertion: Dict[str, Any]) -> Dict[str, Any]:
        """转译 UI 断言(Espresso)"""
        selector = assertion.get('selector', '')
        visible = assertion.get('visible')
        text = assertion.get('text')

        imports = {
            'androidx.test.espresso.Espresso.onView',
            'androidx.test.espresso.matcher.ViewMatchers.withId',
            'androidx.test.espresso.matcher.ViewMatchers.withText',
            'androidx.test.espresso.assertion.ViewAssertions.matches',
            'androidx.test.espresso.matcher.ViewMatchers.isDisplayed',
        }

        assertions = []
        if visible:
            assertions.append(f'onView(withId(R.id.{selector})).check(matches(isDisplayed()))')
        if text:
            assertions.append(f'onView(withId(R.id.{selector})).check(matches(withText("{text}")))')

        return {
            'imports': imports,
            'setup': [],
            'assertions': assertions,
            'helpers': {}
        }

    def _translate_return_value(self, assertion: Dict[str, Any]) -> Dict[str, Any]:
        """转译方法返回值断言"""
        method = assertion.get('method', '')
        equals = assertion.get('equals')

        imports = {'org.junit.Assert.assertEquals'}

        return {
            'imports': imports,
            'setup': [],
            'assertions': [f'// TODO: 调用 {method} 并断言返回值 == {equals}'],
            'helpers': {}
        }

    # === 辅助方法:SQL 解析(简化版) ===

    def _extract_contacts_uri(self, query: str) -> str:
        """从 SQL 提取对应的 ContentProvider URI"""
        query_upper = query.upper()
        if 'RAWCONTACTS' in query_upper:
            return 'ContactsContract.RawContacts.CONTENT_URI'
        elif 'CONTACTS' in query_upper:
            return 'ContactsContract.Contacts.CONTENT_URI'
        elif 'DATA' in query_upper:
            return 'ContactsContract.Data.CONTENT_URI'
        else:
            return 'null  // TODO: 未知表,请手动指定 URI'

    def _parse_where_clause(self, query: str) -> tuple:
        """
        解析 WHERE 子句,返回 (selection, selectionArgs)

        示例: "WHERE account_type='com.openclaw.agent'"
          → ("account_type=?", "arrayOf(\"com.openclaw.agent\")")
        """
        import re
        where_match = re.search(r'WHERE\s+(.+?)(?:ORDER|GROUP|LIMIT|$)', query, re.IGNORECASE)
        if not where_match:
            return ('null', 'null')

        where_clause = where_match.group(1).strip()

        # 简化处理:替换字符串字面量为 ?
        # 例如: account_type='xxx' → account_type=?
        placeholders = []

        def replace_literal(match):
            placeholders.append(match.group(1))
            return '?'

        selection = re.sub(r"'([^']*)'", replace_literal, where_clause)

        if placeholders:
            args_str = ', '.join(f'"{p}"' for p in placeholders)
            return (f'"{selection}"', f'arrayOf({args_str})')
        else:
            return (f'"{selection}"', 'null')

    def _extract_select_fields(self, query: str) -> List[str]:
        """提取 SELECT 的字段列表"""
        import re
        match = re.search(r'SELECT\s+(.+?)\s+FROM', query, re.IGNORECASE)
        if not match:
            return ['*']

        fields_str = match.group(1).strip()
        if fields_str == '*' or 'COUNT(*)' in fields_str.upper():
            return ['*']

        # 分割字段
        fields = [f.strip() for f in fields_str.split(',')]
        return fields
