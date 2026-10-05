"""
telegram_bot/telegram_bot.py - Telegram Bot Integration
Commands: /start, /val <ticker>, /help, /about
"""
from __future__ import annotations

import asyncio
from typing import Optional

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_MAX_MESSAGE_LENGTH,
    YAHOO_ALLOW_SYNTHETIC_FALLBACK,
    DataSource,
    get_logger,
)
from data.errors import YahooFinanceUnavailableError

log = get_logger("telegram_bot")


class ValuationPipeline:
    """Runs the full end-to-end valuation for a given ticker and produces a text report."""

    @staticmethod
    async def run(ticker: str, skip_monte_carlo: bool = False) -> str:
        from analysis.expectation import ExpectationAnalyzer
        from analysis.model_agreement import ModelAgreementAnalyzer
        from analysis.risk import RiskAnalyzer
        from analysis.scenario import ScenarioAnalyzer
        from analysis.sensitivity import SensitivityAnalyzer
        from classification.ml_classifier import MLHybridClassifier
        from data import DataValidator, FinancialNormalizer, YahooFinanceProvider
        from models.router import ModelRouter
        from reporting.dashboard import DashboardReport, ValuationReportBuilder
        from simulation.monte_carlo import MonteCarloSimulator

        ticker = ticker.strip().upper()
        if not ticker:
            return "❌ 请输入证券代码。用法：/val AAPL"

        yf = YahooFinanceProvider()

        try:
            data = await yf.get_financial_data(ticker)
        except YahooFinanceUnavailableError as e:
            log.warning("Yahoo unavailable for %s: %s", ticker, e)
            hint = (
                "请稍后重试，或设置环境变量 `YAHOO_ALLOW_SYNTHETIC_FALLBACK=1` "
                "以允许回退至**已知**演示代码（AAPL/MSFT 等，非任意 ticker）。"
                if not YAHOO_ALLOW_SYNTHETIC_FALLBACK
                else "Yahoo 与演示库均无该代码可用。"
            )
            return (
                f"❌ **无法获取 {ticker} 的真实 Yahoo 数据**\n\n"
                f"{e}\n\n{hint}\n\n"
                "_未生成估值报告，避免使用错误数据。_"
            )

        data = FinancialNormalizer.normalize_all(data)
        data = DataValidator.validate(data)

        classifier = MLHybridClassifier()
        profile = classifier.classify(data)

        router = ModelRouter()
        model_results = router.run_all(data, profile)

        scenario_analyzer = ScenarioAnalyzer()
        scenarios = {}
        for s, sv in scenario_analyzer.run_all(data, profile).items():
            scenarios[s] = sv

        dcf_breakdown = None
        if "DCF" in model_results and model_results["DCF"].is_success():
            dcf_breakdown = model_results["DCF"].breakdown

        risk_analyzer = RiskAnalyzer()
        risk_report = risk_analyzer.analyze(data, dcf_breakdown, profile)

        expectation_analyzer = ExpectationAnalyzer()
        implied, gap = expectation_analyzer.gap_analysis(data, profile)

        sensitivity_analyzer = SensitivityAnalyzer()
        try:
            sens = sensitivity_analyzer.wacc_vs_terminal_growth(data, profile)
        except Exception as e:
            log.exception(f"Sensitivity failed: {e}")
            sens = None

        agreement_analyzer = ModelAgreementAnalyzer()
        agreement = agreement_analyzer.analyze(model_results, data.market.current_price)

        mc_result = None
        if not skip_monte_carlo:
            try:
                mc = MonteCarloSimulator()
                mc_result = mc.run(data, profile)
            except Exception as e:
                log.exception(f"Monte Carlo failed: {e}")

        report = ValuationReportBuilder.build_report(
            data, profile, model_results, scenarios, implied, gap, sens, agreement, risk_report, mc_result
        )

        src = data.source.value if hasattr(data.source, "value") else str(data.source)
        header = f"📊 **估值引擎 — {data.ticker}** — {data.market.company_name or ''}\n"
        header += f"生成时间：{data.fetched_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
        header += f"**数据来源:** {src}\n"
        if data.source == DataSource.SYNTHETIC:
            header += (
                "🚨 **警告：当前为 SYNTHETIC 演示数据，非 live 市场数据。**\n"
            )
        header += "\n"
        return header + report


