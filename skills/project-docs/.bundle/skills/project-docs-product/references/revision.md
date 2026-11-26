# 需求修订、影响范围与恢复

作者：Jeff.Liu

仅在已登记需求变更或恢复中断的修订时读取。沿同一业务目标、正式PRD和原生工作项，不重新访谈已决事项、不创建第二套阶段状态。普通文档修订无需Converge；下面的输入比较与Lifecycle失效也可单独运行。

## 完整输入与准备材料

项目特殊检查需要机器对账时，在唯一主文或追踪文件中放一份 `project-checks` JSON代码块，不复制规则正文：

```project-checks
{"items":[{"id":"PROJECT-KEEP-ID","stage":"L3","check":"acceptance","required":true,"method":"review","requirements":["FR-001"],"source":{"path":"decisions.md","sha256":"实际摘要","quote":"原始决定中的具体规则"}}],"changes":[]}
```

来源使用相对PRD目录的Markdown文件，须由已有链接或显式附件纳入同一输入快照；首次由接收者从原始资料反查索引有无遗漏。快照从冻结正文重建检查定义，不接受评审结果自己缩减必需集合。索引只记录ID、来源、所属FR和检查方法，业务规则仍由正式主文维护；无特殊检查不添加空索引或文件。

修订对账在原FR/AC变化之外列出项目检查的增删改。来源文件摘要仍用于核实输入新鲜度。同一路径和引用原文保持一致时，单独刷新文件摘要不算修改检查规则。删除或修改旧项时，在新输入的 `changes` 中为该ID记录 `{id,reason,source,before,after}`，source仍需当前冻结文件的摘要及决定原文。before/after分别为旧、新快照中该项规范定义的digest（`product_inputs.digest`），删除时after为null；旧决定不能套给另一种修改。缺少依据或摘要错绑返回 `scope_ready=false`，拒绝应用影响、接纳修订或完结后迭代。该状态只证明决定引用完整，不认证批准人的权限。旧失败和旧范围保留，新决定不倒改历史。工具仍只传播已声明依赖；未建模的影响由内容复核保留缺口。

`product_handoff.py`只读准备结果包含`input_snapshot`：正式主文、显式同目录追踪文件、递归Markdown引用、所有选定附件的规范路径及完整SHA-256，并保留FR/AC及其输入关系。快照含正式文档与Markdown附件原文，保存到项目已有受控资料位置；旧快照用于离线比较，不改旧摘要或旧原文冒充恢复。

`--tracking`沿现有PRD拆分约定校验标题、版本、来源、确认及FR/AC；主文必须链接同目录追踪，追踪不能替主文提供标题/版本/状态。非Markdown附件作为不透明完整文件，不解析其内部外链，额外材料须明确列入清单。远程URL不自动访问；`--attachments`接收一个JSON对象，键是文档中的精确引用，值是本地快照文件路径（相对映射文件目录解析）。未被链接的显式附件作为共享输入影响全部FR；被引用的附件按来源关系归属。无法归属的共享文本或引用采用保守影响范围。

```json
{"https://example.invalid/interview": "sources/interview.md"}
```

这只冻结用户提供的本地字节，不认证其与远程原文一致或远程资料仍新鲜。缺本地快照、漏文件、未声明的目录外引用或输入漂移时拒绝；不通过读取任意目录或抓取远程内容补齐。

首次登记也可保存准备请求：

```bash
python3 <集合>/scripts/product_handoff.py --prd <正式PRD> --tracking <同目录追踪> \
  --attachments <本地快照映射.json> --converge-root <Converge根> --project <Git根> \
  --target <原目标ID> --state-root <已有状态根> > prepared-v1.json
python3 <集合>/scripts/product_handoff.py --prepared prepared-v1.json \
  --adopt --expected-contract <准备结果的contract_fingerprint> > adopted-v1.json
```

单文件或无远程资料时省略相应可选参数。保存的是准备请求，不是已登记结果；后者用于下一次修订的`--previous-handoff`。登记仍不启动实现。

旧准备文件缺少完整`input_snapshot`时明确要求重新准备，不由工具自动补签旧摘要；原有工作项保持。新的普通单文件调用仍兼容。准备后可见的物理路径变化（包括同字节symlink替换）和字节变化在native写前拒绝；写后才发生的外部变化仍报告实际状态待核对，不自动回滚或假装未发生写入。

## 比较变化并核对影响

明确本期规则并取得实际确认，更新正式PRD到新产品版本，保留旧接管结果。用相同项目、Git基线、目标和提供方目录准备`prepared-v2.json`。工具不自动bump版本、不更改基线、不授予业务确认；同版本内容漂移可比较，但不能显式接纳为新修订。

```bash
python3 <集合>/scripts/product_revision.py --before adopted-v1.json --after prepared-v2.json \
  --record <现有Lifecycle记录.json> --bindings <需求产物映射.json> > impact-v2.json
```

