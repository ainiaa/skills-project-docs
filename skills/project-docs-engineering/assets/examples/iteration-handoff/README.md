# Engineering交接与下一轮迭代示例

作者：Jeff.Liu

这是整数合计功能的合成示例，展示资料与执行接口；示例确认字段不是任何真实业务批准，目录中没有已运行的测试报告。真实项目使用自己的业务规则、确认和已核验测试命令。

| 输入 | v1 | v2 |
|---|---|---|
| Product唯一主文 | [PRD](v1/prd.md) | [PRD](v2/prd.md) |
| Engineering技术方案 | [设计](v1/design.md) | [设计](v2/design.md) |
| Engineering验证依据 | [测试策略](v1/test-strategy.md) | [测试策略](v2/test-strategy.md) |
| 显式附件选择 | [映射](v1/attachments.json) | [映射](v2/attachments.json) |

两个目录是连续版本的输入快照，不是同一轮的两份正式PRD。业务身份沿用`REQ-total`；第二轮工程执行目标为`REQ-total.iter-2`。业务版本、业务身份与执行身份分别记录。

## 独立使用

只要求技术方案时，沿[设计](v1/design.md)与[测试策略](v1/test-strategy.md)交付，不需要Converge或Lifecycle。PRD引用的设计、测试策略及附件映射选择同一版本；通过`product_inputs.freeze_inputs`可独立冻结并用`require_current_inputs`拒绝资料漂移。此验证不证明业务规则正确或获批。

## 联用步骤

以下命令从集合根运行，`<示例>`为本目录的绝对路径。正式使用时复制需要的版本到受控交付位置并核对内容；保存请求及回执放在被测源码外。

先检查明确选择的Converge是否支持迭代，不需要PRD，也不写状态：

```bash
python3 scripts/product_handoff.py --check-provider --converge-root <Converge根> --capability iterate
```

准备v1完整输入，然后用输出的`contract_fingerprint`显式登记：

```bash
python3 scripts/product_handoff.py --prd <示例>/v1/prd.md --attachments <示例>/v1/attachments.json --converge-root <Converge根> --project <项目Git根> --target REQ-total --state-root <源码外状态目录>
python3 scripts/product_handoff.py --prepared prepared-v1.json --adopt --expected-contract <准备摘要>
```

第一条输出保存为`prepared-v1.json`，第二条输出保存为`adopted-v1.json`。登记只冻结输入；沿返回的`native_result.path`进入Converge原任务，不重复开计划或PRD。使用项目真实命令，经`work_item.py verify`取得通过回执，再将返回的`receipt`对象单独保存并交给`work_item.py complete`。工程通过不等于UAT、发布授权或上线。

完成后用相同项目、提供方及状态根准备v2，执行目标改为`REQ-total.iter-2`。用既有[修订比较命令](../../../../project-docs-product/references/revision.md)从两份准备/登记输出的`input_snapshot`生成`impact-v2.json`。有Lifecycle记录时提供真实FR→产物映射，保守失效本轮受影响证据；没有记录则明确为`requirements_only`，不冒充工程影响完整。

```bash
python3 scripts/product_handoff.py --prd <示例>/v2/prd.md --attachments <示例>/v2/attachments.json --converge-root <Converge根> --project <项目Git根> --target REQ-total.iter-2 --state-root <同一状态目录> --previous-iteration adopted-v1.json --impact-report impact-v2.json
python3 scripts/product_handoff.py --prepared prepared-v2.json --adopt --expected-contract <新准备摘要>
```

首条输出保存为`prepared-v2.json`；后继携带原业务身份和前驱完成指纹，使用新工作项。中断后重放同一准备请求；不要重新准备来覆盖不确定结果。活动任务内变更使用`--previous-handoff`修订，已经完成的任务使用`--previous-iteration`，两者互斥。

## 验证与限制

本集合的`test_engineering_handoff.py`会复制示例，在临时项目中实际执行合计测试：v1通过并完成；v2先增加负数失败测试，再修复并复测，确认原完成档案不变。该夹具验证输入冻结、交接和TDD接口，不代表真实Java或CI/CD验收。

旧版Converge缺API时在写前报告；完成档案写入后清理中断时，先用原通过回执重放complete。历史任务若已删除且没有完成档案，不能凭描述补造证明；先人工核对，再以明确的新任务接入。真实发布、数据库执行及业务效果保持独立授权和验收。