class TelegramBotRunner:
    """Manages the Telegram bot lifecycle (python-telegram-bot v20 async)."""

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or TELEGRAM_BOT_TOKEN
        self._app = None

    def _build_app(self):
        try:
            from telegram import Update
            from telegram.ext import (
                ApplicationBuilder,
                CommandHandler,
                ContextTypes,
            )
        except ImportError:
            raise RuntimeError("python-telegram-bot not installed. Run: pip install python-telegram-bot")

        from reporting.dashboard import DashboardReport

        application = ApplicationBuilder().token(self.token).build()

        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user = update.effective_user
            msg = (
                f"👋 你好 {user.first_name if user else '朋友'}！我是 **Universal Valuation Engine Bot**。\n\n"
                f"**可用命令：**\n"
                f"• `/val <代码>` — 完整估值报告（例如 /val AAPL）\n"
                f"• `/val_fast <代码>` — 快速估值（跳过蒙特卡洛）\n"
                f"• `/help` — 查看全部命令\n"
                f"• `/about` — 关于这个机器人\n\n"
                f"💡 示例：`/val AAPL`"
            )
            await update.message.reply_markdown(msg, disable_web_page_preview=True)

        async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            help_text = (
                "**🤖 机器人命令：**\n\n"
                "`/val <代码>`\n"
                "完整估值：数据 → 分类 → 预测 → DCF + 倍数法 + 反向 DCF → 情景分析 → 敏感性 → 风险 → 蒙特卡洛 → 报告\n\n"
                "`/val_fast <代码>`\n"
                "与 /val 相同，但跳过蒙特卡洛模拟（约快 2 倍）\n\n"
                "`/start` 欢迎页\n"
                "`/help` 查看帮助\n"
                "`/about` 关于机器人\n\n"
                "🔒 所有假设都会透明披露。\n"
                "⚠️ 本信息仅供参考，不构成投资建议。"
            )
            await update.message.reply_markdown(help_text, disable_web_page_preview=True)

        async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            about = (
                "**Universal Valuation Engine Bot**\n\n"
                "一个模块化、可审计、面向业务的股票估值引擎。\n\n"
                "**功能：**\n"
                "• DCF、反向 DCF、5 种倍数法\n"
                "• 熊市 / 基本面 / 乐观情景\n"
                "• WACC 与终值增长率敏感性矩阵\n"
                "• 市场隐含预期与预期差距分析\n"
                "• 9 维风险引擎与可解释规则\n"
                "• 模型一致性与估值离散度\n"
                "• 蒙特卡洛模拟（默认 N=2000）\n"
                "• 数据来源：Yahoo Finance（默认；失败时不静默替换演示数据）\n"
                "• 数据质量评分\n"
                "• 10 类业务类型分类器\n\n"
                "⚠️ 仅供信息参考，不构成投资建议。"
            )
            await update.message.reply_markdown(about, disable_web_page_preview=True)

        async def _send_chunks(update: Update, text: str) -> None:
            max_len = max(200, TELEGRAM_MAX_MESSAGE_LENGTH - 50)
            chunks = DashboardReport.split_for_telegram(text, max_len=max_len)
            for i, chunk in enumerate(chunks):
                if i > 0:
                    chunk = f"(cont'd {i+1}/{len(chunks)})\n\n" + chunk
                try:
                    await update.message.reply_markdown(chunk, disable_web_page_preview=True)
                except Exception:
                    await update.message.reply_text(chunk[:TELEGRAM_MAX_MESSAGE_LENGTH], disable_web_page_preview=True)
                await asyncio.sleep(0.3)

        async def val_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            args = context.args or []
            ticker = (args[0] if args else "").strip()
            if not ticker:
                await update.message.reply_text("❌ 用法：/val AAPL")
                return
            await update.message.reply_text(f"⏳ 正在分析 {ticker.upper()} — 请稍候（10-30秒）...")
            try:
                report = await ValuationPipeline.run(ticker, skip_monte_carlo=False)
            except Exception as e:
                log.exception(f"/val {ticker} failed")
                await update.message.reply_text(f"❌ 分析 {ticker} 时出错：{e}")
                return
            await _send_chunks(update, report)

        async def val_fast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            args = context.args or []
            ticker = (args[0] if args else "").strip()
            if not ticker:
                await update.message.reply_text("❌ 用法：/val_fast MSFT")
                return
            await update.message.reply_text(f"⚡ 正在快速分析 {ticker.upper()}...")
            try:
                report = await ValuationPipeline.run(ticker, skip_monte_carlo=True)
            except Exception as e:
                log.exception(f"/val_fast {ticker} failed")
                await update.message.reply_text(f"❌ 分析 {ticker} 时出错：{e}")
                return
            await _send_chunks(update, report)

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_cmd))
        application.add_handler(CommandHandler("about", about_cmd))
        application.add_handler(CommandHandler("val", val_cmd))
        application.add_handler(CommandHandler("val_fast", val_fast_cmd))
        self._app = application
        return application

    def run_polling(self) -> None:
        if not self.token or self.token == "your_telegram_bot_token_here":
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN not set. Copy .env.example to .env and set your bot token."
            )
        app = self._build_app()
        log.info("Starting Telegram Bot (polling mode)...")
        app.run_polling()


__all__ = ["ValuationPipeline", "TelegramBotRunner"]
