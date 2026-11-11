# PowerfulSkills

收藏和维护日常开发、写作中好用的 AI Agent Skills。

## 技能目录

| Skill | 用途 | 说明 |
| --- | --- | --- |
| [clear-answer-writing](skills/clear-answer-writing/SKILL.md) | 清晰回答与自然写作 | 适用于回答、原创写作、润色、翻译和总结，保留事实、限定条件与作者声音。 |
| [personal-project-engineering](skills/personal-project-engineering/SKILL.md) | 个人项目工程实践 | 编写和维护 README、功能规格与 AGENTS.md，核对文档与实现，并按规格推进开发、测试和验收。 |
| [vibe-tla](skills/vibe-tla/SKILL.md) | 基于代码的形式化验证 | 使用 TLA+ / TLC 检查并发、顺序、恢复与持久性问题，区分候选问题与已确认缺陷。 |
| [technical-visualization](skills/technical-visualization/SKILL.md) | 工程与量化研究可视化 | 生成可编辑、可重现的架构图、性能基准图和量化研究图，保留数据来源、绘图源码与质量检查。 |

每个技能保存在独立目录中，以 `SKILL.md` 为入口；引用资料、脚本和手册随技能一起保留。

## 安装到 Codex

准备 Git、Python 3，以及 Bash 或兼容的 shell。按[官方技能文档](https://learn.chatgpt.com/docs/build-skills)，用户级技能放在 `~/.agents/skills/`。如果目标目录中已有同名技能，先比较或备份，避免覆盖本地修改。

克隆仓库后，选择需要的技能安装：

```bash
git clone https://github.com/Obscurepawn/PowerfulSkills.git
cd PowerfulSkills
mkdir -p "$HOME/.agents/skills"
cp -R skills/clear-answer-writing "$HOME/.agents/skills/"
cp -R skills/personal-project-engineering "$HOME/.agents/skills/"
cp -R skills/vibe-tla "$HOME/.agents/skills/"
python3 skills/technical-visualization/scripts/install_skill.py \
  --dest "$HOME/.agents/skills/technical-visualization"
python3 skills/technical-visualization/scripts/install_skill.py --check \
  --dest "$HOME/.agents/skills/technical-visualization"
```

如果你的环境使用 `${CODEX_HOME:-$HOME/.codex}/skills/`，将上述目标路径统一替换为该目录；安装器未传 `--dest` 时仍使用这一默认位置。只保留实际使用的一处安装。Codex 会自动发现技能变化；未显示时再重启。

## 使用

- **clear-answer-writing**：要求 Agent 按该技能进行回答、写作或润色；若希望每次都使用，可在自己的 `AGENTS.md` 中加入相应要求。长文还需遵循[长文写作规则](skills/clear-answer-writing/references/long-form.md)，并运行检查脚本。技能文件中的检查示例仍写为 `~/.codex/skills/clear-answer-writing/scripts/ai_style_check.py`；按上文安装到 `.agents` 后，使用 `python3 "$HOME/.agents/skills/clear-answer-writing/scripts/ai_style_check.py" <文件.md>`。安装到其他目录时同样替换为实际路径。
- **personal-project-engineering**：说明要编写或审阅的文档，或要按规格实现的功能；技能提供 README、功能规格和 AGENTS.md 的指南与模板，以及从需求到验证的工程工作流。
- **vibe-tla**：先阅读[中文手册](skills/vibe-tla/MANUAL.zh-CN.md)或[英文手册](skills/vibe-tla/MANUAL.md)，再按技能说明初始化目标仓库并运行检查。TLC 工具链的安装要求见[环境说明](skills/vibe-tla/references/tlc-setup.md)。
- **technical-visualization**：提供系统规格、代码或 CSV 数据，生成 SVG/PDF、预览、图注及重现包。Python、Graphviz 依赖和运行示例见[安装与使用说明](skills/technical-visualization/INSTALL.md)；示例数据明确标记为合成数据，统计结论遵循输入数据的证据范围。

## 维护

新增技能时，在 `skills/<skill-name>/` 中保留完整技能文件，并更新上面的目录表。不要提交凭证、本地运行缓存或待验证项目的数据。

本仓库用于收藏技能；收录不代表所有内容均由仓库维护者原创，也不额外授予第三方内容的许可。
