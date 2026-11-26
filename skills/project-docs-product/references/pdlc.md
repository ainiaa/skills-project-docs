# 可选第三方PDLC交接

PDLC是第三方Skill。主路径使用[Project Docs + Converge native-v1](engineering.md)，不依赖PDLC，也不修改其源码或要求定制补丁。

只有用户明确选择第三方PDLC项目或命令时读取；仅发现旧PDLC文件不改变当前自有流程，也不代表选择第三方提供方。本集合的`product_dependencies.py --skill-root <所需目录> --pdlc-root <实际PDLC目录>`只读检查入口及资源完整性；可用时返回`compatibility=handoff_only`、`stateWrite=not_attempted`。不自动安装、升级、全局扫描或写`docs/.pdlc-state`，资源可用不等于模型行为、原生接管或宿主自动执行已验证。

沿用正式PRD路径、业务身份、版本、FR/AC和真实确认，以产物引用及明确交接说明提交给对方已有工作流；先核对其实际契约。不能把上游生成PRD的入口当成“接管已有PRD”入口，也不能伪造支持`prd-adoption-v1`。本集合不为PDLC分配第二份正式需求，不把业务沉默当批准。

已有第三方阶段/历史只读保留。需要迁移至自有体系时，核对原始PRD、当前阶段和证据，使用自有接管显式登记当前输入；不批量改写其状态或自动将旧测试标记为当前通过。第三方执行、发布和恢复依其实际能力及用户授权，结果分别回传，不启动两个控制器互相派发。

方法借鉴与能力去向见[盘点](../../../docs/pdlc-capability-map.md)，完整MIT版权见[声明](../../../references/third-party-notices.md)。
