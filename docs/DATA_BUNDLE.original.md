# Tidepath Grant Challenge 数据包说明

## 数据包用途

本数据包用于 code challenge 的申请撰写、规则校验、资助期支出分类、超预算检测和报告生成流程分析。它根据前面形成的10份提案及对应预算计划，补充了每笔模拟资助需要的规则、预算、支出和结果文件。

> **重要：全包为合成数据。** Tidepath Family Alliance、资助方、奖项、规则、交易、供应商、结果及报告日期均为虚构，仅供开发与测试。不得作为真实申请、会计记录、审计证据或资助报告提交。

## 顶层文件

### `organization_fact_sheet.md`

机构共同事实表和事实使用边界。包含挑战说明明确提供的虚构机构信息、事实编号、来源及是否可用于申请。服务覆盖人数、合作机构、员工资历、往年成效和真实财务状况等未提供的事实均标为缺失，避免模型自行补造。挑战说明提及“14家非营利机构调查”，但没有调查问卷或原始数据，因此被标记为**待证实，不可作为已验证研究结果引用**。

### `grant-01` 至 `grant-10`

每个子文件夹对应一笔模拟资助。文件夹名描述项目用途；项目ID为 `TP-G01` 至 `TP-G10`。各资助方名称及其细则均为此挑战专门编造，并非真实基金会或真实申请指南。

## 每个资助文件夹内的文件

| 文件名 | 用途 | 主要内容与关系 |
|---|---|---|
| `proposal_reference.md` | 项目叙述参考 | 基于先前提案草稿；机构名称在数据包副本中已改为 Tidepath。文件开头标明它只是内容参考，**尚未按本文件夹的虚构资助方题目和字数限制重写**。撰写测试必须以规则文件为准。 |
| `funder_requirements.md` | 资助方规则说明 | 本项目模拟资助方、资助期、财政年度、报告截止日期、各叙述题字数上限、允许支出及合规要求。内容为虚构规则。 |
| `narrative_limits.csv` | 机器可读的字数限制 | 一行一个申请叙述字段，含项目ID、虚构资助方、字段名、最大字数和单位；可用于表单验证。 |
| `award_budget.csv` | 获批预算基准 | 按资助方预算类别列金额，并含总额行、币种、资助起止日、财政年度和报告截止日期。属于模拟授予预算，不是真实 award notice。分类金额应加总为总额。 |
| `monthly_budget_plan_and_actual_tracker.csv` | 按月预算计划与手工填报表 | 延续先前每份提案的月度计划，按“月份 × 预算类别”记录计划金额；实际支出和差额栏留空，供人工录入。金额按项目时间线分配，月度计划汇总应与 `award_budget.csv` 类别额度一致。 |
| `actual_expenses.csv` | 模拟会计交易明细 | 一行一笔合成交易，含日期、供应商、QuickBooks类别、资助方类别、金额、分摊比例、凭证编号和数据状态。不得当作真实支出。第2、6、9、10笔资助各有一个故意构造的预算类别超支样例，用于测试告警；资助总额仍可低于总授予额。 |
| `category_mapping.csv` | 会计类别映射 | 把较通用的 QuickBooks 类别映射至本资助的预算类别，并说明合成映射及复核要求。不同资助方可能对相似支出采用不同预算类别。 |
| `outcomes_data.csv` | 模拟项目结果 | 含指标、目标、模拟实际值、单位、数据来源类型和测量日期。数据是测试用模拟结果，不是实际测量。 |
| `report_template.md` | 报告填写模板 | 包含报告期间、截止日、按该资助规则列出的叙述题、结果和财务核对提示及签核栏。应使用核准事实和核实数据替换占位说明。 |

## 文件间的数据流程

1. 用 `organization_fact_sheet.md` 作为共同事实来源；不能把提案中的假设升级为机构既有成果。
2. 按 `funder_requirements.md` 和 `narrative_limits.csv` 生成并检查各资助方版本的申请叙述。
3. 以 `award_budget.csv` 作为类别额度和资助期基准。
4. 用 `category_mapping.csv` 将 `actual_expenses.csv` 中的账务类别归入资助方类别。
5. 按资助期/财政年度汇总模拟支出，并与获批类别额度比较；超支、日期越界、缺凭证或需批准的类别转拨应触发复核。
6. 使用 `outcomes_data.csv` 填充 `report_template.md` 的结果部分；生成报告时保留数据的合成状态。

## 字段与格式约定

- CSV 使用 UTF-8 with BOM，金额单位为美元（USD），日期采用 `YYYY-MM-DD`。
- “Month 1”等月度表标签相对于项目开始月；实际交易表使用具体日期。
- 月度跟踪表的实际金额和差额为空是有意设计；模拟交易另存于 `actual_expenses.csv`。
- 差额定义为“计划预算 − 实际支出”；真实产品实现时应统一正负号约定。
- 每笔模拟支出均标为生成的测试记录；凭证编号和供应商也为虚构。
- `actual_expenses.csv` 中的“批准”仅表示挑战数据的样例状态，不表示真实资助方或机构审批。

## 推荐的挑战验证场景

- 对10个项目分别检查不同叙述字段的字数上限。
- 核对各预算类别加总、奖项总额和项目起止日期。
- 将交易按各资助方财政年度分组，再按资助方预算类别汇总。
- 检测预算类别超支、支出期间越界、缺少凭证、类别错配及未经批准的转拨。
- 使用事实表与结果文件生成报告草稿，并确保缺失事实不被编造、模拟数据不被描述成真实结果。
# Tidepath Grant Challenge — Synthetic Data Bundle

This folder contains ten fictional grant packages based on the ten proposal drafts and their corresponding monthly planned-budget CSVs. It is designed for code-challenge analysis and workflow testing, not for real applications, bookkeeping, or tax reporting.

## Contents

- `organization_fact_sheet.md`: shared synthetic fact sheet and claim-use guardrails.
- `grant-01` through `grant-10`: each includes the proposal reference, its monthly planned budget, mock funder rules, mock award budget, synthetic actual-expense ledger, category mapping, synthetic outcome data, and a report template.
- Funder names, application limits, award terms, restrictions, financial records, and outcome values are all invented for this challenge.

## Important data labels

- `award_budget.csv` is a mock award allocation based on the planning amount in the proposal draft; it is not an actual award notice.
- `actual_expenses.csv` contains generated sample transactions. These are not real expenses. Selected grants intentionally include a budget-category overrun for testing alerts.
- `outcomes_data.csv` contains synthetic sample results, not measured outcomes.
- Proposal files may contain planning assumptions and placeholders that require organization approval.
- The supplied scenario mentions a survey of 14 nonprofits, but no underlying survey data was provided; that claim is flagged as unverified in the fact sheet.

## Suggested challenge checks

1. Enforce each mock narrative field’s distinct maximum word count.
2. Validate that award budget categories sum to the award amount.
3. Group expense transactions by each funder’s fiscal year and map QuickBooks categories to funder categories.
4. Flag restricted-category overruns, unapproved transfers, missing documentation, and transactions outside the grant period.
5. Generate reports from only the facts and outcome records included in the package, and label synthetic records as such.

## CSV conventions

- Currency is USD. Actual values are intentionally synthetic.
- Dates use ISO `YYYY-MM-DD`.
- Blank actual-spend and variance fields remain in the monthly planning tracker for future manual entry; the separate synthetic ledger contains test transactions.
- The funder fiscal-year field is stored per grant; use the mock rule in that grant’s `funder_requirements.md`.
