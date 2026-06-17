# AI Test Engineer Agent 实施指南

> 版本：v2.1
> 修订日期：2026-06-16
> 配套规范：`docs/AI Test Engineer Agent 需求与方案文档.md`（v2.1）
> 文档定位：把规范里的"必须 / 不允许"等含糊点收敛为**协议级、机器可校验、可直接交给 Claude 执行**的具体方案。

本指南目录：

1. 三角色工程骨架（session 划分、文件锁、状态恢复）
2. 需求语义指纹（§5.9 落地）
3. Flaky 检测、Mutation 抽样、对抗式 review（§5.6 落地）
4. 影响面分析与 GitNexus 漏选兜底（§8 落地）
5. 用例 YAML：targets 自动维护、secret 引用、KPI 反馈通道（§9 落地）
6. Adapter 能力声明矩阵（§14 落地）
7. CLI 输出规范（终端体验）
8. 模式切换确认协议：人触发 vs Agent 触发 + auto_confirm（§18.4 落地）
9. 环境失败 vs 测试失败的判定（§19 落地）
10. Waiver 白名单与签字校验（§5.8 落地）
11. L3 维度切片协议（§7.6 落地）
12. 渐进式接入既有项目（§10A 落地）
13. KPI 数据回流接口（§2.1 落地）

---

<!-- IG_TAIL_PLACEHOLDER -->
