# PowerfulSkills

收藏和维护日常开发、写作中好用的 AI Agent Skills。

## 技能目录

| Skill | 用途 | 说明 |
| --- | --- | --- |
| [clear-answer-writing](skills/clear-answer-writing/SKILL.md) | 清晰回答与自然写作 | 适用于回答、原创写作、润色、翻译和总结，保留事实、限定条件与作者声音。 |
| [personal-project-engineering](skills/personal-project-engineering/SKILL.md) | 个人项目工程实践 | 编写和维护 README、功能规格与 AGENTS.md，核对文档与实现，并按规格推进开发、测试和验收。 |
| [vibe-tla](skills/vibe-tla/SKILL.md) | 基于代码的形式化验证 | 使用 TLA+ / TLC 检查并发、顺序、恢复与持久性问题，区分候选问题与已确认缺陷。 |
| [technical-visualization](skills/technical-visualization/SKILL.md) | 工程与量化研究可视化 | 生成可编辑、可重现的架构图、性能基准图和量化研究图，保留数据来源、绘图源码与质量检查。 |

每个技能保存在 `skills/<skill-name>/` 中，以 `SKILL.md` 为入口；运行期所需的引用资料、模板与辅助脚本随技能保留，面向用户的长篇手册与安装说明放在 `docs/`。

## 安装

准备 Git、Python 3，以及 Bash 或兼容的 shell。默认安装到通用技能目录 `~/.agents/skills/`（若显式设置了 `CODEX_HOME`，默认使用 `$CODEX_HOME/skills/`）；也可通过 `--dest-root` 指定 `~/.claude/skills`、`~/.gemini/config/skills` 或具体项目内的 `.agents/skills`。安装器默认不覆盖已有本地改动，并自动排除开发测试目录。

克隆仓库后一键安装或核验（也可通过 `--skill <名称>` 只安装指定技能）：

```bash
git clone https://github.com/Obscurepawn/PowerfulSkills.git
cd PowerfulSkills
python3 scripts/install_skills.py
python3 scripts/install_skills.py --check
```

若目标目录中已有旧版本且确认需要更新替换，附加 `--force` 执行原子替换。只保留实际使用的一处安装。

## 使用

- **clear-answer-writing**：在撰写或润色技术文章、文档、报告、邮件、翻译、摘要或去除 AI 味时调用；长文配合[长文写作规则](skills/clear-answer-writing/references/long-form.md)并运行 `scripts/ai_style_check.py` 检查表达密度。若希望日常每次简短问答也常驻核心表达规则，可将[常驻规则片段](skills/clear-answer-writing/assets/AGENTS-snippet.md)并入全局 `AGENTS.md`（避免每轮普通对话重复加载完整技能）。
- **personal-project-engineering**：说明要编写或审阅的文档，或要按规格实现的功能；技能提供 README、功能规格和 AGENTS.md 的指南与模板、从需求到验证的工程工作流，以及自动排查死链、锚点、残留占位符和无效脚本的 `scripts/audit_project_docs.py`。
- **vibe-tla**：先阅读[中文手册](docs/vibe-tla/MANUAL.zh-CN.md)或[英文手册](docs/vibe-tla/MANUAL.md)，再按技能说明初始化目标仓库并运行检查（支持内嵌在 `<repo>/.agents/skills/` 或 `<repo>/.claude/skills/`，也支持独立全局安装）。TLC 工具链的安装要求见[环境说明](skills/vibe-tla/references/tlc-setup.md)。
- **technical-visualization**：提供系统规格、代码或 CSV 数据，生成 SVG/PDF、预览、图注及重现包。Python、Graphviz 依赖和运行示例见[安装与使用说明](docs/technical-visualization/INSTALL.md)；示例数据明确标记为合成数据，统计结论遵循输入数据的证据范围。

## 维护

新增技能时，在 `skills/<skill-name>/` 中保留完整技能文件，并更新上面的目录表。不要提交凭证、本地运行缓存或待验证项目的数据。

本仓库用于收藏技能；收录不代表所有内容均由仓库维护者原创，也不额外授予第三方内容的许可。
