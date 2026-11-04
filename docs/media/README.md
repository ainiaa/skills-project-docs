# Petclinic 演示媒体

作者：Jeff.Liu

[演示 GIF](petclinic-demo.gif) · [案例与静态成果](../examples/petclinic/README.md) · [动画验证回执](petclinic-demo.json)

`petclinic-demo.gif` 是 960×600、24 秒、六幕循环的成果走读：任务说明 → 上手手册 → 源码引用 → 模块关系图 → 校验流程 → 已执行的 18 项 Controller 测试。内容直接读取已提交案例，画面内持续标注“剪辑演示 / NOT GENERATION SPEED”。它不是实时录屏，也未重新运行 Petclinic。

中英文首页引用同一文件；不便观看动画时可使用[静态模块图](../examples/petclinic/architecture.png)和[静态流程图](../examples/petclinic/owner-flow.png)。GIF 不包含音频。

## 维护与重建

[构建脚本](build-petclinic-demo.mjs)复用集合现有的 `launchBrowser`，仅启动无界面浏览器，将六幕 HTML 截成 PNG，再用本机已安装的 Pillow 编码 GIF。维护工具需要现有 Mermaid/Puppeteer 浏览器环境、Python 3 和 Pillow；它们不是为本次演示新增的 Skill 运行依赖。缺少维护工具时脚本报错，不自动安装。

在 Project Docs 根目录运行，输出帧保留在仓库外：

```bash
node docs/media/build-petclinic-demo.mjs /tmp/project-docs-petclinic-frames
python3 -m unittest discover -s scripts -p test_public_docs.py
```

构建检查六幕无溢出，实际解码 GIF 的全部帧，核对 24 秒时长、无限循环、960×600 尺寸及不超过 5 MiB 的体积。回执记录 GIF 和输入材料的 SHA-256；提交前仍须检查解码后的每一幕，确认文字、图片、顺序和事实一致。字体来自本机，跨系统重建不承诺像素完全相同。

中间帧及可检查的 `storyboard.html` 留在指定临时目录；仓库只保存 GIF、回执、构建脚本及本说明，不保存临时截图或外部字体。
