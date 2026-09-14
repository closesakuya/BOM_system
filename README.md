# BOM 轻量级 Web 系统

这是可部署的 BOM V1.2：Vue 3 + TypeScript 前端、FastAPI + SQLAlchemy 后端、SQLite 数据库、路径选配、覆盖升级迁移、Excel 导入导出、自动化测试与 Windows 运维脚本。

## 快速入口

- [V1.2 确认需求](docs/requirements/三次需求-确认稿.md)、[实施方案](docs/design/V1.2项目方案.md)、[使用与部署](docs/operations/V1.2使用与部署.md)：当前版本口径
- [V1.2 验收报告](docs/operations/V1.2验收报告.md)：测试结果、正式库对账和备份位置

- [项目方案](docs/design/项目方案.md)：已确认的业务规则与技术方案
- [V1.1 项目方案](docs/design/V1.1项目方案.md)：二次迭代的确认业务边界与实施方案
- [V1.1 确认需求](docs/requirements/V1.1确认需求.md)：逐项打磨后的交付口径
- [V1.1 验收报告](docs/operations/V1.1验收报告.md)：逐项需求、正式库对账及发布门禁证据
- [V1.1.1 确认需求](docs/requirements/V1.1.1未正式原材料调整-确认草案.md)：`99.*` 未正式编号、关键器件码与转正式封存口径
- [V1.1.1 项目方案](docs/design/V1.1.1项目方案.md)：结构、迁移、事务、Excel 和验收设计
- [V1.1.1 验收报告](docs/operations/V1.1.1验收报告.md)：正式库升级对账和自动化门禁证据
- [实施计划](docs/design/实施计划.md)：开发阶段、交付物、退出条件与验收矩阵
- [需求描述](docs/requirements/需求描述.txt)：本项目的主要原始需求
- [规划过程](docs/planning/task_plan.md)：方案制定与 Grill-me 决策过程
- [安装部署](docs/operations/安装部署.md)：Windows 安装、启动、局域网访问和自启动
- [用户手册](docs/operations/用户操作手册.md)：物料、BOM、导入导出、比较和维护
- [备份恢复](docs/operations/备份恢复.md)：在线备份、恢复演练和故障处理

## 快速启动

```powershell
.\scripts\install_v1.ps1
.\scripts\start_v1.ps1
```

浏览器打开 `http://127.0.0.1:8000`。开发验证初始账户为 `admin / admin123`，生产使用前必须通过环境变量改为强密码并设置 `BOM_SECRET_KEY`。

## 目录结构

```text
BOM/
├─ README.md
├─ docs/
│  ├─ requirements/   原始需求与补充说明
│  ├─ reference/      编码等业务参考资料
│  ├─ design/         确认版项目方案与实施计划
│  ├─ planning/       规划、发现和进度记录
│  └─ operations/     安装、操作、迁移与备份恢复文档
├─ backend/           FastAPI、领域服务、迁移和后端测试
├─ frontend/          Vue 前端和 Playwright 测试
├─ scripts/           Windows 安装、启动、备份和恢复脚本
├─ runtime/           首版数据库、报告和运行期文件（不纳入源码）
└─ data/
   ├─ migration/      一次性历史数据初始化输入
   ├─ templates/      系统日常导入模板参考
   └─ samples/        BOM 输出样例
```

## 资料分类

### 原始需求

- [需求描述.txt](docs/requirements/需求描述.txt)
- [BOM管理系统优化需求说明.docx](docs/requirements/BOM管理系统优化需求说明.docx)
- [BOM架构及需求说明_20260306.pdf](docs/requirements/BOM架构及需求说明_20260306.pdf)

### 参考资料

- [物料编码标准.doc](docs/reference/物料编码标准.doc)

### 方案与计划

- [项目方案.md](docs/design/项目方案.md)
- [实施计划.md](docs/design/实施计划.md)

### 规划记录

- [task_plan.md](docs/planning/task_plan.md)
- [findings.md](docs/planning/findings.md)
- [progress.md](docs/planning/progress.md)

### 数据、模板与样例

- [BOM物料清单管理(1).xlsm](<data/migration/BOM物料清单管理(1).xlsm>)：仅作为一次性初始化迁移输入，不是日常导入模板或系统运行依赖
- [新增原材料编码登记表(模版).xlsx](<data/templates/新增原材料编码登记表(模版).xlsx>)：原材料日常导入和编码规则模板参考
- [生产BOM样例](data/samples/00.005.01-TN水质分析仪-D60-YJ-BZ-A1-I-16C-11-0-生产BOM.xlsx)：生产 BOM 输出字段与样式参考

## 当前状态

- BOM V1.1.1 已完成 `99.XXXX.X` 未正式原材料自动取号、关键器件码、转正式新建物料、永久封存来源及双向追溯。
- 升级器会先备份数据库，再以事务迁移历史数据；迁移失败不提交现库，重复执行安全。
- 页面预览、单项 Excel 和批量 ZIP 共用“显示选配替代”和“展开自制/外协原材料”设置；备用选配不参与当前生产数量汇总。
- 当前正式数据库共 4,869 个物料、17,886 条合法 BOM 关系；其中 27 条历史未正式来源已编号为 `99.0001.0`～`99.0003.6` 并封存。
- 后端 pytest、前端 TypeScript 检查和生产构建均纳入交付门禁。
- `superpower` 不属于本项目规划或实施依赖。
