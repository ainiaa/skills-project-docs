# Product 交互证据复核

从评测样本目录提取问句、调用返回及来源行号：

```sh
python3 evals/product/interaction_evidence.py /path/to/sample
python3 evals/product/prepare_judge.py /path/to/blind-key.json /path/to/new-review-directory
python3 -m unittest discover -s evals/product -v
```

匿名映射沿用已有样本编号。输出到新目录，历史报告和判据另行保留。评判者按原业务判据逐项填入下表，以连续原文、来源和轮次支持结论。同一个问题可以包含多项业务决定。

| 业务事项 | 实际请求及来源 | 工具是否接受 | 宿主是否展示 |
|---|---|---|---|
| 例：阈值币种 | 原文及文件行号；区分最终回复、中间文本及结构化调用 | 与该会话、轮次、call_id 对应的布尔返回，缺失或歧义记 unknown | 有独立前端展示证据才可确认，CLI 数据单独使用时记 unknown |

读不到 rollout 时保留 CLI 的 codex 消息段供核实来源。文本只是线索，工具输出也可能回显类似文字。匹配到 session_meta 仅说明找到了同一会话，要断言漏问还须检查完整轮次、全部助手消息、调用以及文稿中的问题去向。返回 accepted:false 记录为拒绝，不能推断用户没有经其他渠道看到该问题。现有输入格式未包含可证明 UI 已展示的宿主回执。

回归夹具保存真实合成采购样本 rollout 的第 62、63、65 行。第 63 行是异步消息完成事件。三行均以原始事件保留，不附整份会话。回归覆盖实际请求、成功接受及展示未知，并验证缺返回、拒绝、跨轮、不同调用 ID、重复返回和无结构化记录的边界。
