# 工程测试证据关联

作者：Jeff.Liu

复用 Converge 原始 Evidence Receipt，不转换成 `lifecycle_test_runner.py` 的 unittest 回执。
每个 AC 显式关联一组必需测试选择器及其回执，任一缺失、跳过、失败、源码过期或选择器不匹配均保留缺口。
示例映射是输入格式，不是通过证据：

```json
{
  "prd": {"path": "prd.md", "version": "v1", "sha256": "<准备时的prd_sha256>"},
  "acceptance": {"AC-001": [{"receipt": "evidence/test.observed.json", "selector": "example.Tests.test_ok"}]}
}
```

```bash
python3 <集合>/scripts/provider_test_evidence.py --prd <正式PRD> --mapping <映射JSON> \
  --provider-root <明确选择的Converge源码目录> --workspace <被测项目> --baseline <实际Git基线>
```

映射必须冻结正式已确认PRD的路径、版本与字节摘要，可沿用接管准备输出；PRD和回执的相对路径均按映射文件目录解析。旧版仅AC字典不再足以判为ready；须核对需求与断言后显式补齐原输入绑定，不能由工具按新PRD自动给旧映射盖章。版本、正文或路径变化均需重新核对映射。校验以明确选择的 Provider 自己的回执规则、测试选择器和
当前源码身份为准；只运行校验器，不执行回执里的业务命令、不安装依赖。上游代码是本地选择的可信执行依赖，
不是针对恶意Provider的沙箱；变更后的 Provider 不能沿用旧 runner 身份。

带追踪或附件时，映射还必须包含`inputs`，其值为本次接管/准备结果的完整`input_snapshot`。校验器据其中明确的追踪与附件配置重建当前快照，逐字节核对所有输入；缺失、变更或检查期间漂移均不能ready。无附件的单文件旧格式仍可用。需求修订须重新核对AC与断言后建立新映射，不能只替换版本或快照给旧测试自动续签；操作见Product的[修订与恢复](../../project-docs-product/references/revision.md)。

`ready` 只表示本次 PRD 所有声明 AC 的已关联测试组均有当前执行证据，不证明测试断言足够。
必须另外逐项核对 AC 含义与断言；人工或未适配的 AC 保留原文与实际验收资料，没有自动测试时保持缺口。
`tdd_verified=false`：只收集绿灯不证明先红后绿；`business_authorization=false` 与 `deployment_verified=false`
始终保留。记录测试选择器和汇总结果不能当作任意单个方法的逐用例报告。

原始回执、映射和本次检查结果作为 L6 的实际证据引用；不补写 `runner_sha256` 或冒充旧 trace 格式。
现有 `tested` 交接仍要求其 unittest 契约；工程 Provider 证据通过已有 `transfer` 路径携带，并保留原来的
`tests_ready=null` 与人工/业务缺口，不能据检查结果自动提升阶段、业务批准或上线状态。

所有AC回执必须绑定同一份项目SourceReceipt；报告就绪前再通过所选Converge复核该源码仍为当前源码。检查期间源码变化、混合不同版本或末次复核失败均保留缺口，不报告ready。

检查开始时解析并固定所选Converge物理根目录和验证脚本集合的字节指纹，每次回执验证前后及返回ready前均复核；可见代码变化会使本轮失败，不混用不同版本。结果保留`provider_root`与`verification_code_fingerprint`，后者是验证脚本集身份，不等同于完整工作流Provider Binding。此结果是本次检查时点的证据视图，后续源码、PRD或校验环境变化须重新核验。
