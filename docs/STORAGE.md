# M1 storage and migration

M1采用SQLite＋SQLAlchemy；用户的本阶段授权替代ADR中首版产品PostgreSQL落地要求，仅为本地验证，不修改原ADR。业务API不依赖SQLite专用查询；PostgreSQL迁移仍需验证，不能声称已支持。

## Schema v1

`schema.py` 是SQLAlchemy模型；`migrations.upgrade` 是幂等bootstrap迁移。它检查PRAGMA user_version（只接受0或1），创建表、版本行和UPDATE/DELETE保护触发器。未来新增列／版本需要显式前向迁移；create_all不是已有表结构升级工具。schema v1含：

| 表 | 作用 |
|---|---|
| sources | 来源URL、类型、使用权、官方披露日及其目录依据 |
| artifacts | 私有原始bytes、来源FK、SHA-256、取得时间、本地引用 |
| evidence | 不可变规范化值、完整scope、原locator与供应商原日期 |
| calculations / calculation_inputs | 命名算子、版本、结果FK、依次排列的输入FK |
| crosschecks | 供应商原字段与官方PDF字段的同值同口径核验关联；不解决日期含义 |
| conflicts | 差异分类与左右原证据FK；状态不覆写本体 |
| reviews | 字段级采用／保留未决事件；有效字段由事件投影 |
| thesis_revisions | 手工确认的主张／节点／关系快照与同Thesis父版本 |
| assessments | 特定revision/subclaim对某证据的方向，独立于质量 |
| checkpoints | Task固定revision、证据／冲突清单、阶段和保存时点 |
| audit_events / schema_version | 本地追加审计与版本记录 |

所有Decimal存为规范字符串／JSON字符串，不经过SQLite REAL。JSON payload只用受控序列化，不用pickle/eval；原始文档存BLOB，关闭源文件后仍可读本地保存bytes。来源与证据插入、计算与输入FK、裁决与审计分别同事务写入；同ID内容不同拒绝，同内容重复导入不覆写。

开启PRAGMA foreign_keys，检查点引用证据／冲突必须已存在；第二版本parent必须同Thesis。SQL UPDATE/DELETE保护包含来源、raw、证据、计算、裁决、审计与检查点。字段审核仅新增Review，不改raw日期或金额；采用官网日不解决供应商日期语义。

未决状态由按sequence排列的最新裁决投影。恢复读取最新Task检查点及当前冲突审计；历史检查点本体保持不变。并发多用户乐观锁、用户ACL、租约队列、完整ResearchRun状态机均不在M1，不把本地检查点当完整产品工作流。

## 限制

本地SQLite文件未加密，不是WORM存储／防管理员篡改系统。持有文件权限的管理员仍可移除触发器或重写数据库；raw hash只提供一致性检测。保护针对正常应用／SQL操作，不能承诺绝对不可变。原始材料删除／保留策略仍受许可要求约束。

未来PostgreSQL需迁移BLOB存储、JSON／金额约束、immutable权限／触发器和版本工具并重跑全部测试；未验证这些迁移。不得为M1提前引入图数据库、分布式队列或服务部署。
