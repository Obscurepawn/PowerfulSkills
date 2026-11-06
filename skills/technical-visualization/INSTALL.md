# 安装与使用

`technical-visualization` 支持工程架构图、性能基准图和量化研究图。入口是 `SKILL.md`；参考文档、脚本、模板、示例和测试随目录一起安装。绘图不依赖 API 密钥，也不要求安装 nature-skills。

## 安装技能

解压下载包，进入其中的 `technical-visualization` 目录，执行：

```bash
python scripts/install_skill.py
python scripts/install_skill.py --check
```

默认目标是 `$CODEX_HOME/skills/technical-visualization`；没有设置 `CODEX_HOME` 时使用 `~/.codex/skills/technical-visualization`。安装器逐文件校验复制结果；已有同名目录内容不一致时会停止，保留原目录。更新时先把旧目录移到备份位置，再重新安装。

安装器会显示实际目标路径；使用 `--check` 可核对安装副本与当前技能目录是否一致。

其他 Codex 环境若采用当前官方文档中的 `.agents/skills` 目录，可以显式指定完整目标路径：

```bash
# 用户级安装
python scripts/install_skill.py --dest "$HOME/.agents/skills/technical-visualization"
# 或在当前项目内安装
python scripts/install_skill.py --dest .agents/skills/technical-visualization
```

Windows PowerShell：

```powershell
py scripts/install_skill.py --dest "$env:USERPROFILE\.codex\skills\technical-visualization"
py scripts/install_skill.py --check --dest "$env:USERPROFILE\.codex\skills\technical-visualization"
```

只需选择实际使用的一处目录。Codex 的技能发现目录和调用方式以[官方技能文档](https://learn.chatgpt.com/docs/build-skills)及本机设置为准；新安装的技能未出现时，重新打开聊天或重启应用。

## 运行依赖

技能文本安装与 Python 依赖安装是两步。推荐在项目工作目录建立独立环境，避免把环境放进技能包：

```bash
python3 -m venv .venv-visualization
.venv-visualization/bin/python -m pip install -r /path/to/technical-visualization/requirements.txt
```

PowerShell 的对应命令：

```powershell
py -m venv .venv-visualization
.\.venv-visualization\Scripts\python.exe -m pip install -r C:\path\to\technical-visualization\requirements.txt
```

Python 版本需为 3.10 或更新版本。NumPy 和 Matplotlib 用于数值图；PyMuPDF 用于最终 PDF 的字号、边界和文字重叠检查。缺少 PyMuPDF 时检查器会报告未执行的项目。`requirements-tested.txt` 固定本次验证所用的 Python 包版本，供需要复现该环境时使用；平台与字体也影响渲染结果。

架构图另外需要 [Graphviz](https://graphviz.org/download/) 的 `dot` 程序。Linux 可通过系统包管理器安装 `graphviz`；Windows 安装 Graphviz 后将其 `bin` 目录加入 PATH。用 `dot -V` 检查是否可用。中文图表可在 JSON 中设置已安装且包含中文字形的 `font_family`；字体缺失时先安装字体或选择本地已有字体。

## 生成与检查

以下命令在技能目录运行。`python` 指向已安装依赖的环境。三个示例均为合成数据或设计提案，图中有明确标识；实际使用时替换数据、配置和来源说明。

```bash
python scripts/plot_benchmark.py --input assets/examples/benchmark.csv --config assets/examples/benchmark.json --output /path/to/project/benchmark-figure
python scripts/plot_quant.py --input assets/examples/quant.csv --config assets/examples/quant.json --output /path/to/project/quant-figure
python scripts/render_architecture.py --input assets/examples/architecture.json --output /path/to/project/architecture-figure
python scripts/audit_bundle.py /path/to/project/benchmark-figure --json /path/to/project/benchmark-figure/qa-auto.json --strict
```

输出目录需为空或尚不存在。每个目录包含 SVG、PDF、PNG、图注、输入和源码副本、版本信息、校验哈希及重现命令。量化图和性能图另含可核对的计算结果 CSV。编辑数据或配置后，生成到新目录并重新检查。

自动检查退出码：`0` 表示没有失败项，`1` 表示失败，严格模式下的 `2` 表示仍有待人工判断的警告。量化示例会提示核对数据日历和频率；这项假设需结合数据来源确认。检查报告不等于完成了人工图面审阅。

在 Codex 中可以这样调用：

```text
使用 $technical-visualization，根据这个项目的代码和配置绘制系统架构图，
区分已实现和拟议部分，交付可编辑 SVG/PDF、源码和检查记录。

使用 $technical-visualization，将 runs.csv 绘制为吞吐量随并发变化的图。
保留各次运行点，解释误差范围，附数据和完整重现命令。

使用 $technical-visualization，检查 returns.csv 的日期和收益口径，
绘制净值与回撤；只在年化频率和无风险利率明确时添加滚动 Sharpe。
```

运行随附测试：

```bash
python -m unittest discover -s tests -v
```

三个生成器覆盖常见起点。请求级延迟分布、火焰图、IC、因子暴露、换手率、复杂时序图和状态图需要按对应参考文档扩展绘图源码，不会由这三个命令自动推导。
