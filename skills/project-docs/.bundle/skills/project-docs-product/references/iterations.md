# 完成后的下一轮迭代

作者：Jeff.Liu

活动任务中的需求变更使用[修订接口](revision.md)，保持原执行目标；已完成任务的新一轮使用本接口，保留业务身份和前驱证据，明确新执行目标。两者互斥，不重新生成正式PRD或恢复旧任务。

## 写前预检

```bash
python3 <集合>/scripts/product_handoff.py --check-provider --converge-root <明确选择的Converge根> --capability iterate
```

普通登记选择`adopt`，活动修订选择`revise`。检查所需函数及调用签名，返回版本、支持能力和缺口，不读取PRD、不写项目或状态。版本仅辅助定位，不用版本号推断API存在；兼容检查不证明业务行为、宿主托管或提供方可信。普通文档与Engineering方案不要求Converge。

准备/重放还会检查实际需要的能力：旧版缺少`exclusive_target`、`revise_work_item`、完成档案读取或前驱参数时，更新所选集合后重新准备。拒绝发生在Lifecycle失效和原生写入之前；提供方在预检后漂移仍由既有摘要护栏拒绝，已发生的保守失效保留并明确恢复。

## 前提和身份

上一轮必须由Converge受控verify产生通过回执，并执行complete。新版本会在原工作项旁的`completed/`保存不可变完成档案，再删除活动项。档案含原契约、原始通过回执和完整指纹；清理中断时先用原回执重放complete。旧版已经删除且没有档案的历史任务不能自动补造证明。

沿同一项目、提供方物理目录和状态根，使用新确认产品版本、新执行目标及上一轮最后一次登记结果。业务身份例如`REQ-total`；新执行目标例如`REQ-total.iter-2`，不能用普通登记绕过活动任务冲突。新迭代可以选择当前项目Git基线，沿用旧基线也须核对实际源码和工程范围；这不是对旧任务自动rebase。

## 准备与重放

先按[完整输入准备](engineering.md)得到新版本`prepared-input-v2.json`，从旧新输入计算[影响报告](revision.md#比较变化并核对影响)。有Lifecycle记录时提供实际映射，没有时保留`requirements_only`边界。

```bash
python3 <集合>/scripts/product_revision.py --before adopted-v1.json --after prepared-input-v2.json > impact-v2.json
python3 <集合>/scripts/product_handoff.py --prd <新正式PRD> --converge-root <同一Converge根> \
  --project <同一项目Git根> --target <新执行目标> --state-root <同一状态根> \
  --previous-iteration adopted-v1.json --impact-report impact-v2.json > prepared-iteration-v2.json
python3 <集合>/scripts/product_handoff.py --prepared prepared-iteration-v2.json \
  --adopt --expected-contract <本次准备摘要> > adopted-v2.json
```

追踪与附件仍显式传入相同的`--tracking`/`--attachments`。准备核对前驱档案与旧PRD完整输入、原契约及当前选择，绑定业务身份、前驱完成指纹和新范围。登记先沿Lifecycle原CAS入口保守失效，再由原生registry锁建立一个后继；不可变关联先于活动项写入，保存请求可在中断后重放。并发竞争只允许一个后继消费同一完成档案。

相同请求重复登记续接同一后继；更换后继、前驱指纹、项目或原始输入则拒绝。后继完成后重放旧准备不能复活它。后继内再修订时仍保留原业务身份；下一轮使用最后一次修订结果接续。旧成功与失败留在旧档案，新轮按新工作项验证，不把旧回执当当前通过。

本接口仅登记输入和关联，不启动实现、第二个工程循环或发布。可执行资料与合成演练见[Engineering示例](https://github.com/ainiaa/skills-project-docs/blob/main/skills/project-docs-engineering/assets/examples/iteration-handoff/README.md)。
