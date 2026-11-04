# Skill 升级了，为什么还要补装？ {#skill-update}

已有入口仍指向原来的 Skill 文件，文件更新后就能读到新内容；**新增 Skill 还需要创建自己的入口**。[](source:links) [](source:update)

@answer scope="本集合的软链接安装方式；解释安装机制，不代表已验证某台电脑的安装或会话加载状态"
@meta locale=zh-CN style=clean
@source links title="安装器如何创建与复用入口" path=install.sh lines=244:255
@source update title="升级先更新源码，再同步安装" path=scripts/update_project_docs.py lines=21:35

## 入口和源码是什么关系？ {#map}

把入口想成书架旁的路标：路标指向书，不会复制一本书。软链接就是这种指向文件位置的入口；它也可能指向已经不存在的位置。[](source:links)

@workflow id=skill-links title="读 Skill 时沿入口找到源码"
| shortcut | 已有入口 | backend |
| old-source | 原有文件 | external |
| new-entry | 新增入口 | backend |
| new-source | 新增文件 | external |
| shortcut > old-source | 读取 |
| new-entry > new-source | 补装后读取 |

## 以新增 Lifecycle 为例，会发生什么？ {#example}

先把仓库里的内容更新，再运行安装同步。已有入口继续使用；新增的 Lifecycle 由安装器补建入口。只更新源码不会凭空产生新入口。[](source:update) [](source:links)

@steps id=update-steps
| refresh | 更新书的内容 | 升级命令先更新同一个源码仓库。 |
| link | 补齐路标 | 安装同步复用已有入口，并为新增 Skill 建入口。 |
| read | 读取新内容 | 入口有效后，宿主才能从它指向的位置读取 Skill。 |

## 哪些情况还不能算升级完成？ {#limits}

路标只说明文件指向，会话加载状态需要另行确认。换了源码位置、入口失效或依赖检查失败时，需要核对实际安装；源码更新成功也可能随后同步失败。判断完成时要同时检查源码、入口和依赖。[](source:update) [](source:links)

- [ ] 确认入口指向实际存在的 Skill。
- [ ] 运行安装诊断；会话是否已加载需在宿主中另行确认。
