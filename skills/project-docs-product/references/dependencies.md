# 上游依赖与版本

## 产品校验器运行依赖

产品校验器使用固定版本 `markdown-it-py==4.2.0`，按 [CommonMark token](https://markdown-it-py.readthedocs.io/en/latest/using.html) 识别可见声明、代码/注释上下文和 Markdown 资源；仅解析，不执行或渲染输入。使用前在运行校验器的 Python 环境安装：

```bash
python3 -m pip install -r <本集合>/scripts/requirements-product.txt
```

可在现有虚拟环境执行；CI 使用相同依赖文件。缺少解析器时校验器返回结构化失败和安装命令，不降级到手写解析。依赖安装遵循用户授权，正常生成不自动升级。引用式链接的定义须按 CommonMark 与前段落用空行分隔；行内/块级代码中的示例链接不作为实际资源。

## 上游 Skill

本集合拥有产品 Skill、产品格式和校验工具，不拥有或自动升级第三方 Skill。通过宿主的技能目录/插件检查实际可见的条目及来源；不要假定所有宿主都有名为 `Skill` 的工具。只检查用户指定的目录和公开技能文件，不读取账号或凭据。

| 能力 | 必要入口及相对资源 | 用途 |
|---|---|---|
| Superpowers | `brainstorming/SKILL.md` | 模糊目标探索、方案比较、阶段复述 |
| Matt Pocock | `grilling/SKILL.md` | 有限范围内的业务决策澄清 |
| Matt Pocock | `domain-modeling/SKILL.md`、`GLOSSARY-FORMAT.md`、`ADR-FORMAT.md` | 术语和选择性决策文档 |

`grill-with-docs` 是用户显式入口，内部组合 grilling 和 domain-modeling；产品入口直接组合这两个底层能力，不自动调用其用户入口。图形或前端技能只在交付物需要时加载。Superpowers 的输出目录、后续实施、提交等默认行为遵循用户当前授权；产品任务不因此获得修改业务代码或提交的权限。

实施基线于 2026-10-21 核对：[brainstorming](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md)、[grill-with-docs](https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md)、[grilling](https://github.com/mattpocock/skills/blob/main/skills/productivity/grilling/SKILL.md)、[domain-modeling](https://github.com/mattpocock/skills/blob/main/skills/engineering/domain-modeling/SKILL.md)。这是观察日期，不是已安装版本承诺。

已有上游安装直接复用。缺失时说明缺项和影响，给出对应上游安装说明，不静默改用自写访谈或拉取整个插件。正常生成不联网升级。用户明确要求升级时使用上游机制，记录实际来源版本或内容 SHA-256；无法识别时写未知。升级后复演 evaluation.md，不把文件存在或静态检查当成模型行为通过。

只读文件诊断：`python3 <本集合>/scripts/product_dependencies.py --skill-root <实际技能目录>`，目录参数可重复，也可传单个 Skill 目录。命令返回内容身份及资源完整性；宿主可见性、来源版本和真实模型行为仍须另行核验。

PDLC 是可选交接能力，不属于上表必需探索依赖。仅用户选择协作时读取 [PDLC 交接约定](pdlc.md)，诊断按需追加 `--pdlc-root`。可选缺失、损坏、遮蔽或缺乏原生接管契约不改变必需依赖的 `ready`，也不影响独立 PRD 与原型交付。
