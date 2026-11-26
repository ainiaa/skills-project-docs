# 已确认PRD接到自有研发体系

作者：Jeff.Liu

只有用户明确选择 Converge 接管时读取；普通PRD、原型、评审和修订保持独立，不因缺少Converge而阻塞文档交付。已明确授权实现时沿用该授权，不重复主持业务访谈。正式PRD是唯一主文；业务身份、Converge工作项/执行ID和发布版本分别保留用途。

## 准备与显式登记

```bash
python3 <集合>/scripts/product_handoff.py --prd <正式PRD路径> \
  --converge-root <明确选择的Converge源码根> --project <项目Git根> \
  --target <沿用的需求或工作项目标ID> --state-root <Converge工作项状态根>
```

默认只读检查，返回当前路径、产品版本、字节摘要、FR/AC、项目Git基线及native-v1提供方摘要，不写项目、不执行研发。目标ID使用字母/数字开头的字母、数字、点、下划线或短横线，最多128字符；复用已有身份，不能为绕过冲突反复另建ID。提供方是用户明确选择的本地可信执行依赖，不是恶意脚本沙箱。

用户已授权研发、关键业务规则已明确后携带准备结果的`contract_fingerprint`追加`--adopt --expected-contract <摘要>`，通过Converge现有`resume_or_create`建立原生工作项及正式PRD引用。状态根沿用既有Converge工作项位置，必须位于被测仓库外或Git返回的真实元数据目录内；工具拒绝源码内目录，避免工作项验证更新使其自身测试回执过期。工具不复制或改写PRD、不写第三方PDLC目录，也不启动实现、子任务或发布。文档标记“已确认”只说明内容声明，调用者仍须核对真实确认与授权。

对仍存在的原生工作项，相同输入重复登记保留状态与验证记录；已有目标输入、FR/AC范围或项目Git基线不符时拒绝覆盖，也不另建同目标工作项，要求显式修订/接续。Converge完成后保留档案并删除活动项；普通重登记拒绝复活旧项，下一轮按[完结后迭代](iterations.md)显式建立新执行身份。CLI显式登记核对上次准备的契约摘要，准备后文档、提供方运行时源码或参数改变则拒绝，Converge 的测试源码变化不影响准备结果；已有实现授权下可直接传递摘要，不要求新增人工确认。执行结果不确定时先核对已有工作项，不盲目重放。需求修订保留原始证据，明确本期新版本和目标，不能改旧摘要冒充恢复。

支持包含FR/AC的单文件正式PRD，或用`--tracking`显式指定同目录追踪文件。主文/追踪及其本地Markdown引用递归进入`input_snapshot`，其他附件按完整字节冻结；远程资料或目录外引用用`--attachments <映射JSON>`提供明确本地快照，不联网抓取。全部文件进入native引用并校验新鲜度；AC映射也须绑定完整快照，不能仅凭主文摘要认证附件。非Markdown附件内部引用不自动解析，额外输入须明确列入清单。未确认、无有效来源/验收、无Git基线或提供方不可用时返回具体缺口；普通文档交付仍可独立进行。

需要更新已登记需求时，读取[修订影响与恢复](revision.md)。使用新确认版本、旧接管结果、完整影响报告准备显式修订，沿原工作项路径继续；保存准备请求后可用`--prepared`重放。普通登记仍拒绝输入漂移，不能借新ID或直接编辑状态绕过修订。

## 实施与回传

登记成功只证明正式输入已进入工作项。Converge在续接、验证前/绿灯返回前及完成前再次核对本地绝对路径引用的完整摘要；PRD变化或丢失时保留工作项并拒绝推进，不能只靠再次调用Product接管才发现变化。下一步读取已安装Converge自身入口，携带登记返回的`native_result.path`续接同一work item，显式使用native-v1，按已有计划/TDD/实现/评审闭环推进；不得另建同范围执行项或反向调用Lifecycle重启完整研发流程。Converge新版本auto也默认native，准备工具仍显式冻结native以兼容已有安装；本工具不是完整Converge控制器，不生成宿主托管运行记录。专项工作按[自有工程方法](https://github.com/ainiaa/skills-project-docs/blob/main/skills/project-docs-engineering/SKILL.md)选择，完整边界见[38项能力盘点](https://github.com/ainiaa/skills-project-docs/blob/main/docs/pdlc-capability-map.md)。

原始测试按[工程证据](../../project-docs-lifecycle/references/engineering-evidence.md)关联AC，功能完成、自动测试、UAT、上线授权、部署与效果分别回传Lifecycle。没有实际宿主/岗位试用证据，不承诺跨会话自动接管或恢复。

已有项目确实选择第三方PDLC时才读[可选兼容约定](pdlc.md)。自有主路径不要求安装、升级或修改PDLC。

Product接管通过原生`resume_or_create(..., exclusive_target=True)`，在Converge registry锁内合并同目标范围检查与登记，桥接脚本不再自行扫描工作项。准备与重放先执行[API能力预检](iterations.md#写前预检)，旧版缺参数时在写前拒绝，不降级为锁外扫描。普通原生调用仍按范围区分活动任务；已经有完成档案的原契约必须显式开启后继，不能普通重建。

首次使用新版指纹时，按现有准备入口刷新旧请求。保留活动工作项和原历史。对要求预先冻结验收命令的 Converge 版本，按所选版本自身契约处理；能力预检通过仍需组合测试才能确认兼容。
