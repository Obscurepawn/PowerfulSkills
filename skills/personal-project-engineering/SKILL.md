---
name: personal-project-engineering
description: 为个人项目建立或修订 README、功能规格（SPECS / RFC）和 AGENTS.md（或 CLAUDE.md / GEMINI.md），审查文档与实现的一致性（doc-code drift），或按规格推进一项变更的开发、测试与验收。适用于项目起步、已有仓库的文档治理，以及需要明确行为契约的开发任务。
---

# 个人项目工程实践

先确定这次要交付什么、给谁用，以及什么结果算完成。用户只要求审阅时，给出有文件依据的发现和修改建议。只要求一种文档时，直接处理这一种。

读取适用的仓库指令，找到与任务直接相关的入口、配置、现有文档和测试。核对命令的工作目录、工具版本与脚本定义。新项目尚无实现时，从用户给出的场景写出第一个可验收的目标，把待定事项留在规格里。沿用项目的语言、命名和目录布局。

## 按交付物选择指南

| 用户要解决的问题 | 参考与可复用模板 |
| --- | --- |
| 初次访问者怎样判断项目适不适合自己，并完成第一次使用？ | [README 指南](references/README-GUIDELINES.md) · [README 模板](assets/README.template.md) |
| 一个功能承诺什么行为，怎样验收？ | [SPECS 指南](references/SPECS-GUIDELINES.md) · [功能规格模板](assets/SPEC.template.md) |
| 在这个仓库或子目录工作时，要遵循哪些本地约定？ | [AGENTS.md 指南](references/AGENTS-GUIDELINES.md) · [仓库指令模板](assets/AGENTS.template.md) |
| 怎样把需求落实为可验证的变更，或找出实现与文档的偏差？ | [工程工作流](references/ENGINEERING-WORKFLOW.md) |

模板供新写段落时取用。已有文件保留有效内容，替换占位符，删除不适用的段落。一个事实指定一个维护位置，其他文档按需链接。例如，README 演示一次成功调用，规格定义该接口对边界输入的承诺，AGENTS.md 说明改动它时运行哪项检查。

## 机械化核对与实测验收

编写或修订文档后，运行随附检查脚本（相对于本技能目录解析路径），排查失效相对链接、标题锚点、残留模板占位符以及不存在的脚本或 `npm run` 命令：

```bash
python3 <skill-dir>/scripts/audit_project_docs.py <repo-root>
```

运行 README 的最短示例，对照规格检查可观察结果，从 AGENTS.md 指定的目录核对项目命令。交付时说明实际运行了什么、观察到什么。若已有实现与约定冲突，分别注明当前行为、预期行为和证据，在用户授权的范围内解决。
