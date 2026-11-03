# Project Docs 分享与试用材料

作者：Jeff.Liu

[中文首页](../README.md) · [English](../README.en.md) · [公开案例](examples/petclinic/README.md)

本页是可编辑的分享草稿与试用清单。未对外发帖、邀请用户、提交目录或采集试用数据；没有把曝光/转化推断写成已获得的结果。

## 可以直接使用的案例短文

**标题：接手陌生 Spring Boot 项目，先让 AI 整理一条能核对的上手路线**

第一次接手项目时，最难的常常不是知道用了哪些框架，而是找到一条可理解、可验证的业务链路。我用 Project Docs 对公开的 Spring Petclinic 做了一个小范围走读：从 Owner 创建表单进入 Controller，检查字段校验、保存和详情跳转，再给出新人阅读顺序。

结果包括一份上手手册、模块关系图和核心流程图。文档引用固定提交的源码，图源与源码锚点一起保留。一个具体例子是：该流程由 Controller 直接调用 Repository，所以图里没有“看起来更规范”的 Service 层；校验失败返回表单，也不能画成提交后总会保存成功。

这次展示的是公开示例应用的代码走读，不是生产落地。没有运行的命令、没有做的端到端验证，都单独列出。你可以先打开[案例与成品](https://github.com/ainiaa/skills-project-docs/tree/main/docs/examples/petclinic)，看看它是否回答了新人真正会问的问题。

如果你也在接手 Java 项目，欢迎用一个可分享的功能试一次。最有用的反馈是：安装卡在哪里、第一份文档是否有用、哪条结论找不到依据。项目地址：[ainiaa/skills-project-docs](https://github.com/ainiaa/skills-project-docs)。

## English short post

**Title: An onboarding guide you can check against the code: a Spring Petclinic walkthrough**

I used Project Docs to trace Owner creation in the public Spring Petclinic sample: form submission, validation, repository access and the detail-page redirect. The output is an onboarding guide plus editable module and flow diagrams, tied to a pinned source revision.

The useful part is preserving what is actually there: this path calls the repository directly, and invalid input returns to the form. The example separates source inspection, rendering checks and tests from steps that were not verified. It is a sample walkthrough, not a production or productivity claim.

[Repository and preview](https://github.com/ainiaa/skills-project-docs). The worked guide is currently in Chinese; the repository has an English introduction and installation instructions. Feedback from developers onboarding to a Java project would be useful, especially installation issues and unsupported claims.

## 45 秒演示分镜

以下是录制脚本，不是已经录制的视频：

| 时间 | 展示 | 讲清楚什么 |
| --- | --- | --- |
| 0–8 秒 | 案例任务说明与固定提交 | 给什么项目、给谁看、范围是什么 |
| 8–20 秒 | 上手手册与源码链接 | 不是类名清单，能沿主链路阅读并回查 |
| 20–33 秒 | 两张真实导出图 | Controller → Repository，校验失败也保留 |
| 33–45 秒 | 验证记录与安装入口 | 哪些已检查、哪些未验证，如何自己试 |

不伪装实时生成速度，不声称一键成功率，不展示私人仓库、终端凭据或业务数据。各社区发帖前核对当前自推广规则，内容围绕可检查的过程与结果，不批量发送邀请。

## 搜索发现与仓库信息

2026-11-03 核对：

- [skills.sh 的创建与发现规则](https://github.com/vercel-labs/skills/blob/main/docs/creating-skills.md)支持 `skills/<name>/SKILL.md` 和 `name` / `description` frontmatter；本仓六个入口已有此结构，无需增加另一份入口清单。
- 集合依赖 Skill 目录外的共享脚本和资料。发现目录不证明单 Skill 复制可用，继续使用本仓安装器；没有宣称通用 `npx skills add` 已通过完整安装验证，也不为排名生成虚假安装量。
- [Skills Directory 的说明](https://skillsdirectory.app/about/)称其索引公开的 SKILL.md 仓库，每日重建。本次没有证据证明已收录；该页面未列出 `agent-skills` topic 为硬性条件，不沿用旧推测。
- 建议仓库简介：`Source-backed project documentation for coding agents: onboarding guides, PRDs, API docs and editable diagrams.`
- 建议 topics：`agent-skills`、`documentation`、`codex`、`claude-code`、`spring-boot`、`mermaid`。这只是待应用的元数据建议，不代表目录审核或平台背书。

本轮只修改仓库材料；未改变 Skill 路由、运行行为、安装布局或依赖。

## 小范围真实试用

邀请 5–10 位确实要接手项目的开发者，先选一个功能，不要求上传完整私有代码。邀请可用：“我做了一个给陌生项目生成带源码依据上手文档的 Skill。能否用你有权处理的项目试一条功能，告诉我安装、首份文档和可信度各卡在哪里？”

收集三问：

1. 安装/诊断是否通过？失败在哪一步，有无脱敏错误？
2. 第一份文档是否回答了你要解决的问题？哪部分最有用或缺失？
3. 哪条结论不能从来源核实，或理解后仍不知道下一步怎么做？

用户反馈保留原话并区分需求新增、项目特例、偏好和实际缺陷；不能把模型自评或合成验收算成真人反馈。经许可才公开匿名摘录。

连续两周手工记录：分享渠道及日期、文章阅读数、GitHub 访问/独立访客、用户主动报告的安装尝试/成功、可复现问题与 Star 变化。没有数据填“未获取”，不要用访问数冒充安装数，或把 Star 变化归因给某一篇文章。GitHub 流量与社区数据可见范围不同，记录统计窗口；不增加遥测、爬虫或新看板。
