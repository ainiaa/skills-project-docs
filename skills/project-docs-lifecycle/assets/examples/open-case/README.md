# 无预设方案案例：当前技术复跑与历史审计

作者：Jeff.Liu

最初输入只有 sources/ 的四份资料：业务原话、运营现状、CSV样本和旧计行命令，没有规定最终方案或计数口径。先调查/追问，再取得明确标为模拟的答复、比较人工/配置/研发后，选择最小CLI增量。PRD前资料、唯一PRD、设计和模拟边界保留为案例来源；部分文档叙述的是当时阶段，不代表当前执行结果。

本目录维护可复用的规格、输入、app/代码、tests/用例和 trace.json。trace.json是2项FR、6项AC与17项实际测试ID的映射计划，包含当前源文件摘要，**不是执行回执**。这些AC的自动化关联只覆盖CLI断言；回原渠道核实、组织者确认和业务验收需要单独人工证据，不能从trace通过推定。每次验证都用当前工具重新采集；改动被绑定的业务规格/源码/测试后须复核并更新映射计划，不能复用旧成功结果。当前业务规则包括冲突先于取消过滤、跨场次独立、空白身份逐行待核实、原值/原表保留和非法输入明确失败。

在集合根目录，将本目录复制到新的工作目录后复跑（下列工作目录需自行指定，输出文件必须尚不存在）：

```sh
python3 scripts/lifecycle_test_runner.py --root <工作副本> --tests tests --trace trace.json --output <工作副本>/execution-current.json
python3 scripts/lifecycle_quality.py trace --root <工作副本> --contract trace.json --execution execution-current.json
PYTHONPATH=scripts python3 -B -m unittest test_lifecycle_quality test_lifecycle_handoff
```

接续回归用小型临时资料和当前采集器构建包，在独立Python进程中核验并按CAS更新；业务回归另复制必要输入/源码/规格，真实重跑本案例17项测试。CI不读取历史成功回执，不复制旧工具，也不依赖历史ZIP。

[完整历史归档](../../../../../audits/lifecycle/open-case-20261031.zip)与[摘要清单](../../../../../audits/lifecycle/open-case-20261031.manifest.json)保存精简前88个文件，包括两轮TDD、最初gap、旧工具、L6检查点及只读修复历史。归档是审计资料，不是新鲜门禁；不要解压旧工具覆盖当前实现。当前Skill按质量与追踪契约生成实际交接包，区分测试通过检查点和仅转交资料。

历史实跑曾在独立新上下文中完成模拟验收、隔离目录发布、故障恢复与支持复跑；真实效果保持待观察。每次本地技术复跑不证明真人验收、真实消费者兼容、生产权限、收益或桌面聊天自动切换。没有新增平台、账号或依赖。
