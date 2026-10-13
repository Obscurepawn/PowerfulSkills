# PowerfulSkills

收藏和维护日常开发、写作中好用的 AI Agent Skills。

## 技能目录

| Skill | 用途 | 说明 |
| --- | --- | --- |
| [clear-answer-writing](skills/clear-answer-writing/SKILL.md) | 清晰回答与自然写作 | 适用于回答、原创写作、润色、翻译和总结，保留事实、限定条件与作者声音。 |
| [vibe-tla](skills/vibe-tla/SKILL.md) | 基于代码的形式化验证 | 使用 TLA+ / TLC 检查并发、顺序、恢复与持久性问题，区分候选问题与已确认缺陷。 |

每个技能保存在独立目录中，以 `SKILL.md` 为入口；引用资料、脚本和手册随技能一起保留。

## 安装到 Codex

克隆仓库，将需要的技能目录复制到 `${CODEX_HOME:-$HOME/.codex}/skills/`：

```bash
git clone https://github.com/Obscurepawn/PowerfulSkills.git
cd PowerfulSkills
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/clear-answer-writing "${CODEX_HOME:-$HOME/.codex}/skills/"
cp -R skills/vibe-tla "${CODEX_HOME:-$HOME/.codex}/skills/"
```

如果目标目录中已有同名技能，请先比较或备份，避免直接覆盖本地修改。安装后重启 Codex，使其重新发现技能。

## 使用

- **clear-answer-writing**：要求 Agent 按该技能进行回答、写作或润色；若希望每次都使用，可在自己的 `AGENTS.md` 中加入相应要求。
- **vibe-tla**：先阅读[中文手册](skills/vibe-tla/MANUAL.zh-CN.md)或[英文手册](skills/vibe-tla/MANUAL.md)，再按技能说明初始化目标仓库并运行检查。TLC 工具链的安装要求见[环境说明](skills/vibe-tla/references/tlc-setup.md)。

## 维护

新增技能时，在 `skills/<skill-name>/` 中保留完整技能文件，并更新上面的目录表。不要提交凭证、本地运行缓存或待验证项目的数据。

本仓库用于收藏技能；收录不代表所有内容均由仓库维护者原创，也不额外授予第三方内容的许可。