映射示例：`{"FR-001":["requirement-artifact"],"FR-002":["other-artifact"]}`。有记录时须覆盖旧新FR的并集，指向实际存在的唯一产物ID；缺映射、未知端点或依赖环拒绝。可同时省略record/bindings，只比较需求，但结果明确为`requirements_only`，不能当作工程影响完整证明。

结果分列FR、AC、文件的新增/修改/删除/未变。规则、关联来源或附件变化影响所属FR和AC；仅产品版本/确认记录变化不自动判成业务规则变化。沿显式映射和记录的depends_on传播直接/间接影响，不把上游或独立分支一并失效。未声明关系无法自动发现；代码影响仍用现有CodeGraph及源码/测试核对，不推测未采集的依赖已被覆盖。

报告内的候选记录将受影响产物增一版本并设为pending_confirmation，保留旧证据和依赖版本，使旧证据及旧依赖不能认证新版本；独立产物保持。确认后由原Lifecycle流程审查、更新依赖版本并补新证据，不自动重新绑定旧观察。

## 显式接纳修订

```bash
python3 <集合>/scripts/product_handoff.py --prd <新确认PRD> \
  --converge-root <同一Converge根> --project <同一Git根> --target <原目标ID> \
  --state-root <原状态根> --previous-handoff adopted-v1.json --impact-report impact-v2.json \
  > prepared-revision-v2.json
python3 <集合>/scripts/product_handoff.py --prepared prepared-revision-v2.json \
  --adopt --expected-contract <新准备结果的contract_fingerprint> > adopted-v2.json
```

拆分或显式附件场景仍带上与prepared-v2一致的tracking/attachments选项。准备绑定实际旧工作项状态指纹和新旧输入/影响报告，只读不失效。应用先沿原Lifecycle CAS入口保存历史并保守失效，再调用Converge原生revise；不新增工作项或执行循环。原生保留目标、workspace、baseline与文件路径，内部task_key按新FR/AC重算；旧状态和转换请求进入history，旧成功失效、失败尝试及其重试保护保留。

Project Docs和Converge需协调更新；旧提供方没有显式修订API时拒绝，不能降级为直接覆盖状态。完成后原生仍删除非终态工作项，修订历史保留为证据；重放旧请求不能复活已完成项。

原生validator已支持的旧state可用原始或规范化等价摘要修订；只补齐其原有可选默认字段，不把真实revision、范围、引用或失败记录变化当作等价。历史保留原始旧字段形态，旧版保存的规范化history也能重放。Lifecycle报告冻结规范绝对路径，恢复还核对project_ref和subject_ref，不能把旧历史接到被替换的其他记录或符号链接目标。

## 中断与恢复

先核对原工作项、Lifecycle当前版本及history，再使用**同一份**`prepared-revision-v2.json`和原摘要重放。不要重新创建目标、删除锁/历史、改JSON状态或重置重试预算。

- Lifecycle写入前失败或CAS冲突：原生不执行；核实实际记录后重新准备影响报告。
- Lifecycle已失效、native尚未更新：保留待确认视图，原请求可继续；不回滚成旧完成状态。
- 原生历史已写、当前项尚未替换：同请求核对历史后完成原子替换；不同请求冲突，不覆盖归档。
- 原生已应用但回复丢失：同请求仅返回当前项；后续验证/记录已推进也不能被旧请求回退。
- 输入、提供方或旧状态再次变化：拒绝。若旧契约仍在且仅验证记录推进，核对后重新准备CAS；若已修订，使用原保存请求核实结果。基线变化需要独立明确的rebase决定。
- 相同源码/argv已有失败：修订不释放重试。沿原验证规则，以实际源码修复或新的同源码observed pass恢复，不能通过换参数或重新登记绕过。

工程验证仍走原工作项的verify。对照新AC和实际断言建立新映射，`inputs`填新接管结果的完整`input_snapshot`；旧映射不能自动换签。新鲜工程证据不代表UAT、部署或业务收益；Lifecycle待确认项须取得各自实际验收，工具不代签。

仅单独维护Lifecycle时，可用`product_revision.py --report impact-v2.json --apply --expected-impact <报告fingerprint>`显式失效；联合接管会调用同一入口，无需重复手工执行。重复应用及已有后续记录时只核实已应用事实，不重写当前记录。

POSIX本地writer使用按记录的内核advisory锁，并保留旧版排他哨兵防止混用写入。进程退出后内核锁释放，只回收本协议可识别的完整标记；同一活跃记录会拒绝竞争，独立记录不受阻。未知旧锁可能仍由其他写入者持有，必须先核实属主，不能自动删除。非POSIX保留旧写入方式，强退恢复未验证；本机制不认证网络文件系统或断电持久性。强退留下的未引用临时文件不作为当前记录或完成证据，未知文件不自动清理。

修订准备报告、应用前Lifecycle快照、当前/历史重放候选统一按JSON值与类型精确比较；1、1.0和true不视为同一冻结值，不能保留旧fingerprint而偷换类型，也不能覆盖同revision中已漂移的扩展元数据。对象键顺序可不同，不影响合法准备与重放。该检查不授予直接绕过写锁编辑记录的权限，也不认证其他程序忽略写锁后的并发写入。
