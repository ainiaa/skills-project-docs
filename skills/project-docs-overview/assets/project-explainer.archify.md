# Project Docs 能交付什么？ {#project-docs}

把源码和需求整理为**带来源**的项目说明、接口文档和技术图。

- 读者先了解用途，再查看关键流程。
- 结论附来源，便于回查。[](source:readme)

@answer scope="结构示例；须按目标仓库重写事实、流程与来源"
@meta locale=zh-CN style=clean
@source readme title="项目介绍" path=README.md lines=1:3

## 文档怎样产生？ {#process}

@workflow id=docs-flow title="从需求到交付"
| scope | 确认范围 | external |
| evidence | 核对来源 | backend |
| write | 编写说明 | backend |
| verify | 验证交付 | backend |
| scope > evidence | |
| evidence > write | |
| write > verify | |

## 交付物怎样选择？ {#outputs}

| 读者需求 | 交付物 |
| --- | --- |
| 理解项目用途与边界 | 项目说明 |
| 联调接口 | 接口文档与调用方式 |
| 理解跨模块关系 | 架构图与流程图 |

## 项目如何描述自己？ {#evidence}

@code source=readme language=markdown

## 下一步做什么？ {#checks}

- [ ] 核对范围与源码版本。
- [ ] 回查关键结论对应的来源。
- [ ] 验证命令与业务解释。
