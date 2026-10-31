# 本地最小追踪契约 v1

作者：Jeff.Liu

这是 V1.6 首个切片的协调记录，未实现历史 V1.2 的完整 25 实体 Schema、通用工作流引擎或平台鉴权。`lifecycle_record.py` 使用标准库检查下列局部契约，不是标准 JSON Schema 验证器。不读取外部引用，不自动做业务批准、状态推进、发布或失效裁决。

| 位置 | 字段与语义 |
|---|---|
| 根 | `schema_version=1`、正整数 `revision`；`project_ref`、`subject_ref`、`goal`、`owner`、带时区 ISO `updated_at`；未知 Owner 用 `unassigned` 并列下一步，不虚构人员 |
| `branches[]` | 唯一 `id`；`route` 为 development/guidance/permission/configuration/data；非空 `required` 产物 ID 列表。各分支独立；分批发布分别建分支，跨分支依赖可引用 |
| `artifacts[]` | 唯一 `id`、`kind`、`stage`（L0–L10）、`branch`、正整数 `version`、`owner`、`source`、`status`、`depends_on[]` 和 `evidence[]`。正式 PRD/代码/构建/测试等用 kind 说明，不复制权威内容 |
| 依赖 | `{id, version}` 精确绑定记录内产物；不存在、循环为结构错误。版本变化为待复核，传播到其下游；不影响无依赖分支。已完成节点依赖未完成节点也待复核 |
| 证据 | `kind` planned/reported/executed/confirmed；`source` 受控引用；`actor` 执行/确认者；带时区 `at`；`result` passed/failed/blocked/skipped/unknown；`subject={id,version}`。可加 `validity`（非 current 为待复核）、`expires_at`（带时区到期时间）、`environment`、`build`、`scope`。已声明的构建/环境/范围须与 executed/confirmed 证据相同，显式过期或对象/版本不符为待复核 |
| `assertions[]` | `text`、`classification`（fact/business_feedback/hypothesis/technical_unknown）、`source`、`owner`、`confirmation`（unconfirmed/confirmed/conflicted）。已确认另需 `confirmed_by`、带时区 `at`、`applies_to` 版本/范围引用；分类不等同真实性校验 |
| `next_actions[]` | `action`、`owner`、`depends_on`、`expected_result`；可补已知期限。无依赖用 `none`，不是自动执行队列 |

状态取值：`not_started / in_progress / blocked / pending_confirmation / completed / not_applicable / cancelled`。阻塞和待确认须有 `reason`、`recovery`；不适用及取消须有理由。状态由协调者依据真实来源记录，不是服务端门禁。只记录已发生步骤，不要求从 L0 补造历史；只写 PRD 不强制后续阶段。

`completed` 至少有当前对象版本的 executed/confirmed passed 证据；只有计划或转述则待复核。除下文所述 planned/unknown 外，失败、跳过、未知或非 current 证据不能被另加一条 passed 隐藏，应通过新对象版本和复测证据明确解决，旧版本留在历史快照中。`recorded` 仅表示该分支记录中的所有产物均有已完成的一致声明，不表示全生命周期已经覆盖、引用真实或通过生产放行。所有项均已完成或有理由取消/不适用、且至少一项为取消/不适用时，分支标 `closed`；它表示范围已关闭，不等于成功交付。未完成项仍为 `incomplete`，证据失效优先为 `needs_review`。工具检查本地已提供的对象/版本、构建/环境/范围一致性及 expires_at 是否到期；不查询真实来源。L6 的覆盖矩阵、L7 的业务身份、L8 批准真实性和适用规则、L9 的实际制品/环境/批次由协调者按阶段规则核实。缺少外部来源仍不能声称通过。

## 安全更新与恢复

先读取当前记录版本，将修改写到独立候选文件，保持 project/subject 身份且 `revision` 加一；产物内容、来源、依赖、构建或适用范围等变化时自身 `version` 增加；状态、证据、负责人和阻断/恢复说明是观察信息，仅提升记录 `revision`，不虚构新产物版本。旧证据 subject 保持原对象版本，新对象版本需要新的实际执行或确认依据；不能改写旧证据或下游旧依赖凑通过。用 `--expected-revision` 与 `--candidate` 更新。工具先解析记录文件的真实路径（通过文件软链接更新时保留链接），在真实文件同目录独占 `.lock` 下重读版本、验证候选和身份，保存仅当前用户可读写、不可覆盖的 `.rev-N.json` 历史快照，临时文件刷盘后原子替换；冲突或坏输入不覆盖当前文件。允许保存合法的未完成/待复核视图，不冒充审批通过。既有产物和分支不得直接删除；取消或不适用需保留对象及理由，避免隐藏未完成范围。

锁失败保留他人锁，先查是否有活跃写者；异常退出遗留锁只在确认无写者后人工移除。不提供跨主机/网络文件系统、多用户原子审计或权限隔离，也不防其他程序绕过锁直接写文件。初次记录在已确认位置由单写者建立；后续写入统一使用工具，历史快照含同等敏感引用，按项目权限和保存策略管理。

同一产物版本的 evidence 仅可追加，已有条目不能删减、改结果或改来源等字段。追加 passed 不会清除既有失败；解决失败后用新产物版本及真实复测依据承接，更新实际受影响的下游依赖，旧版本及失败留在不可覆盖的历史快照中。新版本可不携带旧版本证据，但不能将原观察改绑：同一产物下 kind/source/actor/at 相同视为同一次观察，其内容和 subject 不可改写。新的执行或确认须引用其实际来源和时间；本地比较不能证明来源真实性，不是签名或外部审计系统。

更新时也核对同目录、同记录文件名的已有前序 `.rev-N.json` 观察，防止先保存无证据的中间版本、再改绑更早回执。前序快照须结构有效、项目/问题身份一致且revision与文件名一致；损坏或混入他项记录时停止更新，保留当前文件与历史，不自动修补审计。无关文件和未来版本不作为前序；缺失历史不强造，不要求读取集合内审计ZIP。接续按授权携带必要历史或回权威来源核实，缺失/外部历史的真实性和未重用不能由本地工具证明。

planned/unknown 表示尚待执行的计划，单独存在不证明完成，也不按一次真实执行失败处理；同版本追加实际通过证据后可保留原计划，不必为记录正常进度虚增产物版本。显式 failed/skipped 等结果、reported/unknown、失效/过期或对象与范围错绑仍须复核，不用计划类别隐藏已知异常。

观察身份中的 at 按带时区的实际时刻比较：等价的偏移、Z和小数秒表示不是新观察，不能借格式转换改绑对象或结果。比较保留微秒以下的小数精度，不能把不同的纳秒级观察合并；原证据保持原样，不重写历史时间，真正不同的执行时刻仍按新观察核对。

CLI 只检查时不写文件；退出 1 表示结构无效或存在待复核，退出 0 仅表示本地一致（分支仍可能 incomplete）。更新成功另含 `updated=true`，即使因待复核退出 1，也表示候选已保存；拒绝更新时不返回此标记。报告同时含 `valid`、`errors`、`needs_review`、`branches` 和 `verification=local_consistency_only`。恢复还必须回到权威来源核实当前版本、访问权及冲突，不能仅靠 revision 猜测外部状态。

记录未知、失败和来源冲突，不保存密钥、整份财务资料或超出交接权限的内容。新增能力可以扩展元数据；不支持的 schema_version 停止处理，旧模型迁移须另行做差异和兼容验证。
