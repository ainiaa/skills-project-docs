# 模拟 CLI 设计 v2

作者：Jeff.Liu

沿用设计交接 v1、唯一PRD draft-1，由 [simulation-resolution.md](simulation-resolution.md) 在本轮模拟范围明确采用候选契约；旧设计与原gap在审计包中保持原字节，本页为当前模拟方案入口。适用版本为本次 app/legacy_export.py，字段及约束仅供模拟，不升级生产兼容承诺。

入口仍为 `python3 app/legacy_export.py --session S1 --input sources/registrations.csv`。正常 stdout 是单个 JSON：session、count、pending_records、has_pending、notice。count 是确认基数，pending_records 每项仅复制五个原字段并增加 reason；reason 分别为 missing_employee_id / status_conflict。notice 依次为有待核实、无该场次记录或本快照无待核实。JSON键顺序不承诺；待核实原行以输入次序呈现不影响人数。stderr为空且退出0表示本次快照计算成功，不表示异常已核实或最终座位获组织者确认。

解析使用 csv.DictReader(strict=True)，校验必要表头、重复表头和每行列数。所有行的必要字段及status先校验，错误即整份输入失败，即使错误行在其他场次；字段按原值、不归一化。额外字段不参与计算和异常输出，原表仍保留。缺员工号是合法业务异常；其他四关键字段缺失/空、status非法、文件/编码/CSV解析失败是输入失败。输入失败stderr说明原因，非零退出，stdout无人数JSON。

校验后筛选本场并按非空员工号分组。组状态同时confirmed/cancelled的全组冲突不计；只confirmed计一；只cancelled不计。空员工号逐行pending不计。跨场次相同员工独立，冲突不传播到其他组/场次。已确认人数和待核实原行数不相加成总人数。

原文件没有写操作；无远程依赖、DB、事务或锁。重跑相同输入不变更任何状态。输出不完整丢弃后以保留快照重跑；核实得到新资料另存新快照，运营回原source渠道、组织者确认的职责保持；本文件定义方案，不声明本次UAT或发布结果。真实输出消费者和渠道未核实，禁止推广到生产。

已知影响范围：CLI→summarize→JSON→模拟运营，测试覆盖该真实进程入口及返回值；无其他调用者资料。真实消费者、实际Owner、原渠道权限、规模与收益仍未核实；历史生产待办和阶段计划见[审计包](../../../../../audits/lifecycle/open-case-20261031.zip)的 production-backlog.md、remaining-stages.md，不将旧计划当成本次执行结果。

## 空值防护边界追加

依据boundary-clarification.md，所有内容存在性用strip判断；纯空白员工号逐行待核实且保留原值，record_id/session_id/source纯空白属于整份输入失败。非空员工号的前后空白和大小写仍是原值的一部分，不trim后分组。原PRD不改，第二轮测试和最终构建已覆盖。
