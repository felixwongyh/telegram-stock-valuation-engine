# Financial Business Classification Report — Session #56 P0

## 结论

分类层与路由层已拆成两个独立步骤。`BusinessType`（企业业务分类）保持原义，
新增 `FinancialBusinessModel`（业务模型）作为**独立轴**，模型路由只认后者。

关键判据不是 GICS Sector、不是 "Financial Services" 标签、不是公司名称，
而是**结构性证据**：融资成本占税前经营利润的比例。

## 分类架构

| FinancialBusinessModel | 含义 | 代表 | 允许 Bank DDM/RIM |
|---|---|---|---|
| `Bank` | 存款融资的放贷/承销 | JPM, BAC, GS, WFC, C | 是 |
| `PaymentNetwork` | 收费型支付网络 | V, MA | **否** |
| `FintechLender` | 有贷款资产+融资+信用风险 | SOFI, AXP, COF, NU | 是（需独立判断） |
| `OtherFinancial` | 保险、资管、券商、交易所 | CB, BRK-B, MET | **否** |
| `NotFinancial` | 非金融企业 | NVDA, KO, XOM | 否 |

## 结构性判据

```
interest_expense / operating_income   （operating_income <= 0 时退回 / revenue）
  >= 0.20  → FintechLender
  <  0.20  → PaymentNetwork
```

实测分布（快照 20261123）：

| 股票 | interest expense | operating income | 比率 | 判定 |
|---|---|---|---|---|
| JPM | 1.05e11 | 1.19e11 | 0.881 | Bank（由 BusinessType 直接判定）|
| BAC | 8.36e10 | 1.24e11 | 0.676 | Bank |
| GS  | 7.99e10 | 1.06e11 | 0.754 | Bank |
| **V** | **7.58e8** | **2.99e10** | **0.025** | **PaymentNetwork** |
| CB | 7.94e8 | 1.46e10 | 0.054 | OtherFinancial |
| BRK-B | 5.42e9 | 1.01e11 | 0.054 | OtherFinancial |

银行簇 0.68–0.88 与支付网络簇 0.025 之间跨度近 30 倍，阈值 0.20 远离两侧。

## 证据不足时的保守默认

分类器**不允许**把"没有证据"读成"大概是银行"：

- 无营收基数 → `OtherFinancial`，理由 `"no revenue base"`
- 无利息支出字段 → `OtherFinancial`，理由 `"no evidence of funding cost"`

这两种情况都不会进入 Bank RIM。对应测试：
`test_fintech_without_interest_expense_is_not_routed_to_bank`、
`test_fintech_without_revenue_is_not_routed_to_bank`。

## 可追溯性

每个 profile 记录两个字段（本会话新增）：

- `financial_business_model` — 判定结果
- `financial_business_model_reason` — 判定理由（含实际比率数值）

真实输出示例：

```
V  → PaymentNetwork
     reason: FinTech with fee-based economics
             (interest expense / operating income = 0.025 < 0.20) → payment network
JPM → Bank
     reason: BusinessType=Bank → deposit-funded lending/underwriting
```

## 50 股分类结果分布

| FinancialBusinessModel | 数量 | 股票 |
|---|---|---|
| Bank | 3 | JPM, BAC, GS |
| PaymentNetwork | 1 | V |
| OtherFinancial | 2 | CB, BRK-B |
| NotFinancial | 44 | 其余 |

无任何股票落入 `FintechLender`（50 股池内无 SOFI/AXP/COF 类标的），
该分支由合成数据测试覆盖。
